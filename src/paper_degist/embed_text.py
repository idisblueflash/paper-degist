"""US24 — embed one text with one registered local embedding model.

The near-exact sibling of ``ocr_page`` (US20): the same LM Studio server, the
same **model registry** and the same **stable transport** — only the
``/v1/embeddings`` endpoint instead of chat completions. US20's costliest lesson
was the transport, and it carries over verbatim (rule 02): **build the JSON body
in Python, POST it with ``curl --data @body.json``, sequentially, with a recovery
gap and retry on a 5xx/empty body** — never ``urllib``, never concurrent.

Models are a **registry**, not a code branch: each entry is a
``(query-prefix, doc-prefix)`` pair keyed by the model id. Prefixes matter — the
default ``nomic-embed-text-v1.5`` expects ``search_query: …`` for a query and
``search_document: …`` for a passage, and getting it wrong silently degrades
ranking — so the prefix is registry data selected by the ``--role`` flag. Adding
``Qwen3-Embedding-0.6B`` later is one registry entry, not a new branch.

Classify-then-dispatch (rule 02) runs in two layers. First on the model id: in
the registry → use its ``(query, document)`` prefix pair and apply the one the
role selects; not in it → quarantine (unknown model) **without touching the
network**. Then on the transport result: a 200 → save the vector; a 5xx/empty
body → wait the recovery gap and retry, and after the retry budget quarantine
(server unreachable). No LLM is ever called to classify or rescue an item.

Runnable from the command line (rule 03):

    uv run embed-text nomic-embed-text-v1.5 abstract.txt --role document
    cat abstract.txt | uv run embed-text nomic-embed-text-v1.5 --role document
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, Callable, Optional
from urllib.parse import urlsplit

import typer

from paper_degist import _manifest
from paper_degist._cli import invoke

# The verified transport constants (US20 report §3). The gap is the ~6–8 s
# recovery window the flapping LM Studio runtime needs between hits; a different
# value is a `--gap` option, not a new path. Total attempts include the first try.
# The default server is the always-on mac mini's LM Studio (serve-on-network
# enabled), not the laptop's own — a laptop-local server is `--endpoint`.
DEFAULT_ENDPOINT = "http://SMTVs-Mac-mini-2.local:1234/v1/embeddings"
DEFAULT_GAP = 7.0
DEFAULT_ATTEMPTS = 3


class Role(str, Enum):
    """Which prefix the registry applies — a query vs. a passage/document."""

    query = "query"
    document = "document"


class TransportError(Exception):
    """A POST that did not return a usable 200 (5xx, empty body, curl failure).

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
class EmbedResponse:
    """One model's answer, parsed from the ``/v1/embeddings`` response."""

    embedding: list[float]


@dataclass(frozen=True)
class EmbedModelSpec:
    """A registered embedding model: the query prefix and the document prefix.

    Getting the prefix wrong (a passage sent with the query prefix, or vice
    versa) silently degrades similarity ranking, so the pair is encoded data
    keyed by the model id and selected by the caller's ``--role``.
    """

    query_prefix: str
    doc_prefix: str

    def prefix_for(self, role: str) -> str:
        """The prefix for ``role`` — the query prefix for ``query``, else the doc one."""
        return self.query_prefix if role == Role.query.value else self.doc_prefix


# The model registry (rule 02: a new model is one entry here, not a branch).
# nomic-embed-text-v1.5's Matryoshka prefixes are its documented task instructions.
REGISTRY: dict[str, EmbedModelSpec] = {
    "nomic-embed-text-v1.5": EmbedModelSpec(
        query_prefix="search_query: ",
        doc_prefix="search_document: ",
    ),
}


# post(model_id, input_text, endpoint) -> EmbedResponse, raising TransportError
# on a 5xx/empty/failed POST. Injected in tests; the default is the curl recipe.
Transport = Callable[[str, str, str], EmbedResponse]


