UV ?= uv

.PHONY: setup api check format test test-live nomad-server nomad-agent nomad-up nomad-down test-nomad

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
	$(UV) run --locked --all-packages pytest -m "not live and not nomad"

test-live:
	$(UV) run --locked --all-packages pytest -m live

nomad-server:
	dev/nomad/cluster.sh server

nomad-agent: nomad-server
	dev/nomad/cluster.sh agent

nomad-up: nomad-agent

nomad-down:
	dev/nomad/cluster.sh down

test-nomad: nomad-up
	HARNESS_NOMAD_ADDR=http://127.0.0.1:14646 $(UV) run --locked --all-packages pytest -q -s -m nomad

.PHONY: worker-image
worker-image:
	dev/nomad/cluster.sh worker-image
