import hashlib
import json
from typing import List, Optional, Dict, Any
from app.models.factor import FactorDefinition
from app.services.factors.registry import global_factor_registry
from app.core.database import get_mongo_db


class FactorRepository:
    """因子元数据与计算快照 Repository"""

    def __init__(self, db=None):
        self._db = db

    def get_db(self):
        return self._db if self._db is not None else get_mongo_db()

    async def sync_definitions(self) -> int:
        """基于 Checksum 幂等镜像因子定义元数据至 MongoDB factor_definitions 集合"""
        db = self.get_db()
        col = db["factor_definitions"]
        synced_count = 0

        for defn in global_factor_registry.get_all():
            data_dict = defn.model_dump()
            # Calculate SHA256 checksum
            raw_bytes = json.dumps(data_dict, sort_keys=True, default=str).encode("utf-8")
            checksum = hashlib.sha256(raw_bytes).hexdigest()
            data_dict["checksum"] = checksum

            existing = await col.find_one({"factor_id": defn.factor_id})
            if not existing or existing.get("checksum") != checksum:
                await col.update_one(
                    {"factor_id": defn.factor_id},
                    {"$set": data_dict},
                    upsert=True
                )
                synced_count += 1

        return synced_count

    async def get_definition(self, factor_id: str) -> Optional[Dict[str, Any]]:
        db = self.get_db()
        doc = await db["factor_definitions"].find_one({"factor_id": factor_id})
        if doc and "_id" in doc:
            doc.pop("_id")
        return doc
