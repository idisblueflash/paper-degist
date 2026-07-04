"""Unit tests for US20 ocr_page (pytest).

One assertion per test (rule 05): each test fails for exactly one reason. The
flaky vision-model transport is injected as ``post`` so these stay fast and
offline (rule 01) — the real ``curl``-to-LM-Studio transport is exercised
end-to-end (rule 06 §7), not here. Distinct example pages/models per case
(rule 08) label what each exercises.
"""

import json
from pathlib import Path

import pytest

from paper_degist.ocr_page import (
    REGISTRY,
    OcrResponse,
    TransportError,
    _decode_grounding,
    _parse_response,
    _strip_markdown_fence,
    ocr_page,
)


# --- qwen post-processor: strip the ```markdown fence it wraps output in ---


def test_strip_markdown_fence_unwraps_fenced_markdown():
    fenced = "```markdown\n# Title\n\nBody text.\n```"
    assert _strip_markdown_fence(fenced) == "# Title\n\nBody text."


def test_strip_markdown_fence_leaves_unfenced_markdown_untouched():
    assert _strip_markdown_fence("# Already clean\n\nno fence") == "# Already clean\n\nno fence"


# --- DeepSeek post-processor: decode grounding markup to plain markdown ---


def test_decode_grounding_drops_detection_boxes():
    grounded = "<|ref|>Heading<|/ref|><|det|>[[10, 20, 30, 40]]<|/det|>"
    assert _decode_grounding(grounded) == "Heading"


def test_decode_grounding_leaves_plain_text_untouched():
    assert _decode_grounding("Just a paragraph.") == "Just a paragraph."


# --- the registry maps model ids to their (prompt, post-processor) entry ---


def test_qwen_is_registered():
    assert "qwen/qwen3-vl-4b" in REGISTRY


def test_deepseek_prompt_omits_the_literal_image_token():
    # LM Studio 400s on a double image if the prompt carries a literal <image>;
    # the grounding prompt must not (report §3 / registry-encoded quirk).
    assert "<image>" not in REGISTRY["deepseek-ocr"].prompt


# --- orchestrator: shared arrange/act (rule 05 — factor setup into helpers) ---


def _page(tmp_path: Path, name="p02.png") -> Path:
    """A saved page PNG under pages/WordCraft/ (the render-pdf output shape)."""
    pages = tmp_path / "pages" / "WordCraft"
    pages.mkdir(parents=True)
    page = pages / name
    page.write_bytes(b"\x89PNG page bytes")
    return page


def _ok_post(content="# Doc\n\nbody", finish_reason="stop", completion_tokens=42):
    """A transport that always answers 200 with the given payload; records calls."""

    def post(model_id, prompt, image_path, endpoint):
        post.calls.append((model_id, prompt, image_path, endpoint))
        return OcrResponse(content, finish_reason, completion_tokens)

    post.calls = []
    return post


def _boom_post():
    """A transport that always 502s; records calls so we can assert non-contact."""

    def post(model_id, prompt, image_path, endpoint):
        post.calls.append((model_id, prompt, image_path, endpoint))
        raise TransportError("server returned 502")

    post.calls = []
    return post


def _fail_then_ok(n_fail: int, content="# Recovered"):
    """A transport that 502s ``n_fail`` times, then answers 200 (flap recovery)."""

    def post(model_id, prompt, image_path, endpoint):
        post.calls.append((model_id, prompt, image_path, endpoint))
        if len(post.calls) <= n_fail:
            raise TransportError("server returned 502")
        return OcrResponse(content, "stop", 7)

    post.calls = []
    return post


def _run(tmp_path: Path, *, model="qwen/qwen3-vl-4b", post=None, attempts=3, page_name="p02.png"):
    """Run ocr_page with an injected transport, a zero-cost sleep, and a temp out/."""
    page = _page(tmp_path, name=page_name)
    manifest = tmp_path / "manifest.jsonl"
    sleeps: list[float] = []
    result = ocr_page(
        page,
        model,
        out_dir=tmp_path / "out",
        manifest_path=manifest,
        post=post if post is not None else _ok_post(),
        attempts=attempts,
        gap=7.0,
        sleep=sleeps.append,
    )
    return result, page, manifest, sleeps


def _only_record(manifest: Path):
    (line,) = manifest.read_text(encoding="utf-8").splitlines()
    return json.loads(line)


# --- happy path: post-process, save under out/<model>/<page>.md, record (AC1) ---


def test_success_returns_the_output_path(tmp_path: Path):
    result, _, _, _ = _run(tmp_path)
    assert result == tmp_path / "out" / "qwen_qwen3-vl-4b" / "p02.md"


def test_success_saves_under_the_model_slug_dir(tmp_path: Path):
    result, _, _, _ = _run(tmp_path)
    assert result.parent.name == "qwen_qwen3-vl-4b"


def test_success_writes_the_postprocessed_markdown(tmp_path: Path):
    # qwen wraps output in a ```markdown fence; the saved file is the unwrapped md.
    result, _, _, _ = _run(tmp_path, post=_ok_post(content="```markdown\n# Clean\n```"))
    assert result.read_text(encoding="utf-8") == "# Clean"


def test_success_manifest_records_ocr_page_stage(tmp_path: Path):
    _, _, manifest, _ = _run(tmp_path)
    assert _only_record(manifest)["stage"] == "ocr-page"


def test_success_manifest_records_the_model(tmp_path: Path):
    _, _, manifest, _ = _run(tmp_path)
    assert _only_record(manifest)["model"] == "qwen/qwen3-vl-4b"


def test_success_manifest_records_the_finish_reason(tmp_path: Path):
    _, _, manifest, _ = _run(tmp_path, post=_ok_post(finish_reason="length"))
    assert _only_record(manifest)["finish_reason"] == "length"


