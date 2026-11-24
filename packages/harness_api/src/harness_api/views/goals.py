from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from ..models.goals import AssessmentType, GoalDuration, GoalStatus

GoalTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class GoalDefinitionFields(BaseModel):
    desired_outcome: str | None = None
    duration: GoalDuration | None = None
    assessment_type: AssessmentType | None = None
    success_criteria: str | None = None
    measurement_plan: str | None = None


class GoalCreateRequest(GoalDefinitionFields):
    model_config = ConfigDict(extra="forbid")

    title: GoalTitle
    original_message: str | None = None
    clarification: str | None = None


class GoalUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: GoalTitle | None = None
    desired_outcome: str | None = None


class GoalSummaryView(BaseModel):
    id: int
    status: GoalStatus
    title: str | None
    revision: int | None
    operator: str | None


class GoalView(GoalSummaryView, GoalDefinitionFields):
    pass
