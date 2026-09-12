# Diagrams

Mermaid.js views of the planner for external readers. GitHub renders Mermaid
natively — no images, no external services. One diagram per file keeps deep
links stable: linking a file links its diagram.

> **Reflects:** behavior on `main` as of 2026-09-12 (quality-gates-toolkit
> v1.7.0 era). Every diagram lists the ADRs and files it is grounded in; where
> an ADR and the code disagree, the diagram follows the code and flags the
> mismatch in that file's source list.

| File | Viewpoint | Grounded in |
|---|---|---|
| [setup.md](./setup.md) | Getting the planner up: install, keys, configuration, first run | ADR-0002, ADR-0016, ADR-0024 |
| [process.md](./process.md) | The intended usage process: grill → verify → draft → refine → published agent-ready issues | ADR-0001, ADR-0004, ADR-0005, ADR-0006, ADR-0007, ADR-0019, ADR-0020 |
| [architecture-overview.md](./architecture-overview.md) | Coarse component view: planner core, target repository, external services, CI | ADR-0001, ADR-0002, ADR-0003, ADR-0004, ADR-0008, ADR-0022 |
| [detailed-search-grounding.md](./detailed-search-grounding.md) | How refinement research stays grounded and injection-safe | ADR-0002, ADR-0003, ADR-0010, ADR-0012, ADR-0013, ADR-0020 |
| [detailed-judges.md](./detailed-judges.md) | The CI PR-judge pipeline and its merge-blocking semantics | ADR-0008, ADR-0011, ADR-0014, ADR-0015, ADR-0022, ADR-0023 |
| [detailed-session-persistence.md](./detailed-session-persistence.md) | Custom JSON session serialization and interactive resuming | ADR-0006, ADR-0007 |

For the full prose reference see [architecture.md](../architecture.md); the
root [README](../../README.md) covers setup and the high-level flow.

## Notes

- Configurable behavior is drawn with its defaults and marked as configurable
  (strict-mode source restriction, model routing, HITL publish gate).
- The judge architecture-context loader reads only `docs/context.md` and
  `docs/adr/*.md` (fixed paths, non-recursive), so this directory cannot affect
  the CI judges or the eval harness.
- Several existing ADR titles are German; they are linked as-is while diagram
  labels and prose stay English (ADR-0018).
