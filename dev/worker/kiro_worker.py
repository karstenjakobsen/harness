#!/usr/bin/env python3
"""Start one Kiro session for the authenticated worker assignment."""

import json
import os
import selectors
import socket
import socketserver
import sys
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

from worker_runtime import (
    INSTRUCTION,
    assignment_endpoint,
    main,
    model_selection,
    provider_environment,
)

BRIEF_INSTRUCTION = (
    "Call get_work_brief through worker MCP, then report that you read it."
)
KIRO_EFFORTS = {
    "claude-sonnet-4.6": {"low", "medium", "high", "max"},
    "claude-opus-4.6": {"low", "medium", "high", "max"},
    "claude-opus-4.7": {"low", "medium", "high", "xhigh", "max"},
    "claude-opus-4.8": {"low", "medium", "high", "xhigh", "max"},
}


def cli_environment(environment):
    return provider_environment(environment, "kiro", None, {"api-key": "KIRO_API_KEY"})


def command(attempt_id, environment):
    assignment_endpoint(attempt_id, environment)
    model, effort = model_selection(environment)
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


class MCPRelay(socketserver.ThreadingTCPServer):
    daemon_threads = True

    def __init__(self, destination):
        self.destination = destination
        super().__init__(("127.0.0.1", 0), MCPConnection)


class MCPConnection(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            with socket.create_connection(
                self.server.destination, timeout=5
            ) as upstream:
                upstream.settimeout(None)
                with selectors.DefaultSelector() as streams:
                    streams.register(self.request, selectors.EVENT_READ, upstream)
                    streams.register(upstream, selectors.EVENT_READ, self.request)
                    while streams.get_map():
                        for event, _ in streams.select():
                            data = event.fileobj.recv(64 * 1024)
                            if data:
                                event.data.sendall(data)
                            else:
                                streams.unregister(event.fileobj)
                                event.data.shutdown(socket.SHUT_WR)
        except OSError:
            return


def kiro_mcp_endpoint(environment):
    endpoint = environment["HARNESS_WORKER_MCP_URL"]
    url = urlsplit(endpoint)
    if url.scheme != "http" or url.hostname != "host.docker.internal":
        return endpoint
    # Docker Desktop's host alias reaches the dev MCP service from the worker.
    # Kiro accepts plain HTTP only on loopback, so listen inside the worker.
    relay = MCPRelay((url.hostname, url.port or 80))
    Thread(target=relay.serve_forever, daemon=True).start()
    return url._replace(netloc=f"127.0.0.1:{relay.server_address[1]}").geturl()


def prepare_kiro(environment):
    # This config lives in the allocation's private CLI home, outside scratch.
    home = Path(environment["KIRO_HOME"])
    home.mkdir(mode=0o700, exist_ok=True)
    settings = home / "settings"
    settings.mkdir(mode=0o700, exist_ok=True)
    config = {
        "mcpServers": {
            "worker": {
                "url": kiro_mcp_endpoint(environment),
                "headers": {
                    "Authorization": f"Bearer {environment['HARNESS_WORKER_TOKEN']}"
                },
            },
        }
    }
    fd = os.open(settings / "mcp.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(config, output)


if __name__ == "__main__":
    sys.exit(main(__doc__, cli_environment, command, prepare_kiro))
