from typing import Annotated

from fastapi import APIRouter, Path

from ..views.runs import OperatorRunView
from .goals import GoalService

router = APIRouter(prefix="/runs", tags=["runs"])
RunId = Annotated[int, Path(gt=0, lt=2**63)]


@router.get("/{run_id}")
def get_run(run_id: RunId, goals: GoalService) -> OperatorRunView:
    return goals.get_run(run_id)
