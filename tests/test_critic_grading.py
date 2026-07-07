import os
import unittest
from unittest.mock import patch, MagicMock
from langchain_core.messages import AIMessage
from planner.state import RefinementState
from planner.nodes.propose_options import propose_options_node
from planner.nodes.evaluate_grade import (
    evaluate_grade_node,
    CriticEvaluation,
    GradingOption,
)


class CriticGradingTests(unittest.TestCase):
    def setUp(self):
        self.original_env = dict(os.environ)
        os.environ["OPENROUTER_API_KEY"] = "mock-openrouter-key"
        os.environ["GH_PAT"] = "mock-gh-pat"
        os.environ["GITHUB_REPOSITORY"] = "LuisArteaga/agentic-planner-core"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    @patch("planner.nodes.propose_options.get_llm")
    def test_propose_options_success(self, mock_get_llm):
        mock_instance = MagicMock()
        mock_get_llm.return_value = mock_instance

        mock_response = MagicMock(spec=AIMessage)
        mock_response.content = (
            "Based on search results, here are the options:\n"
            "```json\n"
            "[\n"
            "  {\n"
            '    "choice_id": "option_1",\n'
            '    "name": "Use Database Wrapper",\n'
            '    "description": "Ground in SQLite docs...",\n'
            '    "anticipated_criticism": "YAGNI violation"\n'
            "  },\n"
            "  {\n"
            '    "choice_id": "option_2",\n'
            '    "name": "Keep it Simple",\n'
            '    "description": "Simple function call...",\n'
            '    "anticipated_criticism": "None"\n'
            "  }\n"
            "]\n"
            "```"
        )
        mock_response.response_metadata = {
            "token_usage": {"prompt_tokens": 50, "completion_tokens": 100}
        }
        mock_instance.invoke.return_value = mock_response

        state: RefinementState = {
            "draft_issue_content": "Add DB persistence to logs.",
            "strict_mode": True,
            "allowed_domains": ["github.com"],
            "messages": [],
            "keywords": [],
            "search_queries": [],
            "search_results": [
                {"title": "Docs", "url": "https://github.com", "snippet": "Use SQLite"}
            ],
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "model_name": "google/gemini-2.5-flash",
            "status": "success",
            "proposed_options": [],
            "best_option": {},
            "all_grades": [],
        }

        output = propose_options_node(state)

        self.assertEqual(len(output["proposed_options"]), 2)
        self.assertEqual(output["proposed_options"][0]["choice_id"], "option_1")
        self.assertEqual(output["proposed_options"][1]["choice_id"], "option_2")
        self.assertEqual(output["prompt_tokens"], 60)
        self.assertEqual(output["completion_tokens"], 120)
        self.assertEqual(output["status"], "success")

    @patch("planner.nodes.evaluate_grade.get_llm")
    def test_evaluate_grade_success_first_attempt(self, mock_get_llm):
        mock_instance = MagicMock()
        mock_get_llm.return_value = mock_instance

        mock_structured_model = MagicMock()
        mock_instance.with_structured_output.return_value = mock_structured_model

        # Define mock CriticEvaluation result
        mock_eval_result = CriticEvaluation(
            evaluations=[
                GradingOption(
                    choice_id="option_1",
                    score=7.0,
                    reasoning="Okay but complex.",
                    checks={"Check 1.1": True, "Check 2.1": False},
                ),
                GradingOption(
                    choice_id="option_2",
                    score=9.0,
                    reasoning="Very simple and fits ADRs.",
                    checks={"Check 1.1": True, "Check 2.1": True},
                ),
            ]
        )
        mock_raw_msg = MagicMock()
        mock_raw_msg.response_metadata = {
            "token_usage": {"prompt_tokens": 40, "completion_tokens": 80}
        }
        mock_structured_model.invoke.return_value = {
            "parsed": mock_eval_result,
            "raw": mock_raw_msg,
        }

        state: RefinementState = {
            "draft_issue_content": "Add DB persistence to logs.",
            "strict_mode": True,
            "allowed_domains": ["github.com"],
            "messages": [],
            "keywords": [],
            "search_queries": [],
            "search_results": [],
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "model_name": "google/gemini-2.5-flash",
            "status": "success",
            "proposed_options": [
                {
                    "choice_id": "option_1",
                    "name": "DB wrapper",
                    "description": "Complex DB wrapper",
                },
                {
                    "choice_id": "option_2",
                    "name": "Simple func",
                    "description": "Simple func call",
                },
            ],
            "best_option": {},
            "all_grades": [],
        }

        output = evaluate_grade_node(state)

        self.assertEqual(len(output["all_grades"]), 2)
        self.assertEqual(output["best_option"]["choice_id"], "option_2")
        self.assertEqual(output["best_option"]["score"], 9.0)
        self.assertEqual(output["prompt_tokens"], 50)
        self.assertEqual(output["completion_tokens"], 100)
        self.assertEqual(output["status"], "success")

    @patch("planner.nodes.evaluate_grade.get_llm")
    def test_evaluate_grade_retry_loop_success(self, mock_get_llm):
        mock_instance = MagicMock()
        mock_get_llm.return_value = mock_instance

        mock_structured_model = MagicMock()
        mock_instance.with_structured_output.return_value = mock_structured_model

        # First invoke throws exception (parsing error), second invoke succeeds
        mock_eval_result = CriticEvaluation(
            evaluations=[
                GradingOption(
                    choice_id="option_1",
                    score=8.5,
                    reasoning="Good option.",
                    checks={"Check 1.1": True},
                )
            ]
        )
        mock_raw_msg = MagicMock()
        mock_raw_msg.response_metadata = {
            "token_usage": {"prompt_tokens": 30, "completion_tokens": 60}
        }
        mock_structured_model.invoke.side_effect = [
            ValueError("Bad JSON structure"),
            {"parsed": mock_eval_result, "raw": mock_raw_msg},
        ]

        state: RefinementState = {
            "draft_issue_content": "Add DB persistence to logs.",
            "strict_mode": True,
            "allowed_domains": ["github.com"],
            "messages": [],
            "keywords": [],
            "search_queries": [],
            "search_results": [],
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "model_name": "google/gemini-2.5-flash",
            "status": "success",
            "proposed_options": [
                {
                    "choice_id": "option_1",
                    "name": "DB wrapper",
                    "description": "Complex DB wrapper",
                }
            ],
            "best_option": {},
            "all_grades": [],
        }

        output = evaluate_grade_node(state)

        self.assertEqual(output["best_option"]["choice_id"], "option_1")
        self.assertEqual(output["best_option"]["score"], 8.5)
        self.assertEqual(output["prompt_tokens"], 40)
        self.assertEqual(output["completion_tokens"], 80)
        self.assertEqual(output["status"], "success")
        self.assertEqual(mock_structured_model.invoke.call_count, 2)

    @patch("planner.nodes.evaluate_grade.get_llm")
    def test_evaluate_grade_retry_loop_exhausted_raises(self, mock_get_llm):
        mock_instance = MagicMock()
        mock_get_llm.return_value = mock_instance

        mock_structured_model = MagicMock()
        mock_instance.with_structured_output.return_value = mock_structured_model

        # All 3 attempts fail
        mock_structured_model.invoke.side_effect = [
            ValueError("Bad JSON structure"),
            ValueError("Schema mismatch"),
            ValueError("Missing fields"),
        ]

        state: RefinementState = {
            "draft_issue_content": "Add DB persistence to logs.",
            "strict_mode": True,
            "allowed_domains": ["github.com"],
            "messages": [],
            "keywords": [],
            "search_queries": [],
            "search_results": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model_name": "google/gemini-2.5-flash",
            "status": "success",
            "proposed_options": [
                {
                    "choice_id": "option_1",
                    "name": "DB wrapper",
                    "description": "Complex DB wrapper",
                }
            ],
            "best_option": {},
            "all_grades": [],
        }

        with self.assertRaises(ValueError) as context:
            evaluate_grade_node(state)

        self.assertIn(
            "Critic evaluation failed to produce valid structured output after 3 attempts",
            str(context.exception),
        )

    @patch("planner.nodes.evaluate_grade.get_llm")
    def test_evaluate_grade_retry_loop_returns_none_raises(self, mock_get_llm):
        mock_instance = MagicMock()
        mock_get_llm.return_value = mock_instance

        mock_structured_model = MagicMock()
        mock_instance.with_structured_output.return_value = mock_structured_model

        # Returns raw dict with parsed = None for all 3 attempts
        mock_structured_model.invoke.return_value = {"parsed": None, "raw": MagicMock()}

        state: RefinementState = {
            "draft_issue_content": "Add DB persistence to logs.",
            "strict_mode": True,
            "allowed_domains": ["github.com"],
            "messages": [],
            "keywords": [],
            "search_queries": [],
            "search_results": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model_name": "google/gemini-2.5-flash",
            "status": "success",
            "proposed_options": [
                {
                    "choice_id": "option_1",
                    "name": "DB wrapper",
                    "description": "Complex DB wrapper",
                }
            ],
            "best_option": {},
            "all_grades": [],
        }

        with self.assertRaises(ValueError) as context:
            evaluate_grade_node(state)

        self.assertIn(
            "Critic evaluation failed to produce valid structured output after 3 attempts",
            str(context.exception),
        )
        self.assertIn(
            "Parsed value was not a CriticEvaluation instance",
            str(context.exception),
        )
