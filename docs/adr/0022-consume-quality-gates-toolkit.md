# 0022 - Konsum von quality-gates-toolkit statt vendored Quality-Gates

* **Status**: Accepted
* **Datum**: 2026-09-11
* **Entscheidungsträger**: Luis Arteaga

## Kontext und Problemstellung

Das Repository trägt eine eigene Kopie der Quality-Gates-Infrastruktur mit sich:
eine vendierte Judge-Engine (`scripts/review.py`, ~1000 Zeilen, plus
`scripts/review.sh` und `scripts/secret_scan.py`) und einen monolithischen
`.github/workflows/pr-checks.yml` mit inline-Schritten. Diese Kopie ist gegen
das öffentliche Toolkit `quality-gates-toolkit` (v1.4.0) um etwa 2000 Zeilen
hinterhergehinkt: Die Judge-Prompts weichen ab (darunter ein übernommener
Data-Vault-Naming-Prompt, der fachlich hier nichts mehr zu suchen hat), dem
Toolkit fehlen hier die Usage-Telemetrie, das 429-aware Retry-Budget und die
`NEEDS REVIEW`-Semantik. Zusätzlich:

* Das CI installiert Lint-Werkzeuge unpinned (`pip install -e .[dev]`) —
  genau die Fehlerklasse, die das Toolkit durch zentral gepinnte Werkzeugversionen
  (ruff 0.16.6, mypy 2.3.1) eliminiert hat.
* Pre-commit pinnt ruff über `astral-sh/ruff-pre-commit v0.3.0` — lokal liegt
  damit eine andere Formatter-Version als im CI (Skew).
* `vars.REVIEW_MODEL` umgeht `config/factory.json` als Modellquelle; die
  Judge-Evaluierungssuite (`eval.yml`) liest dagegen factory.json — zwei
  unsynchronisierte Quellen für dieselbe Entscheidung.
* Der geänderte-Linien-Coverage-Gate (100 % je geänderter Zeile) fehlt
  vollständig; es existiert nur der globale 80-%-Floor.

Zwei Kopplungen verhindern ein einfaches „Löschen und Konsumieren“:

1. `planner/eval/judge.py` importiert die vier `SYSTEM_PROMPT_*`-Konstanten,
   `evaluate_response` und `load_architecture_context` aus `scripts.review` —
   die Evaluierungssuite kalibriert die CI-Judges gegen genau diese Artefakte.
2. `scripts/telemetry.py` ist eine Laufzeitabhängigkeit des Planners selbst
   (`orchestrator_phase` in über zehn Knoten); das Toolkit führt nur die
   Judge-Telemetrie weiter. Dasselbe gilt für `scripts/issue_schema.py`
   (planner-eigen).

Eine Paket-Abhängigkeit auf das Toolkit ist heute nicht sauber möglich: Beide
Repositories liefern ein Top-Level-Paket namens `scripts` aus — die lokale
`scripts/`-Kopie würde das Toolkit-Paket beschatten.

## Entscheidungsfaktoren (Drivers)

* **Agenten-lastiger Arbeitsfluss**: Viele Commits je Issue durch KI-Agenten;
  Pre-Commit ist die schnelle Rückmeldeebene pro Commit, während CI inklusive
  LLM-Judges bis zu ~10 Minuten je PR dauert. Starke lokale Gates sparen ganze
  Judge-Iterationen (Zeit und OpenRouter-Kosten).
* **Eine Quelle der Wahrheit für Judge-Modelle**: factory.json soll die
  Modelle bestimmen; die Evaluierungssuite muss das kalibrieren, was im CI
  tatsächlich läuft.
* **Keine doppelte Judge-Engine**: Zwei auseinanderdriftende Engines machen
  die Kalibrierung ungültig und den Betrieb unübersichtlich.
* **Bekannte, gute Werkzeugkette**: Werkzeugversionen sollen an einer Stelle
  gepinnt werden (Toolkit-Release), nicht verstreut je Repository.

## Betrachtete Optionen

* **Option 1**: Vendierte Kopie behalten, nur Workflows umbauen. *Verworfen* —
  es bleiben zwei Engines mit auseinanderlaufenden Prompts; die Evaluierung
  kalibriert die veraltete Engine, während das CI die moderne läuft.
* **Option 2**: Zuerst Toolkit-seitig die Judge-API sauber paketieren
  (echter Paket-Namespace statt `scripts`), dann in einem Schritt migrieren.
  *Verworfen* — blockiert die Migration an arbeitsintensiver Cross-Repo-Arbeit;
  der Migrationsschritt selbst ist unabhängig davon möglich.
* **Option 3**: Toolkit sofort konsumieren; die von der Evaluierungssuite
  benötigten Artefakte als Snapshot in `planner/eval/` kopieren; die
  Paketierung als Toolkit-Follow-up anlegen und später nachziehen.
  *Gewählt* — der migrationsöffnende Minimal-Schritt (Tracer Bullet), die
  Prompts-Abspaltung ist gegenüber dem heutigen Zustand (schon jetzt
  abweichende Prompts) keine Verschlechterung, wird aber explizit sichtbar
  und gepinnt.

## Entscheidung

Wir wählen **Option 3**:

