from typing import TypedDict

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from harness_api import GoalAPI, GoalStatus, GoalSummary


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

    return server


def main() -> None:
    create_server(GoalAPI()).run(transport="stdio")


if __name__ == "__main__":
    main()
