"""US18 — browser-up: launch (or reuse) a dev-mode Chrome for the browser lane.

Classify-then-dispatch over one cheap signal (rule 02): is a dev-mode Chrome
already answering on the CDP port? Reachable → reuse and report the endpoint;
not → locate Chrome and launch it. Unlike every other step this one has no paper
and no batch to keep running, so a launch it cannot complete is a **loud**
failure (``BrowserUpError`` → non-zero exit), not a manifest quarantine.

Every collaborator (the CDP probe, the port probe, the Chrome finder, the
launcher, the readiness wait) is injected so the dispatch is exercised without a
real Chrome — the same shape as ``fetch_one``'s injected ``fetch`` and
``resolve_oa``'s injected ``oa_lookup``.
"""

from pathlib import Path

import pytest

import paper_degist.browser_up as browser_up_mod
from paper_degist.browser_up import (
    BrowserUpError,
    _cdp_host_port,
    _chrome_launch_argv,
    _default_find_chrome,
    _default_wait_ready,
    browser_up,
)

# --- pure helper: parse the CDP endpoint into (host, port) ---


def test_cdp_host_port_parses_the_default_localhost_endpoint():
    assert _cdp_host_port("http://localhost:9222") == ("localhost", 9222)


def test_cdp_host_port_parses_a_custom_host_and_port():
    assert _cdp_host_port("http://127.0.0.1:9333") == ("127.0.0.1", 9333)


def test_cdp_host_port_rejects_an_endpoint_with_no_port():
    with pytest.raises(BrowserUpError):
        _cdp_host_port("http://localhost")


# --- pure helper: the Chrome launch argv (the encoded launch incantation) ---


def _argv():
    return _chrome_launch_argv(Path("/opt/chrome"), 9222, Path(".browser-profile"))


def test_launch_argv_starts_with_the_chrome_binary():
    assert _argv()[0] == "/opt/chrome"


def test_launch_argv_carries_the_remote_debugging_port():
    assert "--remote-debugging-port=9222" in _argv()


def test_launch_argv_carries_the_absolute_user_data_dir():
    resolved = str(Path(".browser-profile").resolve())
    assert f"--user-data-dir={resolved}" in _argv()


# --- readiness wait: poll the CDP probe until the endpoint answers ---


def test_wait_ready_true_when_the_endpoint_answers_at_once():
    assert _default_wait_ready(lambda url: True, "http://localhost:9222") is True


def test_wait_ready_polls_until_the_endpoint_comes_up():
    answers = iter([False, False, True])
    ready = _default_wait_ready(
        lambda url: next(answers),
        "http://localhost:9222",
        sleep=lambda s: None,
        clock=iter([0.0, 1.0, 2.0, 3.0]).__next__,
    )
    assert ready is True


def test_wait_ready_false_when_the_endpoint_never_answers():
    ready = _default_wait_ready(
        lambda url: False,
        "http://localhost:9222",
        timeout=1.0,
        sleep=lambda s: None,
        clock=iter([0.0, 0.5, 2.0]).__next__,
    )
    assert ready is False


# --- Chrome finder: locate the binary (injected exists/which predicates) ---


def test_find_chrome_returns_the_first_existing_candidate():
    found = _default_find_chrome(
        candidates=[Path("/nope/chrome"), Path("/Applications/Chrome")],
        exists=lambda p: p == Path("/Applications/Chrome"),
        which=lambda name: None,
    )
    assert found == Path("/Applications/Chrome")


def test_find_chrome_falls_back_to_which_on_path():
    found = _default_find_chrome(
        candidates=[Path("/nope/chrome")],
        exists=lambda p: False,
        which=lambda name: "/usr/bin/chromium" if name == "chromium" else None,
    )
    assert found == Path("/usr/bin/chromium")


def test_find_chrome_returns_none_when_no_binary_is_present():
    found = _default_find_chrome(
        candidates=[Path("/nope/chrome")],
        exists=lambda p: False,
        which=lambda name: None,
    )
    assert found is None


# --- the real CDP probe must ignore proxy env (a local loopback debug server) ---


