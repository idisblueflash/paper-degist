"""US18 — bring up (or reuse) a dev-mode Chrome for the browser lane.

The browser lane (US 15/16 ``browser-fetch``) attaches to an **already-running**
dev-mode Chrome over the Chrome DevTools Protocol (CDP). In a real run the
operator that *starts* that Chrome is Claude Code, not the researcher: locate the
Chrome binary, pick the flags (``--remote-debugging-port``, a persistent
``--user-data-dir``), launch, then let the researcher do the one manual
confirmation (log in, clear a captcha) once the window is up. That launch is
knowledge re-investigated every session; rule 02 says encode it once. This step
is that encoding — the browser lane's setup command, one layer *before*
``browser-fetch``.

Classify-then-dispatch over one cheap signal: is a dev-mode Chrome already
answering on the CDP port?

- **reachable** → reuse it and print the endpoint (idempotent — never a second
  Chrome, safe to call at the top of every browser-lane run);
- **not reachable, port free** → locate Chrome, launch it against the *fixed*
  persistent profile, wait until the endpoint answers, print it, and detach —
  leaving Chrome running for the researcher to log in;
- **not reachable, port held by a non-debug process** → a **loud** failure;
- **Chrome binary not found** → a **loud** failure with a distinct diagnostic.

Unlike every other step, browser-up has **no paper and no batch** to keep
running, so a launch it cannot complete is a loud ``BrowserUpError`` (non-zero
exit + clear diagnostic), **not** a manifest quarantine — there is nothing to
proceed to and the operator must notice. No LLM in the loop (rule 02). Runnable
from the command line (rule 03):

    uv run browser-up                         # reuse or launch on :9222
    uv run browser-up --cdp http://localhost:9333 --user-data-dir .prof/
"""

import shutil
import subprocess
import time
from pathlib import Path
from typing import Annotated, Callable, Iterable, Optional
from urllib.parse import urlsplit

import typer

from paper_degist._cli import invoke

# The encoded knowledge (rule 02): a different port or profile is a *flag*, not a
# new code path. Defaults chosen to match browser-fetch's own CDP default.
DEFAULT_CDP = "http://localhost:9222"
DEFAULT_PROFILE = Path(".browser-profile")

# Standard install locations for Chrome/Chromium, macOS first (this repo's
# platform). Each new binary location we hit becomes another entry here — the
# rule-02 "new case → new branch" for the finder.
_CHROME_CANDIDATES: tuple[Path, ...] = (
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    Path("/usr/bin/google-chrome"),
    Path("/usr/bin/google-chrome-stable"),
    Path("/usr/bin/chromium"),
    Path("/usr/bin/chromium-browser"),
)
# PATH names to fall back on when no fixed candidate exists.
_CHROME_ON_PATH = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")


class BrowserUpError(Exception):
    """A launch browser-up could not complete — a loud, non-zero-exit failure.

    Carries a human diagnostic (missing binary vs. port in use vs. endpoint
    never came up). The CLI prints it to stderr and exits non-zero; it is never
    a manifest quarantine, because this step has no batch to keep running.
    """


# Injected collaborators (defaults are the real implementations below), so the
# dispatch is testable without a real Chrome — the fetch_one/resolve_oa shape.
CDPProbe = Callable[[str], bool]  # is a dev-mode Chrome answering at this CDP url?
PortProbe = Callable[[str, int], bool]  # is anything listening on host:port?
ChromeFinder = Callable[[], Optional[Path]]
Launcher = Callable[[Path, int, Path], None]  # launch(chrome, port, user_data_dir)
ReadyWait = Callable[[CDPProbe, str], bool]  # poll the probe until the endpoint answers


