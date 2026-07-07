# 0011 - Judge Kontext-Strategie: Enclosing-Function-Erweiterung für LLM-PR-Judges

* **Status**: Accepted
* **Datum**: 2026-07-07
* **Entscheidungsträger**: Luis Arteaga

## Kontext und Problemstellung

Die LLM-PR-Judges in `scripts/review.py` erhalten ausschließlich den rohen `git diff` als Eingabe.
Dieses reine Diff-Format hat zwei strukturelle Schwächen:

1. **Rendering-Artefakte:** GitHub und andere Systeme anonymisieren IP-Adressen in Kommentaren
   (`127.0.0.1` → `[IP_ADDRESS]`, `169.254.169.254` → `[IP_ADDRESS]`). Für einen menschlichen
   Leser des Judge-Reports sehen dadurch zwei unterschiedliche `assertFalse`-Zeilen identisch aus,
   was zu False-Positive-Findings führt (INC-001).

2. **Fehlender semantischer Kontext:** Der Diff zeigt nur geänderte Zeilen ±3 Zeilen Umgebung.
   Ein Judge kann nicht erkennen, ob eine hinzugefügte Zeile wirklich ein Duplikat der vorherigen
   ist, ohne den Rumpf der umgebenden Funktion zu sehen.

Ziel ist ein Ansatz, der dem Judge gerade so viel zusätzlichen Kontext gibt, dass er semantisch
korrekte Urteile treffen kann — ohne das Kontextfenster unverhältnismäßig zu belasten.

## Entscheidungsfaktoren (Drivers)

* Minimierung von False-Positive-Findings durch Rendering-Artefakte
* Kontextfenster-Effizienz: Overhead < +100% gegenüber reinem Diff
* Keine neuen Abhängigkeiten, die nicht bereits im Projekt vorhanden sind
* Einfache Implementierung und Wartbarkeit im `scripts/review.py`-Skript

## Betrachtete Optionen

### Option 1: Vollständige geänderte Dateien mitschicken
Alle im Diff veränderten Dateien vollständig als zusätzlichen Block anhängen.
* **Vorteil:** Trivial zu implementieren, eliminiert alle kontextbedingten False Positives.
* **Nachteil:** Token-Overhead ~+306% (Messung: Diff ~10.800 Tokens, alle Dateien ~44.100 Tokens).
  Einzelne Dateien wie `planner/cli_planning.py` (906 Zeilen) machen fast so viel aus wie der
  gesamte Diff, obwohl nur ~30 Zeilen verändert wurden.

### Option 2: Dynamische Hunk-Erweiterung auf umschließende Funktion/Klasse (pr-agent-Ansatz)
Den Diff-Hunk (`@@`-Grenzen) nach oben und unten bis zur nächsten `def`/`class`-Grenze
erweitern. Der Judge bekommt statt ±3 Zeilen die gesamte umgebende Funktion.
* **Vorteil:** Token-Overhead ~+30–50%, keine neue Abhängigkeit (stdlib `re`), eliminiert das
  IP-Rendering-Problem, da die gesamte Funktion mit allen Assertions lesbar ist.
* **Nachteil:** Findet keine cross-file-Probleme (z. B. geänderte Signatur bricht Aufrufer in
  anderer Datei). Für unsere Judge-Kriterien (Duplikate, Testqualität, YAGNI) ausreichend.

### Option 3: AST + Call-Graph (1-Hop, CodeRabbit-Ansatz)
Aus dem Diff betroffene Funktionen per `ast.parse` extrahieren, Aufrufgraph aufbauen und
alle direkten Aufrufer (`callers`) und Aufgerufenen (`callees`) mitschicken.
* **Vorteil:** Deckt cross-file-Abhängigkeiten auf (beste Kontexttiefe), Token-Overhead ~+40–60%.
* **Nachteil:** Erheblicher Implementierungsaufwand (multi-file AST-Traversal, Importauflösung,
  Graphaufbau). Für unsere bisherigen Judge-Kriterien Over-Engineering (YAGNI).

## Entscheidung

**Option 2** — Dynamische Hunk-Erweiterung auf die umschließende Funktion/Klasse (pr-agent-Ansatz).

### Implementierungsdetail

`scripts/review.py` wird um eine Funktion `enrich_diff_with_function_context(diff, workspace_dir)`
erweitert, die:

1. Jeden `@@`-Hunk aus dem Diff parsed (geänderte Datei + Startzeile).
2. Die vollständige Originaldatei aus dem Checkout liest.
3. Ab der Hunk-Startzeile nach oben sucht, bis eine `def`- oder `class`-Zeile gefunden wird.
4. Ab der Hunk-Endzeile nach unten sucht, bis die nächste `def`/`class`-Zeile auf der gleichen
   Einrückungstiefe erscheint (Ende der Funktion).
5. Den extrahierten Funktionsrumpf als `=== CONTEXT: <datei> <funktion> ===`-Block an den
   User-Prompt aller Judges anhängt.

Dateien, die keine `@@`-Hunks enthalten (z. B. reine Umbenennungen), werden übersprungen.
Pro Datei wird ein Zeichenlimit von 15.000 Zeichen gesetzt; überschreitende Kontexte werden
mit `[... truncated ...]` gekürzt.

### Konsequenzen

* **Positiv:**
  - False Positives durch Rendering-Artefakte (IP-Adressen, `@`-Dekoratoren) werden eliminiert,
    da die gesamte Funktion mit vollständigem Quelltext sichtbar ist.
  - Token-Overhead bleibt bei ~+30–50% gegenüber dem reinen Diff — vertretbar für alle
    Modelle in `config/factory.json`.
  - Keine neuen Abhängigkeiten; `re` ist stdlib.
* **Negativ:**
  - Cross-file-Probleme (z. B. gebrochene Aufrufer in anderen Dateien) werden weiterhin
    nicht erkannt. Kann in einem zukünftigen ADR zu Option 3 eskaliert werden, wenn die
    Judge-Kriterien es erfordern.

## Inspiration & Referenzen

* [pr-agent (Qodo/CodiumAI)](https://pr-agent.ai) — `allow_dynamic_context`, asymmetrisches
  Kontext-Fenster, Enclosing-Component-Strategie.
* [CodeRabbit](https://coderabbit.ai) — AST + 1-Hop Call-Graph als Weiterentwicklung.
* INC-001 Post-Mortem: `docs/post-mortems/INC-001-judge-false-positive-ip-rendering.md`
