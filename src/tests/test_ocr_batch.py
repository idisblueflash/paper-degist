"""Unit tests for US28 ocr_batch (pytest).

ocr-batch walks one page directory across the model registry and calls
``ocr-page`` per (page, model) pair, spacing the server-hitting calls with the
recovery gap (report §3 anti-flap rule, applied *between items*). It holds no
transport logic of its own — the per-item outcome is ``ocr-page``'s — so these
tests inject a fake ``ocr`` collaborator (the ``recover_blocked`` shape) and a
fake ``sleep``, and stay fast and offline (rule 01).

One assertion per test (rule 05): each fails for exactly one reason; shared
arrange/act lives in the helpers. Distinct, self-describing page/model names
label what each case exercises (rule 08).
"""

from pathlib import Path

from paper_degist.ocr_batch import ocr_batch
from paper_degist.ocr_page import DEFAULT_GAP, ModelSpec, output_path

# Two fake registered models so a test's grid never depends on the real
# registry's contents; each name is its own label (rule 08).
_ID = lambda s: s  # noqa: E731 — identity post-processor for the fakes
FAKE_REGISTRY = {
    "vision-alpha": ModelSpec(prompt="alpha", postprocess=_ID),
    "vision-beta": ModelSpec(prompt="beta", postprocess=_ID),
}


def _pages(tmp_path: Path, names=("p0001.png", "p0002.png")) -> Path:
    """A page directory holding rendered PNGs (the render-pdf output shape)."""
    pages = tmp_path / "pages" / "SpacedRepetition"
    pages.mkdir(parents=True)
    for name in names:
        (pages / name).write_bytes(b"\x89PNG page bytes")
    return pages


def _fake_ocr(none_for=()):
    """An ``ocr-page`` stand-in: records each (page-name, model) call.

    Returns the saved path (``ocr-page``'s success/skip contract) unless the
    pair is in ``none_for``, which returns ``None`` — the quarantine signal.
    """

    def ocr(page, model, *, out_dir, **kwargs):
        key = (Path(page).name, model)
        ocr.calls.append(key)
        if key in none_for:
            return None
        return output_path(page, model, out_dir)

    ocr.calls = []
    return ocr


def _fake_sleep():
    """A ``sleep`` that records each requested duration instead of waiting."""

    def sleep(seconds):
        sleep.calls.append(seconds)

    sleep.calls = []
    return sleep


def _run(tmp_path, *, models=None, none_for=(), page_names=("p0001.png", "p0002.png")):
    """Arrange a page dir + fakes, run ocr_batch, return (paths, ocr, sleep)."""
    pages = _pages(tmp_path, page_names)
    ocr, sleep = _fake_ocr(none_for), _fake_sleep()
    paths = ocr_batch(
        pages,
        models=models,
        out_dir=tmp_path / "out",
        manifest_path=tmp_path / "manifest.jsonl",
        registry=FAKE_REGISTRY,
        ocr=ocr,
        sleep=sleep,
    )
    return paths, ocr, sleep


# --- AC1: OCR every (page, model) pair in the grid ---


def test_ocrs_every_page_model_pair(tmp_path):
    _, ocr, _ = _run(tmp_path)
    assert ocr.calls == [
        ("p0001.png", "vision-alpha"),
        ("p0001.png", "vision-beta"),
        ("p0002.png", "vision-alpha"),
        ("p0002.png", "vision-beta"),
    ]


def test_returns_the_saved_path_for_every_pair(tmp_path):
    paths, _, _ = _run(tmp_path)
    assert paths == [
        output_path(tmp_path / "pages/SpacedRepetition" / p, m, tmp_path / "out")
        for p in ("p0001.png", "p0002.png")
        for m in ("vision-alpha", "vision-beta")
    ]


# --- AC2: recovery gap between consecutive server-hitting pairs ---


def test_waits_a_recovery_gap_between_server_hitting_pairs(tmp_path):
    _, _, sleep = _run(tmp_path)
    # four fresh pairs all hit the server → a gap before each of the last three.
    assert sleep.calls == [DEFAULT_GAP, DEFAULT_GAP, DEFAULT_GAP]


