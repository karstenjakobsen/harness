"""Shared setup and process handling for the worker launchers."""

import argparse
import json
import os
import signal
import subprocess
import sys
from threading import Thread
from urllib.parse import urlsplit

INSTRUCTION = (
    "Read your assignment through worker MCP, carry it out in the workspace, "
    "and submit the requested deliverable. Read the assigned skill revisions "
    "through worker MCP before starting. Use ordinary workspace tools as needed. "
    "The operator reviews your result and decides completion separately."
)
PROVIDER_KEYS = ("CODEX_API_KEY", "OPENAI_API_KEY", "KIRO_API_KEY")


def provider_environment(environment, worker, default_auth, auth_keys):
    if environment.get("HARNESS_WORKER_ENGINE", worker) != worker:
        raise ValueError(f"This worker image runs {worker}.")
    auth = environment.get("HARNESS_WORKER_AUTH", default_auth)
    if auth not in auth_keys:
        raise ValueError(f"{worker} supports these auth modes: {', '.join(auth_keys)}.")
    key = auth_keys[auth]
    if key and not environment.get(key, "").strip():
        raise ValueError(f"{key} is required for API-key authentication.")
    return {
        name: value
        for name, value in environment.items()
        if name not in PROVIDER_KEYS or name == key
    }


def assignment_endpoint(attempt_id, environment):
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
    return endpoint


def model_selection(environment):
    model = environment.get("HARNESS_WORKER_MODEL")
    effort = environment.get("HARNESS_WORKER_EFFORT")
    if bool(model) != bool(effort):
        raise ValueError("Supply both a model and a reasoning effort.")
    return model, effort


def cli_output(argv, environment):
    result = subprocess.run(
        argv, env=environment, capture_output=True, text=True, timeout=20, check=True
    )
    return result.stdout.strip()


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


def main(description, cli_environment, command, prepare):
    parser = argparse.ArgumentParser(description=description)
    subcommands = parser.add_subparsers(dest="command", required=True)
    run = subcommands.add_parser("run")
    run.add_argument("--attempt-id", required=True)
    args = parser.parse_args()
    try:
        environment = cli_environment(os.environ)
        argv = command(args.attempt_id, environment)
        os.chdir("/workspace")
        prepare(environment)
        if "HARNESS_WORKER_AUTH" in environment:
            version = cli_output([argv[0], "--version"], environment)
            print(
                json.dumps({"type": "harness.worker_cli", "version": version}),
                flush=True,
            )
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    return run_cli(argv, environment)
