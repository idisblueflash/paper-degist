"""Unit tests for US20 ocr_page (pytest).

One assertion per test (rule 05): each fails for exactly one reason. The flaky
model transport is injected as ``post`` (a single request → ``(code, body)``)
and ``sleep`` as a no-op, so these stay fast, offline, and isolated (rule 01) —
the real ``curl`` transport is exercised end-to-end (rule 06 §7), not here.
Distinct example pages/models per case (rule 08) label what each exercises.
"""

import json
from pathlib import Path

from paper_degist.ocr_page import (
    _strip_markdown_fence,
    decode_grounding,
    ocr_page,
)


def _only_record(manifest: Path):
    (line,) = manifest.read_text(encoding="utf-8").splitlines()
    return json.loads(line)


def _ok_body(content="# Title\n\nBody.", finish="stop", completion_tokens=42):
    """A 200 chat response envelope, as LM Studio returns it."""
    return (
        "200",
        json.dumps(
            {
                "choices": [{"message": {"content": content}, "finish_reason": finish}],
                "usage": {"completion_tokens": completion_tokens},
            }
        ),
    )


def _post_ok(**kwargs):
    """A poster that always answers 200 with a fixed body."""
    body = _ok_body(**kwargs)

    def post(server, body_path):
        return body

    return post


def _post_502(times, then=None):
    """A poster that 502s ``times`` times, then returns ``then`` (default 200)."""
    calls = {"n": 0}

    def post(server, body_path):
        calls["n"] += 1
        if calls["n"] <= times:
            return ("502", "")
        return then if then is not None else _ok_body()

    post.calls = calls
    return post


def _post_boom(server, body_path):
    """A poster that must never be called — proves no network was touched."""
    raise AssertionError("the transport was hit when it should not have been")


def _run(
    tmp_path,
    model,
    *,
    page_name="p02.png",
    post=None,
    sleep=None,
    content=None,
    finish=None,
    completion_tokens=None,
    **kwargs,
):
    """Arrange a page PNG + manifest and run ocr_page; return (result, page, manifest).

    ``content``/``finish``/``completion_tokens`` shape the *default* 200 body;
    remaining ``kwargs`` (e.g. ``retries``) pass through to ``ocr_page``.
    """
    page = tmp_path / page_name
    page.write_bytes(b"\x89PNGfake-image-bytes")
    manifest = tmp_path / "manifest.jsonl"
    if post is None:
        body = {
            k: v
            for k, v in (
                ("content", content),
                ("finish", finish),
                ("completion_tokens", completion_tokens),
            )
            if v is not None
        }
        post = _post_ok(**body)
    result = ocr_page(
        page,
        model,
        out_dir=tmp_path / "out",
        manifest_path=manifest,
        post=post,
        sleep=sleep or (lambda _s: None),
        **kwargs,
    )
    return result, page, manifest


# --- AC1: happy path — save post-processed Markdown + an ocr record ---


def test_happy_path_returns_model_slug_output_path(tmp_path: Path):
    result, _, _ = _run(tmp_path, "qwen/qwen3-vl-4b")
    assert result == tmp_path / "out" / "qwen_qwen3-vl-4b" / "p02.md"


def test_happy_path_saves_the_markdown(tmp_path: Path):
    result, _, _ = _run(tmp_path, "qwen/qwen3-vl-4b", content="# Attention\n\nBody.")
    assert result.read_text(encoding="utf-8") == "# Attention\n\nBody.\n"


def test_happy_path_manifest_stage_is_ocr_page(tmp_path: Path):
    _, _, manifest = _run(tmp_path, "qwen/qwen3-vl-4b")
    assert _only_record(manifest)["stage"] == "ocr-page"


def test_happy_path_manifest_records_the_model(tmp_path: Path):
    _, _, manifest = _run(tmp_path, "qwen/qwen3-vl-4b")
    assert _only_record(manifest)["model"] == "qwen/qwen3-vl-4b"


def test_happy_path_manifest_records_finish_reason(tmp_path: Path):
    _, _, manifest = _run(tmp_path, "qwen/qwen3-vl-4b", finish="length")
    assert _only_record(manifest)["finish_reason"] == "length"


def test_happy_path_manifest_records_completion_tokens(tmp_path: Path):
    _, _, manifest = _run(tmp_path, "qwen/qwen3-vl-4b", completion_tokens=1234)
    assert _only_record(manifest)["completion_tokens"] == 1234


