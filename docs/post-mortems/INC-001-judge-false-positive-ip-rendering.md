# Lightweight Post-Mortem: PR Judge False Positive (IP-Rendering-Artefakt) - 2026-07-07

## 1. Quick Facts

* **Incident ID:** INC-001
* **Total Duration:** ~1 Stunde (PR #41, Iterationen 2–3)
* **Core Symptom:** Der `architecture`-Judge meldete ein `[BUG]`-Finding für ein angebliches
  Duplikat in `tests/test_research_tools.py`. Die angeblich doppelte Zeile war in Wirklichkeit
  eine andere Assertion mit einer anderen IP-Adresse.

## 2. Automated Timeline

* **Iteration 1 (PR #41):** Security-Judge FAIL wegen SSRF-Lücke in `create_fetch_url_tool`
  (kein Schutz gegen private IPs im Non-Strict-Modus). Korrekt erkannt.
* **Fix 1:** `is_ssrf_safe_url()`-Funktion eingeführt. Blockiert `127.0.0.1`, `169.254.169.254`,
  `localhost` etc. über `socket.getaddrinfo` + `ipaddress.ip_address`. Tests ergänzt.
* **Iteration 2 (PR #41):** Architecture-Judge FAIL: *"Redundant duplicate assertion:
  `self.assertFalse(is_url_allowed(..., "http://[IP_ADDRESS]"))` appears twice consecutively."*
* **Befund:** Das Finding ist ein **False Positive**. Im tatsächlichen Quellcode stehen
  `http://127.0.0.1` (Loopback) und `http://169.254.169.254` (AWS-Metadaten) — zwei
  vollständig verschiedene Adressen. Das GitHub-Rendering anonymisiert IP-Adressen in
  PR-Kommentaren zu `[IP_ADDRESS]`, wodurch sie für den menschlichen Leser identisch aussehen.
* **Iteration 3:** Keine Code-Änderung nötig. Der Judge hat das Problem korrekt erkannt
  (aus seiner Sicht waren die Strings gleich — er sah den echten Diff), aber die
  **Ausgabe im GitHub-Report** war durch das Rendering-Artefakt irreführend.

## 3. 3-Whys Root Cause Analysis

* **Why did the false positive occur?**
  Der Judge-Report zeigte `[IP_ADDRESS]` für zwei unterschiedliche IP-Adressen im Diff.
  Der Architecture-Judge wertete dies als doppelte Assertion.

* **Why were the IPs rendered as `[IP_ADDRESS]`?**
  GitHub anonymisiert IPv4-Adressen in PR-Review-Kommentaren aus Datenschutzgründen
  (`127.0.0.1` → `[IP_ADDRESS]`). Dies betrifft den **sichtbaren Report**, nicht den
  Diff, den das LLM tatsächlich als Input bekommt.

* **Why did the judge not distinguish them?**
  Das LLM hat tatsächlich die echten IPs gesehen und korrekt bewertet — der Judge selbst hat
  kein Problem gemacht. Der Mensch sah im GitHub-Kommentar `[IP_ADDRESS]` zweimal und wertete
  das als Judge-Fehler. Das eigentliche strukturelle Problem: Der Judge bekommt nur den Diff,
  nicht den vollständigen Funktionsrumpf. Selbst wenn er die echten IPs sieht, könnte er in
  anderen Fällen ohne Umgebungskontext falsch urteilen.

## 4. Action Items

- [x] **Sofortmaßnahme:** Bestätigt, dass der Code korrekt ist (kein Duplikat).
  `assertFalse(... "http://127.0.0.1")` ≠ `assertFalse(... "http://169.254.169.254")`.
- [ ] **Strukturelle Verbesserung:** `scripts/review.py` um Enclosing-Function-Kontext
  erweitern (pr-agent-Ansatz). Judge bekommt zusätzlich zum Diff den vollständigen
  Funktionsrumpf jedes geänderten Hunks. Beschrieben in ADR-0011.
  Tracking: GitHub Issue (offen).
