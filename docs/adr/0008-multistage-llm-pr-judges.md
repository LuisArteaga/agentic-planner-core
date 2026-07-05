# 0008 - Mehrstufige LLM-as-a-Judge PR-Prüfungen mit zentraler Konfiguration

* **Status**: Accepted
* **Datum**: 2026-07-05
* **Entscheidungsträger**: Luis Arteaga

## Kontext und Problemstellung
Die Qualitätssicherung von Pull Requests (PRs) im Planner-Prozess erfolgte bisher über isolierte und statisch konfigurierte Judges (z. B. getrennte Prüfungen für Security und Architektur). Dies führte zu redundantem API-Overhead und unstrukturiertem Feedback auf GitHub. Zudem war die Modellkonfiguration für den Planner-Prozess und die PR-Judges über verschiedene Umgebungs- und Code-Variablen verstreut, was die Wartung erschwerte. 

Wir benötigen ein System, das:
1. Eine zentrale, deklarative Modellkonfiguration ermöglicht.
2. Mehrere spezialisierte PR-Checks nacheinander ausführt, um Kontext-Konfusion zu vermeiden und Ressourcen zu schonen.
3. Ein einziges, übersichtliches und strukturiertes Feedback (BINEVAL) in einem kombinierten GitHub-Review bereitstellt.

## Entscheidungsfaktoren (Drivers)
* Vermeidung von Kontext-Konfusion bei semantisch anspruchsvollen LLM-Prüfungen
* Senkung von OpenRouter-API-Kosten und Ausführungszeit
* Übersichtliches, konsolidiertes Entwickler-Feedback direkt im PR
* Einfache Wartbarkeit der Modellkonfigurationen für alle Phasen und Knoten

## Betrachtete Optionen
* **Option 1**: Vollständig parallele Ausführung aller Judges. Alle Judges laufen gleichzeitig und posten separate Review-Kommentare.
* **Option 2**: Sequenzielle Ausführung mit Fail-Fast-Logik und zentraler JSON-Konfiguration. Ein schnelles Syntax-Gate (`syntax_lint`) bricht die Pipeline sofort ab, falls grundlegende Fehler vorliegen. Die restlichen Judges laufen nur bei erfolgreichem Gate und posten ein einziges, kombiniertes GitHub-Review (BINEVAL-Muster).

## Entscheidung
Option 2 — Sequenzielle Ausführung mit Fail-Fast-Logik und einer zentralen JSON-Konfigurationsdatei `config/factory.json`.

Das System führt 4 Judges nacheinander aus:
1. **`syntax_lint`** (Fail-Fast-Gate, prüft Syntax, Schemata, Namenskonventionen in Millisekunden).
2. **`test_coverage`** (Prüft Testvorhandensein und Assertions).
3. **`architecture`** (Prüft Schichtgrenzen und Architectural Drift).
4. **`security`** (Führt Deep Security Audit durch).

Sollte `syntax_lint` fehlschlagen, werden alle weiteren Judges übersprungen (`SKIPPED`) und das Review wird sofort mit einer `REQUEST_CHANGES` Aktion und den Teilergebnissen gepostet. Dies verhindert, dass teure Reasoning-Modelle (z. B. `deepseek-v4-pro` für Taint-Analysen) auf syntaktisch inkorrektem Code arbeiten (Kontext-Konfusion) und spart API-Kosten.

### Konsequenzen
* **Positiv**: 
  - Keine Verschwendung von API-Tokens bei Syntaxfehlern.
  - Strukturierte Statustabelle und präzise Binärbewertungen (BINEVAL) in einem einzigen PR-Review.
  - Zentrale Modell- und Routing-Steuerung über `config/factory.json` mit automatischen Provider-Routing Fallbacks auf OpenRouter.
* **Negativ**: 
  - Bei Syntaxfehlern sieht der Entwickler erst nach deren Behebung das Feedback zu Security/Architektur.

## Inspiration & Referenzen
* BINEVAL (Binary Evaluation Pattern) für strukturierte LLM-Klassifizierung.
* OpenRouter Provider Routing API zur Ausfallsicherheit.
