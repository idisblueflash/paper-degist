import json
import tempfile
from pathlib import Path

from behave import given, then, when

from paper_degist.rank_cited import rank_cited


def _build_record(row):
    cited_by_str = (row.get("cited_by") or "").strip()
    record = {"title": row["title"], "url": row["url"], "source": "openalex"}
    if cited_by_str != "":
        record["cited_by"] = int(cited_by_str)
    return record


@given("a rank-cited candidate pool:")
def step_pool(context):
    context.rc_candidates = [_build_record(row) for row in context.table]
    context.rc_manifest = Path(tempfile.mkdtemp()) / "manifest.jsonl"


@when("rank-cited runs with top {n:d}")
def step_run(context, n):
    context.rc_result = rank_cited(
        context.rc_candidates, top=n, manifest_path=context.rc_manifest
    )


@then("the ranked output titles in order are:")
def step_ranked_titles(context):
    expected = [row["title"] for row in context.table]
    got = [r["title"] for r in (context.rc_result or [])]
    assert got == expected, f"expected {expected}, got {got}"


@then("exactly {count:d} candidates are emitted")
def step_count_emitted(context, count):
    got = len(context.rc_result or [])
    assert got == count, f"expected {count} emitted, got {got}"


def _manifest_rows(context):
    path = context.rc_manifest
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@then('the rank-cited manifest has a filtered row with reason "{reason}" for "{url}"')
def step_filtered_row(context, reason, url):
    rows = _manifest_rows(context)
    match = [
        r for r in rows
        if r.get("event") == "filtered"
        and r.get("reason", "").startswith(reason)
        and r.get("url") == url
    ]
    assert match, f"no filtered/{reason} row for {url} in {rows}"


@then('the rank-cited manifest has an empty-rank quarantine row')
def step_empty_rank_row(context):
    rows = _manifest_rows(context)
    match = [
        r for r in rows
        if "empty-rank" in r.get("reason", "") and r.get("event") == "quarantined"
    ]
    assert match, f"no empty-rank quarantine row in {rows}"


@then("nothing is printed to stdout")
def step_nothing_stdout(context):
    assert context.rc_result is None, f"expected None (nothing rankable), got {context.rc_result}"


# --- AC5: garbage line ---

@given("a rank-cited input with a garbage line among valid candidates:")
def step_garbage_input(context):
    context.rc_manifest = Path(tempfile.mkdtemp()) / "manifest.jsonl"
    valid = [_build_record(row) for row in context.table]
    lines = ["NOT JSON AT ALL <<<\n"] + [json.dumps(r) + "\n" for r in valid]
    context.rc_mixed_text = "".join(lines)
    context.rc_valid = valid


@when("rank-cited runs on the mixed input with top {n:d}")
def step_run_mixed(context, n):
    from paper_degist.abstract_filter import load_candidates
    candidates = load_candidates(
        context.rc_mixed_text,
        manifest_path=context.rc_manifest,
        stage="rank-cited",
    )
    context.rc_result = rank_cited(candidates, top=n, manifest_path=context.rc_manifest)


@then('the garbage line is quarantined with stage "{stage}"')
def step_garbage_quarantined(context, stage):
    rows = _manifest_rows(context)
    match = [r for r in rows if r.get("stage") == stage and r.get("event") == "quarantined"]
    assert match, f"no quarantined/{stage} row in {rows}"


@then("the valid candidate is still emitted")
def step_valid_emitted(context):
    result = context.rc_result or []
    expected_urls = {r["url"] for r in context.rc_valid}
    got_urls = {r["url"] for r in result}
    assert expected_urls == got_urls, f"expected {expected_urls}, got {got_urls}"
