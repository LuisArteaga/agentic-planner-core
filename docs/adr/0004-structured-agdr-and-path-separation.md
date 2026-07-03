# 0004 - Structured AgDR and Path Separation

* **Status**: Accepted
* **Datum**: 2026-07-02
* **Entscheidungsträger**: Luis Arteaga / Antigravity

## Kontext und Problemstellung
Mit der Einführung des `apply_decision`-Knotens müssen wir Agenten-Architekturentscheidungen (AgDR) im Ziel-Repository ablegen. Es stellen sich zwei Probleme:
1. **Konzept-Konflikt**: Wo werden AgDRs abgelegt? Wenn wir sie in `docs/adr/` ablegen, vermischen wir menschliche System-Entscheidungen mit autonomen, kontextspezifischen Agenten-Entscheidungen. Zukünftige Reader können sie nicht anhand des Pfades unterscheiden.
2. **Qualitäts-Compliance**: Wie garantieren wir, dass AgDRs zwingend die im Glossar (`CONTEXT.md`) vorgeschriebene Optionen-Matrix und die genauen Bewertungsgründe enthalten? Bei Freitext-Generierung durch das LLM besteht das Risiko von unvollständigen Formaten.

## Entscheidungsfaktoren (Drivers)
* Einhaltung des Domänen-Modells (Saubere Trennung von AgDR und ADR).
* Architektonische Konformität (Garantierte Präsenz der Optionen-Matrix).
* Lesbarkeit und Struktur-Garantie für nachgelagerte Systeme (Ausführungsebene).

## Betrachtete Optionen

### Option 1: Ablage in `docs/adr/` mit Freitext-LLM-Generierung
* **Vorteil**: Keine neuen Ordnerstrukturen, maximale LLM-Flexibilität bei der Markdown-Ausgabe.
* **Nachteil**: Verletzt die begriffliche Trennung des Glossars und bietet keine Struktur-Garantie.

### Option 2: Ablage in `docs/agdr/` mit strukturierter Pydantic-Generierung (Gewählt)
* **Vorteil**: 
  * Klare Konzept-Trennung auf Dateisystem-Ebene (`docs/agdr/` vs. `docs/adr/`).
  * 100%ige Compliance-Garantie, da das LLM über das Pydantic-Schema gezwungen wird, `options_considered` und `decision_rationale` als strukturierte Felder zu liefern.
  * Python übernimmt das Rendering des Markdowns und der Optionen-Tabelle.
* **Nachteil**: Größere Payload bei der LLM-Antwort und Starrheit des Layouts durch das Python-Template.

## Entscheidung
Wir wählen **Option 2**. Die Vorteile der konzeptuellen Reinheit und der garantierten Einhaltung unserer Geschäftsregeln überwiegen die Starrheit des Rendering-Templates bei weitem.

### Konsequenzen
* **Positiv**: Sauberes Domänenmodell. Zukünftige Agenten und Menschen können AgDRs sofort anhand des Pfades identifizieren. Strukturelle Vollständigkeit ist durch Pydantic-Validierung zur Laufzeit gesichert.
* **Negativ**: Änderungen am AgDR-Markdown-Layout erfordern Code-Änderungen im Stitching-Prozess von `apply_decision_node`.