def test_happy_path_manifest_records_latency(tmp_path: Path):
    _, _, manifest = _run(tmp_path, "qwen/qwen3-vl-4b")
    assert isinstance(_only_record(manifest)["latency"], float)


def test_qwen_output_has_its_markdown_fence_stripped(tmp_path: Path):
    result, _, _ = _run(
        tmp_path, "qwen/qwen3-vl-4b", content="```markdown\n# Fenced\n\nBody.\n```"
    )
    assert result.read_text(encoding="utf-8") == "# Fenced\n\nBody.\n"


# --- AC2: idempotent skip — a saved output is never re-computed ---


def _run_with_existing(tmp_path, model, *, post):
    """Run ocr_page when out/<model>/<page>.md already exists from a prior run."""
    page = tmp_path / "p05.png"
    page.write_bytes(b"\x89PNGfake")
    target = tmp_path / "out" / "qwen_qwen3-vl-4b" / "p05.md"
    target.parent.mkdir(parents=True)
    target.write_text("# already ocr'd\n", encoding="utf-8")
    manifest = tmp_path / "manifest.jsonl"
    result = ocr_page(
        page,
        model,
        out_dir=tmp_path / "out",
        manifest_path=manifest,
        post=post,
        sleep=lambda _s: None,
    )
    return result, target, manifest


def test_idempotent_skip_returns_existing_path(tmp_path: Path):
    result, target, _ = _run_with_existing(tmp_path, "qwen/qwen3-vl-4b", post=_post_boom)
    assert result == target


def test_idempotent_skip_does_not_hit_the_server(tmp_path: Path):
    # _post_boom raises if called; a clean return proves the server was skipped.
    result, target, _ = _run_with_existing(tmp_path, "qwen/qwen3-vl-4b", post=_post_boom)
    assert result.read_text(encoding="utf-8") == "# already ocr'd\n"


def test_idempotent_skip_writes_no_manifest_record(tmp_path: Path):
    _, _, manifest = _run_with_existing(tmp_path, "qwen/qwen3-vl-4b", post=_post_boom)
    assert not manifest.exists()


# --- AC3: a 502/flapping runtime is retried, then quarantined distinctly ---


def test_recovers_when_a_502_is_followed_by_200(tmp_path: Path):
    result, _, _ = _run(tmp_path, "qwen/qwen3-vl-4b", post=_post_502(times=2))
    assert result == tmp_path / "out" / "qwen_qwen3-vl-4b" / "p02.md"


def test_exhausted_retries_returns_none(tmp_path: Path):
    result, _, _ = _run(tmp_path, "qwen/qwen3-vl-4b", post=_post_502(times=99), retries=4)
    assert result is None


def test_exhausted_retries_tries_the_configured_number_of_times(tmp_path: Path):
    post = _post_502(times=99)
    _run(tmp_path, "qwen/qwen3-vl-4b", post=post, retries=3)
    assert post.calls["n"] == 3


def test_exhausted_retries_waits_a_gap_between_attempts(tmp_path: Path):
    naps = []
    _run(
        tmp_path,
        "qwen/qwen3-vl-4b",
        post=_post_502(times=99),
        retries=3,
        sleep=lambda s: naps.append(s),
    )
    assert len(naps) == 2  # a gap between attempts, not after the last


def test_exhausted_retries_manifest_reason_names_server_unreachable(tmp_path: Path):
    _, _, manifest = _run(tmp_path, "qwen/qwen3-vl-4b", post=_post_502(times=99), retries=2)
    assert "server unreachable after retries" in _only_record(manifest)["reason"]


def test_exhausted_retries_writes_no_output_file(tmp_path: Path):
    _run(tmp_path, "qwen/qwen3-vl-4b", post=_post_502(times=99), retries=2)
    assert not (tmp_path / "out" / "qwen_qwen3-vl-4b").exists()


def test_malformed_200_body_is_quarantined_not_crashed(tmp_path: Path):
    # A 200 whose body is not the expected JSON must not crash the batch (rule 02);
    # it is treated as a flap and quarantined after the retry budget.
    def post(server, body_path):
        return ("200", "<html>not json</html>")

    result, _, _ = _run(tmp_path, "qwen/qwen3-vl-4b", post=post, retries=2)
    assert result is None


# --- AC3 refinement: a deterministic client error fails fast, not "unreachable" ---


