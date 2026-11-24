import asyncio
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route

from harness.engine import Engine
from harness.evidence import TASK, Run, Worker


def create_app(root: Path = Path("/data"), key_file: Path = Path("/operator/token")):
    root.mkdir(parents=True, exist_ok=True)
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(32))
        key_file.chmod(0o400)
    key = key_file.read_text().strip()
    engine = Engine(root, key)
    security = TransportSecuritySettings(
        allowed_hosts=["harness:8000", "127.0.0.1:*", "localhost:*"],
    )
    settings = {"stateless_http": True, "json_response": True, "transport_security": security}
    operator = FastMCP("Harness operator", **settings)
    worker = FastMCP("Run workspace", **settings)

    @operator.tool()
    async def start_run(task: str = TASK, worker: Worker = "codex") -> dict:
        """Submit the fixed hello-file task and return its lookup ID immediately."""
        if task != TASK:
            raise ValueError("This proof of concept accepts only the fixed hello-file task")
        return {"run_id": engine.submit(worker)}

    @operator.tool()
    async def get_run(run_id: str, include_trace: bool = True) -> dict:
        """Look up a run's launch, tool calls, worker output, exit and verification."""
        run = Run(root, run_id)
        if not run.record.exists():
            raise ValueError("Unknown run ID")
        return run.read(include_trace)

    @worker.tool()
    async def write_file(
        ctx: Context, path: str, content: Annotated[str, Field(max_length=4096)]
    ) -> dict:
        """Write UTF-8 content to result.txt in this run's workspace."""
        return engine.active[ctx.request_context.request.state.token].file_tool(
            "write_file", path, content
        )

    @worker.tool()
    async def read_file(ctx: Context, path: str) -> dict:
        """Read result.txt from this run's workspace."""
        return engine.active[ctx.request_context.request.state.token].file_tool("read_file", path)

    def protected(mcp: FastMCP):
        app = mcp.streamable_http_app()

        async def route(scope, receive, send):
            scheme, _, token = Headers(scope=scope).get("authorization", "").partition(" ")
            allowed = (
                secrets.compare_digest(token.encode(), key.encode())
                if mcp is operator
                else (token in engine.active)
            )
            if scheme.lower() != "bearer" or not allowed:
                await PlainTextResponse("Unauthorized", status_code=401)(scope, receive, send)
                return
            scope.setdefault("state", {})["token"] = token
            await app(scope, receive, send)

        return route

    @asynccontextmanager
    async def lifespan(_app):
        async with operator.session_manager.run(), worker.session_manager.run():
            engine.recover()
            try:
                yield
            finally:
                jobs = list(engine.jobs)
                for job in jobs:
                    job.cancel()
                await asyncio.gather(*jobs, return_exceptions=True)
                engine.docker.close()

    async def health(_request):
        return PlainTextResponse("ready")

    return Starlette(
        routes=[
            Route("/health", health),
            Mount("/operator", app=protected(operator)),
            Mount("/worker", app=protected(worker)),
        ],
        lifespan=lifespan,
    )
