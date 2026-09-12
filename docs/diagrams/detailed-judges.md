# Detailed view — the CI LLM-judge pipeline

How pull requests on this repository are judged: the toolkit composite runs
deterministic gates first, then four sequential LLM judges whose verdicts are
merge-blocking.

> **Reflects:** behavior on `main` as of 2026-09-12. Grounded in the sources
> below; where an ADR and the code disagree, this diagram follows the code and
> the mismatch is flagged under **Sources**.

## Diagram

```mermaid
flowchart TD
    PR["Pull request on agentic-planner-core<br/>event pull_request"]
    CALL["pr-checks.yml caller job<br/>grants contents read + pull-requests write"]
    COMP["Toolkit composite<br/>python-checks.yml at v1.7.0"]
    DET["Deterministic gates<br/>ruff 0.16.6 - mypy - pytest<br/>coverage floor 80 + changed-line gate 100 percent<br/>semgrep - pip-audit - secret-scan"]
    GATE{"Deterministic gates green<br/>and event is pull_request ?"}
    SKIPPED["LLM review job skipped by design<br/>workflow_dispatch runs"]
    CTX["Judge context<br/>git diff enriched with enclosing functions<br/>architecture context from docs/context.md and docs/adr"]
    SYN["Judge 1 - syntax_lint<br/>fail-fast gate"]
    SFAIL{"syntax_lint verdict FAIL ?"}
    REST["Judges 2 to 4 sequential<br/>test_coverage - architecture - security<br/>models from config/factory.json ci_cd_pr_judges"]
    REVIEW["One combined GitHub review<br/>visible status table<br/>hidden machine-readable verdict block"]
    VERDICT{"All four verdicts PASS ?"}
    RC["request-changes - merge blocked<br/>FAIL and NEEDS REVIEW both block"]
    GREEN["Merge allowed"]
    PR --> CALL
    CALL --> COMP
    COMP --> DET
    DET --> GATE
    GATE -->|No| SKIPPED
    GATE -->|Yes| CTX
    CTX --> SYN
    SYN --> SFAIL
    SFAIL -->|Yes - others skipped| REVIEW
    SFAIL -->|No| REST
    REST --> REVIEW
    REVIEW --> VERDICT
    VERDICT -->|Yes| GREEN
    VERDICT -->|No| RC
```

## Notes

- Judge models resolve solely from `config/factory.json` (key
  `ci_cd_pr_judges`); on a fresh clone the file is untracked and missing, and
  the toolkit falls back to its built-in default models (ADR-0024). Env-var
  model overrides exist only as documented exceptions.
- Fail-fast rationale (ADR-0008): a syntax failure skips the remaining judges
  (`SKIPPED`), so expensive reasoning models never run on syntactically broken
  code, and the review still lands immediately with `REQUEST_CHANGES`.
- Verdict semantics (ADR-0014): both `FAIL` and `NEEDS REVIEW` block the merge;
  only verified `PASS` verdicts allow it.
- The hidden verdict block (ADR-0015) is an HTML comment in the review body,
  consumed by the `pr-feedback-loop` parser — the visible table is for humans
  only.
- Calibration (ADR-0023): `planner/eval/judge.py` imports `JUDGE_PROMPTS`,
  `evaluate_response`, and `load_architecture_context` from
  `quality_gates_toolkit.review`, so the eval suite
  (`python -m planner eval --judge <type>`, ADR-0017) calibrates exactly what
  CI runs.

## Sources

- CI caller: [../../.github/workflows/pr-checks.yml](../../.github/workflows/pr-checks.yml)
- ADR-0008 — multistage LLM PR judges:
  [../adr/0008-multistage-llm-pr-judges.md](../adr/0008-multistage-llm-pr-judges.md)
- ADR-0011 — judge context strategy:
  [../adr/0011-judge-kontext-strategie.md](../adr/0011-judge-kontext-strategie.md)
- ADR-0014 — judge merge-blocking:
  [../adr/0014-llm-judge-merge-blocking.md](../adr/0014-llm-judge-merge-blocking.md)
- ADR-0015 — hidden verdict block:
  [../adr/0015-hidden-verdict-block.md](../adr/0015-hidden-verdict-block.md)
- ADR-0022 — consume quality-gates-toolkit:
  [../adr/0022-consume-quality-gates-toolkit.md](../adr/0022-consume-quality-gates-toolkit.md)
- ADR-0023 — importable toolkit judge API:
  [../adr/0023-replace-judge-snapshot-with-importable-toolkit-package.md](../adr/0023-replace-judge-snapshot-with-importable-toolkit-package.md)
- Factory shape: [../../config/factory.example.json](../../config/factory.example.json)
- Eval adapter: [../../planner/eval/](../../planner/eval/)

**Mismatch flagged:** ADR-0011, ADR-0014, and ADR-0015 cite `scripts/review.py`
as the judge engine; since ADR-0022/ADR-0023 the engine ships in the
`quality-gates-toolkit` package, CI consumes it via the composite workflow, and
the local `scripts/` directory no longer exists. The diagram follows the code.
