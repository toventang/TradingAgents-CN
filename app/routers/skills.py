import uuid
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.models.skill import Skill, SkillVersion, SkillType, SkillIOContract, SkillStatus
from app.services.skills.registry import SkillRegistry
from app.services.skills.sandbox import PythonSandboxEngine
from app.services.auth_service import AuthService
from app.utils.timezone import now_tz

router = APIRouter(prefix="/api/skills", tags=["Skills"])


class CreateSkillRequest(BaseModel):
    name: str
    description: str = ""
    skill_type: SkillType = SkillType.MARKET
    code: str
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)


class ExecuteSkillRequest(BaseModel):
    kwargs: Dict[str, Any] = Field(default_factory=dict)


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_skill(
    req: CreateSkillRequest,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    registry = SkillRegistry()
    contract = SkillIOContract(input_schema=req.input_schema, output_schema=req.output_schema)
    skill, version = await registry.create_skill(
        user_id=user_id,
        name=req.name,
        code=req.code,
        description=req.description,
        skill_type=req.skill_type,
        contract=contract
    )
    return {"skill": skill.model_dump(), "version": version.model_dump()}


@router.get("", response_model=List[Dict[str, Any]])
async def list_skills(
    include_system: bool = True,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    from app.core.database import get_mongo_db
    db = get_mongo_db()
    query: Dict[str, Any] = {}
    if include_system:
        query["$or"] = [{"user_id": user_id}, {"is_system_skill": True}]
    else:
        query["user_id"] = user_id

    cursor = db["skills"].find(query).sort("created_at", -1)
    results = []
    async for doc in cursor:
        doc.pop("_id", None)
        results.append(doc)
    return results


@router.get("/{skill_id}", response_model=Dict[str, Any])
async def get_skill(
    skill_id: str,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    registry = SkillRegistry()
    skill = await registry.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.user_id != user_id and not skill.is_system_skill:
        raise HTTPException(status_code=403, detail="Forbidden")

    version = await registry.get_latest_version(skill_id)
    return {"skill": skill.model_dump(), "version": version.model_dump() if version else None}


@router.post("/{skill_id}/execute", response_model=Dict[str, Any])
async def execute_skill(
    skill_id: str,
    req: ExecuteSkillRequest,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    registry = SkillRegistry()
    skill = await registry.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.user_id != user_id and not skill.is_system_skill:
        raise HTTPException(status_code=403, detail="Forbidden")

    version = await registry.get_latest_version(skill_id)
    if not version:
        raise HTTPException(status_code=404, detail="Skill version not found")

    sandbox = PythonSandboxEngine()
    exec_res = sandbox.execute_skill(
        skill_id=skill_id,
        version_num=version.version_num,
        code=version.code,
        kwargs=req.kwargs
    )
    return exec_res.model_dump()
