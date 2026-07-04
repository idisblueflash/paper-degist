"""US20 — OCR one page image with one registered model over the stable transport.

The OCR bench (US 20–23) compares vision models by feeding each the *same* page
bitmap (US19 render-pdf) and scoring the Markdown it returns. This step is one
(page, model) call: look the model up in the registry, POST the image over the
**stable transport**, apply the model's post-processor, and save the Markdown to
``out/<model>/<page>.md``.

The costliest lesson of the investigation report was the *transport*, not the
models (report §3), so it is encoded here once (rule 02) rather than
rediscovered each run:

* Python ``urllib`` on an image POST returns an empty-body 502 and takes down
  the MLX vision worker — so we build the JSON body in Python and hand it to
  **curl** as a file (``curl --data @body.json``), never urllib.
* Rapid-fire requests flap the runtime — so calls are **sequential with a
  recovery gap and retry-on-502**, never concurrent.

Classify-then-dispatch (rule 02) in two layers: first on the *model id* (in the
registry → use its prompt + post-processor; unknown → quarantine without
touching the network), then on the *transport result* (200 → post-process and
save; 502/empty after the retry budget → quarantine server-unreachable). Per
model quirks (the omitted ``<image>`` token, ``decode_grounding`` vs
fence-strip) live in the registry entry, so adding a model is **data, not a new
branch**. No LLM is ever called to classify or rescue an item.

Runnable from the command line (rule 03)::

    uv run ocr-page pages/WordCraft/p02.png qwen/qwen3-vl-4b
    uv run ocr-page pages/WordCraft/p02.png deepseek-ocr-2 --server http://host:1234/v1/chat/completions
"""

import base64
import json
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Annotated, Callable, Optional

import typer

from paper_degist import _manifest
from paper_degist._cli import invoke

# LM Studio's OpenAI-compatible chat endpoint; the operator brings the server up
# with the model loaded (server lifecycle is out of scope — see the US20 spec).
DEFAULT_SERVER = "http://localhost:1234/v1/chat/completions"

# Sequential-with-gap + retry-on-502 is the report's verified recipe (§3): a
# crashed/flapping runtime 502s, then recovers after a few seconds. Never hammer.
DEFAULT_RETRIES = 4
DEFAULT_GAP = 8.0  # seconds between attempts; report used ~6–8 s
DEFAULT_MAX_TOKENS = 6000  # the report's per-page budget for a dense two-column page


# --- per-model post-processors (registry data, not branches) ---


def _strip_markdown_fence(text: str) -> str:
    """Strip a whole-output ```` ```markdown ```` … ```` ``` ```` wrapper.

    qwen sometimes wraps its answer in a single fenced block; unwrap it so the
    saved ``.md`` is the document, not a fence around it. A fence that is *not*
    the whole output (an inline code block) is left untouched.
    """
    stripped = text.replace("\r\n", "\n").strip()
    fence = re.match(r"^```[a-zA-Z]*\n(.*)\n```$", stripped, flags=re.S)
    if fence:
        return fence.group(1).strip() + "\n"
    return stripped + "\n"


def _bytes_to_unicode() -> dict[str, int]:
    """The GPT-2 byte↔unicode map (Radford et al.), reversed to recover bytes."""
    bs = (
        list(range(ord("!"), ord("~") + 1))
        + list(range(ord("¡"), ord("¬") + 1))
        + list(range(ord("®"), ord("ÿ") + 1))
    )
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return {chr(c): b for b, c in zip(bs, cs)}


_U2B = _bytes_to_unicode()


def decode_grounding(text: str) -> str:
    """Detokenize + strip a DeepSeek-OCR grounding response to clean Markdown.

    DeepSeek returns byte-BPE text (``Ġ``/``Ċ`` artifacts) interleaved with
    layout/category tokens (``<|det|>…<|/det|>``, ``<|ref|>…<|/ref|>``) and, at
    8-bit, ``[[x1,y1,x2,y2]]`` coords and ``<center>`` wrappers. Reverse the
    byte map, drop the grounding scaffolding, and tidy whitespace (ported from
    the report's ``decode_grounding.py``).
    """
    out = bytearray()
    for ch in text:
        if ch in _U2B:
            out.append(_U2B[ch])
        else:
            out.extend(ch.encode("utf-8"))
    s = out.decode("utf-8", errors="replace")
    s = re.sub(r"<\|det\|>.*?<\|/det\|>", "", s, flags=re.S)  # layout boxes
    s = re.sub(r"<\|ref\|>.*?<\|/ref\|>", "", s, flags=re.S)  # category refs
    s = re.sub(r"<\|/?ref\|>|<\|grounding\|>|<\|/?det\|>", "", s)  # stray tokens
    s = re.sub(r"<center>|</center>", "", s)  # 8-bit caption/table wrappers
    s = re.sub(r"\[?\[\d+,\s*\d+,\s*\d+,\s*\d+\]\]?", "", s)  # 8-bit coords
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ ]{2,}", " ", s)
    return s.strip() + "\n"


