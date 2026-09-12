# 0014 - LLM-Judge-Verdicts sind merge-blockierend (FAIL und NEEDS REVIEW)

* **Status**: Accepted
* **Datum**: 2026-08-11
* **Entscheidungsträger**: Luis Arteaga

## Kontext und Problemstellung

Die CI (`scripts/review.py`) bewertet jeden PR mit vier LLM-Judges (`syntax_lint`, `test_coverage`, `architecture`, `security`). Jeder Judge liefert eines von `PASS`, `FAIL` oder `NEEDS REVIEW`. Letzteres bedeutet, der Judge hatte nicht genug Kontext, um die Kriterien zu verifizieren — keine explizite Verletzung. Es bestand die Versuchung, `NEEDS REVIEW` als weiche Warnung (mergebar) zu behandeln.

## Entscheidung

Sowohl `FAIL` als auch `NEEDS REVIEW` blockieren den Merge. `review.py` setzt `overall_failed = any(status == "FAIL")` und sendet `request-changes`; der Merge bleibt blockiert, bis jeder Judge `PASS` liefert. Der `pr-feedback-loop`-Skill behandelt jedes Non-PASS-Verdict als actionierbar.

## Betrachtete Optionen

### Option 1: `NEEDS REVIEW` als weiche Warnung (mergebar)
* **Vorteil**: Weniger Blockaden durch unklare Judge-Kontexte.
* **Nachteil**: Ein nicht verifizierbares Urteil wird stillschweigend akzeptiert — genau das Risiko, das die Judges verhindern sollen.

### Option 2: `FAIL` und `NEEDS REVIEW` blockieren (gewählt)
* **Vorteil**: Konservative, einheitliche Semantik — nur verifizierte `PASS`-Urteile erlauben den Merge.
* **Nachteil**: Häufigere Blockaden; erfordert Auflösung durch Kontextbereitstellung oder manuelle Überprüfung.

## Inspiration & References

* Vorbild: das private Sibling-Projekt (developer-core; gleiche Judge-Architektur und Merge-Blocking-Semantik).
* Umsetzung: `scripts/review.py:788` (`overall_failed`), `scripts/review.py:312` (`submit_github_review` mit `request-changes`).
