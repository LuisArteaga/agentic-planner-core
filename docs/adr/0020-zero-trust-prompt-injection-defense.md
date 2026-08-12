# 0020 - Zero-Trust Prompt-Injection Defense for the Refinement Subgraph

* **Status**: Accepted
* **Datum**: 2026-07-21
* **Entscheidungsträger**: Luis Arteaga / Antigravity

## Context and Problem Statement

Phase 3 (Autonomous Refinement & Publish) ingests untrusted external content —
OpenRouter web-search snippets and direct-URL fetches. A malicious source can
carry an indirect prompt injection that manipulates the planner into emitting a
poisoned implementation-ready issue. Because published issues carry the
`agent-ready` label and are consumed by an autonomous Developer Agent, this
forms a multi-agent attack chain
(`Attacker → web/repo content → Planner → refined issue → Developer Agent → system compromise`).

The existing `strict` source allowlist (ADR-0002) is a structural control that
prevents most injection *at the source*, but it cannot fully prevent it:
allowlisted domains (e.g. `github.com`, `arxiv.org`) can still host
user-contributed content (issue bodies, comments, preprint PDFs) that carries
an injection payload. We needed an explicit defense layer for the residual
risk.

## Decision

Adopt a defense-in-depth ranking inside the refinement subgraph, between
`evaluate_grade` and `apply_decision`:

1. **Structural separation (primary, existing)** — external content is treated
   as DATA, not instructions; the `strict` allowlist (ADR-0002) bounds the
   source surface.
2. **LLM Security Judge (primary, new)** — a `security_audit` node invokes a
   cheap instruction-following LLM with a `SecurityAuditResult` structured
   schema over the search snippets + derived proposals; on detection it
   blacklists the offending source.
3. **HITL publish gate (primary, new)** — an optional confirmation prompt
   before the GitHub API call (`--interactive` / `--yes` /
   `[security].require_approval`).
4. **Regex pre-filter (best-effort only)** — a small high-precision pattern
   list. In `normal` mode regex hits are logged but never blacklist alone; in
   `strict` mode they contribute to the blacklisting decision. We explicitly
   reject treating the regex as a primary defense (blacklisting on a denylist
   is brittle and trivially bypassed).

A self-healing loop backs the judge: on detection the offending source is
blacklisted and the graph re-enters `web_search`, which **filters** the
accumulated results against the blacklist (no re-fetch — re-searching the same
queries would return the same indexed source). After `max_security_retries`
(2), or when no clean results remain, the subgraph falls back to **offline
refinement** (external results discarded, local ADRs only). A per-run Markdown
security report is written to `.planner/reports/<repo>/`.

## Considered Options

- **Regex sanitizer as primary defense (issue §2.A original).** Rejected: a
  blacklist of phrases like "ignore previous instructions" is high-recall /
  low-precision and trivially bypassed (synonyms, encoding, obfuscation).
  OWASP A03:2021 and the prompt-injection literature consistently prefer
  allowlisting / structural controls over blacklisting. Downgraded to an
  optional pre-filter.
- **LangGraph `interrupt()` for the HITL gate.** Rejected for now: the refine
  graph is invoked synchronously from the CLI without a checkpointer. A
  resumable interrupt would require adding persistence (a checkpointer) and a
  `Command(resume)` driver loop — real complexity for a one-shot batch CLI.
  A synchronous `input()` prompt before the API call is the right-sized
  solution; it auto-approves (with a warning) when stdin is not a TTY so CI
  runs do not hang.
- **Re-fetch on retry.** Rejected: identical queries return the same (now
  blacklisted) indexed source. Filtering the accumulated results is cheaper,
  deterministic, and matches the issue's "search tools filter out blacklisted
  sources" semantics.

## Consequences

- **Positive:** defense-in-depth that does not rely on a single brittle
  control; the LLM judge catches semantic injections the regex and allowlist
  miss; offline fallback guarantees the batch still produces a (local-only)
  issue instead of poisoning the downstream agent; a per-run report gives
  human traceability.
- **Negative:** the subgraph gains one LLM call per draft (mitigated by the
  cheap model + the `audit_level=off` escape hatch and the triviality gate);
  an extra node + conditional edge makes the topology more complex; the
  `sanitized_search_results` view was introduced so the audit/filter path can
  take effect without disturbing the `search_results` accumulation reducer
  (ADR-0013), requiring downstream nodes to read via `active_search_results`.

## Inspiration & References

- **Google DeepMind — "Securing the future of AI agents" / "Three Layers of
  Agent Security"** (multi-layer agent security: individual agents,
  multi-agent systems, empowering defenders). https://deepmind.google/blog/securing-the-future-of-ai-agents
- **Google — "Mitigating prompt injection attacks with a layered defense
  strategy"** (model hardening + ML-based injection classifiers + system-level
  safeguards; reinforces defense-in-depth over a single filter).
  https://blog.google/security/mitigating-prompt-injection-attacks
- **OWASP Top 10 for LLM Applications (LLM01: Prompt Injection)** and
  **OWASP A03:2021 (Injection)** — blacklisting/denylisting is brittle;
  allowlisting and structural controls are preferred.
  https://genai.owasp.org/
- **LangGraph Human-in-the-Loop** — `interrupt()` / `Command(resume)` is the
  idiomatic resumable HITL pattern; we deliberately defer it in favor of a
  synchronous prompt for the batch CLI.
  https://docs.langchain.com/oss/python/langchain/human-in-the-loop
- **Issue #51 pre-selection verdict** — trimmed the duplicate YAML→TOML
  section (already done in #59 / ADR-0016) and re-ranked the defenses
  (structure + LLM judge + HITL primary; regex optional pre-filter).
