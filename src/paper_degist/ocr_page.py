"""US20 — OCR one page image with one registered vision model.

The investigation report's costliest lesson was the **transport**, not the
models (report §3): a Python ``urllib`` POST of an image returns an empty-body
502 and takes the MLX vision worker down; rapid-fire requests flap the runtime;
a crashed model can still report ``loaded`` while chat 502s. The verified recipe
is encoded here once (rule 02), never rediscovered per run: **build the JSON
body in Python, POST it with ``curl --data @body.json``, sequentially, with a
recovery gap and retry-on-502** — never ``urllib``, never concurrent.

Models are a **registry**, not a code branch: each entry is a
``(prompt, post-processor)`` pair keyed by the model id. qwen takes a plain
instruction and needs only a ```` ```markdown ```` fence stripped; DeepSeek-OCR
takes ``<|grounding|>Convert the document to markdown.`` (the literal ``<image>``
token **omitted**, or LM Studio 400s on a double image) and needs its grounding
markup decoded. Adding a model is one registry entry — data, not a branch.

Classify-then-dispatch (rule 02) runs in two layers. First on the model id: in
the registry → use its ``(prompt, post-processor)``; not in it → quarantine
(unknown model) **without touching the network**. Then on the transport result:
a 200 → post-process and save; a 502/empty body → wait the recovery gap and
retry, and after the retry budget quarantine (server unreachable). No LLM is
ever called to classify or rescue an item.

Runnable from the command line (rule 03):

    uv run ocr-page pages/WordCraft/p02.png qwen/qwen3-vl-4b
    uv run ocr-page pages/WordCraft/p02.png deepseek-ocr --endpoint http://localhost:1234/v1/chat/completions
"""

import base64
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Callable, Optional

import typer

from paper_degist import _manifest
from paper_degist._cli import invoke

# The verified transport constants (report §3). The gap is the ~6–8 s recovery
# window the flapping MLX runtime needs between hits; a different value is a
# `--gap` option, not a new path. Total attempts include the first try.
DEFAULT_ENDPOINT = "http://localhost:1234/v1/chat/completions"
DEFAULT_GAP = 7.0
DEFAULT_ATTEMPTS = 3


class TransportError(Exception):
    """A POST that did not return a usable 200 (502, empty body, curl failure).

    Raised by the transport so the orchestrator can apply the encoded
    retry-after-a-gap policy and, on exhaustion, quarantine rather than crash.
    """


class ClientRequestError(TransportError):
    """A 4xx — the request itself was rejected (a bad body, an unloadable model).

    A subclass of ``TransportError`` so any transport error is caught by one
    ``except``, but distinct so the orchestrator can **fail fast**: a client
    error is deterministic, so retrying it only burns the recovery budget and
    mislabels a rejected request as an unreachable server.
    """


@dataclass(frozen=True)
class OcrResponse:
    """One model's answer, parsed from the chat-completions response."""

    content: str
    finish_reason: str
    completion_tokens: int


# --- per-model post-processors (the registry's encoded quirks) ---

_FENCE_RE = re.compile(r"\A```(?:markdown)?[ \t]*\n(?P<body>.*?)\n?```\s*\Z", re.DOTALL)


def _strip_markdown_fence(text: str) -> str:
    """Unwrap a ```` ```markdown … ``` ```` fence qwen wraps its output in.

    Unfenced output is returned untouched (only the whole-string wrapper is a
    fence; a code block *inside* the document is left alone).
    """
    text = text.replace("\r\n", "\n").strip()  # normalize CRLF so the fence matches
    match = _FENCE_RE.match(text)
    return match.group("body").strip() if match else text


_DET_RE = re.compile(r"<\|det\|>.*?<\|/det\|>", re.DOTALL)
_REF_RE = re.compile(r"<\|/?ref\|>")


def _decode_grounding(text: str) -> str:
    """Strip DeepSeek-OCR grounding markup, keeping the referenced text.

    The ``<|grounding|>`` mode emits ``<|ref|>text<|/ref|><|det|>[[box]]<|/det|>``
    triples; we drop the coordinate boxes and the ref markers, leaving the plain
    Markdown text. Plain (ungrounded) text passes through untouched.
    """
    text = _DET_RE.sub("", text)
    text = _REF_RE.sub("", text)
    return text.strip()


@dataclass(frozen=True)
class ModelSpec:
    """A registered model: the prompt to send and how to clean its output."""

    prompt: str
    postprocess: Callable[[str], str]


