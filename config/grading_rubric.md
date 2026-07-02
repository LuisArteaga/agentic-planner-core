# Agentic Planner - Bewertungsrubrik (Grading Rubric)

Diese Rubrik dient als Grundlage für die automatisierte Bewertung technischer Lösungsansätze durch den Critic-Knoten (`evaluate_grade`). Jeder Lösungsansatz wird anhand von atomaren binären Kriterien (BinEval) bewertet.

---

## Kriterien & Atomare Fragen

### 1. Completeness & Feasibility (Vollständigkeit & Machbarkeit)
* **Check 1.1**: Löst die Option alle im Issue beschriebenen funktionalen Anforderungen?
* **Check 1.2**: Deckt die Option die identifizierten Edge-Cases ab?
* **Check 1.3**: Ist die Option technisch im Kontext des Ziel-Repositories ohne ungelöste Blockaden umsetzbar?

### 2. Radical Simplicity & YAGNI (Radikale Einfachheit)
* **Check 2.1**: Verzichtet die Option auf unnötige Abstraktionsschichten (z. B. keine redundant erstellten Klassen oder Wrapper)?
* **Check 2.2**: Implementiert die Option nur das, was aktuell benötigt wird (kein Overengineering für zukünftige Features)?
* **Check 2.3**: Ist der Wartungsaufwand für diese Implementierung minimal?

### 3. Architecture & ADR Compliance (Architekturkonformität)
* **Check 3.1**: Steht die Option im Einklang mit den geladenen Architekturentscheidungen (ADRs)?
* **Check 3.2**: Verwendet die Option die im Projekt etablierten Bibliotheken und Schnittstellen, anstatt neue einzuführen?

### 4. Robustness & Error Handling (Robustheit & Sicherheit)
* **Check 4.1**: Werden Fehlerszenarien, ungültige Daten oder API-Fehler kontrolliert abgefangen (z. B. durch try-except Blocks oder Validierung)?
* **Check 4.2**: Bietet die Option Schutz vor typischen Schwachstellen (wie z. B. Prompt Injection in LLM-Inputs)?

---

## Bewertungslogik (BinEval)
Die Bewertung (Score) wird als Verhältnis der bestandenen Checks berechnet und auf eine Skala von 0.0 bis 10.0 normiert:
Score = (Anzahl bestandener Checks / Gesamtanzahl Checks (10)) * 10.0
* **10.0**: Alle Checks bestanden.
* **>= 8.0**: Sehr gute Eignung, minimale Abstriche bei Simplicity oder Robustness.
* **< 8.0**: Ungenügend oder Verstöße gegen ADRs/Simplicity.
