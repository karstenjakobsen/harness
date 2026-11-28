"""Attempt-scoped worker tools over authenticated Streamable HTTP."""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ListToolsRequest, Tool, ToolAnnotations
from pydantic import Field, ValidationError
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from harness_api import (
    SkillRevision,
    SkillSummary,
    WorkAPI,
    WorkArtifact,
    WorkAuthorizationError,
    WorkBrief,
)

PositiveInteger = Annotated[int, Field(strict=True, gt=0, lt=2**63)]
StrictString = Annotated[str, Field(strict=True)]


class SkillList(TypedDict):
    skills: list[SkillSummary]


@dataclass(frozen=True)
class _WorkerSession:
    attempt_id: str
    credential: str


class _WorkerAuthentication:
    """Bind each HTTP request to authority established by the public model."""

    def __init__(
        self,
        app: ASGIApp,
        api: WorkAPI,
        session: ContextVar[_WorkerSession | None],
    ) -> None:
        self.app = app
        self.api = api
        self.session = session

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope).getlist("authorization")
        scheme, _, credential = (
            headers[0].partition(" ") if len(headers) == 1 else ("", "", "")
        )
        try:
            if scheme.lower() != "bearer" or not credential or " " in credential:
                raise WorkAuthorizationError("A worker credential is required.")
            attempt = self.api.resolve_attempt(credential)
        except WorkAuthorizationError:
            response = JSONResponse(
                {"error": "Worker authentication required."},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="harness-worker"'},
            )
            await response(scope, receive, send)
            return
        token = self.session.set(_WorkerSession(attempt["id"], credential))
        try:
            await self.app(scope, receive, send)
        finally:
            self.session.reset(token)


class _WorkerServer(FastMCP):
    def __init__(self, api: WorkAPI, allowed_hosts: list[str] | None) -> None:
        super().__init__(
            "harness_worker",
            stateless_http=True,
            json_response=True,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=allowed_hosts
                if allowed_hosts is not None
                else ["127.0.0.1:*", "localhost:*", "[::1]:*"],
            ),
        )
        self.api = api
        self.session: ContextVar[_WorkerSession | None] = ContextVar(
            "worker_session", default=None
        )
        dispatch = self._mcp_server.request_handlers[ListToolsRequest]

        async def record_discovery(request):
            # The SDK also refreshes its tool cache through this handler with
            # None before a direct invocation. Only real discovery is audited.
            if request is not None:
                session = self.authenticated_session()
                self.api.authorize_attempt(
                    session.attempt_id, session.credential, tool="tools/list"
                )
            return await dispatch(request)

        self._mcp_server.request_handlers[ListToolsRequest] = record_discovery

    def authenticated_session(self) -> _WorkerSession:
        session = self.session.get()
        if session is None:
            raise ToolError("An authenticated worker request is required.")
        return session

    async def list_tools(self) -> list[Tool]:
        self.authenticated_session()
        tools = await super().list_tools()
        for tool in tools:
            tool.inputSchema["additionalProperties"] = False
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        session = self.authenticated_session()
        try:
            tool = next(
                (tool for tool in await super().list_tools() if tool.name == name),
                None,
            )
            if tool is None:
                raise ToolError("This tool is unavailable to workers.")
            extras = arguments.keys() - tool.inputSchema["properties"].keys()
            if extras:
                raise ToolError("Unexpected tool arguments.")
            return await super().call_tool(name, arguments)
        except ToolError as error:
            # Domain operations audit their own outcomes. The adapter records only
            # requests rejected before a model operation, including unknown tools.
            if error.__cause__ is None or isinstance(error.__cause__, ValidationError):
                self.api.record_worker_failure(
                    session.attempt_id,
                    session.credential,
                    name if tool is not None else "unknown_tool",
                )
            raise


def create_worker_app(
    api: WorkAPI, *, allowed_hosts: list[str] | None = None
) -> Starlette:
    """Create a worker-only MCP app using the caller's configured workspace.

    Every request supplies its attempt-bound Bearer credential. Stateless HTTP
    avoids sharing MCP session state when different attempts use one endpoint.
    Non-loopback deployments supply the reachable endpoint's allowed host names.
    """
    server = _WorkerServer(api, allowed_hosts)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_work_brief() -> WorkBrief:
        """Read your immutable assignment, goal revision and workspace input."""
        session = server.authenticated_session()
        return api.get_work_brief(session.attempt_id, session.credential)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def list_skills() -> SkillList:
        """Discover permitted skills and choose which guidance is useful.

        Delegated work can use the owner's current catalog. Explicit owner
        assignments expose only their pinned revisions. Brief hints are optional.
        """
        session = server.authenticated_session()
        return {"skills": api.list_skills(session.attempt_id, session.credential)}

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def read_skill(id: StrictString, revision: PositiveInteger) -> SkillRevision:
        """Read one permitted skill revision you choose to use."""
        session = server.authenticated_session()
        return api.read_skill(session.attempt_id, session.credential, id, revision)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True))
    def submit_work_result(relative_path: StrictString) -> WorkArtifact:
        """Save a file from your workspace for review and return its artifact ID.

        The first save is authoritative. Retrying its relative path returns the
        original artifact, including after scratch cleanup.
        """
        session = server.authenticated_session()
        return api.submit_work_result(
            session.attempt_id, session.credential, relative_path
        )

    app = server.streamable_http_app()
    app.add_middleware(_WorkerAuthentication, api=api, session=server.session)
    return app


def serve_worker_mcp(
    api: WorkAPI,
    *,
    host: str = "127.0.0.1",
    port: int = 8001,
    allowed_hosts: list[str] | None = None,
) -> None:
    """Serve the configured workspace's worker MCP endpoint at ``/mcp``."""
    import uvicorn

    uvicorn.run(
        create_worker_app(api, allowed_hosts=allowed_hosts), host=host, port=port
    )
