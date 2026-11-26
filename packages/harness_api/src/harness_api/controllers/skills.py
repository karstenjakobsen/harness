from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from ..models.skills import SkillAPI
from ..views.skills import SkillReadingCallView, SkillRevisionView, SkillSummaryView
from . import owner_service

router = APIRouter(prefix="/skills", tags=["skills"])
Revision = Annotated[int, Path(gt=0, lt=2**63)]


def get_skill_api(request: Request) -> SkillAPI:
    return owner_service(request, request.app.state.skill_api)


SkillService = Annotated[SkillAPI, Depends(get_skill_api)]


@router.get("")
def list_skills(skills: SkillService) -> list[SkillSummaryView]:
    return skills.list_skills()


@router.get("/{skill_id}/revisions/{revision}")
def read_skill(
    skill_id: str, revision: Revision, skills: SkillService
) -> SkillRevisionView:
    return skills.read_skill(skill_id, revision)


@router.get("/{skill_id}/revisions/{revision}/reads")
def reading_calls(
    skill_id: str, revision: Revision, skills: SkillService
) -> list[SkillReadingCallView]:
    return skills.reading_calls(skill_id, revision)
