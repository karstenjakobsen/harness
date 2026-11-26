"""Worker-only MCP endpoint and dispatcher for one trusted development workspace."""

import asyncio
import logging
from argparse import ArgumentParser
from contextlib import asynccontextmanager
from os import environ
from pathlib import Path
from threading import Event, Thread

import jwt
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Tool, ToolAnnotations
from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse

from harness_api import GoalAPI, WorkerNomadBackend, WorkFixture, WorkTextFile

LOG = logging.getLogger(__name__)


def verify_identity(token, keys):
    claims = jwt.decode(
        token,
        keys.get_signing_key_from_jwt(token).key,
        algorithms=["RS256"],
        audience="harness-worker",
        options={
            "require": [
                "exp",
                "nomad_namespace",
                "nomad_task",
                "nomad_job_id",
                "nomad_allocation_id",
            ]
        },
    )
    if claims["nomad_namespace"] != "default" or claims["nomad_task"] != "workload":
        raise jwt.InvalidTokenError("Unexpected workload identity")
    return claims["nomad_job_id"], claims["nomad_allocation_id"]


def tool(name, description, properties):
    return Tool(
        name=name,
        description=description,
        annotations=ToolAnnotations(
            readOnlyHint=name != "submit_work_result",
            idempotentHint=True,
            destructiveHint=False,
        ),
        inputSchema={
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    )


class WorkerServer(FastMCP):
    def __init__(self, work, host, port):
        super().__init__(
            "harness_worker",
            host=host,
            port=port,
            stateless_http=True,
            json_response=True,
            max_request_body_size=131072,
            transport_security=TransportSecuritySettings(
                allowed_hosts=[f"{host}:{port}"]
            ),
        )
        self.work = work

    def binding(self):
        request = self.get_context().request_context.request
        if request is None:
            raise ToolError("A worker HTTP request is required.")
        return request.scope["worker_binding"]

    async def list_tools(self):
        kind = await asyncio.to_thread(self.work.worker_result_type, *self.binding())
        if kind is None:
            return []
        schema = (
            WorkTextFile if kind == "text_file" else WorkFixture
        ).model_json_schema()
        definitions = schema.pop("$defs", {})
        submission = tool(
            "submit_work_result",
            "Submit the deliverable for this attempt.",
            {kind: schema},
        )
        submission.inputSchema["$defs"] = definitions
        return [
            tool("get_work_brief", "Read the brief and pinned goal definition.", {}),
            tool(
                "list_skills", "List the skill revisions assigned to this attempt.", {}
            ),
            tool(
                "read_skill",
                "Read the assigned instructions at this exact revision.",
                {"id": {"type": "string"}, "revision": {"type": "integer"}},
            ),
            submission,
        ]

    async def call_tool(self, name, arguments):
        return await asyncio.to_thread(
            self.work.worker_call, *self.binding(), name, arguments
        )


def create_worker_app(api, backend, host, port, verify):
    server = WorkerServer(api.work, host, port)
    transport = server.streamable_http_app()
    stopped = Event()

    def watch():
        while not stopped.is_set():
            try:
                for attempt in api.work.list_outstanding_attempt_ids():
                    if stopped.is_set():
                        break
                    api.work.dispatch(attempt, backend)
            except Exception:
                LOG.exception("Could not reconcile workspace attempts")
            stopped.wait(0.5)

    @asynccontextmanager
    async def lifespan(app):
        thread = Thread(target=watch, name="worker-dispatch", daemon=True)
        thread.start()
        try:
            async with server.session_manager.run():
                yield
        finally:
            stopped.set()
            await asyncio.to_thread(thread.join)

    transport.router.lifespan_context = lifespan

    async def app(scope, receive, send):
        if scope["type"] == "http":
            scheme, _, token = (
                Headers(scope=scope).get("authorization", "").partition(" ")
            )
            try:
                if scheme.lower() != "bearer" or not token:
                    raise jwt.InvalidTokenError()
                scope["worker_binding"] = await asyncio.to_thread(verify, token)
                await asyncio.to_thread(
                    api.work.refresh_worker, scope["worker_binding"][0], backend
                )
            except jwt.PyJWTError:
                await PlainTextResponse(
                    "Worker authentication required.", status_code=401
                )(scope, receive, send)
                return
        await transport(scope, receive, send)

    return app


def main():
    parser = ArgumentParser(
        description="Serve and dispatch workers for the current workspace."
    )
    parser.add_argument("--image", required=True)
    parser.add_argument(
        "--host",
        required=True,
        help="Local IPv4 address reachable from workload containers",
    )
    parser.add_argument("--port", type=int, default=14660)
    args = parser.parse_args()
    login = Path(environ.get("CODEX_HOME", Path.home() / ".codex")) / "auth.json"
    if not login.is_file():
        parser.error(
            "Sign in to Codex on the local Nomad client host with file-backed credential storage before starting workers."
        )
    address = environ.get("HARNESS_NOMAD_ADDR", "http://127.0.0.1:14646")
    endpoint = f"http://{args.host}:{args.port}/mcp"
    backend = WorkerNomadBackend(address, args.image, endpoint)
    api = GoalAPI(local_owner=False)
    api.work.configure_launcher(args.image, address, endpoint)
    keys = jwt.PyJWKClient(f"{address.rstrip('/')}/.well-known/jwks.json", timeout=3)
    app = create_worker_app(
        api, backend, args.host, args.port, lambda token: verify_identity(token, keys)
    )
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