def _default_post(model_id: str, input_text: str, endpoint: str) -> EmbedResponse:
    """POST one text via ``curl --data @body.json`` (the US20 §3 recipe).

    Builds the embeddings body in Python (the already-prefixed text as ``input``),
    writes it to a temp file, and hands it to ``curl`` — never ``urllib``, whose
    POST empty-body-502s and takes the MLX worker down. A non-200, an empty body,
    or a curl failure raises ``TransportError`` for the caller to retry.
    """
    body = {"model": model_id, "input": input_text}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(body, fh)
        body_file = fh.name
    try:
        proc = subprocess.run(
            [
                "curl",
                "-sS",
                # A machine-wide http(s)_proxy must not intercept the LAN
                # endpoint (browser_fetch._no_proxy_for dodges the same trap).
                "--noproxy",
                urlsplit(endpoint).hostname or "*",
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


def _parse_response(stdout: str) -> EmbedResponse:
    """Parse ``curl -w "\\n%{http_code}"`` output into an ``EmbedResponse``.

    The body is everything before the trailing status line. A non-200, an empty
    body, a 200 whose JSON is truncated/off-schema, or a 200 whose ``embedding``
    is not a list all raise ``TransportError`` — a malformed 200 must retry and
    then quarantine like a 502, never crash the step out of the loop (rule 02).
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
        embedding = data["data"][0]["embedding"]
        if not isinstance(embedding, list):
            # A 200 with null / non-list embedding is a flap, not a vector —
            # retry it rather than let a non-vector reach the save path.
            raise TypeError(f"embedding is {type(embedding).__name__}, not list")
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise TransportError(f"unparseable 200 response ({type(exc).__name__}): {exc}") from exc
    return EmbedResponse(embedding=embedding)


def _model_slug(model_id: str) -> str:
    """Filesystem-safe output-dir name for a model id (``a/b`` → ``a_b``)."""
    return model_id.replace("/", "_")


def _text_hash(model_id: str, role: str, text: str) -> str:
    """Content-address a vector by ``(model, role, text)`` — all three matter.

    Two different roles prefix the same text differently, and two different
    texts embed differently, so each triple gets its own cache file; the hash is
    stable across runs so the idempotency skip (AC2) recognizes a repeat.
    """
    digest = hashlib.sha256()
    for part in (model_id, role, text):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")  # length-delimit so ('a','b') != ('ab','')
    return digest.hexdigest()


def _quarantine(manifest_path: Path, *, model: str, role: str, text_hash: str, reason: str) -> None:
    """Append one unhandled-case record to the manifest, so the batch finishes."""
    _manifest.append(
        manifest_path,
        stage="embed-text",
        model=model,
        role=role,
        text_hash=text_hash,
        reason=reason,
    )


def _save(target: Path, payload: dict) -> None:
    """Write the vector JSON atomically so a killed write never leaves a partial
    file that the idempotency skip would mistake for a complete embedding."""
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + ".writing")
    staging.write_text(json.dumps(payload), encoding="utf-8")
    staging.rename(target)


def embed_text(
    text: str,
    model_id: str,
    *,
    role: str = Role.document.value,
    out_dir: Path = Path("out"),
    manifest_path: Path = Path("manifest.jsonl"),
    endpoint: str = DEFAULT_ENDPOINT,
    attempts: int = DEFAULT_ATTEMPTS,
    gap: float = DEFAULT_GAP,
    registry: dict[str, EmbedModelSpec] = REGISTRY,
    post: Transport = _default_post,
    sleep: Callable[[float], None] = time.sleep,
) -> Optional[Path]:
    """Embed ``text`` with ``model_id``; save the vector under
    ``out/embeddings/<model>/<hash>.json``.

    Returns the output path on success (or the already-saved path on a re-run),
    or ``None`` when the text is quarantined — an unknown model (no network
    touched) or a server unreachable after the retry budget. Never crashes,
    never calls an LLM to rescue an item, never fires concurrently (rule 02).
    """
    out_dir = Path(out_dir)
    manifest_path = Path(manifest_path)
    text_hash = _text_hash(model_id, role, text)

    # Layer 1 — classify on the model id, before any network contact.
    spec = registry.get(model_id)
    if spec is None:
        _quarantine(
            manifest_path,
            model=model_id,
            role=role,
            text_hash=text_hash,
            reason=f"unknown model: {model_id!r} not in registry",
        )
        return None

    target = out_dir / "embeddings" / _model_slug(model_id) / f"{text_hash}.json"
    if target.exists():
        return target  # idempotent skip — the model call is the expensive, flaky resource

    input_text = spec.prefix_for(role) + text

    # Layer 2 — dispatch on the transport result: 200 → save; 4xx → fail fast
    # (deterministic); 5xx/empty → wait the recovery gap and retry; after the
    # budget, quarantine (server down).
    last_error: Optional[TransportError] = None
    for attempt in range(attempts):
        if attempt > 0:
            sleep(gap)  # recovery gap before a retry — never a rapid-fire re-hit
        # Time each call individually so the recorded latency is the *successful*
        # request's round-trip, not the retry budget and gaps burned on a flap.
        start = time.monotonic()
        try:
            response = post(model_id, input_text, endpoint)
        except ClientRequestError as exc:
            # Deterministic — retrying a rejected request cannot help; fail fast
            # with a distinct reason rather than burning the retry budget.
            _quarantine(
                manifest_path, model=model_id, role=role, text_hash=text_hash, reason=str(exc)
            )
            return None
        except TransportError as exc:
            last_error = exc
            continue
        dims = len(response.embedding)
        _save(
            target,
            {"model": model_id, "role": role, "dims": dims, "embedding": response.embedding},
        )
        _manifest.append(
            manifest_path,
            stage="embed-text",
            model=model_id,
            role=role,
            text_hash=text_hash,
            dims=dims,
            latency=round(time.monotonic() - start, 3),
        )
        return target

    _quarantine(
        manifest_path,
        model=model_id,
        role=role,
        text_hash=text_hash,
        reason=f"server unreachable after {attempts} attempts: {last_error}",
    )
    return None


app = typer.Typer(
    add_completion=False,
    help="Embed one text with one registered local embedding model (US24).",
)


@app.command()
def run(
    model: Annotated[
        str,
        typer.Argument(help="a registered model id, e.g. nomic-embed-text-v1.5"),
    ],
    text_file: Annotated[
        Optional[Path],
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="text file to embed; reads stdin when omitted",
        ),
    ] = None,
    role: Annotated[
        Role,
        typer.Option(help="apply the model's query or document prefix"),
    ] = Role.document,
    out_dir: Annotated[
        Path,
        typer.Option("--out-dir", help="directory to save vectors under (out/embeddings/<model>/)"),
    ] = Path("out"),
    endpoint: Annotated[
        str,
        typer.Option(help="embeddings endpoint of the local model server"),
    ] = DEFAULT_ENDPOINT,
    attempts: Annotated[int, typer.Option(help="max POST attempts before quarantine")] = DEFAULT_ATTEMPTS,
    gap: Annotated[float, typer.Option(help="recovery gap (seconds) between retries")] = DEFAULT_GAP,
    manifest: Annotated[
        Path,
        typer.Option(help="manifest of embed records and quarantined texts"),
    ] = Path("manifest.jsonl"),
) -> None:
    """Embed the text; print the saved vector path, or a quarantine note on stderr."""
    text = text_file.read_text(encoding="utf-8") if text_file else sys.stdin.read()
    target = embed_text(
        text,
        model,
        role=role.value,
        out_dir=out_dir,
        manifest_path=manifest,
        endpoint=endpoint,
        attempts=attempts,
        gap=gap,
    )
    if target is None:
        # Quarantine is an expected outcome, not a crash: the batch still
        # finishes. Note it on stderr and exit cleanly.
        typer.echo(f"quarantined (see {manifest}): {model} + role={role.value}", err=True)
        return
    typer.echo(str(target))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run embed-text`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
