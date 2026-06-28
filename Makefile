.PHONY: verify test lint format-check

verify: lint format-check test

test:
	python -m pytest

lint:
	python -m ruff check planner tests

format-check:
	python -m ruff format --check planner tests
