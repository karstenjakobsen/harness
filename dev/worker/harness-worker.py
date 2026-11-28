#!/usr/bin/env python3
"""Start one CLI session for the authenticated worker assignment."""

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

INSTRUCTION = (
    "Read your assignment through worker MCP, carry it out in the workspace, "
    "and submit the requested deliverable. Read the assigned skill revisions "
    "through worker MCP before starting. Use ordinary workspace tools as needed. "
    "The operator reviews your result and decides completion separately."
)
BRIEF_INSTRUCTION = (
    "Call get_work_brief through worker MCP, then report that you read it."
)
PROVIDER_KEYS = ("CODEX_API_KEY", "OPENAI_API_KEY", "KIRO_API_KEY")
KIRO_EFFORTS = {
    "claude-sonnet-4.6": {"low", "medium", "high", "max"},
    "claude-opus-4.6": {"low", "medium", "high", "max"},
    "claude-opus-4.7": {"low", "medium", "high", "xhigh", "max"},
    "claude-opus-4.8": {"low", "medium", "high", "xhigh", "max"},
}


def cli_environment(environment):
    auth = environment.get("HARNESS_WORKER_AUTH", "auth-json")
    engine = environment.get("HARNESS_WORKER_ENGINE", "codex")
    selected_key = {
        ("codex", "auth-json"): None,
        ("codex", "api-key"): "CODEX_API_KEY",
        ("kiro", "api-key"): "KIRO_API_KEY",
    }
    if (engine, auth) not in selected_key:
        raise ValueError("Select Codex api-key or auth-json, or Kiro api-key.")
    key = selected_key[engine, auth]
    if key and not environment.get(key, "").strip():
        raise ValueError(f"{key} is required for API-key authentication.")
    return {
        name: value
        for name, value in environment.items()
        if name not in PROVIDER_KEYS or name == key
    }


def command(attempt_id, environment):
    if environment.get("HARNESS_WORKER_ATTEMPT_ID") != attempt_id:
        raise ValueError("The attempt ID does not match the runtime assignment.")
    if not environment.get("HARNESS_WORKER_TOKEN"):
        raise ValueError("A worker session credential is required.")
    endpoint = environment.get("HARNESS_WORKER_MCP_URL", "")
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
    ):
        raise ValueError("A valid worker MCP endpoint is required.")
    engine = environment.get("HARNESS_WORKER_ENGINE", "codex")
    model = environment.get("HARNESS_WORKER_MODEL")
    effort = environment.get("HARNESS_WORKER_EFFORT")
    if bool(model) != bool(effort):
        raise ValueError("Supply both a model and a reasoning effort.")
    if engine == "kiro":
        if effort not in KIRO_EFFORTS.get(model, ()):
            raise ValueError("Kiro does not support this model and effort in Slice 14.")
        brief_only = environment.get("HARNESS_WORKER_BRIEF_ONLY") == "1"
        trusted = "@worker/get_work_brief"
        if not brief_only:
            trusted += ",@worker/list_skills,@worker/read_skill,@worker/submit_work_result,fs_write"
        return [
            "kiro-cli",
            "chat",
            "--v3",
            "--no-interactive",
            "--model",
            model,
            "--effort",
            effort,
            "--output-format",
            "stream-json",
            "--require-mcp-startup",
            "--trust-tools",
            trusted,
            BRIEF_INSTRUCTION if brief_only else INSTRUCTION,
        ]
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


def prepare_kiro(environment):
    # This config lives in the allocation's private CLI home, outside scratch.
    home = Path(environment["KIRO_HOME"])
    home.mkdir(mode=0o700, exist_ok=True)
    settings = home / "settings"
    settings.mkdir(mode=0o700, exist_ok=True)
    config = {
        "mcpServers": {
            "worker": {
                "url": environment["HARNESS_WORKER_MCP_URL"],
                "headers": {
                    "Authorization": f"Bearer {environment['HARNESS_WORKER_TOKEN']}"
                },
            },
        }
    }
    fd = os.open(settings / "mcp.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(config, output)


def cli_output(argv, environment):
    result = subprocess.run(
        argv, env=environment, capture_output=True, text=True, timeout=20, check=True
    )
    return result.stdout.strip()


def validate_codex_selection(environment):
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


def run_cli(argv, environment):
    secrets = [
        environment[name].encode()
        for name in (*PROVIDER_KEYS, "HARNESS_WORKER_TOKEN")
        if environment.get(name)
    ]
    with subprocess.Popen(
        argv, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ) as child:

        def relay(source, target):
            for line in source:
                for secret in secrets:
                    line = line.replace(secret, b"[redacted]")
                target.write(line)
                target.flush()

        def terminate(number, _frame):
            child.send_signal(number)

        for number in (signal.SIGINT, signal.SIGTERM):
            signal.signal(number, terminate)
        readers = [
            Thread(target=relay, args=(child.stdout, sys.stdout.buffer)),
            Thread(target=relay, args=(child.stderr, sys.stderr.buffer)),
        ]
        for reader in readers:
            reader.start()
        code = child.wait()
        for reader in readers:
            reader.join()
    return code if code >= 0 else 128 - code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    run = subcommands.add_parser("run")
    run.add_argument("--attempt-id", required=True)
    args = parser.parse_args()
    try:
        environment = cli_environment(os.environ)
        argv = command(args.attempt_id, environment)
        os.chdir("/workspace")
        if argv[0] == "kiro-cli":
            prepare_kiro(environment)
        elif environment.get("HARNESS_WORKER_MODEL"):
            validate_codex_selection(environment)
        if "HARNESS_WORKER_AUTH" in environment:
            version = cli_output([argv[0], "--version"], environment)
            print(
                json.dumps({"type": "harness.worker_cli", "version": version}),
                flush=True,
            )
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    return run_cli(argv, environment)


if __name__ == "__main__":
    sys.exit(main())
