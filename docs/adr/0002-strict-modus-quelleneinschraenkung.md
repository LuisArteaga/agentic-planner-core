# 0002 - Strict-Modus für Quelleneinschränkung gegen Prompt Injection

* **Status**: Accepted
* **Datum**: 2026-06-28
* **Entscheidungsträger**: Luis Arteaga

## Kontext und Problemstellung
Der Refinement Subgraph führt Websuchen durch, um Lösungsansätze für Draft Issues mit externer Evidenz zu untermauern. Websuchergebnisse sind jedoch eine unkontrollierte Eingabequelle — sie können adversariale Inhalte enthalten, die über Prompt Injection das Verhalten des LLM beeinflussen (z. B. die Bewertungslogik des Critic-Knotens manipulieren oder unerwünschte Architekturentscheidungen begünstigen). Diese Entscheidung ist schwer umkehrbar, da die gesamte Such- und Quellen-Architektur davon abhängt.

## Entscheidungsfaktoren (Drivers)
* Sicherheit gegen Prompt Injection über Websuchergebnisse
* Kontrollierbarkeit der Informationsquellen pro Projekt
* Flexibilität für explorative Recherche bei vertrauenswürdigen Projekten

## Betrachtete Optionen
* **Option 1**: Nur statische Quellenliste — keine dynamische Erweiterung erlaubt
* **Option 2**: Nur dynamische Erweiterung — der LLM entscheidet frei, welche Quellen durchsucht werden
* **Option 3**: Hybrid mit Strict-Modus-Toggle — statische Basisliste mit optionaler dynamischer Erweiterung, abschaltbar per Konfiguration

## Entscheidung
Option 3 — Hybrid mit einem `strict`-Toggle in der Quellen-Konfiguration. Im Default-Modus (`strict: false`) erweitert der `analyze_sources`-Knoten die Basisliste dynamisch um issue-spezifische Quellen und Keywords. Im Strict-Modus (`strict: true`) werden ausschließlich die in der Konfiguration definierten Quellen und Domains durchsucht; der `analyze_sources`-Knoten generiert nur Keywords, keine neuen Quellen.

### Konsequenzen
* **Positiv**: Vollständige Kontrolle über Informationsquellen bei sicherheitskritischen Projekten. Explorative Flexibilität bleibt für vertrauenswürdige Szenarien erhalten. Der Toggle ist pro Projekt konfigurierbar.
* **Negativ**: Im Strict-Modus können relevante Quellen übersehen werden, die nicht in der Basisliste stehen. Der User muss die Basisliste aktiv pflegen.

## Inspiration & Referenzen
* OWASP LLM Top 10 (2025) — Prompt Injection als Top-1-Risiko bei LLM-Anwendungen
* Anthropic Research on Indirect Prompt Injection — Adversariale Inhalte in externen Datenquellen als Angriffsvektor
