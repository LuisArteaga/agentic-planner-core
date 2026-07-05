import argparse
import glob
import sys
from pathlib import Path
from planner.config import AppConfig
from planner.refine_graph import graph
from scripts.telemetry import (
    end_orchestrator_loop,
    init_telemetry,
    orchestrator_phase,
    start_orchestrator_loop,
)


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
        default="config/sources.yaml",
        help="Path to sources.yaml configuration",
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
    subparsers.add_parser(
        "verify",
        help="Start the interactive learning verification session (wise-teacher).",
    )

    # draft command
    subparsers.add_parser(
        "draft",
        help="Generate draft issues from PRD centrally (draft-issues).",
    )

    args = parser.parse_args()

    if args.command in ["grill", "verify", "draft"]:
        from planner.cli_planning import run_grill, run_verify, run_draft

        config = AppConfig()
        if args.command == "grill":
            run_grill(config, session_id=args.session_id)
        elif args.command == "verify":
            run_verify(config)
        elif args.command == "draft":
            run_draft(config)
    elif args.command == "refine":
        init_telemetry()
        start_orchestrator_loop()
        exit_code = 0
        try:
            with orchestrator_phase("initialize"):
                print(f"Loading configuration from {args.config}...")
                config = AppConfig(sources_yaml_path=args.config)
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

                # 2. Format whitelisted domains / repositories
                allowed_domains = []
                for domain in config.sources.domains:
                    if domain:
                        allowed_domains.append(domain.strip().lower())
                for repo in config.sources.repositories:
                    if repo:
                        allowed_domains.append(f"github.com/{repo.strip().lower()}")

                # 3. Build initial state
                initial_state = {
                    "draft_issues": draft_files,
                    "current_issue_index": 0,
                    "strict_mode": config.sources.strict,
                    "allowed_domains": allowed_domains,
                    "status": "idle",
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
                    result = graph.invoke(initial_state)
                    print(
                        f"Refinement process finished with status: {result.get('status')}"
                    )
                else:
                    print("No draft issues found. Nothing to refine.")
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