# --- the model registry: adding a model is one entry, not a code branch ---

_QWEN_PROMPT = (
    "Convert this document page to clean, well-structured Markdown. This is a "
    "two-column academic paper: read the ENTIRE left column top-to-bottom, then "
    "the right column. Preserve headings, paragraphs, math (LaTeX), and lists. "
    "Output only the Markdown."
)
# DeepSeek/grounding models: DO NOT include a literal "<image>" token — LM Studio
# auto-injects the image and a literal token 400s ("2 != 1"). Report §3/§4.2.
_GROUNDING_PROMPT = "<|grounding|>Convert the document to markdown."


@dataclass(frozen=True)
class ModelSpec:
    """A registry entry: the prompt to send and how to post-process the answer."""

    prompt: str
    postprocess: Callable[[str], str]


# The verified model set from the investigation report (§4). New models are
# added here as data — one entry of (prompt, post-processor).
REGISTRY: dict[str, ModelSpec] = {
    "qwen/qwen3-vl-4b": ModelSpec(_QWEN_PROMPT, _strip_markdown_fence),
    "deepseek-ocr-2": ModelSpec(_GROUNDING_PROMPT, decode_grounding),
    "deepseek-ocr@8bit": ModelSpec(_GROUNDING_PROMPT, decode_grounding),
    "unlimited-ocr-mlx": ModelSpec(_GROUNDING_PROMPT, decode_grounding),
    "deepseek-ocr": ModelSpec(_GROUNDING_PROMPT, decode_grounding),
}


# --- the stable transport (encoded knowledge — always curl, always sequential) ---


class TransportError(Exception):
    """Raised when the server is still unreachable after the retry budget."""


# post(server, body_path) -> (http_code, raw_body). Injected so tests never
# shell out; the default is the report's verified curl invocation.
Poster = Callable[[str, Path], tuple[str, str]]


def _default_post(server: str, body_path: Path) -> tuple[str, str]:
    """POST the JSON body file with curl; return ``(http_code, raw_body)``.

    curl (not urllib) because an image POST via urllib returns an empty-body 502
    and crashes the MLX worker (report §3). The body is handed over as a file
    (``--data @``) because printf/base64-built JSON breaks on ``%``/newlines.
    """
    proc = subprocess.run(
        [
            "curl",
            "-s",
            "-m",
            "600",
            "-w",
            "\n%{http_code}",
            server,
            "-H",
            "Content-Type: application/json",
            "--data",
            "@" + str(body_path),
        ],
        capture_output=True,
        text=True,
    )
    code = proc.stdout.rsplit("\n", 1)[-1].strip()
    raw = proc.stdout.rsplit("\n", 1)[0]
    return code, raw


def _build_body(model: str, prompt: str, image_path: Path, max_tokens: int) -> dict:
    """Build the OpenAI-compatible chat body with the page inlined as base64."""
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    return {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64," + b64},
                    },
                ],
            }
        ],
    }


def _ocr_over_transport(
    server: str,
    model: str,
    prompt: str,
    image_path: Path,
    *,
    post: Poster,
    sleep: Callable[[float], None],
    retries: int,
    gap: float,
    max_tokens: int,
) -> tuple[str, Optional[str], dict, float]:
    """Send one image over the stable transport; return ``(text, finish, usage, latency)``.

    Classify what came back (report §3), three ways:

    * **200 with a usable body** → return it, plus the wall time of *that*
      request only (``latency`` excludes the recovery gaps, so a model retried
      through a flap is not penalised in the bench).
    * **a client error (4xx)** → deterministic; retrying cannot fix it, so fail
      fast with a distinct reason rather than burning the retry budget and
      mislabelling a bad request as an unreachable server.
    * **anything else** (502/503, a connection failure ``000``, or a 200 whose
      body is malformed — a half-crashed runtime) → wait ``gap`` and retry, up
      to ``retries`` attempts, then raise ``TransportError``.

    Sequential only — never concurrent, never an LLM in the loop.
    """
    body = _build_body(model, prompt, image_path, max_tokens)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(body, fh)
        body_path = Path(fh.name)
    try:
        code = ""
        for attempt in range(1, retries + 1):
            call_start = perf_counter()
            try:
                code, raw = post(server, body_path)
            except OSError as exc:
                # The transport itself failed (e.g. curl not on PATH) — a flap,
                # not an answer; retry, then let the budget quarantine it rather
                # than crash the batch (rule 02).
                code, raw = f"transport error ({exc.__class__.__name__})", ""
            if code == "200":
                try:
                    data = json.loads(raw)
                    choice = data["choices"][0]
                    content = choice["message"]["content"]
                    if not isinstance(content, str):
                        raise TypeError("content is not a string")
                except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                    # A 200 with an unexpected shape (non-JSON, missing choices,
                    # or a null/non-string content) is a flap, not an answer —
                    # never crash (rule 02); fall through to the retry path.
                    code = "200 (malformed body)"
                else:
                    latency = round(perf_counter() - call_start, 3)
                    # `usage: null` (not just absent) must still yield a dict.
                    return content, choice.get("finish_reason"), (data.get("usage") or {}), latency
            elif code.startswith("4"):
                raise TransportError(
                    f"request rejected (HTTP {code}) — not a transient server error"
                )
            if attempt < retries:
                sleep(gap)  # recovery gap — do NOT hammer a flapping runtime
        raise TransportError(
            f"server unreachable after retries ({retries} attempts, last HTTP {code or 'no response'})"
        )
    finally:
        body_path.unlink(missing_ok=True)


