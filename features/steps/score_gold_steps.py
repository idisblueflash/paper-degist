import tempfile
from pathlib import Path

from behave import given, when, then

from paper_degist.score_gold import matches_subset, score_gold


def _root(context):
    """A temp root holding out/ and scores.jsonl for the scenario."""
    if not getattr(context, "root", None):
        context.root = Path(tempfile.mkdtemp())
    return context.root


def _save_gold_output(context, text: str) -> Path:
    """Save a model output at out/qwen_qwen3-vl-4b/gold.md under the scenario root."""
    target = _root(context) / "out" / "qwen_qwen3-vl-4b" / "gold.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    context.output = target
    return target


# --- AC1: the subset filter ---


@given('a gold page whose data_source is "{data_source}", layout "{layout}", language "{language}"')
def step_gold_page_attributes(context, data_source, layout, language):
    context.page_attribute = {
        "data_source": data_source,
        "layout": layout,
        "language": language,
    }


@when("score-gold filters the subset")
def step_filter_subset(context):
    context.selected = matches_subset(context.page_attribute)


@then("that page is excluded from scoring")
def step_page_excluded(context):
    assert context.selected is False


# --- AC2: text edit distance ---


@given('a gold page "{slug}" with gold text "{text}"')
def step_gold_text_page(context, slug, text):
    context.gold_page = {"layout_dets": [{"category_type": "text_block", "text": text, "order": 0}]}
    context.gold_text = text


@given("a saved model output that transcribes it faithfully")
def step_output_faithful_text(context):
    _save_gold_output(context, context.gold_text)


@when("score-gold scores it against the gold")
def step_score_against_gold(context):
    context.record = score_gold(
        context.output,
        context.gold_page,
        scores_path=_root(context) / "scores.jsonl",
        manifest_path=_root(context) / "manifest.jsonl",
    )


@then("the text_edit_distance dimension is recorded near zero")
def step_text_edit_distance_low(context):
    assert context.record["text_edit_distance"] < 0.1


# --- AC3: TEDS for tables ---


@given('a gold page "{slug}" carrying a two-row results table')
def step_gold_table_page(context, slug):
    context.gold_table = (
        "<table><tr><td>Model</td><td>Top-1</td></tr>"
        "<tr><td>ResNet</td><td>0.76</td></tr></table>"
    )
    context.gold_page = {"layout_dets": [{"category_type": "table", "html": context.gold_table, "order": 0}]}


@given("a saved model output reproducing that table verbatim")
def step_output_table_verbatim(context):
    _save_gold_output(context, f"Results follow.\n\n{context.gold_table}\n")


@then("the teds dimension is recorded as a perfect one")
def step_teds_perfect(context):
    assert context.record["teds"] == 1.0


# --- AC4: not-applicable skip ---


@given('a gold page "{slug}" with only prose, no table')
def step_gold_text_only_page(context, slug):
    context.gold_page = {
        "layout_dets": [{"category_type": "text_block", "text": "Retention improves with spacing.", "order": 0}]
    }


@given("a saved model output transcribing that prose")
def step_output_prose(context):
    _save_gold_output(context, "Retention improves with spacing.")


@then("the teds dimension is recorded not-applicable, never a false zero")
def step_teds_not_applicable(context):
    assert context.record["teds"] is None
