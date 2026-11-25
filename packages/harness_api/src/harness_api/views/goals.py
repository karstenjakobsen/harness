from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ..models.goals import (
    AssessmentType,
    Completion,
    GoalCreationStatus,
    GoalDuration,
    GoalStatus,
)

GoalTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class GoalDefinitionFields(BaseModel):
    desired_outcome: str | None = None
    duration: GoalDuration | None = None
    duration_days: Annotated[int, Field(strict=True, gt=0, lt=2**63)] | None = None
    assessment_type: AssessmentType | None = None
    success_criteria: str | None = None
    measurement_plan: str | None = None


class GoalCreateRequest(GoalDefinitionFields):
    model_config = ConfigDict(extra="forbid")

    title: GoalTitle
    status: GoalCreationStatus = "draft"
    parent_goal_id: Annotated[int, Field(strict=True, ge=-(2**63), lt=2**63)] | None = (
        None
    )
    original_message: str | None = None
    clarification: str | None = None


class GoalUpdateRequest(GoalDefinitionFields):
    model_config = ConfigDict(extra="forbid")

    title: GoalTitle | None = None


class GoalSummaryView(BaseModel):
    id: int
    status: GoalStatus
    title: str | None
    revision: int | None
    operator: str | None


class GoalView(GoalSummaryView, GoalDefinitionFields):
    parent_goal_id: int | None
    completion: Completion | None
