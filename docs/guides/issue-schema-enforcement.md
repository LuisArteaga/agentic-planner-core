# Issue Schema Enforcement

Server-side enforcement of the repository's `Task` issue template, so issues
created via the REST API or any external client cannot bypass the required-field
schema that the web UI enforces. Implemented in [#39](https://github.com/LuisArteaga/agentic-planner-core/issues/39).

## Why

GitHub Issue Form templates (`.github/ISSUE_TEMPLATE/*.yml`) only validate their
`required` fields through the web UI. Any client creating an issue through the
API (the autonomous planner, scripts, third-party bots) submits a free-form body
and skips that check entirely. This workflow restores the contract server-side.

## How it works

- **Workflow:** `.github/workflows/issue-schema-enforcement.yml`
- **Validator:** `scripts/issue_schema.py` (stdlib only — no new dependencies)
- **Tests:** `tests/test_issue_schema.py`

The workflow triggers on `issues: [opened, edited, reopened]`:

1. Parses `.github/ISSUE_TEMPLATE/task.yml` to derive the **required section
   headers** (fields with `validations.required: true`).
2. Validates that the issue body contains every required `### <Label>` header
   **with non-empty content** (text up to the next `### ` header).
3. On a **non-compliant** issue: closes it (`not planned`), adds the `invalid`
   label, and posts a rejection comment listing the missing/empty sections.
4. On a subsequent **edit that makes it compliant**: removes the `invalid`
   label, reopens the issue, and posts a confirmation comment.

The schema check is **format-based** (presence of the required `### <Header>`
sections), not submission-method-based. Any API integration that emits the
correct headers — including the autonomous planner, which publishes issues in
the template format — passes validation and is not blocked.

## Loop prevention

The workflow **never edits an issue's body or title**. Commenting, labeling,
and closing/reopening fire `issue_comment`, `labeled`, and `closed`/`reopened`
events — none of which the workflow listens to (it listens to `opened`,
`edited`, `reopened`). Because it never produces an `edited` event, it cannot
re-trigger itself. This invariant is the root-cause prevention and is documented
inline in the workflow. Do not add a step that edits the issue body or title
without revisiting it.

To avoid comment spam, the rejection/confirmation comment is posted only on a
state transition (open → closed, or closed → open), not on every edit.

## Required headers

Derived dynamically from `.github/ISSUE_TEMPLATE/task.yml`. As of this writing:

- `### What to build`
- `### Scope`
- `### Constraints`
- `### Edge cases`
- `### Cross-cutting concerns`
- `### Acceptance criteria`

`### Blocked by` is optional. A test (`test_parse_template_extracts_required_headers`)
guards against drift: if the template's required fields change, the test fails
loudly so this validator and the template stay in sync.

## Inspiration & references

- [IssueOps: Automate CI/CD (and more!) with GitHub Issues and Actions — GitHub Blog](https://github.blog/engineering/issueops-automate-ci-cd-and-more-with-github-issues-and-actions):
  the canonical trigger/permission/checkout pattern (`issues: [opened, edited, reopened]`,
  `permissions: {contents: read, issues: write}`).
- [`lucasbento/auto-close-issues`](https://github.com/marketplace/actions/auto-close-issues):
  third-party marketplace action that parses `.github/ISSUE_TEMPLATE` titles.
  This repo owns the validator instead, matching the zero-new-dependency
  convention of the quality-gates-toolkit secret-scan.
- [Configuring issue templates — GitHub Docs](https://docs.github.com/communities/using-templates-to-encourage-useful-issues-and-pull-requests/configuring-issue-templates-for-your-repository)