def test_default_probe_cdp_bypasses_proxy_env(monkeypatch):
    # A CDP endpoint is on localhost; an HTTP(S)_PROXY 502s it, so the probe
    # must hit it directly (trust_env=False). Surfaced by the US18 real E2E.
    import httpx

    captured = {}

    class _Resp:
        status_code = 200

    def fake_get(url, **kwargs):
        captured.update(kwargs)
        return _Resp()

    monkeypatch.setattr(httpx, "get", fake_get)
    browser_up_mod._default_probe_cdp("http://localhost:9222")
    assert captured["trust_env"] is False


# --- browser_up dispatch: shared arrange/act over injected collaborators ---


def _run(**over):
    """Run browser_up with injected fakes; return (result, calls)."""
    calls = {}

    def launch(chrome, port, user_data_dir):
        calls["launch"] = {"chrome": chrome, "port": port, "user_data_dir": user_data_dir}

    kwargs = dict(
        cdp_url="http://localhost:9222",
        user_data_dir=Path(".browser-profile"),
        probe_cdp=lambda url: False,
        port_in_use=lambda host, port: False,
        find_chrome=lambda: Path("/usr/bin/google-chrome"),
        launch=launch,
        wait_ready=lambda probe, url: True,
    )
    kwargs.update(over)
    result = browser_up(**kwargs)
    return result, calls


# AC3 — a reachable dev-mode Chrome is reused (idempotent).


def test_reuses_a_reachable_chrome_and_returns_the_endpoint():
    result, _ = _run(probe_cdp=lambda url: True)
    assert result == "http://localhost:9222"


def test_reusing_a_reachable_chrome_does_not_launch_a_second():
    _, calls = _run(probe_cdp=lambda url: True)
    assert "launch" not in calls


# AC1 — no endpoint → launch, wait, then report the endpoint.


def test_launches_when_no_endpoint_and_returns_the_endpoint_once_up():
    result, calls = _run()
    assert result == "http://localhost:9222"


def test_launch_receives_the_configured_cdp_port():
    _, calls = _run()
    assert calls["launch"]["port"] == 9222


# AC2 — Chrome is launched against the fixed persistent profile, not a temp dir.


def test_launch_uses_the_fixed_persistent_user_data_dir():
    _, calls = _run()
    assert calls["launch"]["user_data_dir"] == Path(".browser-profile")


# AC4 — the Chrome binary cannot be found → loud failure naming the browser.


def test_missing_chrome_binary_raises_browserup_error():
    with pytest.raises(BrowserUpError):
        _run(find_chrome=lambda: None)


def test_missing_chrome_binary_error_names_the_browser():
    with pytest.raises(BrowserUpError, match="Chrome"):
        _run(find_chrome=lambda: None)


# AC5 — the port is held by a non-debug process → distinct loud failure.


def test_port_held_by_non_debug_process_raises_browserup_error():
    with pytest.raises(BrowserUpError):
        _run(port_in_use=lambda host, port: True)


def test_port_in_use_error_is_distinct_from_the_missing_binary_reason():
    with pytest.raises(BrowserUpError, match="port"):
        _run(port_in_use=lambda host, port: True)


def test_port_in_use_does_not_try_to_launch_chrome():
    calls = {}

    def launch(chrome, port, user_data_dir):
        calls["launch"] = True

    with pytest.raises(BrowserUpError):
        browser_up(
            probe_cdp=lambda url: False,
            port_in_use=lambda host, port: True,
            find_chrome=lambda: Path("/usr/bin/google-chrome"),
            launch=launch,
            wait_ready=lambda probe, url: True,
        )
    assert "launch" not in calls


# A launch that never brings the endpoint up is still a loud failure.


def test_launch_that_never_comes_up_raises_browserup_error():
    with pytest.raises(BrowserUpError, match="did not come up"):
        _run(wait_ready=lambda probe, url: False)


# AC6 — the default launcher detaches so Chrome outlives browser-up.


def test_default_launch_spawns_chrome_detached():
    spawned = {}

    def fake_spawn(argv, **kwargs):
        spawned["argv"] = argv
        spawned["kwargs"] = kwargs

    browser_up_mod._default_launch(
        Path("/opt/chrome"), 9222, Path("/tmp/prof-us18"), spawn=fake_spawn
    )
    assert spawned["kwargs"]["start_new_session"] is True
