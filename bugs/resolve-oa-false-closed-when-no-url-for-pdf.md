# resolve-oa reports open-access papers as "closed access" when Unpaywall has no `url_for_pdf`

- **Component:** `resolve-oa` (`src/paper_degist/resolve_oa.py`)
- **Severity:** High — defeats the purpose of the OA-recovery step (US9/US30) for a large class of genuinely open papers, and does so *silently with a confidently-wrong verdict*.
- **Status:** Fixed
- **Found:** 2026-07-09, while filling evidence gaps for the `research-room` mnemonic-sentences plan (recovering paywalled classics after `fetch-batch` hit 403s).

## Summary

`resolve-oa` treats "Unpaywall returned no direct **PDF** URL" as "the paper is **closed access**." These are not the same thing. An open-access paper whose Unpaywall record has `is_oa: true` but `best_oa_location.url_for_pdf: null` (only a landing `url`) is reported as:

```
quarantined … reason: "no OA copy (closed access) — checked Unpaywall and OpenAlex"
```

This is factually false. The paper is open; only a machine-extractable *PDF field* is missing. The user reads "closed access" and abandons a paper that is freely downloadable one hop away.

## Environment

- Repo: `/Users/husongtao/Projects/paper-degist-02`
- Command: `resolve-oa <doi> --email <addr>` (entry point `paper_degist.resolve_oa:main`)
- Unpaywall API reachable and returning HTTP 200 (verified independently with `curl`).

## Reproduction

```bash
# A guaranteed gold-OA paper (eLife):
resolve-oa "10.7554/eLife.00013" --email you@example.com
#   → quarantined (see manifest.jsonl): 10.7554/eLife.00013
#   manifest reason: "no OA copy (closed access) — checked Unpaywall and OpenAlex"

# Its actual Unpaywall record:
curl -s "https://api.unpaywall.org/v2/10.7554/eLife.00013?email=you@example.com" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);b=d['best_oa_location'];print('is_oa=',d['is_oa'],'url_for_pdf=',b.get('url_for_pdf'),'url=',b.get('url'))"
#   → is_oa= True  url_for_pdf= None  url= https://doi.org/10.7554/elife.00013
```

### Observed on three real papers (all `is_oa=True`, all reported "closed")

| DOI | Paper | `is_oa` | `url_for_pdf` | landing `url` (`host_type`) | resolve-oa verdict |
|---|---|---|---|---|---|
| `10.7554/eLife.00013` | eLife sanity check | `True` | `None` | `doi.org/…` (publisher) | **closed access** ❌ |
| `10.1191/0267658304sr233oa` | Barcroft 2004, sentence writing | `True` | `None` | `hal.science/hal-00572075` (repository) | **closed access** ❌ |
| `10.1080/2331186x.2017.1287391` | Cogent Education 2017, spacing | `True` | `None` | `doi.org/…` (publisher) | **closed access** ❌ |

For the Barcroft case the PDF was trivially retrievable from the discarded landing URL:

```bash
curl -sL "https://hal.science/hal-00572075/document" -o barcroft.pdf   # → 247 KB application/pdf
```

So resolve-oa reported "no OA copy" for a paper whose PDF is a single, derivable hop from the URL Unpaywall handed back.

## Expected vs. actual

- **Expected:** an `is_oa: true` record is never reported as "closed access." When no direct PDF field exists, resolve-oa should either (a) surface the OA landing `url` for the human/browser lane, or (b) derive the PDF for known repository hosts — and the quarantine reason must not claim the paper is closed.
- **Actual:** any OA paper lacking `url_for_pdf` is quarantined as `"no OA copy (closed access)"` and its landing `url` is thrown away.

## Root cause

`_pdf_url_from_unpaywall` returns `None` whenever `url_for_pdf` is absent — even when `is_oa` is true and a landing `url` is present (`resolve_oa.py:227-243`):

```python
def _pdf_url_from_unpaywall(data: dict) -> Optional[str]:
    if not data.get("is_oa"):
        return None
    locations = [data.get("best_oa_location") or {}, *(data.get("oa_locations") or [])]
    for loc in locations:
        pdf = (loc or {}).get("url_for_pdf")   # ← only a direct PDF field counts
        if pdf:
            return pdf
    return None                                 # ← is_oa=True with landing-only url collapses to None
```

The docstring (`resolve_oa.py:234`) states this is deliberate: *"Only `url_for_pdf` counts: a bare `url` is a landing page, not a file `fetch-one` can download, so we never return it."* That choice is defensible for the **auto-pipe-into-`fetch-one`** path — but the caller then loses the distinction between the two very different reasons the lookup returned `None`:

1. `is_oa: false` → genuinely closed.
2. `is_oa: true`, no `url_for_pdf` → **open**, but Unpaywall only has a landing URL.

Both collapse to `None`, and `resolve_oa` → `_resolve_via_openalex` labels both with the closed-access reason (`resolve_oa.py:144` and `:159`). OpenAlex, cross-checked next, tends to have the same landing-only shape, so the "checked Unpaywall and OpenAlex" wording makes the wrong verdict look doubly authoritative.

## Impact

- **False negatives across an entire class of OA papers.** Repository-hosted green OA (HAL, PMC, institutional repos) and some gold OA frequently expose only a landing `url` in Unpaywall. Every one of these is now reported "closed."
- **Silent and confidently wrong.** The reason string asserts closed access, so a user (or an agent driving the pipeline) stops looking — the opposite of what US9 exists to do.
- **A recoverable lead is discarded.** The landing `url` that would let the browser/human lane grab the PDF is never surfaced.

## Suggested fix

1. **Never say "closed" when `is_oa` is true.** Split the verdict: return a small result object (or a second return value) that distinguishes `closed` (`is_oa` false on both indexes) from `open-no-direct-pdf` (`is_oa` true, landing only).
2. **Surface the landing `url`.** In the `open-no-direct-pdf` case, emit `best_oa_location.url` with a distinct reason such as `"open access, no direct PDF link (landing only) — route to browser/human lane: <url>"`. That keeps the batch finishing (rule 02) while handing the next stage something actionable.
3. **Optional: derive PDFs for known hosts.** For `host_type: repository` landings with a stable pattern (HAL `…/document`, PMC `…/pdf/…`), attempt the derived PDF URL before quarantining. Low effort, recovers a big fraction of green OA.
4. **Fix the reason strings** at `resolve_oa.py:144` and `:159` so `"closed access"` is emitted only when `is_oa` is false.

## Test coverage to add

`src/tests/test_resolve_oa.py` — add cases for an `oa_lookup` fed an Unpaywall payload with `is_oa: true` and no `url_for_pdf`:
- asserts the outcome is **not** the closed-access reason;
- asserts the landing `url` is surfaced (in the return value and/or the manifest reason);
- a companion `is_oa: false` case still yields the genuine closed-access reason.
