from argparse import ArgumentParser
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict, cast, get_args

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import (
    CallToolRequest,
    CallToolResult,
    ServerResult,
    Tool,
    ToolAnnotations,
)
from pydantic import Field, ValidationError

from harness_api import (
    CallReference,
    DecisionReference,
    DelegatedCompletion,
    GoalAPI,
    GoalConflictError,
    GoalNotFoundError,
    GoalProgress,
    GoalResultReference,
    GoalStatus,
    GoalSummary,
    GoalTree,
    GoalValidationError,
    HarnessTool,
    RunNotFoundError,
    WorkspaceStorageError,
)

PositiveInteger = Annotated[int, Field(strict=True, gt=0, lt=2**63)]
HARNESS_TOOLS = get_args(HarnessTool.__value__)


class GoalList(TypedDict):
    goals: list[GoalSummary]


@dataclass
class _Invocation:
    call: CallReference
    error_outcome: Literal["denied", "failed"] = "failed"


def _positive_id(value: object) -> int | None:
    return value if type(value) is int and 0 < value < 2**63 else None


def _decision_reference(decision: dict[str, Any] | None) -> DecisionReference | None:
    if decision is None:
        return None
    return DecisionReference(
        event_id=decision["event_id"],
        evidence_ids=decision["evidence_ids"],
        statement_evidence_id=decision.get("statement_evidence_id"),
    )


def _result_references(
    tool: HarnessTool, result: dict[str, Any]
) -> list[GoalResultReference]:
    if tool in ("list_goals", "get_goal_tree"):
        return [
            GoalResultReference(
                goal_id=goal["id"],
                revision=goal["revision"],
                status=goal["status"],
                observation_ids=[],
                decision=_decision_reference(goal.get("completion")),
            )
            for goal in result["goals"]
        ]
    if tool == "get_goal_progress":
        return [
            GoalResultReference(
                goal_id=result["goal_id"],
                revision=result["revision"],
                status=result["status"],
                observation_ids=[
                    record["evidence_id"] for record in result["evidence"]
                ],
                decision=None,
            )
        ]
    return [
        GoalResultReference(
            goal_id=result["goal_id"],
            revision=result["revision"],
            status=None,
            observation_ids=[],
            decision=_decision_reference(result),
        )
    ]


class HarnessServer(FastMCP):
    def __init__(self, api: GoalAPI, run_id: int | None) -> None:
        super().__init__("harness_mcp")
        self._invocation: ContextVar[_Invocation | None] = ContextVar(
            "invocation", default=None
        )
        if run_id is None:
            return
        # Wrap FastMCP's protocol handler so both input failures and the validated
        # response are captured before the server sends the result to its transport.
        dispatch = self._mcp_server.request_handlers[CallToolRequest]

        async def record_call(request: CallToolRequest) -> ServerResult:
            if request.params.name not in HARNESS_TOOLS:
                return await dispatch(request)
            tool = cast(HarnessTool, request.params.name)
            arguments = request.params.arguments or {}
            revision_field = (
                "expected_revision" if tool == "complete_goal" else "revision"
            )
            call = api.start_tool_call(
                run_id,
                tool,
                target_goal_id=_positive_id(arguments.get("goal_id"))
                if tool != "list_goals"
                else None,
                target_revision=_positive_id(arguments.get(revision_field))
                if tool in ("complete_goal", "get_goal_progress")
                else None,
            )
            invocation = _Invocation(call)
            token = self._invocation.set(invocation)
            try:
                response = await dispatch(request)
            finally:
                self._invocation.reset(token)
            result = response.root
            assert isinstance(result, CallToolResult)
            if result.isError:
                api.finish_tool_call(call, invocation.error_outcome)
            else:
                assert result.structuredContent is not None
                api.finish_tool_call(
                    call,
                    "returned",
                    returned_goals=_result_references(tool, result.structuredContent),
                )
            return response

        self._mcp_server.request_handlers[CallToolRequest] = record_call

    async def list_tools(self) -> list[Tool]:
        tools = await super().list_tools()
        for tool in tools:
            if tool.name == "complete_goal":
                tool.inputSchema["additionalProperties"] = False
        return tools

    async def call_tool(self, name: str, arguments: dict[str, object]):
        # FastMCP's default argument model ignores unknown fields.
        try:
            if name == "complete_goal":
                tool = next(
                    (tool for tool in await self.list_tools() if tool.name == name),
                    None,
                )
                if tool is None:
                    raise ToolError("Completion is unavailable in this session.")
                extras = arguments.keys() - tool.inputSchema["properties"].keys()
                if extras:
                    raise ToolError(
                        f"Unexpected completion fields: {', '.join(sorted(extras))}"
                    )
            return await super().call_tool(name, arguments)
        except ToolError as error:
            invocation = self._invocation.get()
            if invocation is not None and (
                error.__cause__ is None
                or isinstance(
                    error.__cause__,
                    (
                        GoalValidationError,
                        GoalConflictError,
                        GoalNotFoundError,
                        ValidationError,
                    ),
                )
            ):
                invocation.error_outcome = "denied"
            raise


