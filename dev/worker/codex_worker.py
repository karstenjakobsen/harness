#!/usr/bin/env python3
"""Start one Codex session for the authenticated worker assignment."""

import json
import sys

from worker_runtime import (
    INSTRUCTION,
    assignment_endpoint,
    cli_output,
    main,
    model_selection,
    provider_environment,
)


def cli_environment(environment):
    return provider_environment(
        environment,
        "codex",
        "auth-json",
        {"api-key": "CODEX_API_KEY", "auth-json": None},
    )


def command(attempt_id, environment):
    endpoint = assignment_endpoint(attempt_id, environment)
    model, effort = model_selection(environment)
    selection = (
        ["--model", model, "-c", f"model_reasoning_effort={json.dumps(effort)}"]
        if model
        else []
    )
    return [
        "codex",
        "--ask-for-approval",
        "never",
        "exec",
        "--json",
        "--sandbox",
        "danger-full-access",
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        *selection,
        "-C",
        "/workspace",
        "-c",
        f"mcp_servers.worker.url={json.dumps(endpoint)}",
        "-c",
        'mcp_servers.worker.bearer_token_env_var="HARNESS_WORKER_TOKEN"',
        "-c",
        "mcp_servers.worker.required=true",
        "-c",
        'mcp_servers.worker.tools.submit_work_result.approval_mode="approve"',
        INSTRUCTION,
    ]


def prepare_codex(environment):
    if not environment.get("HARNESS_WORKER_MODEL"):
        return
    model = environment["HARNESS_WORKER_MODEL"]
    effort = environment["HARNESS_WORKER_EFFORT"]
    catalog = json.loads(
        cli_output(["codex", "debug", "models", "--bundled"], environment)
    )
    if not any(
        entry["slug"] == model
        and any(
            level["effort"] == effort for level in entry["supported_reasoning_levels"]
        )
        for entry in catalog["models"]
    ):
        raise ValueError(
            "The bundled Codex catalog does not support this model and effort."
        )


if __name__ == "__main__":
    sys.exit(main(__doc__, cli_environment, command, prepare_codex))
