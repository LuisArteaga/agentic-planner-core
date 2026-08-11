# 0013 - Per-Query Search Fan-Out with Cross-Query Aggregation

* **Status**: Accepted
* **Datum**: 2026-08-11
* **Entscheidungsträger**: Luis Arteaga

## Kontext und Problemstellung

`analyze_sources` extrahiert pro Draft `N` Such-Queries (`search_queries`), doch `web_search` kollabierte alle Queries zu einem einzigen kommagetrennten Prompt und feuerte **einen** OpenRouter-Server-Tool-Aufruf. So wurde pro Draft `N` Queries → 1 gemischte Suche → ≤10 Zitate, die extrahierten Queries waren weitgehend ungenutzt und die Recherche-Abdeckung blieb auf das beschränkt, was eine gemischte Suche zurückgibt (#57).

OpenRouter bietet für `openrouter:web_search` den Parameter `max_total_results` an — er begrenzt aber nur die *kumulativen* Ergebnisse, **wenn das Modell selbst innerhalb eines einzelnen Requests mehrfach sucht**. Verlässt man sich darauf, entscheidet das Modell (nondeterministisch), ob und wie oft es pro Query sucht — genau die Underuse-Klasse, die #57 beseitigen soll.

## Entscheidungsfaktoren (Drivers)

* Deterministische Recherche-Abdeckung: jede extrahierte Query soll ihre eigene Suche erhalten.
* Kein Silent-Drop früherer Query-Ergebnisse (#56-Geist: partielle Läufe müssen ehrlich sein).
* Strict-Modus (`allowed_domains`) muss pro Query durchgesetzt bleiben.
* Keine Überladung des OpenRouter-Params `max_total_results` mit einer semantisch anderen Bedeutung.

## Betrachtete Optionen

### Option 1: Ein Request, Modell sucht mehrfach selbst (`max_total_results` relied upon)
Ein `invoke()` mit allen Queries; das Modell entscheidet, wie oft es sucht; `max_total_results` deckelt kumulativ.
* **Vorteil**: Ein Request, geringere Kosten/Latenz.
* **Nachteil**: Nondeterministisch — das Modell kann Queries auslassen oder nur einmal suchen (aktuelles Underuse-Problem). Keine Garantie, dass jede Query zu einer Suche führt.

### Option 2: Ein `invoke()` pro Query, eigenes Aggregation/Dedupe/Cap (Gewählt)
Pro Query ein eigener `invoke()`-Aufruf; Zitate werden über alle Queries gesammelt, nach URL dedupliziert und auf `MAX_AGGREGATED_RESULTS` (20) gedeckelt. Strict-Modus wird pro Query über dasselbe `allowed_domains`-Binding durchgesetzt.
* **Vorteil**: Deterministisch, testbar, volle Kontrolle über Dedupe/Cap, keine Queries verloren. Pro-Query-Fehlertoleranz (504/Exception einer Query löscht andere nicht).
* **Nachteil**: `N` Requests statt einem — höhere Latenz und Token-Kosten für die jeweilige Prose-Synthese (akzeptabel, da `N` typischerweise 3–5 und `thinking: none` für `web_search`).

### Option 3: Batches (mehrere Queries pro `invoke()`)
Kompromiss aus 1 und 2.
* **Vorteil**: Weniger Requests als Option 2.
* **Nachteil**: Zusätzliche Komplexität (Batch-Größe, Zuordnung der Zitate zu Queries) ohne nennenswerten Vorteil bei kleinen `N`.

## Entscheidung

Wir wählen **Option 2** (Per-Query Fan-Out mit eigener Aggregation). `max_total_results` bleibt im Tool-Binding gültig (begrenzt kumulativ, falls ein Modell in einem Request mehrfach sucht), wird aber **nicht** als Cross-Query-Cap verwendet — dafür existiert die separate Konstante `MAX_AGGREGATED_RESULTS` in `web_search.py`. Die `Annotated[List, operator.add]`-Reducer aus #56 erlauben ein sicheres Per-Query-Akkumulieren im State.

## Konsequenzen

* **Positiv**: Maximale Recherche-Abdeckung pro Draft; deterministisch und gut testbar; partielle Query-Fehler löschen keine Ergebnisse (kein Silent-Drop); Strict-Modus pro Query gewährleistet.
* **Negativ**: Höhere Request-Anzahl und Token-Kosten; Sequential-Ausführung (keine Parallelität) — Parallelität als mögliche spätere Optimierung notiert, bewusst weggelassen (Scope/Rate-Limit-Risiko). Transiente 504-Timeouts werden pro Query abgefangen, aber *nicht* retried (separates Anliegen, Follow-up).

## Inspiration & References

* **gpt-researcher** (assafelovic/gpt-researcher, 28.8k★) — Plan-and-Solve / parallelisierte Multi-Query-Suche, Merge zu Bericht mit Zitaten: https://github.com/assafelovic/gpt-researcher
* **Dify — Enhancing GPT-Researcher with Parallel Features** — parallele Sub-Query-Branches, anschließende Aggregation: https://dify.ai/blog/enhancing-gpt-researcher-with-parallel-and-advanced-iterative-features
* **OpenRouter Web Search Server Tool** — `max_results` vs `max_total_results` (per-Request kumulativ): https://openrouter.ai/docs/guides/features/server-tools/web-search
* Vorgänger: [ADR-0003](./0003-openrouter-server-tools-binding.md) (OpenRouter Tool-Binding), [ADR-0012](./0012-url-citation-annotation-capture.md) (Zitate aus Annotations).
