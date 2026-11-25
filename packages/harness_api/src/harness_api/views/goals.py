from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ..models.evidence import Evidence
from ..models.goals import (
    AssessmentType,
    Completion,
    DelegatedCompletion,
    GoalCreationStatus,
    GoalDuration,
    GoalProgress,
    GoalRevision,
    GoalStatus,
)
from . import PositiveInteger

GoalTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# These endpoints return the public model records verbatim.
EvidenceView = Evidence
CompletionView = Completion
GoalProgressView = GoalProgress
GoalHistoryView = list[GoalRevision]


class GoalDefinitionFields(BaseModel):
    desired_outcome: str | None = None
    duration: GoalDuration | None = None
    duration_days: PositiveInteger | None = None
    target_distinct_dates: PositiveInteger | None = None
    window_start: str | None = None
    assessment_type: AssessmentType | None = None
    success_criteria: str | None = None
    measurement_plan: str | None = None


class GoalCreateRequest(GoalDefinitionFields):
    model_config = ConfigDict(extra="forbid")

    title: GoalTitle
    status: GoalCreationStatus = "draft"
    parent_goal_id: PositiveInteger | None = None
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
    completion: Completion | DelegatedCompletion | None


class StatementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: str | None = None
    reference: str | None = None


class ObservationRequest(StatementRequest):
    retry_key: str
    reported_date: str | None = None


class CompletionRequest(StatementRequest):
    revision: PositiveInteger
    evidence_ids: list[PositiveInteger] = Field(default_factory=list)
