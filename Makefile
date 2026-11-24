UV ?= uv

.PHONY: setup api check format test

setup:
	$(UV) sync --locked --all-packages

api:
	$(UV) run --locked --package harness-api uvicorn harness_api.app:app --host 127.0.0.1 --port 8000

check:
	$(UV) run --locked ruff check .
	$(UV) run --locked ruff format --check .

format:
	$(UV) run --locked ruff format .

test:
	$(UV) run --locked --all-packages pytest
