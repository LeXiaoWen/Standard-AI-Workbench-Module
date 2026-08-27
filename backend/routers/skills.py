from fastapi import APIRouter, Request

from ..schemas import SkillMetadata
from ..skills.registry import list_adapters
from .dependencies import current_user

router = APIRouter()


@router.get("/api/v1/skills", response_model=list[SkillMetadata])
def list_skills(request: Request):
    current_user(request)
    return [adapter.metadata() for adapter in list_adapters()]