def _post_400(server, body_path):
    """A poster that returns a 400 (a bad request — a deterministic client error)."""
    _post_400.calls += 1
    return ("400", '{"error": "bad request"}')


def test_client_error_returns_none(tmp_path: Path):
    _post_400.calls = 0
    result, _, _ = _run(tmp_path, "deepseek-ocr", post=_post_400, retries=4)
    assert result is None


def test_client_error_is_not_retried(tmp_path: Path):
    _post_400.calls = 0
    _run(tmp_path, "deepseek-ocr", post=_post_400, retries=4)
    assert _post_400.calls == 1  # a 4xx is deterministic — retrying cannot fix it


def test_client_error_reason_is_distinct_from_server_unreachable(tmp_path: Path):
    _post_400.calls = 0
    _, _, manifest = _run(tmp_path, "deepseek-ocr", post=_post_400, retries=4)
    assert "server unreachable" not in _only_record(manifest)["reason"]


def test_null_usage_does_not_crash_after_a_successful_ocr(tmp_path: Path):
    # Some servers emit {"usage": null}; the record must still be written, not crash.
    def post(server, body_path):
        return (
            "200",
            json.dumps(
                {"choices": [{"message": {"content": "# ok"}, "finish_reason": "stop"}], "usage": None}
            ),
        )

    _, _, manifest = _run(tmp_path, "qwen/qwen3-vl-4b", post=post)
    assert _only_record(manifest)["completion_tokens"] is None


def test_latency_excludes_the_recovery_gap_between_retries(tmp_path: Path):
    # A call that 502s once then succeeds must not fold the recovery gap into its
    # recorded latency — the bench compares model speed. Use a real, measurable
    # gap so latency-over-the-whole-loop (the bug) is distinguishable from
    # latency-over-the-successful-call-only (the fix).
    import time as _time

    _, _, manifest = _run(
        tmp_path,
        "qwen/qwen3-vl-4b",
        post=_post_502(times=1),
        gap=0.05,
        sleep=lambda _s: _time.sleep(0.05),
    )
    assert _only_record(manifest)["latency"] < 0.04


# --- AC4: a model id not in the registry is quarantined without the network ---


def test_unknown_model_returns_none(tmp_path: Path):
    result, _, _ = _run(tmp_path, "some-unregistered-ocr", post=_post_boom)
    assert result is None


def test_unknown_model_does_not_touch_the_network(tmp_path: Path):
    # Assert the network was not hit *directly* — a counting post called 0 times —
    # rather than inferring it from a side effect the name doesn't advertise.
    calls = {"n": 0}

    def counting_post(server, body_path):
        calls["n"] += 1
        return _ok_body()

    _run(tmp_path, "some-unregistered-ocr", post=counting_post)
    assert calls["n"] == 0


def test_unknown_model_writes_no_output_file(tmp_path: Path):
    _run(tmp_path, "some-unregistered-ocr", post=_post_boom)
    assert not (tmp_path / "out").exists()


def test_unknown_model_manifest_stage_is_ocr_page(tmp_path: Path):
    _, _, manifest = _run(tmp_path, "some-unregistered-ocr", post=_post_boom)
    assert _only_record(manifest)["stage"] == "ocr-page"


def test_unknown_model_reason_is_distinct_from_a_server_error(tmp_path: Path):
    _, _, manifest = _run(tmp_path, "some-unregistered-ocr", post=_post_boom)
    assert "unknown model" in _only_record(manifest)["reason"]


# --- post-processors (registry data) exercised directly ---


def test_strip_markdown_fence_unwraps_a_whole_output_fence():
    assert _strip_markdown_fence("```markdown\n# H\n\ntext\n```") == "# H\n\ntext\n"


def test_strip_markdown_fence_leaves_unfenced_text_alone():
    assert _strip_markdown_fence("# H\n\ntext") == "# H\n\ntext\n"


def test_decode_grounding_strips_layout_boxes():
    assert "<|det|>" not in decode_grounding("Body<|det|>TITLE [1,2,3,4]<|/det|>more")


def test_decode_grounding_undoes_byte_bpe_spacing():
    # 'Ġ' is the byte-BPE marker for a space; it must decode to ' ' (leading/
    # trailing whitespace is then stripped, so assert on an interior boundary).
    assert "Hello world" in decode_grounding("ĠHelloĠworld")
