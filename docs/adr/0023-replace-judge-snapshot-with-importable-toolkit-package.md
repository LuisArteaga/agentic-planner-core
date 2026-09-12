# 0023 - Snapshot durch die importierbare quality_gates_toolkit-Judge-API ersetzt (toolkit D-0017)

* **Status**: Accepted
* **Datum**: 2026-09-12
* **Entscheidungsträger**: Luis Arteaga

## Kontext und Problemstellung

ADR-0022 (Option 3) ließ die von der Judge-Evaluierungssuite benötigten
Judge-Artefakte (vier `SYSTEM_PROMPT_*`-Konstanten, `evaluate_response`,
`load_architecture_context`) als Snapshot in `planner/eval/snapshot.py`
zurück — bewusst eingefroren, dokumentiert driftend. Das Toolkit hat mit
D-0017 (v1.6.0) die importierbare Judge-Paket-API
`quality_gates_toolkit.review` nachgezogen; dieses Follow-up (issue #83)
ersetzt den Snapshot durch den echten Paket-Import.

Die Migration kollidiert mit einer Laststruktur aus ADR-0022: Beide
Repositories liefern ein Top-Level-Paket namens `scripts` aus — hier eine
implizite Namespace-Portion (`scripts/telemetry.py`, `scripts/issue_schema.py`),
dort (Toolkit-Distribution) ein **reguläres** Paket (`scripts/__init__.py`,
Console-Script `secret-scan` plus Backward-Compatibility-Shims). Nach PEP 420
gewinnt ein reguläres Paket auf irgendeinem `sys.path`-Eintrag über jede
Namespace-Portion — unabhängig von der Reihenfolge. Empirisch verifiziert
(venv, Repo-Root als CWD):

* **Vor der Installation**: `scripts.__file__ is None` (Namespace-Portion),
  `import scripts.telemetry` → `agentic-planner-core/scripts/telemetry.py`.
* **Nach der Installation** (toolkit v1.7.0, Commit `af2f1e9`):
  `scripts.__file__` → `site-packages/scripts/__init__.py`,
  `import scripts.telemetry` → Shim → `quality_gates_toolkit/telemetry.py`.

Das Toolkit-Telemetry-Modul besitzt `get_tracer`, aber **kein**
`orchestrator_phase` — die Schattierung würde also ~11 Knoten-Imports mit
ImportError hart brechen UND `get_tracer` in `planner/eval/runner.py` still
auf den Toolkit-Tracer umbinden. Beides unakzeptabel; jede paketbasierte
Lösung musste diese Kollision deshalb zuerst auflösen.

## Entscheidungsfaktoren (Drivers)

* **Kalibrierungs-Exaktheit**: Die Suite muss exakt die Prompts und den
  Parser kalibrieren, die die CI-Judges tatsächlich senden — inklusive des
  Neutrality-Frames (`JUDGE_NEUTRALITY_INSTRUCTIONS`), mit dem das Toolkit
  jeden Basis-Prompt komponiert (`JUDGE_PROMPTS`, toolkit `review.py`).
* **Keine stillen Namespace-Schattierungen**: Planer-Telemetrie und
  Issue-Schema-Validierung müssen deterministisch an planer-eigene Module
  binden, unabhängig davon, was installiert in site-packages liegt.
* **Eine Release-Train-Pin-Disziplin**: Der Toolkit-Ref soll an genau einer
  Stelle pro Release wechseln (Pyproject-Dependency, `toolkit-ref` im
  CI-Composite, Pre-Commit-Rev — gemeinsam gezogen).
* **Offline-deterministische Unit-Tests**: Die Toolkit-Runtime ist
  stdlib-only (`dependencies = []`); der Import von
  `quality_gates_toolkit.review` darf keine Netzwerklast oder
  Abhängigkeitskonflikte erzeugen (verifiziert: Telemetry degradiert
  graceful ohne opentelemetry, Enrichment wird lazy importiert).

## Betrachtete Optionen

* **Option 1 (planner-seitig)**: `telemetry.py` und `issue_schema.py` aus dem
  Top-Level-`scripts`-Namespace in das `planner`-Paket verschieben
  (`planner/telemetry.py`, `planner/issue_schema.py`) und damit die
  Namespace-Portion an der Wurzel entfernen. *Gewählt* — atomar umsetzbar in
  diesem PR (alle Import-Stellen, Patch-Targets, der
  `issue-schema-enforcement.yml`-Aufruf und die Lint-Scopes in einem Zug);
  keine Abhängigkeit von einem Toolkit-Release.
* **Option 2 (toolkit-seitig)**: Das Toolkit hört auf, das Top-Level-
  `scripts`-Paket auszuliefern (Console-Script-Ziel nach
  `quality_gates_toolkit` verschieben). *Verworfen* — cross-repo, blockiert
  an einem Toolkit-Release; D-0017 pinnt die Shim-Verträge bereits
  (inkl. `test_consumer_with_local_scripts_package_can_import_the_judge_api`),
  eine Entfernung wäre ein eigener Toolkit-Decision-Prozess.
* **Option 3 (kein Paket-Import)**: Snapshot behalten, Abhängigkeit
  ablehnen. *Verworfen* — widerspricht dem Ziel des Follow-ups; der
  dokumentierte Drift (u. a. Data-Vault-Fossil im Syntax-Prompt) bliebe
  bestehen und müsste einen superseded-ADR-Strang nach sich ziehen.

## Entscheidung

Wir wählen **Option 1** und migrieren in einem atomaren Change:

1. **Abhängigkeit**: `quality-gates-toolkit @ git+https://github.com/
   LuisArteaga/quality-gates-toolkit@v1.7.0` in `pyproject.toml` — gleicher
   Release-Train wie `toolkit-ref: v1.7.0` in `.github/workflows/
   pr-checks.yml` und `rev: v1.7.0` in `.pre-commit-config.yaml`. Alle drei
   Pin-Stellen werden gemeinsam gezogen (eine Toolkit-Version pro Zug).
2. **Judge-Adapter**: `planner/eval/judge.py` importiert `JUDGE_KEYS`,
   `JUDGE_PROMPTS`, `augment_judge_prompt`, `evaluate_response` und
   `load_architecture_context` aus `quality_gates_toolkit.review`;
   `BINARY_JUDGE_TYPES = JUDGE_KEYS` (eine Quelle für die Judge-Menge).
   Der Adapter baut das System-Prompt jetzt über das Toolkit-Dispatch auf
   (`augment_judge_prompt(judge_key, JUDGE_PROMPTS[judge_key], None,
   arch_context)`) und kalibriert damit exakt die CI-Konstruktion —
   Neutrality-Frame, Architecture-Context-Header und Missing-Context-
   Fallback inklusive. `syntax_result` ist `None`: Die Suite hat für ihre
   synthetischen Fixtures keine deterministische py_compile-Ergebnisbasis,
   deshalb entfällt der Syntax-Verifikations-Block genau wie heute.
3. **Namespace-Restructure**: `scripts/telemetry.py` → `planner/telemetry.py`
   und `scripts/issue_schema.py` → `planner/issue_schema.py` (verbatim
   moves, keine Inhaltsänderung — reine Renames bleiben damit für den
   Diff-Coverage-Gate unsichtbar). Sämtliche Import-Stellen (~13
   Produktionsdateien), Mock-Patch-Targets (4 Testdateien), der
   Workflow-Aufruf (`python3 -m planner.issue_schema`) und die
   Lint-Scopes (Makefile, Pre-Commit) und die Coverage-omit-Ausnahme in
   `pyproject.toml` wechseln im selben Commit. Es bleibt
   kein Top-Level-`scripts`-Namespace zurück; ein Regressionstest
   (`tests/test_telemetry.py::test_scripts_import_never_resolves_into_the_repository`)
   verhindert die stille Re-Introduktion.
4. **Snapshot-Entfernung**: `planner/eval/snapshot.py` und
   `tests/eval/test_snapshot.py` entfallen. Parser- und
   Context-Loader-Branches sind Toolkit-Eigentum (toolkit
   `tests/test_review.py`) und werden nicht dupliziert; behalten wird nur
   die Adapter-Kalibrierungsvertrag-Testsuite
   (`tests/eval/test_judge_prompts.py`: gesendetes System-Prompt ==
   Toolkit-`JUDGE_PROMPTS`-Eintrag bzw. CI-Augmentierung mit Workspace-
   Kontext, Envelope-Rekonstruktion, Verdict-Mapping).

### Konsequenzen

* **Positiv**: Der Snapshot-Drift ist an der Quelle aufgelöst (ADR-0022,
  Folge „Der Prompts-Snapshot driftet …", erledigt); die Suite kalibriert
  die echte CI-Prompt-Konstruktion statt eines eingefrorenen Abbilds; die
  Namespace-Kollision ist an der Wurzel entfernt, künftige
  Toolkit-Releases sind ohne Überraschung installierbar; die
  Pin-Disziplin ist als gemeinsamer Release-Train dokumentiert.
* **Negativ**: Die Architektur-Context-Quelle der Suite wechselt auf die
  Toolkit-Semantik (`docs/context.md` statt `CONTEXT.md` am Repo-Root,
  kein flaches `adr/`-Fallback). Für dieses Repository heißt das: leerer
  Architecture-Context plus CI-Fallback-Wording — konsistent damit, was
  die CI-Judges hier ohnehin seit der Composite-Umstellung sehen. Die
  Gold-Standard-Fixtures waren gegen die alten (vendored) Prompts
  annotiert; die Kennzahlen-Verschiebung (Hard Flips, Kappa) ist
  erwarteter Migrationseffekt und wird als Datenpunkt berichtet, nicht
  als Gate bewertet.
* **Sichtbar in den Metriken**: Die bislang über `[tool.coverage.run]`
  omitierten Module `planner/__main__.py` und `planner/cli_planning.py`
  werden wieder gemessen — beide tragen im Zuge des Renames geänderte
  Import-Zeilen, und der Toolkit-Diff-Coverage-Gate stuft im Diff geänderte
  Dateien ohne Coverage-Eintrag („never imported by any test") als Verstoß
  ein. Beide Module werden von Tests importiert (`tests/test_main.py`,
  `tests/test_session_serialization.py`); die erneute Messung liegt bei
  86 % Gesamt-Coverage, deutlich über dem 80-%-Floor (ADR-0022).

## Inspiration & Referenzen

* **quality-gates-toolkit v1.6.0 Release Notes / D-0017**: importierbare
  `quality_gates_toolkit`-Judge-Paket-API; das Paket ist die
  selbstgenügsame Heimat der Judge-API und importiert sauber, selbst wenn
  ein Consumer ein lokales `scripts`-Paket hält (toolkit
  `tests/test_judge_package.py`).
  <https://github.com/LuisArteaga/quality-gates-toolkit/releases/tag/v1.6.0>
* **PEP 420**: Implicit Namespace Packages — ein reguläres Paket auf
  irgendeinem Pfad-Eintrag gewinnt über alle Namespace-Portionen
  hinweg; deshalb schattiert das Toolkit-`scripts` die planner-eigene
  Portion nach der Installation.
  <https://peps.python.org/pep-0420/>
* **ADR-0022**: Option-3-Snapshot als Transitional-Entscheidung mit
  dokumentiertem Follow-up; diese Entscheidung vollendet sie.

