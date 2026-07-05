"""Unit tests for US20 ocr_page (pytest).

One assertion per test (rule 05): each test fails for exactly one reason. The
flaky vision-model transport is injected as ``post`` so these stay fast and
offline (rule 01) — the real ``curl``-to-LM-Studio transport is exercised
end-to-end (rule 06 §7), not here. Distinct example pages/models per case
(rule 08) label what each exercises.
"""

import json
import time
from pathlib import Path

import pytest

from paper_degist.ocr_page import (
    DEFAULT_ENDPOINT,
    REGISTRY,
    ClientRequestError,
    ModelSpec,
    OcrResponse,
    TransportError,
    _LAYOUT_LABELS,
    _decode_grounding,
    _decode_grounding_layout,
    _default_post,
    _parse_response,
    _strip_markdown_fence,
    ocr_page,
    output_path,
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


# --- DeepSeek-OCR-2/8bit post-processor: the ref slot holds a layout *category*
# (text/sub_title/table/…), not the text — drop the label, keep the content ---


def test_decode_grounding_layout_drops_the_category_label():
    # deepseek-ocr-2 emits <|ref|>CATEGORY<|/ref|> then the content on the next
    # line; the decode drops the category (opposite of base deepseek-ocr, which
    # keeps the ref slot because it holds the actual text).
    grounded = "<|ref|>sub_title<|/ref|><|det|>[[84, 700, 203, 715]]<|/det|>\n## Results"
    assert _decode_grounding_layout(grounded) == "## Results"


def test_decode_grounding_layout_separates_blocks_with_one_blank_line():
    # Removing the markers leaves a 3-newline gap between two content blocks; it
    # collapses to a single paragraph break so the markdown stays clean.
    grounded = (
        "<|ref|>text<|/ref|><|det|>[[1, 2, 3, 4]]<|/det|>\nFirst paragraph.\n\n"
        "<|ref|>text<|/ref|><|det|>[[5, 6, 7, 8]]<|/det|>\nSecond paragraph."
    )
    assert _decode_grounding_layout(grounded) == "First paragraph.\n\nSecond paragraph."


def test_decode_grounding_layout_keeps_content_when_a_label_is_unclosed():
    # A malformed <|ref|> opener (no closer) must not let the label strip run to
    # the *next* block's <|/ref|> and delete the content in between (Codex review):
    # never silently drop OCR'd text. The label region can't contain '<', so a
    # runaway match is impossible; the stray marker is swept, the content stays.
    grounded = (
        "<|ref|>Alpha content\n\n"
        "<|ref|>text<|/ref|><|det|>[[1, 2, 3, 4]]<|/det|>\nBeta"
    )
    assert _decode_grounding_layout(grounded) == "Alpha content\n\nBeta"


def test_decode_grounding_layout_drops_a_bare_unwrapped_category_line():
    # On some pages the model degrades and emits the layout category as a *bare*
    # line with no <|ref|> wrapper, then the content — those bare `text`/`sub_title`
    # lines slipped past the ref-only strip and became the dup_pct artifact
    # (deepseek-ocr-2's j.ergon.2003.12.002.pdf_5 page). Drop the bare label too,
    # keep the content, and collapse the gap it leaves.
    grounded = (
        "text\n(ii) Muscle activity was recorded bilaterally.\n\n"
        "sub_title\n\n## 2.4.1. Electrogoniometry"
    )
    assert _decode_grounding_layout(grounded) == (
        "(ii) Muscle activity was recorded bilaterally.\n\n## 2.4.1. Electrogoniometry"
    )


def test_decode_grounding_layout_normalizes_crlf_before_collapsing_gaps():
    # CRLF output must normalize like the qwen decode (_strip_markdown_fence) or the
    # \n{3,} collapse misses \r\n gaps and leaves a triple break (Codex review).
    grounded = (
        "<|ref|>text<|/ref|><|det|>[[1, 2, 3, 4]]<|/det|>\r\nAlpha.\r\n\r\n"
        "<|ref|>text<|/ref|><|det|>[[5, 6, 7, 8]]<|/det|>\r\nBeta."
    )
    assert _decode_grounding_layout(grounded) == "Alpha.\n\nBeta."


# `_LAYOUT_LABELS` (the categories DeepSeek-OCR-2 emits in the ref slot) is imported
# from the production module — one source of truth, so a category added there is
# covered here without editing a second copy.
_GROUNDING_PAGE = Path(__file__).parent / "samples" / "deepseek-ocr-2-grounding-page.txt"


def test_decode_grounding_layout_leaves_no_bare_category_line_on_a_real_page():
    # Captured live from deepseek-ocr-2 (rule 06 §2 ground truth). Decoding must
    # leave no standalone category word — those bare lines were the dup_pct artifact.
    decoded = _decode_grounding_layout(_GROUNDING_PAGE.read_text(encoding="utf-8"))
    bare = [line for line in decoded.splitlines() if line in _LAYOUT_LABELS]
    assert bare == []


def test_decode_grounding_layout_preserves_content_on_a_real_page():
    # Dropping the label must not eat the content block it introduced: the table
    # under the <|ref|>table<|/ref|> label survives intact.
    decoded = _decode_grounding_layout(_GROUNDING_PAGE.read_text(encoding="utf-8"))
    assert "<table>" in decoded


def test_decode_grounding_layout_leaves_no_grounding_markup_on_a_real_page():
    # Beyond bare labels: no <|ref|>/<|det|> marker of any kind may survive, or a
    # leaked token would ride into the Markdown undetected (Codex review).
    decoded = _decode_grounding_layout(_GROUNDING_PAGE.read_text(encoding="utf-8"))
    residual = [m for m in ("<|ref|>", "<|/ref|>", "<|det|>", "<|/det|>") if m in decoded]
    assert residual == []


def test_decode_grounding_layout_keeps_content_after_the_table_on_a_real_page():
    # The final figure caption sits *after* the big <|ref|>table<|/ref|> block; assert
    # it survives, so an over-removal that deletes everything past the table cannot
    # pass the preservation check silently (Codex review).
    decoded = _decode_grounding_layout(_GROUNDING_PAGE.read_text(encoding="utf-8"))
    assert "Figure 1: Coverage as a function of the fraction of RBS variables" in decoded


# --- the registry maps model ids to their (prompt, post-processor) entry ---


def test_qwen_is_registered():
    assert "qwen/qwen3-vl-4b" in REGISTRY


def test_deepseek_prompt_omits_the_literal_image_token():
    # LM Studio 400s on a double image if the prompt carries a literal <image>;
    # the grounding prompt must not (report §3 / registry-encoded quirk).
    assert "<image>" not in REGISTRY["deepseek-ocr"].prompt


def test_deepseek_ocr_2_registered_with_grounding_spec():
    # A DeepSeek OCR variant; grounding prompt, but the *layout* decode — its ref
    # slot holds a category, not text. Assert the whole ModelSpec (one logical
    # fact) so a prompt typo / wrong postprocessor can't slip past (rule 05).
    assert REGISTRY["deepseek-ocr-2"] == ModelSpec(
        prompt="<|grounding|>Convert the document to markdown.",
        postprocess=_decode_grounding_layout,
    )


def test_deepseek_ocr_8bit_registered_with_grounding_spec():
    # The 8-bit quant of the same -2 model; same grammar → same layout decode. Its
    # id keeps the '@' in the output dir slug (_model_slug only rewrites '/').
    assert REGISTRY["deepseek-ocr@8bit"] == ModelSpec(
        prompt="<|grounding|>Convert the document to markdown.",
        postprocess=_decode_grounding_layout,
    )


# --- output_path: the single source of truth for out/<model>/<page>.md ---


def test_output_path_slugs_the_model_and_keeps_the_page_stem():
    assert output_path(Path("pages/WordCraft/p02.png"), "qwen/qwen3-vl-4b", Path("out")) == (
        Path("out/qwen_qwen3-vl-4b/p02.md")
    )


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


def _run(tmp_path: Path, *, model="qwen/qwen3-vl-4b", post=None, attempts=3, page_name="p02.png", hostname=None):
    """Run ocr_page with an injected transport, a zero-cost sleep, and a temp out/."""
    page = _page(tmp_path, name=page_name)
    manifest = tmp_path / "manifest.jsonl"
    sleeps: list[float] = []
    kwargs = {} if hostname is None else {"hostname": hostname}
    result = ocr_page(
        page,
        model,
        out_dir=tmp_path / "out",
        manifest_path=manifest,
        post=post if post is not None else _ok_post(),
        attempts=attempts,
        gap=7.0,
        sleep=sleeps.append,
        **kwargs,
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


def test_success_manifest_records_the_host(tmp_path: Path):
    # latency is machine-dependent, so the producing machine is recorded to keep
    # a mixed-host scores.jsonl attributable (DEVLOG: host recorded, not segmented).
    _, _, manifest, _ = _run(tmp_path, hostname=lambda: "mac-mini.local")
    assert _only_record(manifest)["host"] == "mac-mini.local"


def test_success_latency_excludes_the_hostname_lookup(tmp_path: Path):
    # the host lookup must not fold into latency — that is the machine-speed signal
    # host recording exists to keep clean (Codex review). A 0.2s hostname vs a
    # near-instant fake transport leaves a wide margin, so the bound is not flaky.
    def slow_hostname() -> str:
        time.sleep(0.2)
        return "mac-mini.local"

    _, _, manifest, _ = _run(tmp_path, hostname=slow_hostname)
    assert _only_record(manifest)["latency"] < 0.1


def _raising_hostname() -> str:
    raise RuntimeError("hostname lookup failed")


def test_a_raising_hostname_still_returns_the_output_path(tmp_path: Path):
    # a hostname lookup failure must not lose the OCR — the row it annotates is
    # still written and the call still succeeds (never crash, rule 02; Codex review).
    result, _, _, _ = _run(tmp_path, hostname=_raising_hostname)
    assert result == tmp_path / "out" / "qwen_qwen3-vl-4b" / "p02.md"


def test_a_raising_hostname_records_a_null_host(tmp_path: Path):
    _, _, manifest, _ = _run(tmp_path, hostname=_raising_hostname)
    assert _only_record(manifest)["host"] is None


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


# --- hardening (US20 follow-up): CRLF, null content, 4xx fast-fail, missing file ---


def test_strip_markdown_fence_handles_crlf_line_endings():
    # A qwen answer with \r\n line endings must still have its outer fence
    # stripped, not saved verbatim with the fence intact.
    assert _strip_markdown_fence("```markdown\r\n# H\r\n```") == "# H"


def test_parse_null_content_raises_transport_error():
    # A 200 whose choices[0].message.content is JSON null (not a string) must
    # convert to a retryable TransportError — never reach the post-processor and
    # AttributeError on None.strip().
    body = json.dumps({"choices": [{"message": {"content": None}}], "usage": {}})
    with pytest.raises(TransportError):
        _parse_response(_curl_stdout(body, code="200"))


def test_parse_client_error_raises_client_request_error():
    # A 4xx is a deterministic client error (e.g. a rejected body); it must be a
    # ClientRequestError so the orchestrator can fail fast instead of retrying.
    with pytest.raises(ClientRequestError):
        _parse_response(_curl_stdout("", code="400"))


def _client_error_post():
    """A transport that rejects with a 4xx (deterministic — retrying cannot help)."""

    def post(model_id, prompt, image_path, endpoint):
        post.calls.append((model_id, prompt, image_path, endpoint))
        raise ClientRequestError("request rejected: server returned 400")

    post.calls = []
    return post


def test_client_error_returns_none(tmp_path: Path):
    result, _, _, _ = _run(tmp_path, post=_client_error_post(), attempts=3)
    assert result is None


def test_client_error_quarantines_without_retrying(tmp_path: Path):
    post = _client_error_post()
    _run(tmp_path, post=post, attempts=3)
    assert len(post.calls) == 1  # deterministic — no retry burned on a rejected request


def test_client_error_reason_is_distinct_from_server_unreachable(tmp_path: Path):
    _, _, manifest, _ = _run(tmp_path, post=_client_error_post(), attempts=3)
    assert "server unreachable" not in _only_record(manifest)["reason"]


def test_missing_page_is_quarantined_not_crashed(tmp_path: Path):
    # A stale/missing page path (e.g. from a batch driver calling the library)
    # must not crash — the CLI guards existence via Typer, ocr_page must too.
    manifest = tmp_path / "manifest.jsonl"
    result = ocr_page(
        tmp_path / "pages" / "WordCraft" / "gone.png",
        "qwen/qwen3-vl-4b",
        out_dir=tmp_path / "out",
        manifest_path=manifest,
        post=_boom_post(),
        sleep=lambda _s: None,
    )
    assert result is None


def test_missing_page_does_not_hit_the_network(tmp_path: Path):
    post = _boom_post()
    ocr_page(
        tmp_path / "pages" / "WordCraft" / "gone.png",
        "qwen/qwen3-vl-4b",
        out_dir=tmp_path / "out",
        manifest_path=tmp_path / "manifest.jsonl",
        post=post,
        sleep=lambda _s: None,
    )
    assert post.calls == []


def test_default_post_curl_missing_raises_transport_error(tmp_path: Path, monkeypatch):
    # curl absent from PATH → subprocess raises FileNotFoundError; the transport
    # must convert it to a retryable TransportError, never crash the batch.
    page = _page(tmp_path)

    def boom_run(*args, **kwargs):
        raise FileNotFoundError("curl")

    monkeypatch.setattr("paper_degist.ocr_page.subprocess.run", boom_run)
    with pytest.raises(TransportError):
        _default_post("qwen/qwen3-vl-4b", "prompt", page, DEFAULT_ENDPOINT)
