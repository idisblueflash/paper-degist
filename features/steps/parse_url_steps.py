from pathlib import Path

from behave import given, when, then

from paper_degist.parse_url import parse_url


@given('the text blob "{filename}"')
def step_load_blob(context, filename):
    context.blob = Path(filename).read_text(encoding="utf-8")


@when("parse-url processes the text")
def step_parse(context):
    context.urls = parse_url(context.blob)


@then("we get a list of {count:d} URLs")
def step_count(context, count):
    assert isinstance(context.urls, list), f"expected a list, got {type(context.urls)}"
    assert len(context.urls) == count, f"expected {count} URLs, got {len(context.urls)}"


@then('the list contains "{url}"')
def step_contains(context, url):
    assert url in context.urls, f"{url!r} not in {context.urls}"


@then("no URL appears more than once")
def step_unique(context):
    assert len(context.urls) == len(set(context.urls)), "duplicate URLs found"
