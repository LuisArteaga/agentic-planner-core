---
name: draft-issues
description: Break a plan, spec, or PRD into local, temporary Markdown files (Draft Issues) under .planner/drafts/<repo_name>/ following the standard issue template.
---

# Draft Issues Skill

This skill guides you in decomposing a product requirement document (`PRD.md`), project domain glossary (`CONTEXT.md`), and active architecture decisions (`docs/adr/`) into granular, local, temporary Markdown files called **Draft Issues**.

These Draft Issues will be stored locally and processed autonomously by the refinement orchestrator in the next phase.

## Input Context

Before starting the decomposition, locate and read the following files in the workspace:
1. `PRD.md` — The product requirement document containing goals and target features.
2. `CONTEXT.md` (Domain Glossary) — Defines the domain terminology and active constraints.
3. `docs/adr/` — Contains all Architecture Decision Records that must be respected.

## Decomposing into Tracer Bullets

Break down the implementation plan into **tracer-bullet vertical slices**. A tracer bullet is a thin, end-to-end slice through all layers of the application (e.g., database schema, backend API, frontend UI, tests) rather than a horizontal layer (e.g., "implement the database schema" or "build the UI").

### Tracer-Bullet Rules:
1. **Vertical Isolation**: Each slice must cut through all integration layers and be testable on its own.
2. **Granularity**: Keep slices narrow. Prefer multiple small, independent, or sequentially linked issues over a few monolithic issues.
3. **End-to-End Verifiable**: A completed slice must be demonstrable or verifiable by automated tests.

## File Placement & Naming

Write the generated Draft Issues as individual Markdown files to:
`.planner/drafts/<repository_name>/`

### Naming Convention:
1. Determine the dependency graph of the issues.
2. Sort them topologically (issues that block others must come first).
3. Name the files using a 4-digit sequential prefix with leading zeros, followed by a short slug.
   - Example: `0001-setup-schema.md` (blocks `0002`)
   - Example: `0002-implement-auth.md` (depends on `0001`)

## Issue Template

Every Draft Issue file MUST strictly follow this Markdown structure:

```markdown
# {type}: {Short Description}

## What to build
{Concise, technical description of the vertical slice behavior, using the domain glossary terms from CONTEXT.md}

## Scope
{A single lowercase word identifying the subsystem, e.g., auth, api, ui, db, ci}

## Constraints
{List of active constraints the implementation must follow, referencing relevant ADRs. E.g., - Citing [ADR-0001](./docs/adr/0001-some-decision.md)}

## Edge cases
{List of testable edge cases, boundary values, entity lifecycles, and concurrency conditions}

## Cross-cutting concerns
{Aspects outside this issue that the developer must be aware of but should not implement (e.g., Caching, API Envelopes, Logging)}

## Acceptance criteria
- [ ] {Testable criterion 1}
- [ ] {Testable criterion 2}
- [ ] All new code paths have test coverage
- [ ] Local checks pass

## Blocked by
{The filename of the blocker, e.g., 0001-setup-schema.md, or "None" if there are no blockers}
```

### Formatting Rules:
* The first line must be a level-1 heading (`# `) containing the conventional commit type (e.g., `feat`, `fix`, `docs`, `refactor`) and a short description.
* Do not include any text outside the specified headings.
* The `Acceptance criteria` section must contain the two standard checks:
  - `- [ ] All new code paths have test coverage`
  - `- [ ] Local checks pass`
