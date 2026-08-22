from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.models.analysis import AnalysisProfile, AnalysisProfileVersion, AnalysisDepth, RiskPreference, InvestmentHorizon
from app.repositories.analysis_profile_repository import AnalysisProfileRepository, AnalysisProfileNotFoundError
from app.services.analysis_profiles.resolver import AnalysisProfileResolver, AnalysisProfileConflictError
from app.services.auth_service import AuthService
from app.utils.timezone import now_tz

router = APIRouter(prefix="/api/analysis-profiles", tags=["AnalysisProfiles"])


class CreateProfileRequest(BaseModel):
    name: str
    description: str = ""
    analysts: List[str] = Field(default_factory=lambda: ["market_analyst", "fundamentals_analyst", "technical_analyst", "risk_analyst"])
    depth: AnalysisDepth = AnalysisDepth.STANDARD
    model_refs: Dict[str, str] = Field(default_factory=dict)
    risk_preference: RiskPreference = RiskPreference.BALANCED
    horizon: InvestmentHorizon = InvestmentHorizon.MEDIUM_TERM
    factor_context_limits: int = 20


class ResolveProfileRequest(BaseModel):
    profile_id: Optional[str] = None
    legacy_params: Optional[Dict[str, Any]] = None


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_profile(
    req: CreateProfileRequest,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    repo = AnalysisProfileRepository()
    import uuid
    pid = f"p_{uuid.uuid4().hex[:12]}"
    vid = f"v_{uuid.uuid4().hex[:12]}"
    now = now_tz()

    profile = AnalysisProfile(
        profile_id=pid,
        user_id=user_id,
        name=req.name,
        description=req.description,
        created_at=now,
        updated_at=now
    )

    version = AnalysisProfileVersion(
        version_id=vid,
        profile_id=pid,
        version_num=1,
        analysts=req.analysts,
        depth=req.depth,
        model_refs=req.model_refs,
        risk_preference=req.risk_preference,
        horizon=req.horizon,
        factor_context_limits=req.factor_context_limits,
        created_at=now
    )

    await repo.create_profile(profile, version)
    return {"profile": profile.model_dump(), "version": version.model_dump()}


@router.get("/{profile_id}", response_model=Dict[str, Any])
async def get_profile(
    profile_id: str,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    repo = AnalysisProfileRepository()
    profile = await repo.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="AnalysisProfile not found")

    latest_ver = await repo.get_latest_version(profile_id)
    return {"profile": profile.model_dump(), "version": latest_ver.model_dump() if latest_ver else None}


@router.post("/resolve", response_model=Dict[str, Any])
async def resolve_profile(
    req: ResolveProfileRequest,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    resolver = AnalysisProfileResolver()
    try:
        resolved = await resolver.resolve_profile(profile_id=req.profile_id, legacy_params=req.legacy_params)
        return resolved.model_dump()
    except AnalysisProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except AnalysisProfileConflictError as e:
        raise HTTPException(status_code=400, detail=str(e))
