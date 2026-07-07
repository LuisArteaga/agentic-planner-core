.PHONY: verify test lint format-check type-check

verify: lint format-check type-check test

test:
	python -m pytest

lint:
	python -m ruff check planner tests scripts

format-check:
	python -m ruff format --check planner tests scripts


type-check:
	python -m mypy planner tests scripts
