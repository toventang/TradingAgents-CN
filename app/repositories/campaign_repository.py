import uuid
from typing import Optional, List, Dict, Any
from app.core.database import get_mongo_db
from app.models.campaign import Campaign, CampaignStatus, CampaignRevision
from app.utils.timezone import now_tz


class CampaignNotFoundError(Exception):
    """Campaign 未找到"""
    pass


class CampaignForbiddenError(Exception):
    """无权访问 Campaign"""
    pass


class CampaignRepository:
    """Campaign 与 Revision 持久化 Repository"""

    def __init__(self, db=None):
        self._db = db

    def get_db(self):
        return self._db if self._db is not None else get_mongo_db()

    async def create_campaign(self, campaign: Campaign, revision: CampaignRevision) -> Campaign:
        db = self.get_db()
        await db["campaigns"].insert_one(campaign.model_dump())
        await db["campaign_revisions"].insert_one(revision.model_dump())
        return campaign

    async def get_campaign(self, campaign_id: str) -> Optional[Campaign]:
        db = self.get_db()
        doc = await db["campaigns"].find_one({"campaign_id": campaign_id})
        if not doc:
            return None
        doc.pop("_id", None)
        return Campaign(**doc)

    async def update_campaign(self, campaign_id: str, update_data: Dict[str, Any]) -> Campaign:
        db = self.get_db()
        update_data["updated_at"] = now_tz()
        res = await db["campaigns"].find_one_and_update(
            {"campaign_id": campaign_id},
            {"$set": update_data},
            return_document=True
        )
        if not res:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found")
        res.pop("_id", None)
        return Campaign(**res)

    async def save_revision(self, revision: CampaignRevision) -> CampaignRevision:
        db = self.get_db()
        await db["campaign_revisions"].insert_one(revision.model_dump())
        return revision
