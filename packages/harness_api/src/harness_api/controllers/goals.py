from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from ..models.goals import Goal, GoalAPI, GoalStatus, GoalSummary
from ..views.goals import (
    CompletionRequest,
    CompletionView,
    EvidenceView,
    GoalCreateRequest,
    GoalHistoryView,
    GoalProgressView,
    GoalSummaryView,
    GoalUpdateRequest,
    GoalView,
    ObservationRequest,
)

router = APIRouter(prefix="/goals", tags=["goals"])


def get_goal_api(request: Request) -> GoalAPI:
    return request.app.state.goal_api


GoalService = Annotated[GoalAPI, Depends(get_goal_api)]
GoalId = Annotated[int, Path(ge=-(2**63), le=2**63 - 1)]


@router.get("", response_model=list[GoalSummaryView])
def list_goals(
    goals: GoalService, status: GoalStatus | None = None
) -> list[GoalSummary]:
    return goals.list_goals(status)


@router.post("", response_model=GoalView, status_code=HTTPStatus.CREATED)
def create_goal(
    body: GoalCreateRequest, response: Response, goals: GoalService
) -> Goal:
    goal = goals.create_goal(**body.model_dump())
    response.headers["Location"] = f"/goals/{goal['id']}"
    return goal


@router.get("/{goal_id}", response_model=GoalView)
def get_goal(goal_id: GoalId, goals: GoalService) -> Goal:
    return goals.get_goal(goal_id)


@router.patch("/{goal_id}", response_model=GoalView)
def update_goal(goal_id: GoalId, body: GoalUpdateRequest, goals: GoalService) -> Goal:
    return goals.update_goal(goal_id, **body.model_dump(exclude_unset=True))


@router.delete("/{goal_id}", status_code=HTTPStatus.NO_CONTENT)
def delete_goal(goal_id: GoalId, goals: GoalService) -> Response:
    goals.delete_goal(goal_id)
    return Response(status_code=HTTPStatus.NO_CONTENT)


@router.post("/{goal_id}/observations")
def record_observation(
    goal_id: GoalId, body: ObservationRequest, goals: GoalService
) -> EvidenceView:
    return goals.record_observation(goal_id, **body.model_dump())


@router.get("/{goal_id}/progress")
def get_goal_progress(
    goal_id: GoalId,
    goals: GoalService,
    revision: Annotated[int, Query(ge=1, lt=2**63)] | None = None,
) -> GoalProgressView:
    return goals.get_goal_progress(goal_id, revision)


@router.get("/{goal_id}/history")
def get_goal_history(goal_id: GoalId, goals: GoalService) -> GoalHistoryView:
    return goals.get_goal_history(goal_id)


@router.post("/{goal_id}/completion")
def complete_goal(
    goal_id: GoalId, body: CompletionRequest, goals: GoalService
) -> CompletionView:
    return goals.complete_goal(goal_id, **body.model_dump())