# --- AC3: idempotent skip — no re-hit, no gap ---


def test_skips_a_pair_whose_output_already_exists(tmp_path):
    pages = _pages(tmp_path)
    already = output_path(pages / "p0001.png", "vision-alpha", tmp_path / "out")
    already.parent.mkdir(parents=True)
    already.write_text("prior OCR", encoding="utf-8")
    ocr, sleep = _fake_ocr(), _fake_sleep()
    ocr_batch(pages, out_dir=tmp_path / "out", registry=FAKE_REGISTRY, ocr=ocr, sleep=sleep,
              manifest_path=tmp_path / "manifest.jsonl")
    assert ("p0001.png", "vision-alpha") not in ocr.calls


def test_a_skipped_pair_still_appears_in_the_returned_paths(tmp_path):
    pages = _pages(tmp_path)
    already = output_path(pages / "p0001.png", "vision-alpha", tmp_path / "out")
    already.parent.mkdir(parents=True)
    already.write_text("prior OCR", encoding="utf-8")
    paths = ocr_batch(pages, out_dir=tmp_path / "out", registry=FAKE_REGISTRY,
                      ocr=_fake_ocr(), sleep=_fake_sleep(), manifest_path=tmp_path / "manifest.jsonl")
    assert already in paths


def test_a_fully_cached_grid_waits_no_gap(tmp_path):
    pages = _pages(tmp_path)
    for p in ("p0001.png", "p0002.png"):
        for m in FAKE_REGISTRY:
            target = output_path(pages / p, m, tmp_path / "out")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("prior OCR", encoding="utf-8")
    sleep = _fake_sleep()
    ocr_batch(pages, out_dir=tmp_path / "out", registry=FAKE_REGISTRY,
              ocr=_fake_ocr(), sleep=sleep, manifest_path=tmp_path / "manifest.jsonl")
    assert sleep.calls == []


# --- AC4: one quarantined pair never aborts the batch ---


def test_a_quarantined_pair_does_not_stop_the_remaining_pairs(tmp_path):
    _, ocr, _ = _run(tmp_path, none_for={("p0001.png", "vision-alpha")})
    assert ocr.calls[-1] == ("p0002.png", "vision-beta")


def test_a_quarantined_pair_is_omitted_from_the_returned_paths(tmp_path):
    paths, _, _ = _run(tmp_path, none_for={("p0001.png", "vision-alpha")})
    quarantined = output_path(
        tmp_path / "pages/SpacedRepetition/p0001.png", "vision-alpha", tmp_path / "out"
    )
    assert quarantined not in paths


# --- AC5: model selection — default whole registry, or a named subset ---


def test_defaults_to_the_whole_registry(tmp_path):
    _, ocr, _ = _run(tmp_path)
    assert {model for _, model in ocr.calls} == set(FAKE_REGISTRY)


def test_restricts_to_the_named_models(tmp_path):
    _, ocr, _ = _run(tmp_path, models=["vision-beta"])
    assert {model for _, model in ocr.calls} == {"vision-beta"}


# --- edges: never crash on an empty or missing directory (rule 02) ---


def test_empty_page_directory_makes_no_calls(tmp_path):
    empty = tmp_path / "pages" / "Empty"
    empty.mkdir(parents=True)
    ocr = _fake_ocr()
    ocr_batch(empty, out_dir=tmp_path / "out", registry=FAKE_REGISTRY,
              ocr=ocr, sleep=_fake_sleep(), manifest_path=tmp_path / "manifest.jsonl")
    assert ocr.calls == []


def test_missing_page_directory_returns_no_paths(tmp_path):
    paths = ocr_batch(tmp_path / "pages" / "Nonexistent", out_dir=tmp_path / "out",
                      registry=FAKE_REGISTRY, ocr=_fake_ocr(), sleep=_fake_sleep(),
                      manifest_path=tmp_path / "manifest.jsonl")
    assert paths == []
