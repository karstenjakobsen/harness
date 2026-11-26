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
    TextContent,
    Tool,
    ToolAnnotations,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from harness_api import (
    AssessmentType,
    CallReference,
    DecisionReference,
    DelegatedCompletion,
    DelegatedGoalResult,
    DelegatedWorkResult,
    GoalActivity,
    GoalAPI,
    GoalConflictError,
    GoalCreationStatus,
    GoalDefinitionChanges,
    GoalDuration,
    GoalNotFoundError,
    GoalProgress,
    GoalResultReference,
    GoalStatus,
    GoalSummary,
    GoalTree,
    GoalValidationError,
    HarnessTool,
    OperatorRun,
    RunNotFoundError,
    SkillNotFoundError,
    SkillReference,
    SkillRevision,
    SkillSummary,
    SkillValidationError,
    WorkspaceStorageError,
)

PositiveInteger = Annotated[int, Field(strict=True, gt=0, lt=2**63)]
HARNESS_TOOLS = get_args(HarnessTool.__value__)
WRITE_TOOLS = (
    "delegate_work",
    "retry_work",
    "complete_goal",
    "create_goal",
    "create_subgoal",
    "revise_goal",
)
HISTORY_TOOLS = ("get_goal_activity", "get_run")
SKILL_TOOLS = ("list_skills", "read_skill")
RUN_REQUIRED_TOOLS = WRITE_TOOLS + HISTORY_TOOLS + SKILL_TOOLS


class SkillSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    revision: PositiveInteger


class SkillList(TypedDict):
    skills: list[SkillSummary]


class GoalList(TypedDict):
    goals: list[GoalSummary]


@dataclass
class _Invocation:
    call: CallReference
    supplied_fields: frozenset[str]
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
            status=result.get("status"),
            observation_ids=[],
            decision=_decision_reference(result) if tool == "complete_goal" else None,
        )
    ]


class HarnessServer(FastMCP):
    def __init__(self, api: GoalAPI, run_id: int | None) -> None:
        super().__init__("harness_mcp")
        self._api = api
        self._run_id = run_id
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
            goal_field = "parent_goal_id" if tool == "create_subgoal" else "goal_id"
            revision_field = {
                "delegate_work": "expected_revision",
                "create_subgoal": "expected_parent_revision",
                "complete_goal": "expected_revision",
                "revise_goal": "expected_revision",
                "get_goal_progress": "revision",
                "read_skill": "revision",
            }.get(tool)
            skill_id = arguments.get("id")
            try:
                call = api.start_tool_call(
                    run_id,
                    tool,
                    target_goal_id=_positive_id(arguments.get(goal_field))
                    if tool
                    not in ("list_goals", "create_goal", "get_run", *SKILL_TOOLS)
                    else None,
                    target_revision=_positive_id(arguments.get(revision_field))
                    if revision_field
                    else None,
                    target_skill_id=skill_id
                    if tool == "read_skill" and isinstance(skill_id, str)
                    else None,
                    target_work_item_id=_positive_id(arguments.get("work_item_id"))
                    if tool == "retry_work"
                    else None,
                    target_run_id=_positive_id(arguments.get("run_id"))
                    if tool == "get_run"
                    else None,
                )
            except (GoalValidationError, GoalConflictError, RunNotFoundError) as error:
                return ServerResult(
                    CallToolResult(
                        isError=True,
                        content=[TextContent(type="text", text=str(error))],
                    )
                )
            invocation = _Invocation(call, frozenset(arguments))
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
                if tool in SKILL_TOOLS:
                    items = (
                        result.structuredContent["skills"]
                        if tool == "list_skills"
                        else [result.structuredContent]
                    )
                    api.finish_tool_call(
                        call,
                        "returned",
                        returned_skills=[
                            SkillReference(id=item["id"], revision=item["revision"])
                            for item in items
                        ],
                    )
                elif tool in HISTORY_TOOLS:
                    api.finish_tool_call(
                        call,
                        "returned",
                        history_result=cast(
                            GoalActivity | OperatorRun, result.structuredContent
                        ),
                    )
                else:
                    api.finish_tool_call(
                        call,
                        "returned",
                        returned_goals=_result_references(
                            tool, result.structuredContent
                        ),
                    )
            return response

        self._mcp_server.request_handlers[CallToolRequest] = record_call

    async def list_tools(self) -> list[Tool]:
        tools = []
        for tool in await super().list_tools():
            if tool.name in WRITE_TOOLS and (
                self._run_id is None
                or self._api.get_run_write_action(self._run_id)
                != ("delegate_work" if tool.name == "retry_work" else tool.name)
            ):
                continue
            if tool.name in RUN_REQUIRED_TOOLS:
                tool.inputSchema["additionalProperties"] = False
            tools.append(tool)
        return tools

    async def call_tool(self, name: str, arguments: dict[str, object]):
        # FastMCP's default argument model ignores unknown fields.
        try:
            if name in RUN_REQUIRED_TOOLS:
                tool = next(
                    (tool for tool in await super().list_tools() if tool.name == name),
                    None,
                )
                if tool is None or self._invocation.get() is None:
                    raise ToolError(f"{name} is unavailable in this session.")
                extras = arguments.keys() - tool.inputSchema["properties"].keys()
                if extras:
                    raise ToolError(
                        f"Unexpected {name} fields: {', '.join(sorted(extras))}"
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
                        RunNotFoundError,
                        SkillNotFoundError,
                        SkillValidationError,
                        ValidationError,
                    ),
                )
            ):
                invocation.error_outcome = "denied"
            raise

    def audited_invocation(self) -> _Invocation:
        invocation = self._invocation.get()
        if invocation is None:
            raise ToolError("A recorded invocation is required for this tool.")
        return invocation


