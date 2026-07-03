from pathlib import Path

from behave import given, when, then

from paper_degist.browser_up import BrowserUpError, browser_up


def _fakes(context):
    """Lazily seed the injected collaborators with launch-succeeds defaults."""
    if not getattr(context, "fakes_ready", False):
        context.launch_calls = []

        def launch(chrome, port, user_data_dir):
            context.launch_calls.append(
                {"chrome": chrome, "port": port, "user_data_dir": user_data_dir}
            )

        context.deps = dict(
            probe_cdp=lambda url: False,
            port_in_use=lambda host, port: False,
            find_chrome=lambda: Path("/usr/bin/google-chrome"),
            launch=launch,
            wait_ready=lambda probe, url: True,
        )
        context.user_data_dir = Path(".browser-profile")
        context.fakes_ready = True
    return context


@given('no dev-mode Chrome is answering on "{cdp_url}"')
def step_no_chrome(context, cdp_url):
    _fakes(context)
    context.cdp_url = cdp_url
    context.deps["probe_cdp"] = lambda url: False


@given('a dev-mode Chrome is already reachable on "{cdp_url}"')
def step_chrome_reachable(context, cdp_url):
    _fakes(context)
    context.cdp_url = cdp_url
    context.deps["probe_cdp"] = lambda url: True


@given("a Chrome binary is installed")
def step_chrome_installed(context):
    _fakes(context)
    context.deps["find_chrome"] = lambda: Path("/usr/bin/google-chrome")


@given("no Chrome binary can be found")
def step_no_chrome_binary(context):
    _fakes(context)
    context.deps["find_chrome"] = lambda: None


@given('the CDP port on "{cdp_url}" is held by a non-debug process')
def step_port_in_use(context, cdp_url):
    _fakes(context)
    context.cdp_url = cdp_url
    context.deps["probe_cdp"] = lambda url: False
    context.deps["port_in_use"] = lambda host, port: True


def _run(context):
    context.error = None
    try:
        context.result = browser_up(
            cdp_url=context.cdp_url,
            user_data_dir=context.user_data_dir,
            **context.deps,
        )
    except BrowserUpError as exc:
        context.result = None
        context.error = exc


@when("browser-up brings the browser up")
def step_bring_up(context):
    _run(context)


@when('browser-up brings the browser up against profile "{profile}"')
def step_bring_up_profile(context, profile):
    context.user_data_dir = Path(profile)
    _run(context)


@when("browser-up tries to bring the browser up")
def step_try_bring_up(context):
    _run(context)


@then('it prints the CDP endpoint "{cdp_url}"')
def step_prints_endpoint(context, cdp_url):
    assert context.result == cdp_url, f"got {context.result!r}, expected {cdp_url!r}"


@then("it launches exactly one Chrome and leaves it running")
def step_launched_one(context):
    assert len(context.launch_calls) == 1, f"launched {len(context.launch_calls)} times"


@then("it does not launch a second Chrome")
def step_no_second_chrome(context):
    assert context.launch_calls == [], f"unexpected launch: {context.launch_calls!r}"


@then("it does not launch a Chrome")
def step_no_chrome_launched(context):
    assert context.launch_calls == [], f"unexpected launch: {context.launch_calls!r}"


@then('Chrome is launched against the persistent profile "{profile}"')
def step_launched_against_profile(context, profile):
    (call,) = context.launch_calls
    assert call["user_data_dir"] == Path(profile), f"launched against {call['user_data_dir']!r}"


@then('it fails loudly with a reason mentioning "{needle}"')
def step_fails_loudly(context, needle):
    assert context.error is not None, "expected a loud BrowserUpError, got none"
    assert needle in str(context.error), f"{needle!r} not in {str(context.error)!r}"
