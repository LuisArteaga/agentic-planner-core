# 0019 - Zero-Error-Tolerance Validation AddOn (Deterministic Gates + Fable-Adapted Intent/Judge)

* **Status**: Accepted
* **Datum**: 2026-07-14
* **Entscheidungsträger**: Luis Arteaga / Antigravity

## Kontext und Problemstellung

Der autonome Verfeinerungsprozess (`python -m planner refine`) veröffentlicht
Draft-Issues ohne deterministische Vorab-Prüfung auf Glossar-Konformität,
Abhängigkeits-Zyklen oder ADR-Rückverfolgbarkeit. Strukturelle Änderungen an
einem vorgelagerten Issue invalidieren nachgelagerte Issues aktuell unbemerkt.
Inkonsistenzen schleichen sich durch LLM-Drift ein, weil jegliche Validierung
der LLM überlassen wäre.

Es fehlt ein optionaler, strenger Qualitäts-Korridor, der Fehler deterministisch
erkennt und den Prozess sofort anhält (Human-in-the-Loop), anstatt Fehler
autonom zu beheben.

## Entscheidungsfaktoren (Drivers)

* **Determinismus**: Kern-Lints dürfen keine LLM-Aufrufe enthalten, um
  Inkonsistenzen durch LLM-Drift auszuschließen (AddOn-Constraint).
* **Fail-loud statt Fail-safe**: Ein Validierungsverstoß hält den gesamten
  Batch an und übergibt an den Menschen, anstatt den Fehler zu verschlucken
  oder autonom zu beheben.
* **Isolation vs. Halt**: Der bestehende Master-Loop isoliert Einzel-Fehler
  (ADR-0005). Zero-Tolerance-Verstöße brechen bewusst mit diesem Muster und
  halten die gesamte Verarbeitung an.
* **Kaskadeneffekte**: Strukturelle Änderungen an vorgelagerten Issues müssen
  nachgelagerte Issues deterministisch als veraltet markieren.

## Betrachtete Optionen

### Option 1: Deterministische Kern-Lints + LLM Intent/Judge Gates, halt-on-violation (Gewählt)

Vier deterministische Checks (Glossar-Linter, topologischer
Abhängigkeits-Validator via `graphlib.TopologicalSorter`, ADR-Rückverfolgbarkeit,
Kaskaden-Kollisions-Gate) arbeiten ohne LLM. Zwei LLM-basierte Gates (Intent
Gate, Planning Judge) adaptieren den Think/Act/Prove-Loop der Fable Method auf
Planing-Zeit. Ein Trivialitäts-Gate umgeht die LLM-Gates für triviale Issues.
Verstöße werfen `ZeroToleranceViolation` und halten den Batch an.

### Option 2: Rein LLM-basierte Validierung

* **Vorteil**: Flexibler, erfordert keine Parser.
* **Nachteil**: Verletzt die Determinismus-Constraint; LLM-Drift produziert
  inkonsistente Urteile; nicht reproduzierbar in CI.

### Option 3: Deterministische Lints nur, ohne Intent/Judge

* **Vorteil**: Vollständig deterministisch, minimaler Kosten.
* **Nachteil**: Keine semantische Hypothesen-Prüfung gegen die Spezifikation;
  der Fable-Method-„Prove"-Schritt fehlt, womit plausible, aber spekulative
  Issues ungeprüft durchgelassen werden.

## Entscheidung

Wir wählen **Option 1**. Die Kombination aus deterministischen Kern-Lints
(reproduzierbar, drift-frei, CI-tauglich) und zwei LLM-Gates (semantische
Endprüfung analog Fable-Method) erfüllt sowohl die Determinismus- als auch die
 semantische Prüf-Anforderung. Die `halt-on-violation`-Semantik bricht bewusst
mit der Einzel-Fehler-Isolation aus ADR-0005, da Zero-Tolerance-Verstöße
per Definition menschliche Intervention erfordern.

### Konsequenzen

* **Positiv**: Reproduzierbare, drift-freie Kern-Validierung; nachgelagerte
  Issues werden bei Upstream-Änderungen deterministisch als `stale` markiert;
  klare HITL-Fallback-Pfade mit verständlichen Fehlermeldungen.
* **Negativ**: Der Master-Loop benötigt eine Sonderbehandlung für
  `ZeroToleranceViolation` (Re-Raise statt Isolation); der Subgraph erhält
  zusätzliche Knoten, was die Topologie komplexer macht; der Intent/Judge-Pfad
  verursacht zusätzliche LLM-Kosten (durch das Trivialitäts-Gate für triviale
  Issues reduziert).

## Inspiration & Referenzen

* **Fable Method** (`Sahir619/fable-method`, ~2.1k★) — der Think/Act/Prove-Loop,
  das Intent Gate, das Trivialitäts-Gate (1 Datei, <10 Zeilen, keine Suche) und
  der `fable-judge` (Prove). Verifizierer in unabhängigem Kontext finden laut
  Beobachtungen ~73 % gesäter Fehler vs. 7–33 % bei Self-Critique im selben
  Kontext — Grundlage für den separaten Planning Judge.
  https://github.com/Sahir619/fable-method
* **Claude Fable 5 Prompting Guide** — Bestätigt die
  Verify-by-Observation-Praxis und begründet die Adaption auf Planning-Zeit
  (statische text-to-text-Prüfung statt Code-Ausführung).
  https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5
* **Kahn's Algorithmus / `graphlib.TopologicalSorter`** —
  Zyklenerkennung über Topological-Sort-Misserfolg (ein Graph ist genau dann
  ein DAG, wenn eine topologische Sortierung existiert). Python-Standardbibliothek
  ab 3.9, hier ohne externe Abhängigkeit eingesetzt.
  https://docs.python.org/3/library/graphlib.html
* **LangGraph Conditional Edges** — Routing-Muster (`add_conditional_edges` mit
  Path Map), um die Zero-Tolerance-Knoten bedingt zu durchlaufen.
  https://langchain-ai.github.io/langgraph/concepts/low_level/#conditional-edges
