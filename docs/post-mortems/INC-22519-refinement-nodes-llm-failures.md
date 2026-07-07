# Lightweight Post-Mortem: Refinement Graph Nodes LLM Failures - 2026-07-07

## 1. Quick Facts
* **Incident ID:** INC-22519
* **Total Duration:** 1 hour 01 minute
* **Core Symptom:** Refinement process aborted due to repeated critic schema failures (yielding `Last error: None`) and silent empty web search results.

## 2. Automated Timeline
* **21:31 CET** - Refine runner initiated on repository `ai-commander-wargame-engine`.
* **22:20 CET** - Critic evaluation fails to produce valid structured output for draft issue `0012-telemetry-pipeline.md` after 3 attempts, raising `ValueError` with `Last error: None`.
* **22:21 CET** - Process interrupted by USER (KeyboardInterrupt) during subsequent retry.
* **22:23 CET** - Analysis of trace logs reveals empty web search results (`[]`) for all previous steps.
* **22:24 CET** - Scratch script isolation diagnostics reveal that `web_search_node` always raises `AssertionError` internally because `response.content` is returned as a list of blocks instead of a string.
* **22:29 CET** - Plan proposed to fix list parsing, migrate all nodes to `get_llm()`, fix `last_error` formatting, and filter Pydantic serialization warnings.
* **22:30 CET** - Plan approved and implemented.
* **22:32 CET** - Tests successfully updated to mock `get_llm()` and test suite passes.

## 3. 3-Whys Root Cause Analysis
* **Why did the symptom occur?** The critic evaluation failed because the critic model `z-ai/glm-5.2` did not have correct provider routing or reasoning parameters, and the web search node silently failed to return any results on every iteration.
* **Why did [Answer 1] happen?** The nodes (`evaluate_grade`, `web_search`, `propose_options`, `analyze_sources`, `apply_decision`) manually instantiated `ChatOpenAI` instead of using the centralized `get_llm()` factory, and `web_search` asserted that `response.content` must be a string (which fails when reasoning blocks are returned as a list of dicts).
* **Why did [Answer 2] happen? (Systemic Root Cause):** There was a lack of unified LLM factory usage across the refinement pipeline, and the content parser did not accommodate multi-block message content containing both thinking/reasoning and text blocks.

## 4. Action Items
- [x] **Fix:** Migrate all graph nodes to `get_llm()` and implement block-list parsing in `web_search_node`. | Owner: Agent
- [ ] **Monitoring:** Implement a validation check or linting rule to prevent direct `ChatOpenAI` instantiations in graph nodes. | Owner: Dev Team
