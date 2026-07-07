# Lightweight Post-Mortem: CI/CD PR Judges (Empty LLM Response) - 2026-07-07

## 1. Quick Facts
* **Incident ID:** INC-3401
* **Total Duration:** 69 minutes (18:55 UTC - 20:04 UTC)
* **Core Symptom:** Automated LLM PR check `test_coverage` failed with "Empty response from LLM" and 0 violations found on GitHub Actions.

## 2. Automated Timeline
* **18:55 UTC** - LLM review judge fails in PR checks (Run 28819030682). `test_coverage` reports 0 violations but is labeled `FAIL` with reasoning "Empty response from LLM".
* **19:15 UTC** - Diagnostic script shows all four Kimi providers (Inceptron, Together, SiliconFlow, MoonshotAI) succeed and return non-empty responses for small diffs.
* **19:54 UTC** - Diagnostic script execution with the full 62 KB PR diff reveals Inceptron returns HTTP 200 but with `content = None` inside the choices list. `Together` successfully processes the 62 KB diff and returns a 2,209 character response.
* **19:57 UTC** - Timeout configuration and empty response validation logic added to `scripts/review.py`. Kimi routing updated to put `Together` first in `config/factory.json` and `planner/config.py`.
* **20:04 UTC** - Workflow checks (Run 28840669436) finish successfully with all four judges reporting `✅ PASS` status.

## 3. 3-Whys Root Cause Analysis
* **Why did the symptom occur?** The `test_coverage` judge was evaluated as a failure because the API completion returned an empty response body instead of structured reasoning.
* **Why did the judge receive an empty response?** The primary provider in the Kimi routing order (`Inceptron`) returned an HTTP 200 SUCCESS but with empty choices content when processing the large 62 KB diff payload.
* **Why did the review script not fall back to the next provider?** The HTTP request did not throw an exception (since it was HTTP 200 with a valid choices structure), so the retry loop assumed the request was completely successful and did not trigger fallback.

## 4. Action Items
- [x] **Fix:** Update `scripts/review.py` to validate that choices content is non-empty, throwing an exception to trigger the retry/fallback loop if blank. | Owner: Backend Team
- [x] **Fix:** Reorder Kimi model routing list to put `Together` first (since it is fast and supports large payloads). | Owner: Backend Team
- [x] **Monitoring:** Ensure all review judges have tests validating timeout selection and empty response content handling. | Owner: QA/Testing Team
