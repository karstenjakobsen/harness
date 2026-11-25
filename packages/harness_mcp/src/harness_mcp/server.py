from argparse import ArgumentParser
from typing import Annotated, TypedDict

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import Tool, ToolAnnotations
from pydantic import Field

from harness_api import (
    DelegatedCompletion,
    GoalAPI,
    GoalProgress,
    GoalStatus,
    GoalSummary,
    GoalTree,
    GoalValidationError,
    WorkspaceStorageError,
)

PositiveInteger = Annotated[int, Field(strict=True, gt=0, lt=2**63)]


class GoalList(TypedDict):
    goals: list[GoalSummary]


class HarnessServer(FastMCP):
    async def list_tools(self) -> list[Tool]:
        tools = await super().list_tools()
        for tool in tools:
            if tool.name == "complete_goal":
                tool.inputSchema["additionalProperties"] = False
        return tools

    async def call_tool(self, name: str, arguments: dict[str, object]):
        # FastMCP's default argument model ignores unknown fields.
        if name == "complete_goal":
            for tool in await self.list_tools():
                if tool.name == name:
                    extras = arguments.keys() - tool.inputSchema["properties"].keys()
                    if extras:
                        raise ToolError(
                            f"Unexpected completion fields: {', '.join(sorted(extras))}"
                        )
        return await super().call_tool(name, arguments)


def create_server(api: GoalAPI, completion_grant_id: int | None = None) -> FastMCP:
    server = HarnessServer("harness_mcp")

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
            return api.complete_goal(
                goal_id,
                expected_revision,
                completion_grant_id=grant["id"],
                evidence_ids=evidence_ids,
                rationale=rationale,
            )

    return server


def main() -> None:
    parser = ArgumentParser(description="Serve workspace goals over MCP stdio.")
    parser.add_argument("--completion-grant", type=int)
    args = parser.parse_args()
    try:
        server = create_server(GoalAPI(local_owner=False), args.completion_grant)
    except (GoalValidationError, WorkspaceStorageError) as error:
        parser.exit(1, f"harness_mcp: {error}\n")
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
