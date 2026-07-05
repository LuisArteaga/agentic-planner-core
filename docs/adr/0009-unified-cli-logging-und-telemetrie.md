# 0009 - Einheitliches CLI-Logging und Telemetrie für alle Kommandos

* **Status**: Accepted
* **Datum**: 2026-07-05
* **Entscheidungsträger**: Luis Arteaga, Antigravity

## Kontext und Problemstellung
Die drei interaktiven Planungskommandos `draft`, `verify` und `refine` hatten keine konsistente Sichtbarkeit in den Laufzeitabläufen:

* `refine` hatte zwar OTel-Tracing, aber keine Konsolenausgabe bei LLM-/Tool-Events.
* `draft` hatte weder Tracing noch Live-Konsolenausgabe.
* `verify` hatte weder Tracing noch Session-Persistenz.

Ziel ist eine einheitliche Strategie für alle Kommandos, die sowohl lokale Transparenz (Entwickler sieht, was der Agent tut) als auch optionale Telemetrie (Langfuse/OTel) bietet.

## Entscheidungsfaktoren (Drivers)
* **Transparenz**: Entwickler soll live sehen, wenn der Agent denkt oder Tools aufruft, ohne die Logdatei öffnen zu müssen.
* **Einheitlichkeit**: Alle Kommandos sollen dasselbe Logging-Verhalten aufweisen.
* **Optionale Telemetrie**: Langfuse/OTel-Tracing ist wertvoll für Debugging, darf aber nicht Pflicht sein (kein LANGFUSE_*-Key = kein Fehler).
* **Minimale Invasivität**: Keine Änderung der Agenten-Logik selbst — Logging-Konfiguration passiert am CLI-Einstiegspunkt.

## Betrachtete Optionen

### Option A: Python `logging.basicConfig` allein
Konfiguriert den Root-Logger auf INFO, sodass alle `logger.info()`-Aufrufe in Node-Funktionen erscheinen.
* Vorteil: Sehr einfach, keine LangChain-Kenntnisse erforderlich.
* Nachteil: LLM- und Tool-Events (LangChain-intern) erscheinen **nicht** — diese nutzen kein Python-Logging.

### Option B: `BaseCallbackHandler` (ConsoleLoggingHandler) allein
Ein LangChain-`BaseCallbackHandler` fängt `on_llm_start`, `on_tool_start`, `on_tool_end` ab und gibt sie auf der Konsole aus.
* Vorteil: Volle Sichtbarkeit in LLM/Tool-Events.
* Nachteil: Node-eigene `logger.info()`-Aufrufe erscheinen nicht, wenn kein `logging.basicConfig` gesetzt ist.

### Option C: Kombination aus `logging.basicConfig(INFO)` + `ConsoleLoggingHandler`
* Vorteil: Vollständige Abdeckung beider Event-Quellen.
* Nachteil: Etwas mehr Boilerplate am Einstiegspunkt.

## Entscheidung
Wir wählen **Option C** — Kombination für alle drei Kommandos:

| Kommando  | `logging.basicConfig` | `ConsoleLoggingHandler` | OTel/Langfuse |
|-----------|-----------------------|------------------------|---------------|
| `grill`   | Nein (nicht nötig)    | Nein (TTY-Loop reicht) | Ja (bestehend)|
| `verify`  | Nein (nicht nötig)    | Nein (TTY-Loop reicht) | Ja (neu)      |
| `draft`   | Nein                  | **Ja** (non-interactive) | Ja (neu)    |
| `refine`  | **Ja** (LangGraph)    | **Ja** (LLM/Tool events) | Ja (bestehend)|

### Implementierungsdetails
* **`ConsoleLoggingHandler`** ist in `cli_planning.py` als wiederverwendbare Klasse definiert. Sie kürzt lange Ausgaben auf 200 Zeichen, um die Konsole nicht zu überfluten.
* **OTel/Langfuse-Telemetrie** ist für `draft` und `verify` optional: Sie wird nur aktiviert, wenn `LANGFUSE_PUBLIC_KEY` und `LANGFUSE_SECRET_KEY` in der Umgebung gesetzt sind. Fehlen sie, wird kein Fehler ausgelöst.
* **`init_telemetry`, `start_orchestrator_loop`, `end_orchestrator_loop`** werden in `cli_planning.py` auf Modulebene importiert (nicht mehr lazy), damit sie in Tests korrekt gemockt werden können.
* Der **OTel-Teardown** erfolgt stets in einem `finally`-Block, um sicherzustellen, dass Spans auch bei Ausnahmen korrekt abgeschlossen werden (`exit_code=1`).

### Konsequenzen
* **Positiv**:
  * Entwickler sehen bei `draft` und `refine` live, welche Tools der Agent aufruft.
  * Optionale Telemetrie ist konsistent für alle Kommandos — kein Command ist "blind".
  * Teardown-Garantie via `finally` verhindert hängende OTel-Spans.
  * Module-level Import der Telemetrie-Funktionen ermöglicht zuverlässiges Testen via `unittest.mock.patch`.
* **Negativ**:
  * `grill`/`verify` (interaktive TTY-Loop-Kommandos) nutzen keinen `ConsoleLoggingHandler`, da die TTY-Loop selbst bereits ausreichende Sichtbarkeit bietet.
  * `logging.basicConfig` darf nur einmal pro Prozess gesetzt werden; bei mehrfachem Aufruf von `refine` im selben Prozess würde es ignoriert (kein praktisches Problem für CLI-Use).

## Inspiration & Referenzen
* LangChain `BaseCallbackHandler` Dokumentation.
* OpenTelemetry Python SDK — Lifecycle und Span-Teardown-Best-Practices.
* ADR-0007: Interaktives Fortsetzen von Interaktiven Sitzungen (Telemetrie-Kontext für `verify`).
