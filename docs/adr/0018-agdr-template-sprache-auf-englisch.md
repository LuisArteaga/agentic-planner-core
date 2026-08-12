# 0018 - AgDR-Template-Sprache auf Englisch übersetzt

* **Status**: Accepted
* **Datum**: 2026-07-07
* **Entscheidungsträger**: Luis Arteaga (Architect)

## Kontext und Problemstellung

Issue #47 dokumentiert, dass das vom `apply_decision`-Knoten generierte
AgDR-Markdown-Template deutsche Metadaten-Schlüssel und Abschnitts-Header
verwendete (`Datum`, `Entscheidungsträger`, `Kontext und Problemstellung`,
`Entscheidungsfaktoren (Drivers)`, `Betrachtete Optionen`, `Entscheidung`,
`Konsequenzen`, `Positiv`, `Negativ`, `Inspiration & Referenzen`), während das
LLM englischen Inhalt generiert. Das Ergebnis war ein "Denglish"-Mix in den
erzeugten Dokumenten, der die Lesbarkeit beeinträchtigte.

Dies berührt ADR-0004, das festlegt, dass sich AgDRs und ADRs **über den Pfad**
(`docs/agdr/` vs. `docs/adr/`) unterscheiden, **nicht über das Format**. Eine
einfache Übersetzung der AgDR-Header ins Englische würde — ohne dokumentierte
Entscheidung — einen Sprach-Drift zwischen dem deutschen ADR-Korpus und den
englischen AgDRs einführen, den ADR-0004 nicht vorsieht.

## Entscheidungsfaktoren (Drivers)
* Lesbarkeit der agentengenerierten AgDRs: Das LLM produziert englischen
  Inhalt; deutsche Header erzwingen einen Sprachmix (Issue #47).
* Autorschaftsmodell: AgDRs werden *autonom vom LLM* verfasst (englischer
  Inhalt), ADRs werden *von Menschen* verfasst (historisch deutsch). Die
  Sprache folgt dem jeweiligen Autor.
* Wahrung des ADR-0004-Prinzips: Die Pfad-Trennung bleibt die primäre
  Unterscheidung; der Sprachunterschied ist eine Konsequenz der Autorschaft,
  keine eigenständige Format-Divergenz.
* Unveränderlichkeit historischer ADRs: Die 17 bestehenden ADRs bleiben in
  ihrer ursprünglichen (deutschen) Form erhalten.

## Betrachtete Optionen

### Option 1: Sämtliche Header (ADR + AgDR) auf Englisch übersetzen
Übersetzung aller 17 historischen ADRs und beider Templates auf Englisch.
* **Vorteil**: Vollständige sprachliche Konsistenz über beide Dokumenttypen.
* **Nachteil**: Verletzt die Unveränderlichkeit historischer
  Architekturentscheidungen (ADRs sind Dokumentations-Records, keine
  refactorbaren Code-Dateien). Massive, out-of-scope-Änderung für Issue #47.

### Option 2: Nur AgDR-Template übersetzen, ADR-Korpus bleibt deutsch (gewählt)
Das AgDR-Template in `planner/nodes/apply_decision.py` wird auf Englisch
übersetzt (Issue #47). Menschliche ADRs bleiben deutsch; dieses ADR (0018)
selbst verwendet deutsche Header, um mit dem ADR-Korpus konsistent zu bleiben.
* **Vorteil**: Behebt den Denglish-Mix in agentengenerierten Dokumenten ohne
  historische Records anzutasten. Die Sprache folgt konsistent dem
  Autorschaftsmodell (Mensch = deutsch, Agent = englisch).
* **Nachteil**: ADRs und AgDRs verwenden unterschiedliche Anzeigesprachen.
  Dieser Drift wird durch vorliegendes ADR explizit dokumentiert und begründet.

## Entscheidung
Wir wählen **Option 2**. ADR-0004s Prinzip "Unterscheidung über den Pfad, nicht
über das Format" bezieht sich auf die *strukturelle Formatierung* (welche
Abschnitte vorhanden sind), nicht auf die *Anzeigesprache*. Die
Sprach-Divergenz ist eine direkte Konsequenz des Autorschaftsmodells:
Agentengenerierte AgDRs tragen englischen LLM-Inhalt und erhalten daher
englische Header; menschenverfasste ADRs bleiben deutsch. Beide Templates
behalten die identische Struktur (Status, Datum/Date, Kontext/Context, Drivers,
Optionen/Options, Entscheidung/Decision, Konsequenzen/Consequences,
Referenzen/References), sodass die strukturelle Format-Konsistenz gewahrt bleibt.

## Konsequenzen
* **Positiv**: Agentengenerierte AgDRs sind sprachlich kohärent (durchgehend
  englisch); Issue #47 ist behoben. Das Autorschaftsmodell ist explizit
  dokumentiert.
* **Negativ**: ADR- und AgDR-Korpus verwenden unterschiedliche
  Anzeigesprachen. Zukünftige, von Menschen verfasste ADRs bleiben deutsch;
  dieser ADR verwendet bewusst deutsche Header, um die ADR-Konvention
  fortzuführen.
* Klarstellung zu ADR-0004: "Format" meint Struktur, nicht Sprache. Diese
  Präzisierung ist normativ für künftige Template-Änderungen.

## Inspiration & Referenzen
* Issue #47 — Translate AgDR markdown template headers to English to resolve
  Denglish mix.
* ADR-0004 — Structured AgDR and Path Separation ("Unterscheidung über den
  Pfad, nicht über das Format").
* MADR-Template (Markdown Any Decision Records) — kanonische englische
  ADR-Abschnittsbezeichnungen ("Context and Problem Statement", "Decision
  Drivers", "Considered Options", "Consequences").
