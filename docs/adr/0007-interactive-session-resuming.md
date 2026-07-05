# 0007 - Interaktives Fortsetzen von Interaktiven Sitzungen (Session Resuming)

* **Status**: Accepted (Erweitert: 2026-07-05)
* **Datum**: 2026-07-05
* **Entscheidungsträger**: Luis Arteaga, Antigravity

## Kontext und Problemstellung
Um den Entwicklungszyklus bei unvollständigen Planungsphasen zu optimieren, soll es möglich sein, abgebrochene oder beendete Sitzungen fortzusetzen. Dies gilt für alle interaktiven Kommandos: `grill` (Phase 1a) und `verify` (Phase 1b).

Hierbei muss entschieden werden, wie die CLI mit mehreren unvollständigen Sitzungen umgeht (interaktives Menü vs. automatisches Laden des neuesten Zustands) und wie der Konversationszustand des Agenten so wiederhergestellt wird, dass keine redundanten Agenten-Reaktionen ausgelöst werden.

Da zukünftige Entwickler über das Überspringen des ersten Agenten-Turns beim Laden stolpern könnten, dokumentiert dieses ADR den genauen Mechanismus und die Gründe hierfür.

## Entscheidungsfaktoren (Drivers)
* **Benutzerfreundlichkeit (UX)**: Einfache Möglichkeit, eine bestimmte Sitzung auszuwählen oder neu zu starten.
* **Effizienz**: Vermeidung redundanter API-Aufrufe/Tokens beim Wiederaufnehmen einer Session.
* **Robustheit**: Verhinderung von Fehlern bei beschädigten JSON-Dateien oder ungültigen CLI-Argumenten.
* **Einheitlichkeit**: Alle interaktiven Kommandos (`grill`, `verify`) teilen denselben Mechanismus.

## Betrachtete Optionen
* **Option 1**: Automatisches Laden der zeitstempel-mäßig neuesten unvollständigen Session ohne Nachfrage.
* **Option 2**: Interaktives Auswahlmenü bei unvollständigen Sessions beim Starten und Unterstützung eines direkten `--session-id` CLI-Parameters.

## Entscheidung
Wir wählen **Option 2** (Interaktives Auswahlmenü & `--session-id`) für alle interaktiven Kommandos.

### Implementierung
* Session-Dateien werden unter `.planner/sessions/{repo_name}/{prefix}_{session_id}.json` gespeichert, wobei `prefix` den Kommandotyp kennzeichnet (z.B. `grill_`, `verify_`).
* Eine gemeinsame Hilfsfunktion `save_session(config, session_id, messages, prefix, completed)` serialisiert alle Session-Typen. Kommando-spezifische Wrapper (`save_grill_session`, `save_verify_session`) delegieren an diese Funktion.
* Das Verzeichnis wird nach unvollständigen (`completed: false`) Sitzungen des jeweiligen Typs gescannt und absteigend nach `last_modified` sortiert.
* Wenn unvollständige Sessions existieren, erhält der Benutzer ein Menü zur Auswahl oder zum Start einer neuen Session.
* Über `--session-id` kann eine spezifische Session direkt geladen werden (für beide Kommandos verfügbar).
* Um redundante Agenten-Aktionen zu vermeiden, prüfen wir beim Laden der Historie, ob die letzte Nachricht eine `AIMessage` ist. Ist dies der Fall, überspringen wir den ersten Agentenschritt und wechseln direkt in die Benutzereingabe.

### Konsequenzen
* **Positiv**:
  * Flexibilität: Benutzer können gezielt zwischen verschiedenen Sitzungen wechseln oder neu starten.
  * Robustheit: Fehlerhafte Dateien werden ignoriert, ungültige Auswählen abgefangen.
  * API-Effizienz: Verhindert unnötige Kosten/Token-Verbrauch durch doppelte Agentenantworten beim Start.
  * Einheitlichkeit: `grill` und `verify` teilen exakt denselben Persistenz- und Resume-Mechanismus.
* **Negativ**:
  * Geringfügig höhere Komplexität im CLI-Einstiegspunkt.
  * Präfixbasiertes Dateisystem-Schema setzt voraus, dass neue Kommandos sich an die Namenskonvention halten.

## Inspiration & Referenzen
* LangChain Core Upgrading Guides (Umgang mit Konversations-States und CLI-Menü-Kombinationen).
* ADR-0006: Custom JSON Session-Serialisierung (technische Grundlage für die Persistenz).