1. **CI**: `.github/workflows/pr-checks.yml` wird zum Komposit
   `LuisArteaga/quality-gates-toolkit/.github/workflows/python-checks.yml@v1.7.0`
   (Retarget v1.6.0 → v1.7.0 mit dem per-Language-Komposit aus D-0020: für ein
   Python-only-Repository die One-Call-Ergonomie ohne `Skipped`-Einträge der
   JS-Gates; das polyglotte `pr-checks.yml` bliebe sonst mit drei dauerhaft
   übersprungenen Jobs zurück)
   (`coverage-floor: 80`, Diff-Coverage-Gate aktiv, `lint-paths`/`scan-paths`
   `planner tests scripts`, `cov-paths` `planner`). Geheimnisse: das vorhandene
   `OPENROUTER_API_KEY` und `GH_PAT` (als `judge-token`-Eingang, Name bleibt).
   `vars.REVIEW_MODEL` entfällt; `config/factory.json` ist alleinige Quelle
   der Judge-Modelle (env-Overrides bleiben als dokumentierte Ausnahmen).
2. **Pre-Commit**: Der lokale `secret-scan`-Hook wird durch den Toolkit-Hook
   (`rev: v1.7.0`) ersetzt; der astral-ruff-Rev wird auf die CI-Version
   angehoben (v0.16.6). Seit Toolkit v1.6.0 (D-0016) stammen auch `mypy`
   (System-Env-Hook, beratend — der CI-Pin bleibt maßgeblich), `semgrep`
   (gepinnt 1.177.0) und `pip-audit` (gepinnt 2.10.1, jeweils isolierte
   Umgebung) aus der Toolkit-Hook-Sammlung (`rev: v1.7.0`); die lokalen
   Hook-Definitionen entfallen. v1.7.0 ändert die Hook-Sammlung und die
   Werkzeug-Pins (ruff 0.16.6 / mypy 2.3.1) nicht — nur die Composite-Refs.
3. **Evaluierung**: Die vier Judge-Prompts, `evaluate_response` und
   `load_architecture_context` wandern als Snapshot nach `planner/eval/`;
   danach entfallen `scripts/review.py`, `scripts/review.sh`,
   `scripts/secret_scan.py` und `tests/test_review.py`.
4. **Bleibt planner-eigen**: `scripts/telemetry.py`, `scripts/issue_schema.py`,
   `eval.yml` (inkl. `workflow_call`-Konsum durch agentic-developer-core) und
   `issue-schema-enforcement.yml` sind unberührt.
5. **Schichtung (grundsätzlich)**: Pre-Commit = schnelle, beratende Ebene für
   den KI-Commit-Loop; CI = verbindliche, gepinnte Gate-Ebene. Lokales `mypy`
   bleibt bis auf Weiteres versionsseitig Consumer-eigen; das gepinnte
   CI-`mypy` ist maßgeblich.

### Konsequenzen

* **Positiv**: Ein Toolkit-Rev bestimmt CI-Werkzeugkette und Secret-Scan;
  die Version-Skew-Klasse (ruff/mypy lokal vs. CI) entfällt im CI; neuer
  Diff-Coverage-Gate erzwingt volle Abdeckung geänderter Zeilen je PR;
  Judge-Modelle sind einheitlich über factory.json (und damit synchron mit
  der Evaluierungssuite); die ~2000-Zeilen-Abweichung samt Data-Vault-Fossil
  entfällt.
* **Negativ**: Der Prompts-Snapshot driftet mit der Zeit vom Toolkit ab —
  begrenzt durch das paketierungsseitige Follow-up (Austausch des Snapshots
  gegen die echte Paket-API). Das CI hängt an der Verfügbarkeit eines
  externen, öffentlichen Repos (gepinnter Ref mindert das Risiko). Lokales
  `mypy` bleibt über den Toolkit-Hook (v1.7.0, D-0016) beratend und
  ungepinnt — maßgeblich ist der gepinnte CI-`mypy`.

## Inspiration & Referenzen

* **quality-gates-toolkit README (v1.4.0)**: Komposit-Workflows, Pin-Disziplin
  (ruff 0.16.6 / mypy 2.3.1), Judge-Konfiguration via `config/factory.json`
  inkl. `ci_cd_pr_judges`-Sektion, Secret-Scan-Hook.
  <https://github.com/LuisArteaga/quality-gates-toolkit>
* **ADR-0008 / ADR-0014 / ADR-0015**: Mehrstufige Judges, Merge-Blocking und
  Hidden-Verdict-Block — das Verdict-Protokoll wird mit dieser Entscheidung
  vom Toolkit weitergeführt (D-0002 im Toolkit ist der versionierte Vertrag).
* **Toolkit v1.6.0 Release Notes**: Lokale Python-Tool-Hooks (`mypy`
  beratend im Consumer-Env, `semgrep` 1.177.0 und `pip-audit` 2.10.1
  gepinnt in isolierter Umgebung, D-0016) sowie die importierbare
  `quality_gates_toolkit`-Judge-Paket-API (D-0017) — Letztere bleibt als
  künftiger Austausch des Prompts-Snapshots (Follow-up) bestehen, wird
  hier aber nicht konsumiert.
  <https://github.com/LuisArteaga/quality-gates-toolkit/releases/tag/v1.6.0>
* **Toolkit v1.7.0 Release Notes (Retarget-Grundlage)**: Per-Language-Komposit
  `python-checks.yml` (D-0020, PR #36) — One-Call-Ergonomie für
  Python-only-Consumer ohne `Skipped`-Einträge; Gate-Toggles der
  Sprach-Composites default-ON (D-0004 bleibt neutral beim polyglotten
  Komposit). Hook-Sammlung und Werkzeug-Pins unverändert gegenüber v1.6.0.
  <https://github.com/LuisArteaga/quality-gates-toolkit/releases/tag/v1.7.0>
* **Toolkit DECISIONS D-0012**: „The harness owns the environment, the
  project owns the tools“ — Vorbild für den künftigen System-Env-`mypy`-Hook
  und die Schichtung aus lokaler beratender und CI-verbindlicher Ebene.