# The model registry (rule 02: a new model is one entry here, not a branch).
# The DeepSeek prompt deliberately omits the literal `<image>` token — the image
# rides the chat `image_url` part, and a second literal token 400s LM Studio.
REGISTRY: dict[str, ModelSpec] = {
    "qwen/qwen3-vl-4b": ModelSpec(
        prompt="Convert the document to markdown.",
        postprocess=_strip_markdown_fence,
    ),
    "deepseek-ocr": ModelSpec(
        prompt="<|grounding|>Convert the document to markdown.",
        postprocess=_decode_grounding,
    ),
}


# post(model_id, prompt, image_path, endpoint) -> OcrResponse, raising
# TransportError on a 502/empty/failed POST. Injected in tests; the default is
# the curl recipe below.
Transport = Callable[[str, str, Path, str], OcrResponse]


def _default_post(model_id: str, prompt: str, image_path: Path, endpoint: str) -> OcrResponse:
    """POST one page image via ``curl --data @body.json`` (the report §3 recipe).

    Builds the chat-completions body in Python (image as a base64 data URL),
    writes it to a temp file, and hands it to ``curl`` — never ``urllib``, whose
    image POST empty-body-502s and takes the MLX worker down. A non-200, an empty
    body, or a curl failure raises ``TransportError`` for the caller to retry.
    """
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    body = {
        "model": model_id,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }
        ],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(body, fh)
        body_file = fh.name
    try:
        proc = subprocess.run(
            [
                "curl",
                "-sS",
                "--max-time",
                "600",
                "-w",
                "\n%{http_code}",
                "-H",
                "Content-Type: application/json",
                "--data",
                f"@{body_file}",
                endpoint,
            ],
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        # curl not on PATH (or otherwise unspawnable) is a transport failure, not
        # a crash — convert it so the caller retries then quarantines (rule 02).
        raise TransportError(f"curl unavailable: {exc}") from exc
    finally:
        os.unlink(body_file)

    if proc.returncode != 0:
        raise TransportError(f"curl exited {proc.returncode}: {proc.stderr.strip()[-200:]}")
    return _parse_response(proc.stdout)


def _parse_response(stdout: str) -> OcrResponse:
    """Parse ``curl -w "\\n%{http_code}"`` output into an ``OcrResponse``.

    The body is everything before the trailing status line. A non-200, an empty
    body, or a 200 whose JSON is truncated/off-schema all raise
    ``TransportError`` — a malformed 200 must retry and then quarantine like a
    502, never crash the step out of the loop (rule 02).
    """
    resp_body, _, code = stdout.rpartition("\n")
    if code.startswith("4"):
        # A client error (bad body, unloadable model) is deterministic — surface
        # it distinctly so the caller fails fast instead of retrying.
        raise ClientRequestError(f"request rejected: server returned {code}")
    if code != "200" or not resp_body.strip():
        raise TransportError(f"server returned {code or 'empty body'}")
    try:
        data = json.loads(resp_body)
        choice = data["choices"][0]
        content = choice["message"]["content"]
        if not isinstance(content, str):
            # A 200 with null / non-string content is a flap, not an answer —
            # retry it rather than let None reach the post-processor and crash.
            raise TypeError(f"content is {type(content).__name__}, not str")
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise TransportError(f"unparseable 200 response ({type(exc).__name__}): {exc}") from exc
    usage = data.get("usage") or {}
    return OcrResponse(
        content=content,
        finish_reason=choice.get("finish_reason", ""),
        completion_tokens=usage.get("completion_tokens", 0),
    )


def _model_slug(model_id: str) -> str:
    """Filesystem-safe output-dir name for a model id (``a/b`` → ``a_b``)."""
    return model_id.replace("/", "_")


def _quarantine(manifest_path: Path, *, page: str, model: str, reason: str) -> None:
    """Append one unhandled-case record to the manifest, so the batch finishes."""
    _manifest.append(manifest_path, stage="ocr-page", page=page, model=model, reason=reason)


def _save(target: Path, markdown: str) -> None:
    """Write the Markdown atomically so a killed write never leaves a partial
    file that the idempotency skip would mistake for a complete OCR result."""
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + ".writing")
    staging.write_text(markdown, encoding="utf-8")
    staging.rename(target)


