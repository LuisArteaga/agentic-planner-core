# 0006 - Custom JSON Session-Serialisierung statt Bibliotheks-Serialisierung

* **Status**: Accepted
* **Datum**: 2026-07-05
* **Entscheidungsträger**: Luis Arteaga, Antigravity

## Kontext und Problemstellung
Die interaktive Grill-Session muss nach jedem Schritt (Benutzereingabe und Agentenantwort) lokal serialisiert und unter `.planner/sessions/{repo_name}/` gespeichert werden. Hierbei stellt sich die Frage, wie die LangChain-Nachrichten (`HumanMessage`, `AIMessage`, `SystemMessage`, `ToolMessage`) in das JSON-Format überführt werden.
LangChain bietet ein eigenes Serialisierungs-Modul (`langchain_core.load`), das jedoch sehr komplex ist und bei Updates der Bibliothek häufig inkompatible Änderungen einführt. Zudem verstößt es gegen das Prinzip, keine externen Serializer zu nutzen, um Versionskonflikte zu vermeiden.

## Entscheidungsfaktoren (Drivers)
* **Wartbarkeit**: Stabilität der gespeicherten Dateistruktur über LangChain-Updates hinweg.
* **Einfachheit**: Minimierung externer Abhängigkeiten (Verwendung der Python Standard-Bibliothek `json`).
* **Robustheit**: Vermeidung von unkontrolliertem Laden beliebiger Klassen beim Deserialisieren (Sicherheitsaspekt).

## Betrachtete Optionen
* **Option 1**: Verwendung von LangChains integrierten `dumpd`/`load` Funktionen.
* **Option 2**: Eigene, explizite Serialisierungs- und Deserialisierungs-Funktionen unter Verwendung von Standard-Python (`json`).

## Entscheidung
Wir wählen **Option 2** (Eigene Custom-Serialisierung).
Durch die explizite Zuordnung in `serialize_messages` und `deserialize_messages` stellen wir sicher, dass nur die relevanten Felder (`type`, `content`, `tool_calls`, `tool_call_id`, `name`) persistiert werden. Dies entkoppelt das Speicherformat vollständig von internen Klassenstrukturen der LangChain-Bibliothek und verhindert Versionskonflikte.

### Konsequenzen
* **Positiv**: 
  * Keine externen Abhängigkeiten, reine Standard-Python-Implementierung.
  * Hohe Stabilität bei Versionssprüngen von LangChain.
  * JSON-Dateien sind menschenlesbar und leicht zu und manipulieren/verifizieren.
* **Negativ**:
  * Manuelle Pflege der Mappings notwendig, falls neue Nachrichtentypen oder zusätzliche Pflichtfelder hinzukommen.

## Inspiration & Referenzen
* Python standard library `json` best practices.
* LangChain Core Upgrading Guides (Vermeidung von In-Memory Dependency Serialization in langzeit-persistierten Dateien).
