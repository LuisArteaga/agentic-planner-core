---
name: pr-feedback-loop
description: Poll a pull request for LLM PR Review Judge verdicts and CI status, act on actionable feedback, and iterate until all judges PASS and CI is green. Use when finalizing a PR created by the autonomous loop (after `gh pr create`), when asked to run a "feedback loop", "wait for PR review", "resolve judge feedback", "fix CI", or iterate on LLM-judge findings. Encodes the ADR-0015 hidden verdict block format and ADR-0014 merge-blocking semantics specific to this repository.
---

# PR Feedback Loop

Poll an open PR for LLM PR Review Judge verdicts and CI status. Act on actionable feedback (FAIL findings) until all judges PASS and CI is green, then stop.

## Context

This repository gates PRs with four LLM judges run by the `quality-gates-toolkit` composite workflow (`.github/workflows/pr-checks.yml`, pinned `v1.7.0` — ADR-0022). The judges post a single GitHub review with a human-readable summary and a hidden machine-parseable verdict block at the end.

## The Judges

| Key | Dimension |
|-----|-----------|
| `syntax_lint` | Syntax, JSON schemas, naming conventions |
| `test_coverage` | Test presence and assertion quality for changed logic |
| `architecture` | ADR compliance |
| `security` | Verified security vulnerabilities |

Each judge returns one of: `PASS`, `FAIL`, or `NEEDS REVIEW`.

## Merge-Blocking Semantics (ADR-0014)

Both `FAIL` and `NEEDS REVIEW` block the merge. `NEEDS REVIEW` is not a soft warning — it means the judge lacked context to verify and the merge is blocked until resolved. Treat any non-PASS verdict as actionable.

## Verdict Block Format (ADR-0015)

The review body ends with a hidden HTML comment:

```
<!-- llm-pr-review-verdicts
syntax_lint: PASS
test_coverage: FAIL
architecture: PASS
security: PASS
-->
```

## Workflow

### 1. Check verdicts (non-blocking, preferred)

Run the bundled parser on the PR number. It fetches the latest review, extracts the verdict block and any actionable findings, and exits 0 if all PASS / 1 if any FAIL or NEEDS REVIEW / 2 on error.

```bash
python3 .agents/skills/pr-feedback-loop/scripts/parse_pr_verdicts.py <PR_NUMBER>
```

The JSON output includes `verdicts`, `failing`, `needs_review`, and `findings` (actionable `[SEVERITY]`-tagged lines from the review body). If `has_review` is false, the judges have not posted yet — CI may still be running.

### 2. Check CI status

```bash
gh pr checks <PR_NUMBER>
```

CI is green only when every check shows `pass` (no `fail`, `pending`, or `in_progress`).

### 3. Act on actionable feedback

If any judge returned `FAIL` or `NEEDS REVIEW`:

- Read the `findings` array from the parser output — each entry is a `[SEVERITY] message` line from the failing judge's detail section.
- Implement the fix locally.
- Run `make verify` to confirm tests and linters pass.
- Commit as `fix: <short description>` and push.
- The push triggers a new CI run and a fresh judge review. Return to step 1.

### 4. Stop condition

Stop when **all judges PASS** and **CI is green**. No fix commits needed.

## Polling Pattern

**Do NOT** block with a long-running `sleep 60` loop — it is cancellable and wastes a turn. Instead, perform a single non-blocking check (steps 1 + 2) per turn. If verdicts or CI are not yet ready, report status and continue on the next turn.

When a bounded poll is explicitly required (e.g., "poll every 60s for up to 15 iterations"), use a backgrounded loop with an exit-code contract:
- `0` = success (all PASS + CI green)
- `1` = actionable feedback found (fetch findings and act)
- `2` = timeout reached (escalate to human)

## Escalation

If actionable feedback remains unresolved after the agreed iteration cap: post a summary of open points as a PR comment and hand over to a human reviewer.

```bash
gh pr comment <PR_NUMBER> --body "<summary of unresolved findings>"
```

## Source Locators

The judge engine lives in the toolkit (pinned `v1.7.0`):
`quality_gates_toolkit/review.py` at <https://github.com/LuisArteaga/quality-gates-toolkit/blob/v1.7.0/quality_gates_toolkit/review.py>.

- Judge keys: `review.py:1308` (`JUDGE_KEYS`)
- Verdict block builder (inline in the report builder): `review.py:1723` (`hidden_lines`)
- Review submission: `review.py:862` (`submit_github_review`)
- CI workflow: `.github/workflows/pr-checks.yml` (composite call with `enable-llm-review: true`)
