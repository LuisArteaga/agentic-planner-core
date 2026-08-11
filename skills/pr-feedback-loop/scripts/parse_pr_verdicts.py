#!/usr/bin/env python3
"""Parse LLM PR Review Judge verdicts from a GitHub PR.

The PR Review Judges (scripts/review.py) post a single GitHub review whose body
ends with a hidden HTML-comment verdict block (ADR-0019):

    <!-- llm-pr-review-verdicts
    syntax_lint: PASS
    test_coverage: PASS
    architecture: PASS
    security: PASS
    -->

This script fetches the latest review on a PR via `gh pr view --json reviews`,
extracts that block, and prints structured status + any actionable findings.

Exit codes:
    0  All judges PASS (or no review posted yet)
    1  At least one judge returned FAIL or NEEDS REVIEW (merge-blocking)
    2  gh CLI or parsing error

Usage:
    python3 parse_pr_verdicts.py <PR_NUMBER>
    python3 parse_pr_verdicts.py 90
"""

import json
import subprocess
import sys

BLOCK_START = "<!-- llm-pr-review-verdicts"
BLOCK_END = "-->"


def fetch_reviews(pr_number):
    """Return the list of review dicts from gh, or None on error."""
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--json", "reviews"],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
        return data.get("reviews") or []
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(json.dumps({"error": f"gh/parse failure: {e}"}))
        sys.exit(2)


def parse_verdict_block(body):
    """Extract the {judge_key: status} dict from the hidden verdict block."""
    verdicts = {}
    in_block = False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith(BLOCK_START):
            in_block = True
            continue
        if in_block:
            if s == BLOCK_END:
                break
            if ":" in s:
                k, v = s.split(":", 1)
                verdicts[k.strip()] = v.strip()
    return verdicts


def extract_findings(body):
    r"""Extract actionable findings: lines formatted as `- `[SEVERITY]` message`."""
    findings = []
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("- `[") and "]`" in s:
            findings.append(s)
    return findings


def main():
    if len(sys.argv) != 2:
        print("Usage: parse_pr_verdicts.py <PR_NUMBER>", file=sys.stderr)
        sys.exit(2)

    pr_number = sys.argv[1]
    reviews = fetch_reviews(pr_number)

    if not reviews:
        print(
            json.dumps(
                {
                    "has_review": False,
                    "message": "No review posted yet. Judges may still be running in CI.",
                }
            )
        )
        sys.exit(0)

    # Latest review containing a verdict block (skip stale reviews without one)
    review = None
    for r in reversed(reviews):
        body = r.get("body") or ""
        if BLOCK_START in body:
            review = r
            break

    if review is None:
        print(
            json.dumps(
                {
                    "has_review": False,
                    "message": "Latest review has no verdict block (judges may not have run).",
                }
            )
        )
        sys.exit(0)

    body = review.get("body") or ""
    state = review.get("state") or "UNKNOWN"
    verdicts = parse_verdict_block(body)
    findings = extract_findings(body)

    failing = [k for k, v in verdicts.items() if v == "FAIL"]
    needs_review = [k for k, v in verdicts.items() if v == "NEEDS REVIEW"]
    all_pass = bool(verdicts) and all(v == "PASS" for v in verdicts.values())

    output = {
        "has_review": True,
        "review_state": state,
        "verdicts": verdicts,
        "all_pass": all_pass,
        "failing": failing,
        "needs_review": needs_review,
        "findings": findings,
    }
    print(json.dumps(output, indent=2))

    if failing or needs_review:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
