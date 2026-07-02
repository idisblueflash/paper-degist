#!/usr/bin/env python3
"""Fetch PR review feedback for the current branch, grouped into threads.

Used by the /pr-feedback slash command. Prints, for each review-comment
thread that has a human reply, the original finding plus the reply chain, and
flags whether the thread still NEEDS ACTION (the last comment is a human reply
that Claude has not yet answered) or is already HANDLED.

Idempotency is carried by the PR itself, not a state file: when Claude acts on
a thread it posts a reply containing the marker below, so a re-run sees the
thread as HANDLED. No LLM is called here; this only classifies and prints.
"""
from __future__ import annotations

import json
import subprocess
import sys

# Claude stamps its PR replies with one of these markers so a re-run can tell a
# thread it has already touched from one still awaiting Claude. A thread NEEDS
# ACTION only when its last comment carries no marker — i.e. the last word is a
# human's. HANDLED = resolved (fix/defer). AWAITING = Claude answered a question
# and is waiting on the human's next reply.
MARKER_HANDLED = "<!-- claude-code:handled -->"
MARKER_AWAITING = "<!-- claude-code:awaiting-reply -->"
MARKERS = (MARKER_HANDLED, MARKER_AWAITING)


def _claude_marker(body: str) -> str | None:
    for m in MARKERS:
        if m in body:
            return m
    return None


def _gh(args: list[str]) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=30
        )
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "gh CLI not found on PATH"
    except subprocess.TimeoutExpired:
        return 124, "", "gh timed out"


def _repo_and_pr() -> tuple[str, str, int] | None:
    code, out, err = _gh(
        ["pr", "view", "--json", "number,headRepositoryOwner,headRepository"]
    )
    if code != 0:
        code2, out2, _ = _gh(["repo", "view", "--json", "owner,name"])
        code3, out3, _ = _gh(["pr", "view", "--json", "number"])
        if code2 != 0 or code3 != 0:
            print(f"No PR for the current branch (or gh error): {err.strip()}")
            return None
        repo = json.loads(out2)
        pr = json.loads(out3)
        return repo["owner"]["login"], repo["name"], pr["number"]
    data = json.loads(out)
    # nameWithOwner is the most reliable; derive from repo view for owner/name.
    code2, out2, _ = _gh(["repo", "view", "--json", "owner,name"])
    repo = json.loads(out2)
    return repo["owner"]["login"], repo["name"], data["number"]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    rp = _repo_and_pr()
    if rp is None:
        return 0
    owner, name, number = rp
    if argv and argv[0].isdigit():
        number = int(argv[0])

    code, out, err = _gh(
        [
            "api",
            f"repos/{owner}/{name}/pulls/{number}/comments",
            "--paginate",
        ]
    )
    if code != 0:
        print(f"Could not fetch review comments: {err.strip()}")
        return 0

    try:
        comments = json.loads(out)
    except json.JSONDecodeError:
        print("Could not parse review comments from gh.")
        return 0

    by_id = {c["id"]: c for c in comments}

    # Group into threads: a reply's root is its in_reply_to_id; a finding is its
    # own root. GitHub sets in_reply_to_id to the thread root for every reply.
    threads: dict[int, list[dict]] = {}
    for c in comments:
        root = c.get("in_reply_to_id") or c["id"]
        threads.setdefault(root, []).append(c)

    print(f"# PR #{number} — {owner}/{name}")
    print("Threads with your feedback (reply chains).")
    print(f"Markers: handled={MARKER_HANDLED}  awaiting={MARKER_AWAITING}\n")

    actionable = 0
    for root_id in sorted(threads):
        chain = sorted(threads[root_id], key=lambda c: c["created_at"])
        root = by_id.get(root_id, chain[0])
        replies = [c for c in chain if c["id"] != root_id]
        if not replies:
            continue  # a finding with no human decision yet — skip

        last_marker = _claude_marker(chain[-1].get("body") or "")
        needs = last_marker is None
        if needs:
            status = "NEEDS ACTION"
            actionable += 1
        elif last_marker == MARKER_AWAITING:
            status = "AWAITING YOUR REPLY"
        else:
            status = "HANDLED"

        loc = f"{root.get('path')}:{root.get('line')}"
        print(f"## [{status}] thread root={root_id}  ({loc})")
        print(f"- reply-to id for posting: {root_id}")
        print(f"- url: {root.get('html_url')}")
        print(f"\n**Finding** (by @{root['user']['login']}):")
        print(_indent(root.get("body") or ""))
        for r in replies:
            marked = " [claude]" if _claude_marker(r.get("body") or "") else ""
            print(f"\n**Reply** by @{r['user']['login']}{marked}:")
            print(_indent(r.get("body") or ""))
        print("\n---\n")

    if actionable == 0:
        print("No threads need action — every reply has been handled.")
    else:
        print(f"{actionable} thread(s) NEED ACTION.")
    return 0


def _indent(text: str) -> str:
    return "\n".join("    " + ln for ln in text.strip().splitlines())


if __name__ == "__main__":
    raise SystemExit(main())