def test_success_manifest_records_the_completion_tokens(tmp_path: Path):
    _, _, manifest, _ = _run(tmp_path, post=_ok_post(completion_tokens=1234))
    assert _only_record(manifest)["completion_tokens"] == 1234


def test_success_manifest_records_a_numeric_latency(tmp_path: Path):
    _, _, manifest, _ = _run(tmp_path)
    assert isinstance(_only_record(manifest)["latency"], (int, float))


# --- idempotent skip: an already-saved (page, model) must not re-hit the server (AC2) ---


def _run_with_existing(tmp_path: Path, post):
    """Pre-save out/<slug>/p02.md, then run again on the same page + model."""
    page = _page(tmp_path)
    target = tmp_path / "out" / "qwen_qwen3-vl-4b" / "p02.md"
    target.parent.mkdir(parents=True)
    target.write_text("# already OCR'd", encoding="utf-8")
    manifest = tmp_path / "manifest.jsonl"
    result = ocr_page(
        page, "qwen/qwen3-vl-4b", out_dir=tmp_path / "out", manifest_path=manifest,
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
    result, _, _, _ = _run(tmp_path, model="some-unregistered-ocr", post=_boom_post())
    assert result is None


def test_unknown_model_does_not_hit_the_network(tmp_path: Path):
    post = _boom_post()
    _run(tmp_path, model="some-unregistered-ocr", post=post)
    assert post.calls == []


def test_unknown_model_reason_names_the_unknown_model(tmp_path: Path):
    _, _, manifest, _ = _run(tmp_path, model="some-unregistered-ocr", post=_boom_post())
    assert "unknown model" in _only_record(manifest)["reason"]


def test_unknown_model_reason_is_distinct_from_a_server_error(tmp_path: Path):
    _, _, manifest, _ = _run(tmp_path, model="some-unregistered-ocr", post=_boom_post())
    assert "server" not in _only_record(manifest)["reason"]


def test_unknown_model_manifest_records_ocr_page_stage(tmp_path: Path):
    _, _, manifest, _ = _run(tmp_path, model="some-unregistered-ocr", post=_boom_post())
    assert _only_record(manifest)["stage"] == "ocr-page"


# --- 502/flapping runtime: retry after a gap, then quarantine cleanly (AC3) ---


def test_server_down_after_retries_returns_none(tmp_path: Path):
    result, _, _, _ = _run(tmp_path, post=_boom_post(), attempts=3)
    assert result is None


def test_server_down_reason_names_server_unreachable(tmp_path: Path):
    _, _, manifest, _ = _run(tmp_path, post=_boom_post(), attempts=3)
    assert "server unreachable" in _only_record(manifest)["reason"]


def test_server_down_retries_up_to_the_attempt_budget(tmp_path: Path):
    post = _boom_post()
    _run(tmp_path, post=post, attempts=3)
    assert len(post.calls) == 3


def test_server_down_waits_the_recovery_gap_between_attempts(tmp_path: Path):
    _, _, _, sleeps = _run(tmp_path, post=_boom_post(), attempts=3)
    assert sleeps == [7.0, 7.0]  # a gap before each retry, none before the first try


def test_server_down_writes_no_output_file(tmp_path: Path):
    _run(tmp_path, post=_boom_post(), attempts=3)
    assert not (tmp_path / "out" / "qwen_qwen3-vl-4b" / "p02.md").exists()


def test_flap_recovers_and_saves_when_a_retry_succeeds(tmp_path: Path):
    result, _, _, _ = _run(tmp_path, post=_fail_then_ok(1), attempts=3)
    assert result == tmp_path / "out" / "qwen_qwen3-vl-4b" / "p02.md"


def test_flap_recovery_stops_retrying_once_it_succeeds(tmp_path: Path):
    post = _fail_then_ok(1)
    _run(tmp_path, post=post, attempts=3)
    assert len(post.calls) == 2  # one 502, then the success — no further tries


# --- transport parse: a 200 with bad JSON/schema must retry+quarantine, not crash (rule 02) ---
#
# `curl -w "\n%{http_code}"` appends the status as a final line, so the parser's
# input is the response body, a newline, then the HTTP code.


def _curl_stdout(body: str, code: str = "200") -> str:
    return f"{body}\n{code}"


def _chat_json(content="# Doc", finish_reason="stop", completion_tokens=9) -> str:
    return json.dumps(
        {
            "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
            "usage": {"completion_tokens": completion_tokens},
        }
    )


def test_parse_response_extracts_the_content():
    assert _parse_response(_curl_stdout(_chat_json(content="# Real Page"))).content == "# Real Page"


def test_parse_response_extracts_the_completion_tokens():
    assert _parse_response(_curl_stdout(_chat_json(completion_tokens=321))).completion_tokens == 321


def test_parse_non_200_raises_transport_error():
    with pytest.raises(TransportError):
        _parse_response(_curl_stdout(_chat_json(), code="502"))


def test_parse_empty_body_raises_transport_error():
    with pytest.raises(TransportError):
        _parse_response(_curl_stdout("", code="200"))


def test_parse_malformed_json_raises_transport_error():
    # A 200 whose body is truncated/not JSON must convert to a retryable error,
    # never a raw JSONDecodeError out of the step (Codex review).
    with pytest.raises(TransportError):
        _parse_response(_curl_stdout("{not: valid json", code="200"))


def test_parse_unexpected_schema_raises_transport_error():
    # A 200 with valid JSON but no choices[0].message.content (a wrong schema)
    # must also become a retryable TransportError, not a KeyError.
    with pytest.raises(TransportError):
        _parse_response(_curl_stdout(json.dumps({"error": "model not loaded"}), code="200"))
