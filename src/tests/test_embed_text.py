"""Unit tests for US24 embed_text (pytest).

One assertion per test (rule 05): each test fails for exactly one reason. The
flaky embedding-model transport is injected as ``post`` so these stay fast and
offline (rule 01) — the real ``curl``-to-LM-Studio transport is exercised
end-to-end (rule 06 §7), not here. Distinct example texts/models/roles per case
(rule 08) label what each exercises.
"""

import json
from pathlib import Path

import pytest

from paper_degist.embed_text import (
    DEFAULT_ENDPOINT,
    REGISTRY,
    ClientRequestError,
    EmbedResponse,
    TransportError,
    _default_post,
    _parse_response,
    _text_hash,
    embed_text,
)


# --- the registry maps a model id to its (query, document) prefix pair ---


def test_nomic_is_registered():
    assert "nomic-embed-text-v1.5" in REGISTRY


def test_document_role_selects_the_search_document_prefix():
    assert REGISTRY["nomic-embed-text-v1.5"].prefix_for("document") == "search_document: "


def test_query_role_selects_the_search_query_prefix():
    assert REGISTRY["nomic-embed-text-v1.5"].prefix_for("query") == "search_query: "


# --- the cache key is a hash of (model, role, text) — all three matter ---


def test_text_hash_differs_when_the_role_differs():
    query = _text_hash("nomic-embed-text-v1.5", "query", "spaced repetition")
    document = _text_hash("nomic-embed-text-v1.5", "document", "spaced repetition")
    assert query != document


def test_text_hash_differs_when_the_text_differs():
    a = _text_hash("nomic-embed-text-v1.5", "document", "retrieval practice")
    b = _text_hash("nomic-embed-text-v1.5", "document", "elaborative interrogation")
    assert a != b


# --- orchestrator: shared arrange/act (rule 05 — factor setup into helpers) ---


def _ok_post(embedding=None):
    """A transport that always answers 200 with the given vector; records calls."""
    if embedding is None:
        embedding = [0.1, 0.2, 0.3]

    def post(model_id, text, endpoint):
        post.calls.append((model_id, text, endpoint))
        return EmbedResponse(list(embedding))

    post.calls = []
    return post


def _boom_post():
    """A transport that always 502s; records calls so we can assert non-contact."""

    def post(model_id, text, endpoint):
        post.calls.append((model_id, text, endpoint))
        raise TransportError("server returned 502")

    post.calls = []
    return post


def _fail_then_ok(n_fail: int, embedding=(0.4, 0.5)):
    """A transport that 502s ``n_fail`` times, then answers 200 (flap recovery)."""

    def post(model_id, text, endpoint):
        post.calls.append((model_id, text, endpoint))
        if len(post.calls) <= n_fail:
            raise TransportError("server returned 502")
        return EmbedResponse(list(embedding))

    post.calls = []
    return post


def _client_error_post():
    """A transport that rejects with a 4xx (deterministic — retrying cannot help)."""

    def post(model_id, text, endpoint):
        post.calls.append((model_id, text, endpoint))
        raise ClientRequestError("request rejected: server returned 400")

    post.calls = []
    return post


def _run(
    tmp_path: Path,
    *,
    text="Spaced repetition improves long-term retention.",
    model="nomic-embed-text-v1.5",
    role="document",
    post=None,
    attempts=3,
):
    """Run embed_text with an injected transport, a zero-cost sleep, and a temp out/."""
    manifest = tmp_path / "manifest.jsonl"
    sleeps: list[float] = []
    result = embed_text(
        text,
        model,
        role=role,
        out_dir=tmp_path / "out",
        manifest_path=manifest,
        post=post if post is not None else _ok_post(),
        attempts=attempts,
        gap=7.0,
        sleep=sleeps.append,
    )
    return result, manifest, sleeps


def _only_record(manifest: Path):
    (line,) = manifest.read_text(encoding="utf-8").splitlines()
    return json.loads(line)


# --- happy path: prefix, save under out/embeddings/<model>/<hash>.json, record (AC1) ---


def test_success_returns_the_output_path(tmp_path: Path):
    text = "Retrieval practice strengthens memory."
    result, _, _ = _run(tmp_path, text=text)
    expected = (
        tmp_path
        / "out"
        / "embeddings"
        / "nomic-embed-text-v1.5"
        / f"{_text_hash('nomic-embed-text-v1.5', 'document', text)}.json"
    )
    assert result == expected


def test_success_saves_under_the_embeddings_model_dir(tmp_path: Path):
    result, _, _ = _run(tmp_path)
    assert result.parent == tmp_path / "out" / "embeddings" / "nomic-embed-text-v1.5"


