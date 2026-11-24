SHELL := /bin/sh
.DEFAULT_GOAL := help
export UV_CACHE_DIR ?= $(CURDIR)/.uv-cache
export WORKER_UID ?= $(shell id -u)
WORKER ?= codex
# Pass user-supplied values as quoted shell variables in recipes.
export WORKER RUN_ID
OPERATOR = docker compose run --rm --no-deps -T operator

.PHONY: help setup lint fmt test build up run get smoke down
help:
	@echo 'make run                     Build and run the signed-in Codex worker'
	@echo 'make get RUN_ID=<uuid>       Retrieve the persisted trace'
	@echo 'make smoke                   Exercise real containers with three fixture workers'
	@echo 'make setup lint test         Set up Python 3.14 and check the code'
	@echo 'make down                    Stop Compose and keep run evidence'

setup:
	uv sync --locked --python 3.14

lint: setup
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

fmt: setup
	.venv/bin/ruff format .

test: setup
	.venv/bin/python -m unittest discover -s tests -v

build:
	docker compose build harness worker

up: build
	docker compose up -d --wait harness

run: up
	$(OPERATOR) run --worker "$$WORKER"

get:
	@test -n "$$RUN_ID" || { echo 'Usage: make get RUN_ID=<uuid>' >&2; exit 2; }
	@docker compose up -d --no-recreate --wait harness >&2
	@$(OPERATOR) get "$$RUN_ID"

smoke: up setup
	.venv/bin/python tests/smoke.py

down:
	docker compose down
