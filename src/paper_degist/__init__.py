"""paper-degist — convert papers into Markdown for an LLM wiki.

The root ``paper-degist`` command is a signpost only: the pipeline is run one
step at a time via each step's own console script (see ``[project.scripts]``).
"""


_STEPS = [
    ("parse-url", "Extract http(s) URLs from a text blob (US1 AC1)."),
]


def main() -> int:
    print("paper-degist — run a pipeline step directly:\n")
    for name, desc in _STEPS:
        print(f"  {name:<12} {desc}")
    print("\nRun `uv run <step> --help` for a step's options.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