def ocr_page(
    page_path: Path,
    model_id: str,
    *,
    out_dir: Path = Path("out"),
    manifest_path: Path = Path("manifest.jsonl"),
    endpoint: str = DEFAULT_ENDPOINT,
    attempts: int = DEFAULT_ATTEMPTS,
    gap: float = DEFAULT_GAP,
    registry: dict[str, ModelSpec] = REGISTRY,
    post: Transport = _default_post,
    sleep: Callable[[float], None] = time.sleep,
) -> Optional[Path]:
    """OCR ``page_path`` with ``model_id``; save Markdown to ``out/<model>/<page>.md``.

    Returns the output path on success (or the already-saved path on a re-run),
    or ``None`` when the (page, model) is quarantined — an unknown model (no
    network touched) or a server unreachable after the retry budget. Never
    crashes, never calls an LLM to rescue an item, never fires concurrently
    (rule 02).
    """
    page_path = Path(page_path)
    out_dir = Path(out_dir)
    manifest_path = Path(manifest_path)

    # Layer 1 — classify on the model id, before any network contact.
    spec = registry.get(model_id)
    if spec is None:
        _quarantine(
            manifest_path,
            page=str(page_path),
            model=model_id,
            reason=f"unknown model: {model_id!r} not in registry",
        )
        return None

    target = out_dir / _model_slug(model_id) / (page_path.stem + ".md")
    if target.exists():
        return target  # idempotent skip — the model call is the expensive, flaky resource

    # A missing/unreadable page (e.g. a stale path from a batch driver on the
    # library path) is quarantined, not crashed over, before any network call —
    # the Typer CLI already rejects it up front; this guards direct callers.
    if not page_path.is_file():
        _quarantine(
            manifest_path,
            page=str(page_path),
            model=model_id,
            reason=f"page image not found: {page_path}",
        )
        return None

    # Layer 2 — dispatch on the transport result: 200 → save; 4xx → fail fast
    # (deterministic); 502/empty → wait the recovery gap and retry; after the
    # budget, quarantine (server down).
    last_error: Optional[TransportError] = None
    for attempt in range(attempts):
        if attempt > 0:
            sleep(gap)  # recovery gap before a retry — never a rapid-fire re-hit
        # Time each call individually so the recorded latency is the *successful*
        # request's round-trip — the bench's model-speed signal — not the retry
        # budget and gaps burned recovering from a flap.
        start = time.monotonic()
        try:
            response = post(model_id, spec.prompt, page_path, endpoint)
        except ClientRequestError as exc:
            # Deterministic — retrying a rejected request cannot help; fail fast
            # with a distinct reason rather than burning the retry budget.
            _quarantine(manifest_path, page=str(page_path), model=model_id, reason=str(exc))
            return None
        except TransportError as exc:
            last_error = exc
            continue
        markdown = spec.postprocess(response.content)
        _save(target, markdown)
        _manifest.append(
            manifest_path,
            stage="ocr-page",
            page=str(page_path),
            model=model_id,
            latency=round(time.monotonic() - start, 3),
            finish_reason=response.finish_reason,
            completion_tokens=response.completion_tokens,
        )
        return target

    _quarantine(
        manifest_path,
        page=str(page_path),
        model=model_id,
        reason=f"server unreachable after {attempts} attempts: {last_error}",
    )
    return None


app = typer.Typer(
    add_completion=False,
    help="OCR one page image with one registered vision model (US20).",
)


@app.command()
def run(
    page: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, help="the page PNG to OCR"),
    ],
    model: Annotated[
        str,
        typer.Argument(help="a registered model id, e.g. qwen/qwen3-vl-4b"),
    ],
    out_dir: Annotated[
        Path,
        typer.Option("--out-dir", help="directory to save Markdown under (out/<model>/)"),
    ] = Path("out"),
    endpoint: Annotated[
        str,
        typer.Option(help="chat-completions endpoint of the vision server"),
    ] = DEFAULT_ENDPOINT,
    attempts: Annotated[int, typer.Option(help="max POST attempts before quarantine")] = DEFAULT_ATTEMPTS,
    gap: Annotated[float, typer.Option(help="recovery gap (seconds) between retries")] = DEFAULT_GAP,
    manifest: Annotated[
        Path,
        typer.Option(help="manifest of OCR records and quarantined (page, model) pairs"),
    ] = Path("manifest.jsonl"),
) -> None:
    """OCR the page; print the saved Markdown path, or a quarantine note on stderr."""
    target = ocr_page(
        page,
        model,
        out_dir=out_dir,
        manifest_path=manifest,
        endpoint=endpoint,
        attempts=attempts,
        gap=gap,
    )
    if target is None:
        # Quarantine is an expected outcome, not a crash: the batch still
        # finishes. Note it on stderr and exit cleanly.
        typer.echo(f"quarantined (see {manifest}): {page} + {model}", err=True)
        return
    typer.echo(str(target))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run ocr-page`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