# --- output pathing + quarantine ---


def _model_slug(model: str) -> str:
    """Filesystem-safe output subdir for a model id (``qwen/qwen3-vl-4b`` → ``qwen_qwen3-vl-4b``)."""
    return model.replace("/", "_")


def _quarantine(manifest_path: Path, *, page: str, model: str, reason: str) -> None:
    """Append one unhandled-case record so the batch still finishes (rule 02)."""
    _manifest.append(
        manifest_path, stage="ocr-page", page=page, model=model, reason=reason
    )


def ocr_page(
    image_path: Path,
    model: str,
    *,
    out_dir: Path = Path("out"),
    manifest_path: Path = Path("manifest.jsonl"),
    server: str = DEFAULT_SERVER,
    retries: int = DEFAULT_RETRIES,
    gap: float = DEFAULT_GAP,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    post: Poster = _default_post,
    sleep: Callable[[float], None] = time.sleep,
) -> Optional[Path]:
    """OCR ``image_path`` with ``model``; save Markdown to ``out/<model>/<page>.md``.

    Returns the saved path on success (or the already-saved path on a re-run),
    or ``None`` when quarantined — an unknown model (no network touched), or a
    server still unreachable after the retry budget. A pre-existing output is
    left untouched so re-runs never re-hit the flaky, expensive server.
    """
    image_path = Path(image_path)
    out_dir = Path(out_dir)
    manifest_path = Path(manifest_path)

    # Layer 1: classify on the model id — unknown models never touch the network.
    spec = REGISTRY.get(model)
    if spec is None:
        _quarantine(
            manifest_path,
            page=str(image_path),
            model=model,
            reason=f"unknown model (not in registry): {model}",
        )
        return None

    target = out_dir / _model_slug(model) / (image_path.stem + ".md")
    if target.exists():
        return target  # idempotent skip — no server hit, no manifest record

    # A missing/unreadable page (e.g. a stale path from a batch driver) is
    # quarantined, not crashed over (rule 02) — and before any network call.
    if not image_path.is_file():
        _quarantine(
            manifest_path,
            page=str(image_path),
            model=model,
            reason=f"page image not found: {image_path}",
        )
        return None

    # Layer 2: dispatch on the transport result.
    try:
        text, finish_reason, usage, latency = _ocr_over_transport(
            server,
            model,
            spec.prompt,
            image_path,
            post=post,
            sleep=sleep,
            retries=retries,
            gap=gap,
            max_tokens=max_tokens,
        )
    except TransportError as exc:
        _quarantine(manifest_path, page=str(image_path), model=model, reason=str(exc))
        return None

    markdown = spec.postprocess(text)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Write to a staging sibling and publish with one rename, so a crash mid-write
    # never leaves a partial file the idempotency skip would accept as complete.
    staging = target.with_name(target.name + ".writing")
    staging.write_text(markdown, encoding="utf-8")
    staging.rename(target)

    _manifest.append(
        manifest_path,
        stage="ocr-page",
        model=model,
        page=str(image_path),
        latency=latency,
        finish_reason=finish_reason,
        completion_tokens=usage.get("completion_tokens"),
    )
    return target


app = typer.Typer(
    add_completion=False,
    help="OCR one page image with one registered model over the stable transport (US20).",
)


@app.command()
def run(
    page: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, help="the page PNG to OCR"),
    ],
    model: Annotated[str, typer.Argument(help="a registered model id, e.g. qwen/qwen3-vl-4b")],
    out_dir: Annotated[
        Path, typer.Option(help="directory to save Markdown under (out/<model>/)")
    ] = Path("out"),
    server: Annotated[str, typer.Option(help="LM Studio chat-completions endpoint")] = DEFAULT_SERVER,
    retries: Annotated[int, typer.Option(help="retry-on-502 budget")] = DEFAULT_RETRIES,
    gap: Annotated[float, typer.Option(help="recovery gap between attempts (seconds)")] = DEFAULT_GAP,
    manifest: Annotated[
        Path, typer.Option(help="manifest of ocr records + quarantined cases")
    ] = Path("manifest.jsonl"),
) -> None:
    """OCR the page; print the saved Markdown path, or a quarantine note on stderr."""
    saved = ocr_page(
        page,
        model,
        out_dir=out_dir,
        manifest_path=manifest,
        server=server,
        retries=retries,
        gap=gap,
    )
    if saved is None:
        typer.echo(f"quarantined (see {manifest}): {page} [{model}]", err=True)
        return
    typer.echo(str(saved))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run ocr-page`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
