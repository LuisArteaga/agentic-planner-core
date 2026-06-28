import argparse
import sys
from planner.config import AppConfig


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
        from scripts.telemetry import (
            init_telemetry,
            start_orchestrator_loop,
            end_orchestrator_loop,
        )

        init_telemetry()
        start_orchestrator_loop()
        exit_code = 0
        try:
            print(f"Loading configuration from {args.config}...")
            config = AppConfig(sources_yaml_path=args.config)
            print("Configuration loaded successfully.")
            print(f"Target Repository: {config.github_repository}")
            print(f"Strict Mode: {config.sources.strict}")
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
