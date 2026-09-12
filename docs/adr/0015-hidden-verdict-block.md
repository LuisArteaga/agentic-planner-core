# 0015 - Versteckter maschinenlesbarer Verdict-Block in der PR-Review

* **Status**: Accepted
* **Datum**: 2026-08-11
* **Entscheidungsträger**: Luis Arteaga

## Kontext und Problemstellung

`scripts/review.py` veröffentlicht die Judge-Verdicts als menschenlesbare Markdown-Tabelle in einer GitHub-Review. Ein automatisierter Feedback-Loop (`pr-feedback-loop`-Skill) muss diese Verdicts verlässlich parsen, um actionierbare `FAIL`/`NEEDS REVIEW`-Befunde zu extrahieren. Die sichtbare Tabelle ist für Maschinen fehleranfällig (Emoji-Variation, Lokalisierung, Spaltenformat-Drift).

## Entscheidung

`review.py` hängt an die Review-Body einen versteckten HTML-Kommentar-Block an, der jeden Judge als `key: status` enthält:

```
<!-- llm-pr-review-verdicts
syntax_lint: PASS
test_coverage: FAIL
architecture: PASS
security: PASS
-->
```

Der Block ist im GitHub-Rendering unsichtbar und wird ausschließlich vom `parse_pr_verdicts.py`-Parser des Skills konsumiert. Der Status ist der kanonische Code (`PASS`/`FAIL`/`SKIPPED`/`NEEDS REVIEW`), keine Emojis.

## Betrachtete Optionen

### Option 1: Sichtbare Tabelle parsen
* **Vorteil**: Kein zusätzliches Format im Review.
* **Nachteil**: Fragil — Emojis, Spaltenformat und Übersetzungen brechen den Parser.

### Option 2: Versteckter HTML-Kommentar-Block (gewählt)
* **Vorteil**: Stabil, maschinenlesbar, für Menschen unsichtbar; trennt Darstellung von Daten.
* **Nachteil**: Doppelführung (Tabelle + Block); Status-Strings müssen synchron gehalten werden.

## Inspiration & References

* Vorbild: das Review-Skript des privaten Sibling-Projekts (developer-core; gleicher `<!-- llm-pr-review-verdicts -->`-Block).
* Umsetzung: `scripts/review.py:779` (`hidden_lines`), Parser `skills/pr-feedback-loop/scripts/parse_pr_verdicts.py`.
