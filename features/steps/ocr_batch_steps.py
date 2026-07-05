import tempfile
from pathlib import Path

from behave import given, when, then

from paper_degist.ocr_batch import ocr_batch
from paper_degist.ocr_page import DEFAULT_GAP, ModelSpec, output_path


def _root(context):
    """A temp root holding pages/ and out/ for the scenario."""
    if not getattr(context, "root", None):
        context.root = Path(tempfile.mkdtemp())
    return context.root


def _recording_ocr(context):
    """A stand-in ocr-page: records each (page-name, model) call.

    Returns the saved path (ocr-page's success contract) unless the pair is in
    ``context.quarantine``, which returns None — the quarantine signal.
    """
    context.calls = []
    quarantine = getattr(context, "quarantine", set())

    def ocr(page, model, *, out_dir, **kwargs):
        key = (Path(page).name, model)
        context.calls.append(key)
        if key in quarantine:
            return None
        return output_path(page, model, out_dir)

    return ocr


def _recording_sleep(context):
    """A sleep that records each requested gap instead of waiting."""
    context.sleeps = []
    return lambda seconds: context.sleeps.append(seconds)


@given('a page directory "{rel}" with pages:')
def step_page_dir(context, rel):
    context.pages_dir = _root(context) / rel
    context.pages_dir.mkdir(parents=True, exist_ok=True)
    context.page_names = [row["page"] for row in context.table]
    for name in context.page_names:
        (context.pages_dir / name).write_bytes(b"\x89PNG page bytes")


@given('the registered models "{a}" and "{b}"')
def step_two_models(context, a, b):
    context.registry = {m: ModelSpec(prompt=m, postprocess=lambda s: s) for m in (a, b)}


@given('the registered models "{a}"')
def step_one_model(context, a):
    context.registry = {a: ModelSpec(prompt=a, postprocess=lambda s: s)}


@given('the pair "{page}" + "{model}" was already OCR\'d in a prior run')
def step_already_ocrd(context, page, model):
    target = output_path(context.pages_dir / page, model, _root(context) / "out")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# already OCR'd", encoding="utf-8")


@given('ocr-page quarantines the pair "{page}" + "{model}"')
def step_quarantine_pair(context, page, model):
    context.quarantine = {(page, model)}


def _run(context, *, models=None):
    context.result = ocr_batch(
        context.pages_dir,
        models=models,
        out_dir=_root(context) / "out",
        manifest_path=_root(context) / "manifest.jsonl",
        gap=DEFAULT_GAP,
        registry=context.registry,
        ocr=_recording_ocr(context),
        sleep=_recording_sleep(context),
    )


@when("ocr-batch runs over the directory")
def step_run(context):
    _run(context)


@when('ocr-batch runs restricted to model "{model}"')
def step_run_restricted(context, model):
    _run(context, models=[model])


@then("ocr-page is called for every page and model pair")
def step_full_grid(context):
    expected = [(p, m) for p in context.page_names for m in context.registry]
    assert set(context.calls) == set(expected), f"grid {context.calls} != {expected}"


@then("each saved Markdown path is returned")
def step_paths_returned(context):
    assert len(context.result) == len(context.page_names) * len(context.registry), context.result


@then("a recovery gap is waited before each pair after the first")
def step_gaps_between(context):
    hits = len(context.page_names) * len(context.registry)
    assert context.sleeps == [DEFAULT_GAP] * (hits - 1), context.sleeps


@then("ocr-page is not called for that pair")
def step_pair_skipped(context):
    assert ("p0001.png", "qwen/qwen3-vl-4b") not in context.calls, context.calls


@then("no recovery gap is waited")
def step_no_gap(context):
    assert context.sleeps == [], context.sleeps


@then("the remaining pairs are still OCR'd")
def step_remaining_ocrd(context):
    assert ("p0002.png", "qwen/qwen3-vl-4b") in context.calls, context.calls


@then("the quarantined pair is absent from the returned paths")
def step_quarantined_absent(context):
    absent = output_path(context.pages_dir / "p0001.png", "qwen/qwen3-vl-4b", _root(context) / "out")
    assert absent not in context.result, context.result


@then('only "{model}" is used across the grid')
def step_only_model(context, model):
    assert {m for _, m in context.calls} == {model}, context.calls
