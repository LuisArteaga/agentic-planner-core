# Detailed view — search grounding and injection safety

Inside the refinement subgraph's research path: how queries fan out, how
results stay grounded in `url_citation` annotations, and how the zero-trust
defense handles flagged sources.

> **Reflects:** behavior on `main` as of 2026-09-12. Grounded in the sources
> below; where an ADR and the code disagree, this diagram follows the code and
> the mismatch is flagged under **Sources**.

## Diagram

```mermaid
flowchart TD
    AN["analyze_sources<br/>extracts keywords and search_queries<br/>in strict mode keywords only - no new sources"]
    SA["security_audit<br/>runs after grading"]
    WS["web_search node"]
    RETRY{"security_retries greater than 0 ?"}
    FILTER["Filter-only re-entry<br/>drop blacklisted sources from accumulated results<br/>write sanitized_search_results - no re-fetch"]
    STRICTCHK{"strict mode and allowlist empty ?"}
    ABORT["ValueError - the draft fails<br/>startup already rejects this combination"]
    FETCH["Pre-fetch configured urls from sources config<br/>snippets capped at 2000 characters"]
    PERQ["Fan out - one invoke per query<br/>openrouter:web_search server tool bound via model.bind<br/>allowed_domains injected in strict mode"]
    ANN["Read citations from url_citation annotations<br/>captured by OpenRouterAnnotationChatOpenAI<br/>web snippets capped at 300 characters"]
    ISO["Per-query failure isolated<br/>transient errors never drop earlier results"]
    AGG["Aggregate<br/>dedupe by URL - direct results first<br/>cap MAX_AGGREGATED_RESULTS = 20"]
    OK["status success<br/>web_search_error lists per-query issues"]
    FAILED["status web_search_failed<br/>honest durable failure signal"]
    NEXT["Refinement continues<br/>propose_options then evaluate_grade<br/>reading active_search_results"]
    AN --> WS
    SA -.->|retry on detection| WS
    WS --> RETRY
    RETRY -->|Yes| FILTER
    RETRY -->|No| STRICTCHK
    STRICTCHK -->|Yes| ABORT
    STRICTCHK -->|No| FETCH
    FETCH --> PERQ
    PERQ --> ANN
    ANN --> ISO
    ISO --> AGG
    AGG -->|results found| OK
    AGG -->|no results at all| FAILED
    FILTER --> NEXT
    OK --> NEXT
    FAILED --> NEXT
```

## Notes

- Defaults (configurable in `config/sources.toml`): `strict = true`,
  `engine = "auto"`, `search_context_size`, `max_results`, `max_total_results`,
  `excluded_domains`. In strict mode the `allowed_domains` set is the merged
  set of configured `domains` plus the hosts of configured `urls`.
- Defense ranking (ADR-0020): the strict allowlist, the LLM security judge, and
  the HITL publish gate are PRIMARY; the regex pre-filter is best-effort only
  (logs in `normal` mode, contributes to blocking in `strict` mode).
- Self-healing loop: on detection the offending source is blacklisted and the
  graph re-enters `web_search` in filter-only mode — no re-fetch, because the
  same queries would return the same indexed source. After
  `max_security_retries = 2` or when no clean results remain, refinement falls
  back to offline mode (external results discarded, local ADRs only).
- The aggregate cap constant `MAX_AGGREGATED_RESULTS = 20` lives in
  `planner/nodes/web_search.py`; per-query results use the
  `Annotated[List, operator.add]` reducers so partial failures never silently
  drop earlier results.

## Sources

- ADR-0002 — strict-mode source restriction:
  [../adr/0002-strict-modus-quelleneinschraenkung.md](../adr/0002-strict-modus-quelleneinschraenkung.md)
- ADR-0003 — OpenRouter server-tools binding:
  [../adr/0003-openrouter-server-tools-binding.md](../adr/0003-openrouter-server-tools-binding.md)
- ADR-0010 — direct-URL and GitHub-API tools:
  [../adr/0010-direkt-url-und-github-api-werkzeuge.md](../adr/0010-direkt-url-und-github-api-werkzeuge.md)
- ADR-0012 — url_citation annotation capture:
  [../adr/0012-url-citation-annotation-capture.md](../adr/0012-url-citation-annotation-capture.md)
- ADR-0013 — per-query search fan-out:
  [../adr/0013-per-query-search-fanout.md](../adr/0013-per-query-search-fanout.md)
- ADR-0020 — zero-trust prompt-injection defense:
  [../adr/0020-zero-trust-prompt-injection-defense.md](../adr/0020-zero-trust-prompt-injection-defense.md)
- Node code: [../../planner/nodes/web_search.py](../../planner/nodes/web_search.py),
  tools: [../../planner/tools/research.py](../../planner/tools/research.py),
  analyzer: [../../planner/nodes/analyze_sources.py](../../planner/nodes/analyze_sources.py)
- Security report writer:
  [../../planner/nodes/security_audit.py](../../planner/nodes/security_audit.py)

**Mismatch flagged:** ADR-0010 documents a 10-entry cap on `search_results`;
the code and ADR-0013 cap the aggregate at `MAX_AGGREGATED_RESULTS = 20`
(`planner/nodes/web_search.py`). The diagram follows the code.