def test_success_applies_the_role_prefix_to_the_posted_text(tmp_path: Path):
    post = _ok_post()
    _run(tmp_path, text="cats sleep a lot", role="query", post=post)
    (_, posted_text, _) = post.calls[0]
    assert posted_text == "search_query: cats sleep a lot"


def test_success_saves_the_embedding_vector(tmp_path: Path):
    result, _, _ = _run(tmp_path, post=_ok_post(embedding=[1.0, 2.0, 3.0, 4.0]))
    assert json.loads(result.read_text(encoding="utf-8"))["embedding"] == [1.0, 2.0, 3.0, 4.0]


def test_success_manifest_records_embed_text_stage(tmp_path: Path):
    _, manifest, _ = _run(tmp_path)
    assert _only_record(manifest)["stage"] == "embed-text"


def test_success_manifest_records_the_model(tmp_path: Path):
    _, manifest, _ = _run(tmp_path)
    assert _only_record(manifest)["model"] == "nomic-embed-text-v1.5"


def test_success_manifest_records_the_role(tmp_path: Path):
    _, manifest, _ = _run(tmp_path, role="query")
    assert _only_record(manifest)["role"] == "query"


def test_success_manifest_records_the_dims(tmp_path: Path):
    _, manifest, _ = _run(tmp_path, post=_ok_post(embedding=[0.0] * 768))
    assert _only_record(manifest)["dims"] == 768


def test_success_manifest_records_a_numeric_latency(tmp_path: Path):
    _, manifest, _ = _run(tmp_path)
    assert isinstance(_only_record(manifest)["latency"], (int, float))


# --- idempotent skip: an already-saved (model, role, text) must not re-hit the server (AC2) ---


def _run_with_existing(tmp_path: Path, post, *, role="document"):
    """Pre-save the target vector, then run again on the same text + model + role."""
    text = "Interleaving beats blocked practice."
    model = "nomic-embed-text-v1.5"
    target = (
        tmp_path
        / "out"
        / "embeddings"
        / model
        / f"{_text_hash(model, role, text)}.json"
    )
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"embedding": [9.9]}), encoding="utf-8")
    manifest = tmp_path / "manifest.jsonl"
    result = embed_text(
        text, model, role=role, out_dir=tmp_path / "out", manifest_path=manifest,
        post=post, sleep=lambda _s: None,
    )
    return result, target, manifest


def test_idempotent_skip_returns_the_existing_path(tmp_path: Path):
    result, target, _ = _run_with_existing(tmp_path, post=_boom_post())
    assert result == target


def test_idempotent_skip_does_not_hit_the_server(tmp_path: Path):
    post = _boom_post()  # raises if called; a clean return proves it was skipped
    _run_with_existing(tmp_path, post=post)
    assert post.calls == []


def test_idempotent_skip_writes_no_manifest_record(tmp_path: Path):
    _, _, manifest = _run_with_existing(tmp_path, post=_ok_post())
    assert not manifest.exists()


# --- unknown model: quarantine without touching the network, distinctly (AC4) ---


def test_unknown_model_returns_none(tmp_path: Path):
    result, _, _ = _run(tmp_path, model="some-unregistered-embed", post=_boom_post())
    assert result is None


def test_unknown_model_does_not_hit_the_network(tmp_path: Path):
    post = _boom_post()
    _run(tmp_path, model="some-unregistered-embed", post=post)
    assert post.calls == []


def test_unknown_model_reason_names_the_unknown_model(tmp_path: Path):
    _, manifest, _ = _run(tmp_path, model="some-unregistered-embed", post=_boom_post())
    assert "unknown model" in _only_record(manifest)["reason"]


def test_unknown_model_reason_is_distinct_from_a_server_error(tmp_path: Path):
    _, manifest, _ = _run(tmp_path, model="some-unregistered-embed", post=_boom_post())
    assert "server" not in _only_record(manifest)["reason"]


def test_unknown_model_manifest_records_embed_text_stage(tmp_path: Path):
    _, manifest, _ = _run(tmp_path, model="some-unregistered-embed", post=_boom_post())
    assert _only_record(manifest)["stage"] == "embed-text"


# --- 502/flapping runtime: retry after a gap, then quarantine cleanly (AC3) ---


def test_server_down_after_retries_returns_none(tmp_path: Path):
    result, _, _ = _run(tmp_path, post=_boom_post(), attempts=3)
    assert result is None


def test_server_down_reason_names_server_unreachable(tmp_path: Path):
    _, manifest, _ = _run(tmp_path, post=_boom_post(), attempts=3)
    assert "server unreachable" in _only_record(manifest)["reason"]


