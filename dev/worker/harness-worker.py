#!/usr/bin/env python3
"""Start one ordinary Codex session for the authenticated worker assignment."""

import argparse
import json
import os
from urllib.parse import urlsplit

INSTRUCTION = (
    "Read your assignment through worker MCP, carry it out in the workspace, "
    "and submit the requested deliverable. Read the assigned skill revisions "
    "through worker MCP before starting. Use ordinary workspace tools as needed. "
    "The operator reviews your result and decides completion separately."
)


def command(attempt_id, environment):
    if environment.get("HARNESS_WORKER_ATTEMPT_ID") != attempt_id:
        raise ValueError("The attempt ID does not match the runtime assignment.")
    if not environment.get("HARNESS_WORKER_TOKEN"):
        raise ValueError("A worker session credential is required.")
    endpoint = environment.get("HARNESS_WORKER_MCP_URL", "")
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ValueError("A valid worker MCP endpoint is required.")
    return [
        "codex",
        "--ask-for-approval",
        "never",
        "exec",
        "--json",
        "--sandbox",
        "workspace-write",
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    run = subcommands.add_parser("run")
    run.add_argument("--attempt-id", required=True)
    args = parser.parse_args()
    try:
        argv = command(args.attempt_id, os.environ)
    except ValueError as error:
        parser.error(str(error))
    os.chdir("/workspace")
    os.execvp(argv[0], argv)


if __name__ == "__main__":
    main()
