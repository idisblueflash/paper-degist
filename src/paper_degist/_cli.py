"""Shared helper for the Typer-based CLI steps.

Every step's rule-03 ``main(argv=None) -> int`` delegates here so the
convention lives in one place: run the Typer app in standalone mode (which
prints clean usage/validation errors instead of tracebacks) and normalize the
``SystemExit`` it raises into the integer exit code the shell expects.
"""

import typer


def invoke(app: typer.Typer, argv: list[str] | None) -> int:
    """Run ``app`` in standalone mode; return its exit code.

    ``SystemExit.code`` is ``None`` on a clean exit and an ``int`` for the
    usual usage/validation paths; any other payload (a message string) is
    normalized to ``1`` rather than propagated, so the wrapper never crashes.
    """
    try:
        app(args=argv)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 1
    return 0
