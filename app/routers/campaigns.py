import uuid
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.models.campaign import Campaign, CampaignStatus
from app.models.notification import NotificationPayload, NotificationEvent, NotificationSeverity
from app.services.campaigns.lifecycle_service import CampaignLifecycleService, CampaignLifecycleError
from app.services.campaigns.risk_exit import CampaignRiskExitService
from app.services.campaigns.performance_service import CampaignPerformanceService
from app.repositories.campaign_repository import CampaignRepository, CampaignNotFoundError
from app.services.notifications.notification_service import NotificationService
from app.services.auth_service import AuthService
from app.utils.timezone import now_tz

router = APIRouter(prefix="/api/campaigns", tags=["Campaigns"])


class CreateCampaignRequest(BaseModel):
    name: str
    description: str = ""
    strategy_id: str
    strategy_version_num: int = 1
    portfolio_id: str
    initial_allocation_cash: float
    start_date: str
    rebalance_frequency: str = "daily"


class ResumeCampaignRequest(BaseModel):
    confirmation_note: str = ""


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_campaign(
    req: CreateCampaignRequest,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    service = CampaignLifecycleService()
    camp, rev = await service.create_campaign_draft(
        user_id=user_id,
        name=req.name,
        strategy_id=req.strategy_id,
        strategy_version_num=req.strategy_version_num,
        portfolio_id=req.portfolio_id,
        initial_allocation_cash=req.initial_allocation_cash,
        start_date=req.start_date,
        description=req.description,
        rebalance_frequency=req.rebalance_frequency
    )
    return {"campaign": camp.model_dump(), "revision": rev.model_dump()}


@router.get("", response_model=List[Dict[str, Any]])
async def list_campaigns(
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    from app.core.database import get_mongo_db
    db = get_mongo_db()
    cursor = db["campaigns"].find({"user_id": user_id}).sort("created_at", -1)
    results = []
    async for doc in cursor:
        doc.pop("_id", None)
        results.append(doc)
    return results


@router.get("/{campaign_id}", response_model=Dict[str, Any])
async def get_campaign(
    campaign_id: str,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    repo = CampaignRepository()
    camp = await repo.get_campaign(campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if camp.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    return camp.model_dump()


@router.post("/{campaign_id}/activate", response_model=Dict[str, Any])
async def activate_campaign(
    campaign_id: str,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    service = CampaignLifecycleService()
    try:
        camp = await service.activate_campaign(campaign_id, user_id)
        return camp.model_dump()
    except CampaignLifecycleError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{campaign_id}/pause", response_model=Dict[str, Any])
async def pause_campaign(
    campaign_id: str,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    repo = CampaignRepository()
    camp = await repo.get_campaign(campaign_id)
    if not camp or camp.user_id != user_id:
        raise HTTPException(status_code=404, detail="Campaign not found or forbidden")

    now = now_tz()
    updated = await repo.update_campaign(campaign_id, {"status": CampaignStatus.PAUSED, "paused_at": now})

    # 通知推送
    notif_service = NotificationService()
    await notif_service.dispatch(NotificationPayload(
        event_id=f"evt_pause_{uuid.uuid4().hex[:8]}",
        user_id=user_id,
        event_type=NotificationEvent.RISK_ALERT,
        severity=NotificationSeverity.WARNING,
        title="Campaign Paused",
        message=f"Campaign '{camp.name}' ({campaign_id}) was paused."
    ))

    return updated.model_dump()


@router.post("/{campaign_id}/resume", response_model=Dict[str, Any])
async def resume_campaign(
    campaign_id: str,
    req: ResumeCampaignRequest,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    service = CampaignRiskExitService()
    try:
        camp = await service.resume_campaign(campaign_id, user_id, req.confirmation_note)
        return camp.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{campaign_id}/stop", response_model=Dict[str, Any])
async def stop_campaign(
    campaign_id: str,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    repo = CampaignRepository()
    camp = await repo.get_campaign(campaign_id)
    if not camp or camp.user_id != user_id:
        raise HTTPException(status_code=404, detail="Campaign not found or forbidden")

    now = now_tz()
    updated = await repo.update_campaign(campaign_id, {"status": CampaignStatus.STOPPED, "stopped_at": now})
    return updated.model_dump()


@router.get("/{campaign_id}/performance", response_model=Dict[str, Any])
async def get_campaign_performance(
    campaign_id: str,
    user_id: str = Depends(AuthService.get_canonical_user_id)
):
    repo = CampaignRepository()
    camp = await repo.get_campaign(campaign_id)
    if not camp or camp.user_id != user_id:
        raise HTTPException(status_code=404, detail="Campaign not found or forbidden")

    perf_service = CampaignPerformanceService()
    return await perf_service.calculate_campaign_performance(
        campaign_id=campaign_id,
        portfolio_id=camp.portfolio_id,
        initial_capital=camp.initial_allocation_cash,
        daily_equity_curve=[]
    )
