from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.models.strategy import Strategy, StrategyVersion, StrategyStatus, StrategyType, UniverseSnapshot, StrategySignal
from app.repositories.strategy_repository import StrategyRepository, StrategyNotFoundError, StrategyForbiddenError
from app.services.strategies.version_service import VersionService
from app.services.strategies.signal_engine import DeterministicSignalEngine
from app.services.auth_service import AuthService
from app.utils.timezone import now_tz

router = APIRouter(prefix="/api/strategies", tags=["Strategies"])


class CreateStrategyRequest(BaseModel):
    name: str
    description: str = ""
    strategy_type: StrategyType = StrategyType.FACTOR_MODEL
    parameters: Dict[str, Any] = Field(default_factory=dict)
    rules: Dict[str, Any] = Field(default_factory=dict)
    universe_symbols: List[str] = Field(default_factory=list)


class UpdateDraftRequest(BaseModel):
    parameters: Optional[Dict[str, Any]] = None
    rules: Optional[Dict[str, Any]] = None
    universe_symbols: Optional[List[str]] = None
    commit_message: Optional[str] = None


class PublishVersionRequest(BaseModel):
    version_num: Optional[int] = None
    commit_message: Optional[str] = None


class CloneStrategyRequest(BaseModel):
    new_name: Optional[str] = None
    version_num: Optional[int] = None


class EvaluateSignalsRequest(BaseModel):
    strategy_id: str
    version_num: Optional[int] = None
    as_of: Optional[datetime] = None
    factor_values: Dict[str, Dict[str, float]]  # symbol -> {factor_id: value}


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_strategy(
    req: CreateStrategyRequest,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    service = VersionService()
    univ = UniverseSnapshot(universe_id=f"univ_{user_id}", user_id=user_id, symbols=req.universe_symbols)
    strat, ver = await service.create_strategy(
        user_id=user_id,
        name=req.name,
        description=req.description,
        strategy_type=req.strategy_type,
        parameters=req.parameters,
        rules=req.rules,
        universe=univ
    )
    return {"strategy": strat.model_dump(), "version": ver.model_dump()}


@router.get("", response_model=List[Dict[str, Any]])
async def list_strategies(
    include_system: bool = Query(True),
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    repo = StrategyRepository()
    strategies = await repo.list_strategies(user_id=user_id, include_system=include_system)
    return [s.model_dump() for s in strategies]


@router.get("/{strategy_id}", response_model=Dict[str, Any])
async def get_strategy(
    strategy_id: str,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    repo = StrategyRepository()
    strat = await repo.get_strategy(strategy_id)
    if not strat:
        raise HTTPException(status_code=404, detail="Strategy not found")
    if strat.user_id != user_id and not strat.is_system_template:
        raise HTTPException(status_code=403, detail="Forbidden")

    versions = await repo.list_versions(strategy_id)
    return {
        "strategy": strat.model_dump(),
        "versions": [v.model_dump() for v in versions]
    }


@router.put("/{strategy_id}/draft", response_model=Dict[str, Any])
async def update_draft(
    strategy_id: str,
    req: UpdateDraftRequest,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    service = VersionService()
    univ = UniverseSnapshot(universe_id=f"univ_{user_id}", user_id=user_id, symbols=req.universe_symbols) if req.universe_symbols is not None else None
    try:
        ver = await service.update_draft(
            strategy_id=strategy_id,
            user_id=user_id,
            parameters=req.parameters,
            rules=req.rules,
            universe=univ,
            commit_message=req.commit_message
        )
        return ver.model_dump()
    except StrategyForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except StrategyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{strategy_id}/publish", response_model=Dict[str, Any])
async def publish_version(
    strategy_id: str,
    req: PublishVersionRequest,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    service = VersionService()
    try:
        ver = await service.publish_version(
            strategy_id=strategy_id,
            user_id=user_id,
            version_num=req.version_num,
            commit_message=req.commit_message
        )
        return ver.model_dump()
    except StrategyForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except StrategyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{strategy_id}/clone", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def clone_strategy(
    strategy_id: str,
    req: CloneStrategyRequest,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    service = VersionService()
    try:
        strat, ver = await service.clone_strategy(
            strategy_id=strategy_id,
            user_id=user_id,
            new_name=req.new_name,
            version_num=req.version_num
        )
        return {"strategy": strat.model_dump(), "version": ver.model_dump()}
    except StrategyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{strategy_id}", response_model=Dict[str, Any])
async def archive_strategy(
    strategy_id: str,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    repo = StrategyRepository()
    try:
        strat = await repo.archive_strategy(strategy_id, user_id=user_id)
        return strat.model_dump()
    except StrategyForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except StrategyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/signals/evaluate", response_model=List[Dict[str, Any]])
async def evaluate_signals(
    req: EvaluateSignalsRequest,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    import pandas as pd
    repo = StrategyRepository()
    strat = await repo.get_strategy(req.strategy_id)
    if not strat:
        raise HTTPException(status_code=404, detail="Strategy not found")
    if strat.user_id != user_id and not strat.is_system_template:
        raise HTTPException(status_code=403, detail="Forbidden")

    versions = await repo.list_versions(req.strategy_id)
    if req.version_num:
        target_ver = next((v for v in versions if v.version_num == req.version_num), None)
    else:
        target_ver = versions[0] if versions else None

    if not target_ver:
        raise HTTPException(status_code=404, detail="Version not found")

    engine = DeterministicSignalEngine()
    df = pd.DataFrame.from_dict(req.factor_values, orient="index")
    as_of = req.as_of or now_tz()

    signals = engine.generate_signals(target_ver, user_id, as_of, df)
    return [s.model_dump() for s in signals]

class RollbackRequest(BaseModel):
    target_version_num: int
    commit_message: Optional[str] = None


@router.get("/{strategy_id}/diff", response_model=Dict[str, Any])
async def diff_strategy_versions(
    strategy_id: str,
    v1: int = Query(...),
    v2: int = Query(...),
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    repo = StrategyRepository()
    strat = await repo.get_strategy(strategy_id)
    if not strat:
        raise HTTPException(status_code=404, detail="Strategy not found")
    if strat.user_id != user_id and not strat.is_system_template:
        raise HTTPException(status_code=403, detail="Forbidden")

    versions = await repo.list_versions(strategy_id)
    ver1 = next((v for v in versions if v.version_num == v1), None)
    ver2 = next((v for v in versions if v.version_num == v2), None)

    if not ver1 or not ver2:
        raise HTTPException(status_code=404, detail="One or both target versions not found")

    from app.services.strategies.diff_service import StrategyDiffService
    diff_service = StrategyDiffService(repo=repo)
    return diff_service.diff_versions(ver1, ver2)


@router.post("/{strategy_id}/rollback", response_model=Dict[str, Any])
async def rollback_strategy_version(
    strategy_id: str,
    req: RollbackRequest,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    from app.services.strategies.diff_service import StrategyDiffService
    diff_service = StrategyDiffService()
    try:
        new_ver = await diff_service.rollback_to_version(
            strategy_id=strategy_id,
            target_version_num=req.target_version_num,
            user_id=user_id,
            commit_message=req.commit_message
        )
        return new_ver.model_dump()
    except StrategyForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except StrategyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