def test_server_down_retries_up_to_the_attempt_budget(tmp_path: Path):
    post = _boom_post()
    _run(tmp_path, post=post, attempts=3)
    assert len(post.calls) == 3


def test_server_down_waits_the_recovery_gap_between_attempts(tmp_path: Path):
    _, _, sleeps = _run(tmp_path, post=_boom_post(), attempts=3)
    assert sleeps == [7.0, 7.0]  # a gap before each retry, none before the first try


def test_server_down_writes_no_output_file(tmp_path: Path):
    text = "Testing effect."
    _run(tmp_path, text=text, post=_boom_post(), attempts=3)
    target = (
        tmp_path / "out" / "embeddings" / "nomic-embed-text-v1.5"
        / f"{_text_hash('nomic-embed-text-v1.5', 'document', text)}.json"
    )
    assert not target.exists()


def test_flap_recovers_and_saves_when_a_retry_succeeds(tmp_path: Path):
    result, _, _ = _run(tmp_path, post=_fail_then_ok(1), attempts=3)
    assert result is not None


def test_flap_recovery_stops_retrying_once_it_succeeds(tmp_path: Path):
    post = _fail_then_ok(1)
    _run(tmp_path, post=post, attempts=3)
    assert len(post.calls) == 2  # one 502, then the success — no further tries


# --- client error (4xx): fail fast, distinct reason, no retry ---


def test_client_error_returns_none(tmp_path: Path):
    result, _, _ = _run(tmp_path, post=_client_error_post(), attempts=3)
    assert result is None


def test_client_error_quarantines_without_retrying(tmp_path: Path):
    post = _client_error_post()
    _run(tmp_path, post=post, attempts=3)
    assert len(post.calls) == 1  # deterministic — no retry burned on a rejected request


def test_client_error_reason_is_distinct_from_server_unreachable(tmp_path: Path):
    _, manifest, _ = _run(tmp_path, post=_client_error_post(), attempts=3)
    assert "server unreachable" not in _only_record(manifest)["reason"]


# --- transport parse: a 200 with bad JSON/schema must retry+quarantine, not crash (rule 02) ---
#
# `curl -w "\n%{http_code}"` appends the status as a final line, so the parser's
# input is the response body, a newline, then the HTTP code.


def _curl_stdout(body: str, code: str = "200") -> str:
    return f"{body}\n{code}"


def _embed_json(embedding=(0.1, 0.2, 0.3)) -> str:
    return json.dumps({"data": [{"embedding": list(embedding)}]})


def test_parse_response_extracts_the_embedding():
    assert _parse_response(_curl_stdout(_embed_json((1.0, 2.0)))).embedding == [1.0, 2.0]


def test_parse_non_200_raises_transport_error():
    with pytest.raises(TransportError):
        _parse_response(_curl_stdout(_embed_json(), code="502"))


def test_parse_empty_body_raises_transport_error():
    with pytest.raises(TransportError):
        _parse_response(_curl_stdout("", code="200"))


def test_parse_malformed_json_raises_transport_error():
    # A 200 whose body is truncated/not JSON must convert to a retryable error,
    # never a raw JSONDecodeError out of the step.
    with pytest.raises(TransportError):
        _parse_response(_curl_stdout("{not: valid json", code="200"))


def test_parse_unexpected_schema_raises_transport_error():
    # A 200 with valid JSON but no data[0].embedding (a wrong schema) must also
    # become a retryable TransportError, not a KeyError.
    with pytest.raises(TransportError):
        _parse_response(_curl_stdout(json.dumps({"error": "model not loaded"}), code="200"))


def test_parse_non_list_embedding_raises_transport_error():
    # A 200 whose embedding is null / not a list must convert to a retryable
    # TransportError — never reach the save path with a non-vector.
    body = json.dumps({"data": [{"embedding": None}]})
    with pytest.raises(TransportError):
        _parse_response(_curl_stdout(body, code="200"))


def test_parse_client_error_raises_client_request_error():
    # A 4xx is a deterministic client error (e.g. a rejected body); it must be a
    # ClientRequestError so the orchestrator can fail fast instead of retrying.
    with pytest.raises(ClientRequestError):
        _parse_response(_curl_stdout("", code="400"))


def test_default_post_curl_missing_raises_transport_error(monkeypatch):
    # curl absent from PATH → subprocess raises FileNotFoundError; the transport
    # must convert it to a retryable TransportError, never crash the batch.
    def boom_run(*args, **kwargs):
        raise FileNotFoundError("curl")

    monkeypatch.setattr("paper_degist.embed_text.subprocess.run", boom_run)
    with pytest.raises(TransportError):
        _default_post("nomic-embed-text-v1.5", "search_document: hi", DEFAULT_ENDPOINT)
