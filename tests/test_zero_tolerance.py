import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from planner.state import AgentState, RefinementState
from planner.zero_tolerance.gate import (
    compute_dependency_map,
    detect_structural_change_node,
    route_after_decision,
    run_batch_gate,
    run_cascade_pass,
    threshold_check_node,
)
from planner.zero_tolerance.intent_gate import IntentGateOutput, intent_gate_node
from planner.zero_tolerance.linters import (
    adr_traceability_lint,
    dependency_lint,
    glossary_lint,
    is_trivial,
    parse_blocked_by,
    parse_scope,
    parse_glossary,
    structural_signature,
)
from planner.zero_tolerance.models import (
    Severity,
    ZeroToleranceConfig,
    ZeroToleranceViolation,
)
from planner.zero_tolerance.planning_judge import (
    PlanningJudgeOutput,
    planning_judge_node,
)


# ---------------------------------------------------------------------------
# Deterministic linters
# ---------------------------------------------------------------------------


class GlossaryLinterTests(unittest.TestCase):
    def test_deprecated_synonym_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = Path(d) / "CONTEXT.md"
            ctx.write_text(
                "# Domain Glossary\n\n## Begriffe\n\n"
                "### Customer\n"
                "* **Definition**: A paying account holder.\n"
                "* **Synonyme / Abzugrenzende Begriffe**: Veraltete Synonyme: Client\n",
                encoding="utf-8",
            )
            glossary = parse_glossary(str(ctx))
            self.assertIn("customer", glossary)
            self.assertEqual(glossary["customer"].deprecated_synonyms, ["Client"])

            drafts = {
                "0001-uses-client.md": "# feat: x\nThe Client logs in here.\n",
                "0002-uses-customer.md": "# feat: y\nThe Customer logs in here.\n",
            }
            findings = glossary_lint(drafts, glossary)
            errors = [f for f in findings if f.severity == Severity.ERROR]
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].issue, "0001-uses-client.md")
            self.assertIn("Client", errors[0].message)
            self.assertIn("customer", errors[0].message)

    def test_no_deprecated_synonyms_passes(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = Path(d) / "CONTEXT.md"
            ctx.write_text(
                "### Agentic Planner\n"
                "* **Synonyme / Abzugrenzende Begriffe**: Nicht zu verwechseln mit dem Loop.\n",
                encoding="utf-8",
            )
            glossary = parse_glossary(str(ctx))
            # No "Veraltete Synonyme:" marker -> no deprecated synonyms.
            self.assertEqual(glossary["agentic planner"].deprecated_synonyms, [])
            findings = glossary_lint({"0001.md": "The Agentic Planner runs."}, glossary)
            self.assertEqual(findings, [])


class DependencyLinterTests(unittest.TestCase):
    def test_valid_dag_no_findings(self):
        drafts = {
            "0001-a.md": "# feat: a\n\n## Blocked by\nNone\n",
            "0002-b.md": "# feat: b\n\n## Blocked by\n0001-a.md\n",
            "0003-c.md": "# feat: c\n\n## Blocked by\n0001-a.md, 0002-b.md\n",
        }
        findings, dep_map = dependency_lint(drafts)
        self.assertEqual(findings, [])
        self.assertEqual(dep_map["0003-c.md"], ["0001-a.md", "0002-b.md"])

    def test_cycle_detected(self):
        drafts = {
            "0001-a.md": "# feat: a\n\n## Blocked by\n0002-b.md\n",
            "0002-b.md": "# feat: b\n\n## Blocked by\n0001-a.md\n",
        }
        findings, _ = dependency_lint(drafts)
        errors = [f for f in findings if f.severity == Severity.ERROR]
        self.assertTrue(any("Circular dependency" in f.message for f in errors))

    def test_dangling_reference_detected(self):
        drafts = {
            "0001-a.md": "# feat: a\n\n## Blocked by\n0099-missing.md\n",
        }
        findings, _ = dependency_lint(drafts)
        errors = [f for f in findings if f.severity == Severity.ERROR]
        self.assertEqual(len(errors), 1)
        self.assertIn("0099-missing.md", errors[0].message)


class ADRTraceabilityLinterTests(unittest.TestCase):
    def test_missing_adr_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            adr_dir = Path(d) / "docs" / "adr"
            adr_dir.mkdir(parents=True)
            (adr_dir / "0001-real.md").write_text("content", encoding="utf-8")
            drafts = {
                "0001.md": (
                    "# feat: x\nMust follow [ADR-0001](docs/adr/0001-real.md) "
                    "and ADR-0099 which does not exist.\n"
                ),
            }
            findings = adr_traceability_lint(drafts, [str(adr_dir)])
            errors = [f for f in findings if f.severity == Severity.ERROR]
            self.assertEqual(len(errors), 1)
            self.assertIn("0099", errors[0].message)

    def test_existing_adr_passes(self):
        with tempfile.TemporaryDirectory() as d:
            adr_dir = Path(d) / "docs" / "adr"
            adr_dir.mkdir(parents=True)
            (adr_dir / "0001-real.md").write_text("content", encoding="utf-8")
            drafts = {"0001.md": "Follows ADR-0001.\n"}
            findings = adr_traceability_lint(drafts, [str(adr_dir)])
            self.assertEqual(findings, [])


class TrivialityAndSignatureTests(unittest.TestCase):
    def test_trivial_docs_issue(self):
        config = ZeroToleranceConfig()
        content = (
            "# docs: fix typo\n\n## What to build\nFix a typo.\n\n"
            "## Scope\ndocs\n\n## Acceptance criteria\n- [x] done\n"
        )
        self.assertTrue(is_trivial(content, config))

    def test_non_trivial_due_to_blockers(self):
        config = ZeroToleranceConfig()
        content = "# docs: fix\n\n## Scope\ndocs\n\n## Blocked by\n0001-x.md\n"
        self.assertFalse(is_trivial(content, config))

    def test_non_trivial_due_to_scope(self):
        config = ZeroToleranceConfig()
        content = "# feat: x\n\n## Scope\napi\n\nShort.\n"
        self.assertFalse(is_trivial(content, config))

    def test_structural_signature_detects_heading_change(self):
        original = "# feat: x\n\n## Scope\napi\n\n## Blocked by\nNone\n"
        changed_headings = (
            "# feat: x\n\n## Scope\napi\n\n## New Section\n\n## Blocked by\nNone\n"
        )
        self.assertNotEqual(
            structural_signature(original), structural_signature(changed_headings)
        )

    def test_structural_signature_ignores_prose(self):
        base = (
            "# feat: x\n\n## Scope\napi\n\n## What to build\nOriginal prose.\n\n"
            "## Blocked by\nNone\n"
        )
        reworded = (
            "# feat: x\n\n## Scope\napi\n\n## What to build\nEnriched prose.\n\n"
            "## Blocked by\nNone\n"
        )
        self.assertEqual(structural_signature(base), structural_signature(reworded))


class ParseHelpersTests(unittest.TestCase):
    def test_parse_blocked_by_multiple(self):
        content = "## Blocked by\n0001-a.md, 0002-b.md\n- 0003-c.md\n"
        self.assertEqual(
            parse_blocked_by(content), ["0001-a.md", "0002-b.md", "0003-c.md"]
        )

    def test_parse_blocked_by_none(self):
        self.assertEqual(parse_blocked_by("## Blocked by\nNone\n"), [])

    def test_parse_scope(self):
        self.assertEqual(parse_scope("## Scope\napi\n"), "api")


# ---------------------------------------------------------------------------
# Gate orchestration
# ---------------------------------------------------------------------------


class BatchGateTests(unittest.TestCase):
    def _write_drafts(self, d: Path, drafts: dict) -> list:
        paths = []
        for name, content in drafts.items():
            p = d / name
            p.write_text(content, encoding="utf-8")
            paths.append(str(p))
        return paths

    def test_batch_gate_passes_clean_drafts(self):
        with tempfile.TemporaryDirectory() as d:
            dpath = Path(d)
            (dpath / "CONTEXT.md").write_text(
                "### Customer\n* stuff\n", encoding="utf-8"
            )
            adr = dpath / "docs" / "adr"
            adr.mkdir(parents=True)
            (adr / "0001-real.md").write_text("x", encoding="utf-8")
            paths = self._write_drafts(
                dpath,
                {
                    "0001-a.md": "# feat: a\n\n## Scope\napi\n\n## Blocked by\nNone\n",
                    "0002-b.md": "# feat: b\n\n## Scope\napi\n\n## Blocked by\n0001-a.md\n",
                },
            )
            config = ZeroToleranceConfig(
                context_path=str(dpath / "CONTEXT.md"),
                adr_dirs=[str(adr)],
            )
            result = run_batch_gate(paths, config)
            self.assertTrue(result.passed)

    def test_batch_gate_fails_on_cycle(self):
        with tempfile.TemporaryDirectory() as d:
            dpath = Path(d)
            paths = self._write_drafts(
                dpath,
                {
                    "0001-a.md": "# feat: a\n\n## Blocked by\n0002-b.md\n",
                    "0002-b.md": "# feat: b\n\n## Blocked by\n0001-a.md\n",
                },
            )
            config = ZeroToleranceConfig(
                context_path=str(dpath / "CONTEXT.md"), adr_dirs=[]
            )
            result = run_batch_gate(paths, config)
            self.assertFalse(result.passed)
            self.assertTrue(any(f.check == "dependency" for f in result.errors()))


class CascadePassTests(unittest.TestCase):
    def test_downstream_marked_stale(self):
        with tempfile.TemporaryDirectory() as d:
            dpath = Path(d)
            downstream = dpath / "0002-b.md"
            downstream.write_text(
                "# feat: b\n\n## Blocked by\n0001-a.md\n", encoding="utf-8"
            )
            dep_map = {
                "0001-a.md": [],
                "0002-b.md": ["0001-a.md"],
            }
            stale = run_cascade_pass([str(downstream)], ["0001-a.md"], dep_map)
            self.assertEqual(stale, [str(downstream)])
            self.assertTrue(Path(str(downstream) + ".stale").exists())

    def test_no_change_no_stale(self):
        self.assertEqual(run_cascade_pass([], ["0001-a.md"], {}), [])


class RoutingTests(unittest.TestCase):
    def test_non_zero_tolerance_routes_to_publish(self):
        state: RefinementState = {"zero_tolerance": False}  # type: ignore[dict-item]
        self.assertEqual(route_after_decision(state), "publish_issue")

    def test_zero_tolerance_trivial_routes_to_publish(self):
        state: RefinementState = {"zero_tolerance": True, "trivial": True}  # type: ignore[dict-item]
        self.assertEqual(route_after_decision(state), "publish_issue")

    def test_zero_tolerance_non_trivial_routes_to_threshold(self):
        state: RefinementState = {"zero_tolerance": True, "trivial": False}  # type: ignore[dict-item]
        self.assertEqual(route_after_decision(state), "threshold_check")


class ThresholdCheckTests(unittest.TestCase):
    def _state(self, score, n_results):
        return {
            "zero_tolerance_config": {},
            "draft_issue_path": "0001-x.md",
            "best_option": {"score": score},
            "search_results": [{} for _ in range(n_results)],
        }

    def test_low_score_raises(self):
        with self.assertRaises(ZeroToleranceViolation) as ctx:
            threshold_check_node(self._state(3.0, 5))
        self.assertEqual(ctx.exception.check, "threshold")

    def test_empty_search_raises(self):
        with self.assertRaises(ZeroToleranceViolation):
            threshold_check_node(self._state(8.0, 0))

    def test_passes_when_score_and_results_ok(self):
        result = threshold_check_node(self._state(8.0, 5))
        self.assertEqual(result, {})


class DetectStructuralChangeTests(unittest.TestCase):
    def test_detects_change(self):
        with tempfile.TemporaryDirectory() as d:
            draft = Path(d) / "0001-x.md"
            original = "# feat: x\n\n## Scope\napi\n\n## Blocked by\nNone\n"
            refined = (
                "# feat: x\n\n## Scope\napi\n\n## New Section\n\n## Blocked by\nNone\n"
            )
            draft.write_text(refined, encoding="utf-8")
            state = {
                "zero_tolerance_config": {},
                "draft_issue_path": str(draft),
                "original_draft_signature": structural_signature(original),
            }
            out = detect_structural_change_node(state)  # type: ignore[arg-type]
            self.assertTrue(out["structurally_changed"])

    def test_no_change(self):
        with tempfile.TemporaryDirectory() as d:
            draft = Path(d) / "0001-x.md"
            content = "# feat: x\n\n## Scope\napi\n\n## Blocked by\nNone\n"
            draft.write_text(content, encoding="utf-8")
            state = {
                "zero_tolerance_config": {},
                "draft_issue_path": str(draft),
                "original_draft_signature": structural_signature(content),
            }
            out = detect_structural_change_node(state)  # type: ignore[arg-type]
            self.assertFalse(out["structurally_changed"])


# ---------------------------------------------------------------------------
# LLM nodes (mocked)
# ---------------------------------------------------------------------------


def _mock_structured_response(parsed_obj):
    """Build a mocked with_structured_output().invoke() return dict."""
    return {"parsed": parsed_obj, "raw": None, "parsing_error": None}


class IntentGateTests(unittest.TestCase):
    def setUp(self):
        self.original_env = dict(os.environ)
        os.environ["OPENROUTER_API_KEY"] = "mock-key"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    @patch("planner.zero_tolerance.llm_utils.get_llm")
    def test_agreement_passes(self, mock_get_llm):
        mock_model = MagicMock()
        mock_get_llm.return_value = mock_model
        mock_struct = MagicMock()
        mock_model.with_structured_output.return_value = mock_struct
        mock_struct.invoke.return_value = _mock_structured_response(
            IntentGateOutput(
                intent_line="INTENT: draft issue assumes X; target system/code shows Y; PRD/Glossary/ADR says Z",
                assumptions="X",
                system_state="Y",
                spec_state="Z",
                agreement=True,
                contradictions="",
            )
        )
        with tempfile.TemporaryDirectory() as d:
            draft = Path(d) / "0001-x.md"
            draft.write_text("# feat: x\n\n## Scope\napi\n", encoding="utf-8")
            state = {
                "draft_issue_path": str(draft),
                "draft_issue_content": "x",
                "search_results": [{"title": "t", "url": "u", "snippet": "s"}],
                "best_option": {"name": "opt", "score": 8.0},
                "intent_line": "",
            }
            out = intent_gate_node(state)  # type: ignore[arg-type]
            self.assertIn("INTENT", out["intent_line"])

    @patch("planner.zero_tolerance.llm_utils.get_llm")
    def test_contradiction_halts(self, mock_get_llm):
        mock_model = MagicMock()
        mock_get_llm.return_value = mock_model
        mock_struct = MagicMock()
        mock_model.with_structured_output.return_value = mock_struct
        mock_struct.invoke.return_value = _mock_structured_response(
            IntentGateOutput(
                intent_line="INTENT: ...",
                assumptions="X",
                system_state="Y",
                spec_state="Z",
                agreement=False,
                contradictions="Draft assumes lib A but search shows it is deprecated.",
            )
        )
        with tempfile.TemporaryDirectory() as d:
            draft = Path(d) / "0001-x.md"
            draft.write_text("# feat: x\n\n## Scope\napi\n", encoding="utf-8")
            state = {
                "draft_issue_path": str(draft),
                "search_results": [],
                "best_option": {},
            }
            with self.assertRaises(ZeroToleranceViolation) as ctx:
                intent_gate_node(state)  # type: ignore[arg-type]
            self.assertEqual(ctx.exception.check, "intent_gate")


class PlanningJudgeTests(unittest.TestCase):
    def setUp(self):
        self.original_env = dict(os.environ)
        os.environ["OPENROUTER_API_KEY"] = "mock-key"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    @patch("planner.zero_tolerance.llm_utils.get_llm")
    def test_passed(self, mock_get_llm):
        mock_model = MagicMock()
        mock_get_llm.return_value = mock_model
        mock_struct = MagicMock()
        mock_model.with_structured_output.return_value = mock_struct
        mock_struct.invoke.return_value = _mock_structured_response(
            PlanningJudgeOutput(passed=True, verdict="ok", issues=[])
        )
        with tempfile.TemporaryDirectory() as d:
            draft = Path(d) / "0001-x.md"
            draft.write_text("# feat: x\n", encoding="utf-8")
            state = {"draft_issue_path": str(draft), "search_results": []}
            out = planning_judge_node(state)  # type: ignore[arg-type]
            self.assertEqual(out, {})

    @patch("planner.zero_tolerance.llm_utils.get_llm")
    def test_failed_halts(self, mock_get_llm):
        mock_model = MagicMock()
        mock_get_llm.return_value = mock_model
        mock_struct = MagicMock()
        mock_model.with_structured_output.return_value = mock_struct
        mock_struct.invoke.return_value = _mock_structured_response(
            PlanningJudgeOutput(
                passed=False, verdict="bad", issues=["ungrounded claim"]
            )
        )
        with tempfile.TemporaryDirectory() as d:
            draft = Path(d) / "0001-x.md"
            draft.write_text("# feat: x\n", encoding="utf-8")
            state = {"draft_issue_path": str(draft), "search_results": []}
            with self.assertRaises(ZeroToleranceViolation) as ctx:
                planning_judge_node(state)  # type: ignore[arg-type]
            self.assertEqual(ctx.exception.check, "planning_judge")


# ---------------------------------------------------------------------------
# Shared LLM helpers
# ---------------------------------------------------------------------------


class LLMUtilsTests(unittest.TestCase):
    def setUp(self):
        self.original_env = dict(os.environ)
        os.environ["OPENROUTER_API_KEY"] = "mock-key"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_build_search_context_empty(self):
        from planner.zero_tolerance.llm_utils import build_search_context

        self.assertEqual(build_search_context([]), "No web search results available.")

    def test_build_search_context_with_results(self):
        from planner.zero_tolerance.llm_utils import build_search_context

        ctx = build_search_context([{"title": "T", "url": "U", "snippet": "S"}])
        self.assertIn("T", ctx)
        self.assertIn("U", ctx)
        self.assertIn("S", ctx)

    @patch("planner.zero_tolerance.llm_utils.get_llm")
    def test_invoke_structured_with_retry_returns_parsed(self, mock_get_llm):
        from planner.zero_tolerance.llm_utils import invoke_structured_with_retry

        mock_model = MagicMock()
        mock_get_llm.return_value = mock_model
        mock_struct = MagicMock()
        mock_model.with_structured_output.return_value = mock_struct
        expected = PlanningJudgeOutput(passed=True, verdict="ok", issues=[])
        mock_struct.invoke.return_value = _mock_structured_response(expected)
        result = invoke_structured_with_retry(
            "planning_judge", PlanningJudgeOutput, "sys", "user"
        )
        self.assertIs(result, expected)

    @patch("planner.zero_tolerance.llm_utils.get_llm")
    def test_invoke_structured_with_retry_raises_after_attempts(self, mock_get_llm):
        from planner.zero_tolerance.llm_utils import invoke_structured_with_retry

        mock_model = MagicMock()
        mock_get_llm.return_value = mock_model
        mock_struct = MagicMock()
        mock_model.with_structured_output.return_value = mock_struct
        # Always returns a non-matching parsed value -> never succeeds.
        mock_struct.invoke.return_value = {
            "parsed": "not-a-model",
            "raw": None,
            "parsing_error": "bad",
        }
        with self.assertRaises(ValueError):
            invoke_structured_with_retry(
                "planning_judge", PlanningJudgeOutput, "sys", "user", max_attempts=2
            )
        self.assertEqual(mock_struct.invoke.call_count, 2)


# ---------------------------------------------------------------------------
# Master-loop halt semantics
# ---------------------------------------------------------------------------


class MasterLoopZeroToleranceTests(unittest.TestCase):
    @patch("planner.refine_graph.refine_subgraph")
    def test_zero_tolerance_violation_halts_batch(self, mock_subgraph):
        """A ZeroToleranceViolation must NOT be isolated per-draft; it halts."""
        from planner.refine_graph import run_refinement_subgraph_node

        mock_subgraph.invoke.side_effect = ZeroToleranceViolation(
            "intent_gate", "contradiction", "0001-x.md"
        )
        with tempfile.TemporaryDirectory() as d:
            draft = Path(d) / "0001-x.md"
            draft.write_text("# feat: x\n", encoding="utf-8")
            state: AgentState = {
                "draft_issues": [str(draft)],
                "current_issue_index": 0,
                "zero_tolerance": True,
                "zero_tolerance_config": {},
                "dependency_map": {},
            }
            with self.assertRaises(ZeroToleranceViolation):
                run_refinement_subgraph_node(state)

    @patch("planner.refine_graph.refine_subgraph")
    def test_cascade_marks_downstream_stale(self, mock_subgraph):
        """A structurally changed upstream draft marks downstream drafts stale."""
        from planner.refine_graph import run_refinement_subgraph_node

        mock_subgraph.invoke.return_value = {
            "status": "success",
            "structurally_changed": True,
        }
        with tempfile.TemporaryDirectory() as d:
            dpath = Path(d)
            up = dpath / "0001-a.md"
            down = dpath / "0002-b.md"
            up.write_text("# feat: a\n", encoding="utf-8")
            down.write_text("# feat: b\n\n## Blocked by\n0001-a.md\n", encoding="utf-8")
            state: AgentState = {
                "draft_issues": [str(up), str(down)],
                "current_issue_index": 0,
                "zero_tolerance": True,
                "zero_tolerance_config": {},
                "dependency_map": {
                    "0001-a.md": [],
                    "0002-b.md": ["0001-a.md"],
                },
            }
            result = run_refinement_subgraph_node(state)
            self.assertIn("0001-a.md", result.get("changed_drafts", []))
            self.assertIn("0002-b.md", result.get("stale_drafts", []))
            self.assertTrue(Path(str(down) + ".stale").exists())


class ConfigTests(unittest.TestCase):
    def test_zero_tolerance_config_defaults(self):
        cfg = ZeroToleranceConfig()
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.min_acceptable_score, 5.0)
        self.assertEqual(cfg.max_fruitless_searches, 0)
        self.assertEqual(cfg.trivial_scopes, ["docs"])

    def test_dependency_map_computed(self):
        with tempfile.TemporaryDirectory() as d:
            dpath = Path(d)
            (dpath / "0001-a.md").write_text("# a\n", encoding="utf-8")
            (dpath / "0002-b.md").write_text(
                "# b\n\n## Blocked by\n0001-a.md\n", encoding="utf-8"
            )
            dep = compute_dependency_map(
                [str(dpath / "0001-a.md"), str(dpath / "0002-b.md")]
            )
            self.assertEqual(dep["0002-b.md"], ["0001-a.md"])


if __name__ == "__main__":
    unittest.main()
