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

    args = parser.parse_args()

    if args.command == "refine":
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

                # 1. Resolve drafts directory path
                drafts_base = Path(config.github_workspace) / ".planner" / "drafts"
                repo_full_path = drafts_base / config.github_repository
                repo_short_path = drafts_base / Path(config.github_repository).name

                drafts_dir = (
                    repo_full_path if repo_full_path.exists() else repo_short_path
                )

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
