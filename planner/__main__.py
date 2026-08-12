import argparse
import glob
import logging
import os
import sys
import warnings
from pathlib import Path

from planner.config import AppConfig
from planner.state import AgentState
from planner.refine_graph import graph
from scripts.telemetry import (
    orchestrator_phase,
)

# Suppress harmless Pydantic serialization warnings from OpenRouter custom tools mismatch
warnings.filterwarnings("ignore", message=".*PydanticSerializationUnexpectedValue.*")


def main():
    parser = argparse.ArgumentParser(
        description="agentic-planner-core CLI - Orchestrator for planning and issue refinement."
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # refine command
    refine_parser = subparsers.add_parser(
        "refine", help="Start the refinement process for draft issues."
    )
    refine_parser.add_argument(
        "--config",
        default="config/sources.toml",
        help="Path to sources.toml configuration",
    )

    # grill command
    grill_parser = subparsers.add_parser(
        "grill",
        help="Start the interactive PRD/ADR design session (grill-with-docs).",
    )
    grill_parser.add_argument(
        "--session-id",
        help="Explicit session ID to resume an existing session.",
    )

    # verify command
    verify_parser = subparsers.add_parser(
        "verify",
        help="Start the interactive learning verification session (wise-teacher).",
    )
    verify_parser.add_argument(
        "--session-id",
        help="Explicit session ID to resume an existing verify session.",
    )

    # draft command
    subparsers.add_parser(
        "draft",
        help="Generate draft issues from PRD centrally (draft-issues).",
    )

    # eval command
    eval_parser = subparsers.add_parser(
        "eval",
        help="Run the LLM-Judge regression evaluation suite against a gold standard.",
    )
    eval_parser.add_argument(
        "--judge",
        required=True,
        help="Judge type to evaluate (syntax_lint, test_coverage, architecture, "
        "security). evaluate_grade is a placeholder (ADR-0017).",
    )
    eval_parser.add_argument(
        "--model",
        help="OpenRouter model id overriding config/factory.json for this run.",
    )
    eval_parser.add_argument(
        "--fixtures-dir",
        default="tests/eval/fixtures",
        help="Directory holding the gold-standard fixtures.",
    )
    eval_parser.add_argument(
        "--results-json",
        default="results.json",
        help="Path to write the results.json artifact.",
    )

    args = parser.parse_args()

    if args.command in ["grill", "verify", "draft"]:
        from planner.cli_planning import run_grill, run_verify, run_draft

        config = AppConfig()
        if args.command == "grill":
            run_grill(config, session_id=args.session_id)
        elif args.command == "verify":
            run_verify(config, session_id=args.session_id)
        elif args.command == "draft":
            run_draft(config)
    elif args.command == "refine":
        from scripts.telemetry import (
            init_telemetry,
            start_orchestrator_loop,
            end_orchestrator_loop,
        )

        init_telemetry()
        start_orchestrator_loop()
        exit_code = 0
        try:
            with orchestrator_phase("initialize"):
                print(f"Loading configuration from {args.config}...")
                config = AppConfig(sources_toml_path=args.config)
                print("Configuration loaded successfully.")
                print(f"Target Repository: {config.github_repository}")
                print(f"Strict Mode: {config.sources.strict}")

                # 1. Resolve drafts directory path centrally within the planner core repository
                planner_core_root = Path(__file__).resolve().parents[1]
                drafts_base = planner_core_root / ".planner" / "drafts"

                repo_name = config.github_repository
                if repo_name and "/" in repo_name:
                    repo_name = repo_name.split("/")[-1]
                if not repo_name:
                    repo_name = Path(config.github_workspace).name

                drafts_dir = drafts_base / repo_name

                # Check for files
                draft_files = []
                if drafts_dir.exists():
                    draft_files = sorted(glob.glob(str(drafts_dir / "*.md")))

                print(f"Found {len(draft_files)} draft issues in {drafts_dir}")

                # 2. Format whitelisted domains / urls
                allowed_domains = []
                for domain in config.sources.domains:
                    if domain:
                        allowed_domains.append(domain.strip().lower())
                from urllib.parse import urlparse

                for url in config.sources.urls:
                    if url:
                        parsed = urlparse(url)
                        domain = parsed.netloc
                        if domain.startswith("www."):
                            domain = domain[4:]
                        if domain and domain not in allowed_domains:
                            allowed_domains.append(domain.strip().lower())

                # 3. Build initial state
                search_params = {
                    "engine": config.sources.search.engine,
                    "search_context_size": config.sources.search.search_context_size,
                    "max_results": config.sources.search.max_results,
                    "max_total_results": config.sources.search.max_total_results,
                    "excluded_domains": config.sources.search.excluded_domains,
                }

                initial_state: AgentState = {
                    "draft_issues": draft_files,
                    "current_issue_index": 0,
                    "strict_mode": config.sources.strict,
                    "allowed_domains": allowed_domains,
                    "search_params": search_params,
                    "status": "idle",
                    "succeeded_drafts": [],
                    "failed_drafts": [],
                }

                # Abort at startup if strict mode is enabled but whitelist is empty
                if config.sources.strict and not allowed_domains:
                    raise ValueError(
                        "Strict-mode is enabled (strict: true), but allowed_domains is empty. "
                        "At least one source must be defined."
                    )

                # 4. Invoke graph
                if draft_files:
                    session = config.get_github_session()

                    print("Checking GitHub API rate limit quota...")
                    response = session.get("https://api.github.com/rate_limit")
                    response.raise_for_status()

                    remaining = response.json()["resources"]["core"]["remaining"]
                    required = max(50, len(draft_files) * 3)
                    print(
                        f"GitHub API quota remaining: {remaining} (required: {required})"
                    )

                    if remaining < required:
                        raise ValueError(
                            f"Insufficient GitHub API rate limit quota. "
                            f"Remaining: {remaining}, required: {required}."
                        )

                    print("Starting refinement process...")
                    # Enable INFO-level logging so node logger.info() calls appear on console
                    logging.basicConfig(
                        level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
                        datefmt="%H:%M:%S",
                    )
                    from planner.cli_planning import ConsoleLoggingHandler

                    handler = ConsoleLoggingHandler()
                    result = graph.invoke(
                        initial_state, config={"callbacks": [handler]}
                    )
                    # Derive the terminal batch status from the accumulated
                    # per-draft outcomes rather than an overwriteable ``status``
                    # field, so a partial run is reported honestly (#56).
                    failed_drafts = result.get("failed_drafts", [])
                    succeeded_drafts = result.get("succeeded_drafts", [])
                    if failed_drafts:
                        exit_code = 1
                        print(
                            f"Refinement process finished with status: partial "
                            f"({len(succeeded_drafts)} succeeded, "
                            f"{len(failed_drafts)} failed/skipped)"
                        )
                        print("Failed/skipped drafts (left on disk for rerun):")
                        for draft_path in failed_drafts:
                            print(f"  - {draft_path}")
                    else:
                        print(
                            f"Refinement process finished with status: success "
                            f"({len(succeeded_drafts)} draft(s) published)"
                        )
                else:
                    print("No draft issues found. Nothing to refine.")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            exit_code = 1
        finally:
            from scripts.telemetry import end_orchestrator_loop

            end_orchestrator_loop(exit_code=exit_code)

        if exit_code != 0:
            sys.exit(exit_code)
    elif args.command == "eval":
        from scripts.telemetry import (
            init_telemetry,
            start_orchestrator_loop,
            end_orchestrator_loop,
        )
        from planner.eval.runner import run_eval
        from planner.eval.report import to_markdown, write_results_json, write_summary

        init_telemetry()
        start_orchestrator_loop()
        exit_code = 0
        try:
            workspace_dir = os.environ.get("GITHUB_WORKSPACE")
            result = run_eval(
                judge_type=args.judge,
                model=args.model,
                fixtures_dir=args.fixtures_dir,
                workspace_dir=workspace_dir,
            )
            json_path = write_results_json(result, path=args.results_json)
            summary_path = write_summary(result)
            print(to_markdown(result))
            if summary_path:
                print(f"\nMarkdown summary appended to {summary_path}")
            print(f"results.json written to {json_path}")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            exit_code = 1
        finally:
            end_orchestrator_loop(exit_code=exit_code)

        if exit_code != 0:
            sys.exit(exit_code)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
