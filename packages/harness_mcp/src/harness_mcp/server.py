from typing import Annotated, TypedDict

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from harness_api import GoalAPI, GoalProgress, GoalStatus, GoalSummary, GoalTree


class GoalList(TypedDict):
    goals: list[GoalSummary]


def create_server(api: GoalAPI) -> FastMCP:
    server = FastMCP("harness_mcp")

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def list_goals(status: GoalStatus | None = None) -> GoalList:
        """List saved goals with their status, latest title and revision, and assigned operator.

        Omit status to include all goals, or pass a status such as active.
        """
        return {"goals": api.list_goals(status)}

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_goal_tree(
        goal_id: Annotated[int, Field(strict=True, ge=-(2**63), lt=2**63)],
    ) -> GoalTree:
        """Read a goal and all visible descendants, linked by parent_goal_id.

        Each goal carries its own status, current requirements and revision's
        completion evidence. An owner_supplied_reference was entered by the owner.
        """
        return api.get_goal_tree(goal_id)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_goal_progress(
        goal_id: Annotated[int, Field(strict=True, ge=-(2**63), lt=2**63)],
        revision: Annotated[int, Field(strict=True, ge=1, lt=2**63)] | None = None,
    ) -> GoalProgress:
        """Read the model's assessment, lifecycle status, dates and evidence citations.

        Omit revision for the latest criteria. Every revision uses evidence available now.
        """
        return api.get_goal_progress(goal_id, revision)

    return server


def main() -> None:
    create_server(GoalAPI()).run(transport="stdio")


if __name__ == "__main__":
    main()