def _cdp_host_port(cdp_url: str) -> tuple[str, int]:
    """Parse ``cdp_url`` into ``(host, port)``; loud-fail on a portless endpoint.

    The port is needed to tell "nothing is listening, free to launch" from
    "something non-debug holds the port" (AC5). An endpoint with no port is a
    misconfiguration we surface loudly rather than guessing 9222.
    """
    parts = urlsplit(cdp_url)
    if parts.hostname is None or parts.port is None:
        raise BrowserUpError(
            f"CDP endpoint {cdp_url!r} needs an explicit host and port "
            f"(e.g. {DEFAULT_CDP})"
        )
    return parts.hostname, parts.port


def _chrome_launch_argv(chrome: Path, port: int, user_data_dir: Path) -> list[str]:
    """The dev-mode Chrome launch incantation (the knowledge this story encodes).

    Opens the remote-debugging port and pins the *fixed* persistent profile
    (absolute, so it does not depend on the cwd of a later run) — the profile is
    what carries the researcher's manual login across runs. ``--no-first-run`` /
    ``--no-default-browser-check`` keep a fresh profile from popping setup dialogs
    in front of the researcher.
    """
    return [
        str(chrome),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={Path(user_data_dir).resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def _default_probe_cdp(cdp_url: str) -> bool:
    """Is a dev-mode Chrome answering at ``cdp_url``? (the classify signal).

    Hits CDP's ``/json/version`` endpoint — which only a debug-enabled Chrome
    serves — so a non-debug process holding the port does not read as reusable.
    Any error (connection refused, timeout, non-200) means "not reachable".

    ``trust_env=False`` bypasses any ``HTTP(S)_PROXY`` env: the CDP endpoint is a
    local loopback debug server, and a proxy would 502 it (a would-be reachable
    Chrome then reads as down — surfaced by the US18 real E2E run).
    """
    import httpx

    try:
        resp = httpx.get(f"{cdp_url.rstrip('/')}/json/version", timeout=2.0, trust_env=False)
    except Exception:
        return False
    return resp.status_code == 200


def _default_port_in_use(host: str, port: int) -> bool:
    """Is *anything* listening on ``host:port``? (distinguishes AC5 from launch).

    A plain TCP connect: if it succeeds but the CDP probe already said "not a
    dev-mode Chrome", the port is held by a non-debug process and launching
    would fail — a loud, distinct failure rather than a doomed launch.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((host, port)) == 0


def _default_find_chrome(
    *,
    candidates: Iterable[Path] = _CHROME_CANDIDATES,
    exists: Callable[[Path], bool] = Path.is_file,
    which: Callable[[str], Optional[str]] = shutil.which,
) -> Optional[Path]:
    """Locate a Chrome/Chromium binary, or ``None`` when none is installed.

    Checks the fixed install locations first, then falls back to ``$PATH``.
    ``None`` drives AC4's loud "binary not found" failure. The predicates are
    injected so the search order is tested without depending on what is actually
    installed on the test machine.
    """
    for candidate in candidates:
        if exists(candidate):
            return candidate
    for name in _CHROME_ON_PATH:
        found = which(name)
        if found:
            return Path(found)
    return None


def _default_launch(
    chrome: Path,
    port: int,
    user_data_dir: Path,
    *,
    spawn: Callable[..., object] = subprocess.Popen,
) -> None:
    """Launch Chrome **detached** so it outlives browser-up (AC6).

    ``start_new_session`` puts Chrome in its own process group, and stdio is
    discarded, so the browser keeps running after this process returns — the
    warm session survives for browser-fetch and later runs. browser-up owns the
    launch; the researcher owns the shutdown (this step never kills Chrome).
    Creates the persistent profile dir up front so a first run has somewhere to
    write the session cookies.
    """
    Path(user_data_dir).mkdir(parents=True, exist_ok=True)
    spawn(
        _chrome_launch_argv(chrome, port, user_data_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _default_wait_ready(
    probe_cdp: CDPProbe,
    cdp_url: str,
    *,
    timeout: float = 30.0,
    interval: float = 0.25,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Poll ``probe_cdp`` until the endpoint answers or ``timeout`` elapses.

    Returns as soon as the endpoint is up (browser-up does **not** block waiting
    on the human — it returns once CDP answers, then the researcher logs in).
    Returns ``False`` on timeout so the caller can raise a loud failure. Clock
    and sleep are injected so the loop is tested without real waiting.
    """
    deadline = clock() + timeout
    while True:
        if probe_cdp(cdp_url):
            return True
        if clock() >= deadline:
            return False
        sleep(interval)


def browser_up(
    *,
    cdp_url: str = DEFAULT_CDP,
    user_data_dir: Path = DEFAULT_PROFILE,
    probe_cdp: Optional[CDPProbe] = None,
    port_in_use: Optional[PortProbe] = None,
    find_chrome: Optional[ChromeFinder] = None,
    launch: Optional[Launcher] = None,
    wait_ready: Optional[ReadyWait] = None,
) -> str:
    """Reuse or launch a dev-mode Chrome; return the reachable CDP endpoint.

    Classify-then-dispatch (rule 02) on one cheap signal — is a dev-mode Chrome
    already answering on the CDP port? Reachable → reuse (idempotent, never a
    second Chrome). Not reachable → the port is either free (locate Chrome and
    launch it against the fixed persistent profile, then wait until the endpoint
    answers) or held by a non-debug process (a loud, distinct failure). A missing
    Chrome binary and a launch that never comes up are loud failures too. Raises
    ``BrowserUpError`` on any launch it cannot complete — never a quarantine,
    because this step has no batch to keep running.

    Each collaborator defaults to its module-level ``_default_*`` implementation,
    resolved here at call time so a test (or the CLI) can monkeypatch the module
    attribute; tests inject fakes directly to exercise the dispatch offline.
    """
    probe_cdp = probe_cdp or _default_probe_cdp
    port_in_use = port_in_use or _default_port_in_use
    find_chrome = find_chrome or _default_find_chrome
    launch = launch or _default_launch
    wait_ready = wait_ready or _default_wait_ready

    host, port = _cdp_host_port(cdp_url)

    if probe_cdp(cdp_url):
        return cdp_url  # reuse the running browser (AC3) — never a second Chrome

    if port_in_use(host, port):
        raise BrowserUpError(
            f"the CDP port {port} is already held by a non-debug process — free it "
            f"or point --cdp at another port; nothing dev-mode to reuse on {cdp_url}"
        )

    chrome = find_chrome()
    if chrome is None:
        raise BrowserUpError(
            "could not find a Google Chrome / Chromium binary to launch — install "
            "Chrome or put it on PATH (looked in the standard install locations)"
        )

    launch(chrome, port, user_data_dir)
    if not wait_ready(probe_cdp, cdp_url):
        raise BrowserUpError(
            f"launched Chrome but the CDP endpoint {cdp_url} did not come up in time"
        )
    return cdp_url  # endpoint answers (AC1); Chrome left running & detached (AC6)


app = typer.Typer(
    add_completion=False,
    help="Launch (or reuse) a dev-mode Chrome for the browser lane (US18).",
)


@app.command()
def run(
    cdp: Annotated[
        str,
        typer.Option(help="CDP endpoint to reuse or bring a dev-mode Chrome up on"),
    ] = DEFAULT_CDP,
    user_data_dir: Annotated[
        Path,
        typer.Option(
            help="persistent Chrome profile dir (secrets-at-rest — gitignored)",
        ),
    ] = DEFAULT_PROFILE,
) -> None:
    """Bring up (or reuse) Chrome; print the CDP endpoint, or fail loudly."""
    try:
        endpoint = browser_up(cdp_url=cdp, user_data_dir=user_data_dir)
    except BrowserUpError as exc:
        # Loud failure, not a quarantine: there is no batch to carry on, so the
        # operator must notice. Clear diagnostic on stderr, non-zero exit.
        typer.echo(f"browser-up failed: {exc}", err=True)
        raise typer.Exit(code=1)
    typer.echo(endpoint)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run browser-up`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