def create_server(
    api: GoalAPI,
    completion_grant_id: int | None = None,
    *,
    run_id: int | None = None,
) -> FastMCP:
    if run_id is not None:
        run = api.get_run(run_id)
        if (
            run["completion_grant_id"] != completion_grant_id
            or run["outcome"] != "unfinished"
        ):
            raise GoalValidationError("The run does not match this session.")
    server = HarnessServer(api, run_id)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def list_goals(status: GoalStatus | None = None) -> GoalList:
        """List saved goals with their status, latest title and revision, and assigned operator.

        Omit status to include all goals, or pass a status such as active.
        """
        return {"goals": api.list_goals(status)}

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_goal_tree(
        goal_id: PositiveInteger,
    ) -> GoalTree:
        """Read a goal and all visible descendants, linked by parent_goal_id.

        Each goal carries its own status, current requirements and revision's
        completion evidence. An owner_supplied_reference was entered by the owner.
        """
        return api.get_goal_tree(goal_id)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_goal_progress(
        goal_id: PositiveInteger,
        revision: PositiveInteger | None = None,
    ) -> GoalProgress:
        """Read the model's assessment, lifecycle status, dates and evidence citations.

        Omit revision for the latest criteria. Every revision uses evidence available now.
        The evidence list contains all records considered. For distinct dates, days
        cites owner confirmations within the window and dated on or before submission (UTC).
        """
        return api.get_goal_progress(goal_id, revision)

    if completion_grant_id is not None:
        grant = api.get_completion_grant(completion_grant_id)

        @server.tool(
            annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True)
        )
        def complete_goal(
            goal_id: PositiveInteger,
            expected_revision: PositiveInteger,
            evidence_ids: list[PositiveInteger],
            rationale: str,
        ) -> DelegatedCompletion:
            """Complete the assigned subgoal using existing evidence when you judge it sufficient."""
            invocation = server._invocation.get()
            return api.complete_goal(
                goal_id,
                expected_revision,
                completion_grant_id=grant["id"],
                evidence_ids=evidence_ids,
                rationale=rationale,
                call=invocation.call if invocation is not None else None,
            )

    return server


def main() -> None:
    parser = ArgumentParser(description="Serve workspace goals over MCP stdio.")
    parser.add_argument("--completion-grant", type=int)
    parser.add_argument("--run-id", type=int)
    args = parser.parse_args()
    try:
        server = create_server(
            GoalAPI(local_owner=False), args.completion_grant, run_id=args.run_id
        )
    except (GoalValidationError, RunNotFoundError, WorkspaceStorageError) as error:
        parser.exit(1, f"harness_mcp: {error}\n")
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
