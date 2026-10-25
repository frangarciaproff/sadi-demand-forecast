.PHONY: install lint format types test check

install:
	uv sync

lint:
	uv run ruff check .

format:
	uv run ruff format .

types:
	uv run mypy

test:
	uv run pytest -q

check: lint types test
	uv run ruff format --check .
