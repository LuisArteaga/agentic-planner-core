# 0017 - evaluate_grade aus der binären Judge-Eval-Suite ausgeschlossen

* **Status**: Accepted
* **Datum**: 2026-07-06
* **Entscheidungsträger**: Luis Arteaga (Architect)

## Kontext und Problemstellung

Issue #43 fordert eine Regressions-Evaluierungssuite, die *alle konfigurierten
Judges* (`syntax_lint`, `test_coverage`, `architecture`, `security`,
`evaluate_grade`) gegen einen Gold-Standard ausführt. Die Suite benötigt ein
einheitliches Interface `judge(diff, judge_type) -> BINEVALResult`, damit jeder
Judge isoliert evaluiert und gegen binäre Kennzahlen (Cohen's Kappa, MAE, Hard
Flips, Verbosity Bias) kalibriert werden kann.

Eine eingehende Code-Analyse zeigt jedoch, dass `evaluate_grade` architektonisch
nicht zum binären BINEVAL-Interface passt:

| Aspekt | PR-Judges (`scripts/review.py`) | `evaluate_grade` (`planner/nodes/`) |
|---|---|---|
| Bewertet | einen Git-Diff (PR) | vorgeschlagene Lösungs-Optionen |
| Ausgabe | Pass/Fail/Needs-Review + XML-`<findings>` | numerischer Score 0–10 + `checks`-Dict |
| LLM-Transport | roher `urllib`-POST | LangChain `ChatOpenAI.invoke` |
| Ausgabeformat | Freitext mit XML-Tags | Function-Calling / strukturiertes JSON (`CriticEvaluation`) |
| Config-Bucket | `ci_cd_pr_judges` | `refine_graph_nodes` |
| Fail-Fast-Gate | ja (ADR-0008, syntax_lint) | nein (einzelner Knoten in einem linearen Subgraph) |

`evaluate_grade` ist somit ein *numerischer Optionen-Bewerter*, kein *binärer
Diff-Judge*. Seine Eingabe (`proposed_options`, eine Liste strukturierter
Dictionaries) und seine Ausgabe (ein Pydantic-Schema mit 0–10-Scores) sind
inkompatibel mit der `judge(diff, judge_type)`-Signatur und dem
`<reasoning>`/`<findings>`-XML-Parser, den die vier PR-Judges teilen.

## Entscheidungsfaktoren (Drivers)
* Schnittstellen-Homogenität: Die Suite berechnet Cohen's Kappa und Hard Flips
  auf *binären* `passed`-Verdicts. Diese Metriken setzen ein einheitliches
  Pass/Fail-Interface voraus.
* Vermeidung von Fälschungen: Ein erzwungener binärer Adapter für
  `evaluate_grade` müsste die numerische 0–10-Skala an einem Schwellwert
  (z. B. 8.0) binarisieren und würde die Transport-/Parsing-Pfade koppeln —
  ein Bruch mit Radical Simplicity (Check 2.1/2.2 der Bewertungsrubrik).
* ADR-0008-Konformität: Die Fail-Fast-Pipeline definiert ausschließlich die vier
  PR-Judges; `evaluate_grade` gehört nicht dazu.

## Betrachtete Optionen

### Option 1: `evaluate_grade` über einen binarisierten Adapter einbeziehen
Ein Adapter würde `proposed_options` entgegennehmen, die Optionen bewerten und
den Score bei ≥ 8.0 als `passed` binarisieren.
* **Vorteil**: Vollständige Abdeckung aller fünf Judge-Typen aus Issue #43.
* **Nachteil**: Verwirft die numerische Auflösung (MAE auf 0–10 wäre
  aussagekräftiger als ein harter 8.0-Schnitt); koppelt zwei unterschiedliche
  LLM-Transporte (urllib vs. LangChain) und zwei Parsing-Pfade unter ein
  Interface; verletzt die Fail-Fast-Semantik von ADR-0008, der diese Judges
  gar nicht umfasst.

### Option 2: `evaluate_grade` aus der binären Suite ausschließen (gewählt)
Die Suite evaluiert die vier homogenen PR-Judges vollständig. Für
`evaluate_grade` wird das Fixture-Verzeichnis `tests/eval/fixtures/evaluate_grade/`
als Platzhalter angelegt (AC-konform), und der Runner dokumentiert den Typ als
"numerischer Bewerter ohne binären Adapter". Ein separater numerischer
Eval-Harness (MAE auf 0–10-Skala, Best-Option-Übereinstimmung) ist einer
künftigen Aufgabe vorbehalten.
* **Vorteil**: Saubere, homogene Schnittstelle; keine Schein-Metriken; ehrliche
  Begrenzung des Gültigkeitsbereichs.
* **Nachteil**: `evaluate_grade` ist zunächst nicht quantifizierbar; ein
  Modellwechsel für `evaluate_grade` bleibt bis zum separaten Harness unkalibriert.

## Entscheidung
Wir wählen **Option 2**. Die binäre Eval-Suite deckt `syntax_lint`,
`test_coverage`, `architecture` und `security` ab. `evaluate_grade` erhält ein
Fixture-Platzhalter-Verzeichnis, wird aber vom binären Runner nicht ausgeführt.
Die Aufnahme von `evaluate_grade` erfordert einen dedizierten numerischen
Eval-Harness und ist als separate Aufgabe zu verfolgen.

## Konsequenzen
* **Positiv**: Konsistentes, testbares Interface; Metriken sind semantisch
  korrekt (binäre `passed`-Labels nur für binäre Judges).
* **Negativ**: `evaluate_grade`-Modellwechsel sind zunächst nicht regressions-
  gesichert. Das Risiko ist akzeptabel, da `evaluate_grade` nur im
  autonomen Refinement läuft (nicht im CI/CD-Pfad) und ein Modellwechsel dort
  seltener auftritt.
* Folge-Aufgabe: Numerischer Eval-Harness für `evaluate_grade` (MAE auf 0–10,
  Best-Option-Agreement, Token/Cost-Metriken über den bestehenden Streaming-Client).

## Inspiration & Referenzen
* Issue #43 — Akzeptanzkriterium "Fixtures-Struktur" verlangt das
  `evaluate_grade`-Verzeichnis; der Text selbst räumt ein, dass die
  `agentic-judge-core`-Extraktion "initial auch als internes Modul" umgesetzt
  werden kann.
* ADR-0008 — Fail-Fast-Pipeline umfasst nur die vier PR-Judges.
* "Judging the Judges" (arXiv:2406.12624) — Cohen's Kappa als
  Kalibrierungsmetrik für *binäre* Annotatoren.
