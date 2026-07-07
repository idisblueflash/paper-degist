import json
import tempfile
from pathlib import Path

from behave import given, then, when

from paper_degist.snowball import snowball


def _work(openalex_id, *, doi=None, title="", cited_by=None):
    oa_id = openalex_id.strip() if openalex_id else ""
    w = {
        "id": f"https://openalex.org/{oa_id}" if oa_id else None,
        "doi": f"https://doi.org/{doi}" if doi else None,
        "title": title,
        "publication_date": "2023-01-01",
        "authorships": [],
        "referenced_works": [],
        "abstract_inverted_index": None,
        "best_oa_location": None,
        "oa_locations": [],
        "locations": [],
    }
    if cited_by is not None:
        w["cited_by_count"] = int(cited_by)
    return w


def _page(works):
    return {"meta": {}, "results": works}


@given('a seed paper "{seed}" with references:')
def step_seed_with_refs(context, seed):
    context.sb_seed = seed
    context.sb_ref_works = [
        _work(
            row["openalex_id"].strip() or None,
            doi=row.get("doi", "").strip() or None,
            title=row.get("title", "").strip(),
            cited_by=int(row["cited_by"]) if row.get("cited_by", "").strip() else None,
        )
        for row in context.table
    ]
    context.sb_citer_works = []
    context.sb_manifest = Path(tempfile.mkdtemp()) / "manifest.jsonl"


@given('the same seed has citers:')
def step_same_seed_citers(context):
    context.sb_citer_works = [
        _work(
            row["openalex_id"].strip() or None,
            doi=row.get("doi", "").strip() or None,
            title=row.get("title", "").strip(),
            cited_by=int(row["cited_by"]) if row.get("cited_by", "").strip() else None,
        )
        for row in context.table
    ]


@given('a seed paper "{seed}" with citers:')
def step_seed_with_citers(context, seed):
    context.sb_seed = seed
    context.sb_ref_works = []
    context.sb_citer_works = [
        _work(
            row["openalex_id"].strip() or None,
            doi=row.get("doi", "").strip() or None,
            title=row.get("title", "").strip(),
            cited_by=int(row["cited_by"]) if row.get("cited_by", "").strip() else None,
        )
        for row in context.table
    ]
    context.sb_manifest = Path(tempfile.mkdtemp()) / "manifest.jsonl"


@given('a seed "{seed}" that raises a not-found error')
def step_seed_not_found(context, seed):
    context.sb_seed = seed
    context.sb_ref_works = []
    context.sb_citer_works = []
    context.sb_raise_on_seed = True
    context.sb_manifest = Path(tempfile.mkdtemp()) / "manifest.jsonl"


@when('snowball runs with direction "{direction}"')
def step_run_snowball(context, direction):
    seed_data = {"id": "https://openalex.org/W100", "doi": f"https://doi.org/{context.sb_seed}",
                 "referenced_works": [f"https://openalex.org/{w['id'].rsplit('/',1)[-1]}" if w.get('id') else ""
                                      for w in getattr(context, 'sb_ref_works', [])],
                 "authorships": [], "abstract_inverted_index": None,
                 "best_oa_location": None, "oa_locations": [], "locations": []}

    def fetch_seed(doi, email):
        if getattr(context, 'sb_raise_on_seed', False):
            raise RuntimeError("404 not found")
        return seed_data

    context.sb_result = snowball(
        context.sb_seed,
        direction=direction,
        manifest_path=context.sb_manifest,
        _fetch_seed=fetch_seed,
        _fetch_refs=lambda ids, email: _page(getattr(context, 'sb_ref_works', [])),
        _fetch_citers=lambda sid, max_c, email: _page(getattr(context, 'sb_citer_works', [])),
    )


def _titles(result):
    return [r["title"] for r in (result or [])]


def _manifest_rows(context):
    p = context.sb_manifest
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


@then("the snowball output titles are:")
def step_titles_exact(context):
    expected = [row["title"].strip() for row in context.table]
    got = _titles(context.sb_result)
    assert got == expected, f"expected {expected}, got {got}"


@then('the snowball output titles include "{title}"')
def step_titles_include(context, title):
    got = _titles(context.sb_result)
    assert title in got, f"{title!r} not in {got}"


@then("nothing is emitted by snowball")
def step_nothing_emitted(context):
    assert context.sb_result is None


@then("the snowball manifest has a quarantined row for the seed")
def step_quarantine_row(context):
    rows = _manifest_rows(context)
    match = [r for r in rows if r.get("stage") == "snowball" and r.get("event") == "quarantined"]
    assert match, f"no snowball quarantined row in {rows}"


@then('the snowball manifest has a filtered row with reason "{reason}"')
def step_filtered_row(context, reason):
    rows = _manifest_rows(context)
    match = [r for r in rows if r.get("event") == "filtered" and r.get("reason") == reason]
    assert match, f"no filtered/{reason} row in {rows}"
