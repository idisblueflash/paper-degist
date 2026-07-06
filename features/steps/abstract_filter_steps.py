import json
import tempfile
from pathlib import Path

from behave import given, then, when

from paper_degist.abstract_filter import abstract_filter

# Signal → 2-D document vector. The topic query embeds to (1, 0), so cosine is:
# on≈1.0, near≈0.995, far≈0.707 (both ≥ 0.65 → kept, near ranks first), off=0.0
# (< 0.65 → dropped). ``down`` returns None to simulate an embed-text quarantine.
_VECTORS = {
    "on": (1.0, 0.0),
    "near": (10.0, 1.0),
    "far": (1.0, 1.0),
    "off": (0.0, 1.0),
    "down": None,
}


@given("the candidate list:")
def step_candidate_list(context):
    context.candidates = []
    context.doc_vectors = {}
    for row in context.table:
        abstract = row["abstract"] or None
        record = {
            "url": row["url"],
            "abstract": abstract,
            "abstract_present": row["present"].strip().lower() == "true",
            "source": "arxiv",
        }
        doi = (row["doi"] or "").strip()
        if doi:
            record["doi"] = doi
        context.candidates.append(record)
        if abstract is not None:
            context.doc_vectors[abstract] = _VECTORS[row["signal"].strip()]
    context.af_manifest = Path(tempfile.mkdtemp()) / "manifest.jsonl"


@when('abstract-filter narrows the list for topic "{topic}"')
def step_narrow(context, topic):
    context.embed_calls = []

    def embed(text, role):
        context.embed_calls.append((text, role))
        if role == "query":
            return [1.0, 0.0]
        vec = context.doc_vectors.get(text)
        return list(vec) if vec is not None else None

    context.kept = abstract_filter(
        context.candidates, topic, embed=embed, threshold=0.65, manifest_path=context.af_manifest
    )


def _urls(kept):
    return [k["url"] for k in kept]


def _records(context):
    return [json.loads(line) for line in context.af_manifest.read_text(encoding="utf-8").splitlines()]


@then('the kept candidate urls are exactly "{urls}"')
def step_kept_exactly(context, urls):
    expected = [u.strip() for u in urls.split(",") if u.strip()]
    assert _urls(context.kept) == expected, f"expected {expected}, got {_urls(context.kept)}"


@then("the shortlist is empty")
def step_shortlist_empty(context):
    assert context.kept == [], f"expected an empty shortlist, got {_urls(context.kept)}"


@then('the kept candidate urls in order are "{urls}"')
def step_kept_in_order(context, urls):
    expected = [u.strip() for u in urls.split(",") if u.strip()]
    assert _urls(context.kept) == expected, f"expected {expected}, got {_urls(context.kept)}"


@then('"{url}" is filtered with reason "{reason}"')
def step_filtered(context, url, reason):
    match = [
        r for r in _records(context)
        if r.get("url") == url and r.get("event") == "filtered" and r.get("reason", "").startswith(reason)
    ]
    assert match, f"no filtered/{reason} record for {url}: {_records(context)}"


@then('"{url}" is quarantined with reason "{reason}"')
def step_quarantined(context, url, reason):
    match = [
        r for r in _records(context)
        if r.get("url") == url and r.get("event") == "quarantined" and reason in r.get("reason", "")
    ]
    assert match, f"no quarantined/{reason} record for {url}: {_records(context)}"


@then('"{url}" is kept with a similarity score')
def step_kept_with_similarity(context, url):
    kept = {k["url"]: k for k in context.kept}
    assert url in kept, f"{url} was not kept: {_urls(context.kept)}"
    assert isinstance(kept[url].get("similarity"), (int, float)), kept[url]


@then("exactly {count:d} abstract was embedded")
def step_abstracts_embedded(context, count):
    docs = sum(1 for _, role in context.embed_calls if role == "document")
    assert docs == count, f"embedded {docs} abstracts, expected {count}"
