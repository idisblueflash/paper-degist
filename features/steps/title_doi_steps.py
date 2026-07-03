"""BDD steps for US10 title→DOI (Crossref) resolution.

Behave shares one step registry, so these define *new* Given/When phrases (a
title lookup is injected here, unlike US9's OA-only steps) and reuse US9's Then
phrases for the OA-PDF and quarantine assertions — never redefining them.
"""

import tempfile
from pathlib import Path

from behave import given, when

from paper_degist.resolve_oa import resolve_oa


def _work_dir(context):
    if not getattr(context, "work_dir", None):
        context.work_dir = Path(tempfile.mkdtemp())
    return context.work_dir


@given('a slug URL "{url}" whose title Crossref resolves to a DOI, open at "{pdf_url}"')
def step_title_resolves_open(context, url, pdf_url):
    context.url = url
    context.title_lookup = lambda title: "10.1191/1362168805lr151oa"
    context.oa_lookup = lambda doi: pdf_url


@given('a slug URL "{url}" whose title Crossref cannot confidently match')
def step_title_no_match(context, url):
    context.url = url
    context.title_lookup = lambda title: None
    # No DOI recovered → the OA lookup must never run.
    def _must_not_call(doi):
        raise AssertionError("oa_lookup ran without a recovered DOI")

    context.oa_lookup = _must_not_call


@given('a slug URL "{url}" whose Crossref lookup errors')
def step_title_lookup_errors(context, url):
    context.url = url

    def _boom(title):
        raise RuntimeError("crossref 500")

    context.title_lookup = _boom

    def _must_not_call(doi):
        raise AssertionError("oa_lookup ran after a title lookup error")

    context.oa_lookup = _must_not_call


@when("resolve-oa resolves it via title lookup")
def step_resolve_via_title(context):
    context.manifest = _work_dir(context) / "manifest.jsonl"
    context.result = resolve_oa(
        context.url,
        manifest_path=context.manifest,
        oa_lookup=context.oa_lookup,
        title_lookup=context.title_lookup,
    )