def _definition_fields(
    invocation: _Invocation, values: dict[str, Any]
) -> GoalDefinitionChanges:
    return cast(
        GoalDefinitionChanges,
        {
            field: values[field]
            for field in GoalDefinitionChanges.__optional_keys__
            & invocation.supplied_fields
        },
    )


def create_server(
    api: GoalAPI,
    completion_grant_id: int | None = None,
    *,
    run_id: int | None = None,
    definition_grant_id: int | None = None,
    work_grant_id: int | None = None,
) -> FastMCP:
    if run_id is None and (
        completion_grant_id is not None
        or definition_grant_id is not None
        or work_grant_id is not None
    ):
        raise GoalValidationError("A grant requires a recorded run.")
    if run_id is not None:
        run = api.get_run(run_id)
        definition_grant = run["definition_grant"]
        if (
            run["completion_grant_id"] != completion_grant_id
            or (definition_grant["id"] if definition_grant else None)
            != definition_grant_id
            or run.get("work_grant_id") != work_grant_id
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

    if run_id is not None:

        @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
        def list_skills() -> SkillList:
            """Discover current skill revisions by name and description."""
            return {"skills": api.skills.list_skills()}

        @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
        def read_skill(id: str, revision: PositiveInteger) -> SkillRevision:
            """Read the exact instructions, manifest and provenance for a skill revision."""
            return api.skills.read_skill(id, revision)

        @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
        def get_goal_activity(goal_id: PositiveInteger) -> GoalActivity:
            """Read a goal's revisions, observations, decisions and calls across operators.

            A committing_call gives the run ID and sequence that saved a revision or decision.
            """
            return api.get_goal_activity(goal_id, call=server.audited_invocation().call)

        @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
        def get_run(run_id: PositiveInteger) -> OperatorRun:
            """Inspect an owner-visible run and its ordered calls, including other operators' runs.

            The run identifies the operator and grant. Each call has a sequence, outcome,
            and references to saved changes and returned records.
            """
            return api.get_run(run_id, call=server.audited_invocation().call)

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
            return api.complete_goal(
                goal_id,
                expected_revision,
                completion_grant_id=grant["id"],
                evidence_ids=evidence_ids,
                rationale=rationale,
                call=server.audited_invocation().call,
            )

    if definition_grant_id is not None:
        definition_grant = api.get_definition_grant(definition_grant_id)
        if definition_grant["action"] == "create_goal":

            @server.tool(
                annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True)
            )
            def create_goal(
                title: str,
                retry_key: str,
                status: GoalCreationStatus = "draft",
                desired_outcome: str | None = None,
                duration: GoalDuration | None = None,
                duration_days: PositiveInteger | None = None,
                assessment_type: AssessmentType | None = None,
                success_criteria: str | None = None,
                measurement_plan: str | None = None,
                target_distinct_dates: PositiveInteger | None = None,
                window_start: str | None = None,
            ) -> DelegatedGoalResult:
                """Save one top-level goal definition. Reuse the same key and input to retry."""
                invocation = server.audited_invocation()
                return api.create_delegated_goal(
                    title,
                    call=invocation.call,
                    retry_key=retry_key,
                    status=status,
                    **_definition_fields(invocation, locals()),
                )

        elif definition_grant["action"] == "create_subgoal":

            @server.tool(
                annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True)
            )
            def create_subgoal(
                parent_goal_id: PositiveInteger,
                expected_parent_revision: PositiveInteger,
                retry_key: str,
                title: str,
                success_criteria: str,
                desired_outcome: str | None = None,
                duration: GoalDuration | None = None,
                duration_days: PositiveInteger | None = None,
                assessment_type: AssessmentType | None = None,
                measurement_plan: str | None = None,
                target_distinct_dates: PositiveInteger | None = None,
                window_start: str | None = None,
            ) -> DelegatedGoalResult:
                """Save one draft child under the granted parent. Reuse the key for an identical retry."""
                invocation = server.audited_invocation()
                return api.create_delegated_subgoal(
                    parent_goal_id,
                    expected_parent_revision,
                    title,
                    call=invocation.call,
                    retry_key=retry_key,
                    **_definition_fields(invocation, locals()),
                )

        elif definition_grant["action"] == "revise_goal":

            @server.tool(annotations=ToolAnnotations(readOnlyHint=False))
            def revise_goal(
                goal_id: PositiveInteger,
                expected_revision: PositiveInteger,
                title: str | None = None,
                desired_outcome: str | None = None,
                duration: GoalDuration | None = None,
                duration_days: PositiveInteger | None = None,
                assessment_type: AssessmentType | None = None,
                success_criteria: str | None = None,
                measurement_plan: str | None = None,
                target_distinct_dates: PositiveInteger | None = None,
                window_start: str | None = None,
            ) -> DelegatedGoalResult:
                """Revise the granted goal. Omit fields to preserve them or send null to clear a nullable definition field."""
                invocation = server.audited_invocation()
                return api.revise_delegated_goal(
                    goal_id,
                    expected_revision,
                    call=invocation.call,
                    title=title,
                    **_definition_fields(invocation, locals()),
                )

    if work_grant_id is not None:

        @server.tool(
            annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True)
        )
        def delegate_work(
            goal_id: PositiveInteger,
            expected_revision: PositiveInteger,
            brief: str,
            skill_revisions: list[SkillSelection],
            retry_key: str,
        ) -> DelegatedWorkResult:
            """Send a brief and exact skill revisions to a worker on the granted goal."""
            return api.work.delegate_work(
                goal_id,
                expected_revision,
                brief,
                [
                    SkillReference(id=skill.id, revision=skill.revision)
                    for skill in skill_revisions
                ],
                retry_key,
                call=server.audited_invocation().call,
            )

        @server.tool(
            annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True)
        )
        def retry_work(
            work_item_id: PositiveInteger,
            expected_latest_attempt_id: PositiveInteger,
            retry_key: str,
        ) -> DelegatedWorkResult:
            """Request another attempt against the work item you reviewed."""
            return api.work.retry_work(
                work_item_id,
                expected_latest_attempt_id,
                retry_key,
                call=server.audited_invocation().call,
            )

    return server


def main() -> None:
    parser = ArgumentParser(description="Serve workspace goals over MCP stdio.")
    parser.add_argument("--completion-grant", type=int)
    parser.add_argument("--definition-grant", type=int)
    parser.add_argument("--work-grant", type=int)
    parser.add_argument("--run-id", type=int)
    args = parser.parse_args()
    try:
        server = create_server(
            GoalAPI(local_owner=False),
            args.completion_grant,
            run_id=args.run_id,
            work_grant_id=args.work_grant,
            definition_grant_id=args.definition_grant,
        )
    except (GoalValidationError, RunNotFoundError, WorkspaceStorageError) as error:
        parser.exit(1, f"harness_mcp: {error}\n")
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
