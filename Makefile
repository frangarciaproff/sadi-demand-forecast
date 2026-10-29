.PHONY: install lint format types test check requirements image

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

requirements:
	uv export --frozen --no-dev --no-emit-project --format requirements-txt -o infra/forecaster/requirements.txt

image: requirements
	docker build --platform linux/amd64 --provenance=false -t sadi-forecaster .
