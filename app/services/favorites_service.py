"""
自选股服务
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Dict, Any
from uuid import NAMESPACE_URL, uuid5

from bson import ObjectId

from app.core.database import get_mongo_db
from app.models.alert import (
    AlertCompareOperator,
    AlertEvaluationMode,
    AlertMarket,
    AlertRule,
    AlertRuleOrigin,
    AlertTrigger,
    AlertType,
    CompareAlertCondition,
    ConstantOperand,
    CurrentValueOperand,
    MarketHoursSchedule,
    SymbolScope,
)
from app.repositories.alert_repository import (
    AlertRepository,
    AlertRepositoryConflict,
)
from app.services.quotes_service import get_quotes_service
from app.services.symbols.normalizer import SymbolNormalizer


LEGACY_ALERT_FIELDS = ("alert_price_high", "alert_price_low")
LEGACY_ALERT_SOURCE = "legacy_favorite"
_UNSET = object()


@dataclass(frozen=True)
class FavoriteAlertSyncResult:
    rule_ids: dict[str, str]
    created: int = 0
    updated: int = 0
    soft_deleted: int = 0


class FavoriteAlertRuleSynchronizer:
    """Synchronize legacy threshold fields with versioned alert rules."""

    MAPPINGS_COLLECTION = "favorite_alert_migrations"

    def __init__(self, db, *, alerts: AlertRepository | None = None):
        self.db = db
        self.alerts = alerts or AlertRepository(db)
        self._indexes_ready = False
        self._index_lock = asyncio.Lock()

    async def ensure_indexes(self) -> None:
        await self.alerts.ensure_indexes()
        if self._indexes_ready:
            return
        async with self._index_lock:
            if self._indexes_ready:
                return
            collection = self.db[self.MAPPINGS_COLLECTION]
            await collection.create_index(
                [("migration_key", 1)],
                unique=True,
                name="favorite_alert_migration_identity",
            )
            await collection.create_index(
                [("user_id", 1), ("symbol", 1), ("legacy_field", 1)],
                name="favorite_alert_owner_symbol_field",
            )
            await collection.create_index(
                [("status", 1), ("updated_at", 1)],
                name="favorite_alert_migration_status",
            )
            self._indexes_ready = True

    async def synchronize(
        self,
        user_id: str,
        favorite: Dict[str, Any],
    ) -> FavoriteAlertSyncResult:
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("favorite alert owner must be non-empty")
        await self.ensure_indexes()
        identity = SymbolNormalizer.from_mapping(favorite)
        thresholds = {
            field: _threshold_decimal(favorite.get(field), field)
            for field in LEGACY_ALERT_FIELDS
        }
        rule_ids: dict[str, str] = {}
        created = updated = soft_deleted = 0
        for field in LEGACY_ALERT_FIELDS:
            key = f"{user_id}:{identity.symbol}:{field}"
            mapping = await self.db[self.MAPPINGS_COLLECTION].find_one(
                {"migration_key": key}
            )
            threshold = thresholds[field]
            if mapping is None and threshold is None:
                continue
            mapped_rule_id = mapping.get("rule_id") if mapping is not None else None
            if mapping is not None and not isinstance(mapped_rule_id, str):
                raise RuntimeError("favorite alert migration mapping is corrupted")
            rule_id = str(
                mapped_rule_id or uuid5(NAMESPACE_URL, f"legacy-favorite:{key}")
            )
            rule_ids[field] = rule_id
            if threshold is None:
                if mapping is not None and mapping.get("status") != "soft_deleted":
                    await self._disable_rule(rule_id, user_id)
                    await self._store_mapping(
                        key=key,
                        user_id=user_id,
                        market=identity.market.value,
                        symbol=identity.symbol,
                        field=field,
                        rule_id=rule_id,
                        threshold=None,
                        status="soft_deleted",
                    )
                    soft_deleted += 1
                continue

            desired = self._build_rule(
                rule_id=rule_id,
                user_id=user_id,
                stock_name=str(favorite.get("stock_name") or identity.symbol),
                market=AlertMarket(identity.market.value),
                symbol=identity.symbol,
                field=field,
                threshold=threshold,
                created_at=_favorite_created_at(favorite),
            )
            existing = await self.alerts.get_rule(rule_id, user_id=user_id)
            if existing is None:
                try:
                    existing = await self.alerts.create_rule(desired)
                    created += 1
                except AlertRepositoryConflict:
                    existing = await self.alerts.get_rule(rule_id, user_id=user_id)
                    if existing is None:
                        raise
            if not _rule_matches_threshold(existing, field, threshold):
                await self._replace_rule(existing, desired)
                updated += 1
            await self._store_mapping(
                key=key,
                user_id=user_id,
                market=identity.market.value,
                symbol=identity.symbol,
                field=field,
                rule_id=rule_id,
                threshold=str(threshold),
                status="active",
            )
        return FavoriteAlertSyncResult(
            rule_ids=rule_ids,
            created=created,
            updated=updated,
            soft_deleted=soft_deleted,
        )

    async def _replace_rule(self, current: AlertRule, desired: AlertRule) -> AlertRule:
        for _ in range(4):
            proposed = current.model_copy(
                update={
                    "name": desired.name,
                    "description": desired.description,
                    "enabled": desired.enabled,
                    "alert_type": desired.alert_type,
                    "scope": desired.scope,
                    "market": desired.market,
                    "trigger": desired.trigger,
                }
            )
            try:
                updated, _ = await self.alerts.update_rule(
                    proposed,
                    user_id=current.user_id,
                    expected_version=current.version,
                )
                return updated
            except AlertRepositoryConflict:
                latest = await self.alerts.get_rule(
                    current.rule_id,
                    user_id=current.user_id,
                )
                if latest is None:
                    raise
                current = latest
        raise AlertRepositoryConflict("favorite alert rule changed repeatedly")

    async def _disable_rule(self, rule_id: str, user_id: str) -> None:
        current = await self.alerts.get_rule(rule_id, user_id=user_id)
        if current is None or not current.enabled:
            return
        await self._replace_rule(current, current.model_copy(update={"enabled": False}))

    async def _store_mapping(
        self,
        *,
        key: str,
        user_id: str,
        market: str,
        symbol: str,
        field: str,
        rule_id: str,
        threshold: str | None,
        status: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.db[self.MAPPINGS_COLLECTION].update_one(
            {"migration_key": key},
            {
                "$setOnInsert": {
                    "migration_key": key,
                    "source": LEGACY_ALERT_SOURCE,
                    "user_id": user_id,
                    "market": market,
                    "symbol": symbol,
                    "legacy_field": field,
                    "rule_id": rule_id,
                    "created_at": now,
                },
                "$set": {
                    "threshold": threshold,
                    "status": status,
                    "updated_at": now,
                },
            },
            upsert=True,
        )

    @staticmethod
    def _build_rule(
        *,
        rule_id: str,
        user_id: str,
        stock_name: str,
        market: AlertMarket,
        symbol: str,
        field: str,
        threshold: Decimal,
        created_at: datetime,
    ) -> AlertRule:
        high = field == "alert_price_high"
        label = "高价" if high else "低价"
        return AlertRule(
            rule_id=rule_id,
            user_id=user_id,
            name=f"{stock_name}{label}提醒",
            description=f"source={LEGACY_ALERT_SOURCE};legacy_field={field}",
            enabled=True,
            alert_type=AlertType.PRICE_ABOVE if high else AlertType.PRICE_BELOW,
            scope=SymbolScope(symbol=symbol),
            market=market,
            trigger=AlertTrigger(
                condition=CompareAlertCondition(
                    left=CurrentValueOperand(),
                    operator=AlertCompareOperator.GT if high else AlertCompareOperator.LT,
                    right=ConstantOperand(value=threshold),
                )
            ),
            evaluation_mode=AlertEvaluationMode.EDGE,
            frequency_seconds=60,
            active_schedule=MarketHoursSchedule(),
            cooldown_seconds=300,
            recovery_enabled=True,
            origin=AlertRuleOrigin.USER,
            created_at=created_at,
            updated_at=created_at,
        )


class FavoritesService:
    """自选股服务类"""
    
    def __init__(self, db=None, *, alert_synchronizer=None):
        self.db = db
        self._alert_synchronizer = alert_synchronizer
    
    async def _get_db(self):
        """获取数据库连接"""
        if self.db is None:
            self.db = get_mongo_db()
        return self.db

    def _is_valid_object_id(self, user_id: str) -> bool:
        """
        检查是否是有效的ObjectId格式
        注意：这里只检查格式，不代表数据库中实际存储的是ObjectId类型
        为了兼容性，我们统一使用 user_favorites 集合存储自选股
        """
        # 强制返回 False，统一使用 user_favorites 集合
        return False

    def _format_favorite(self, favorite: Dict[str, Any]) -> Dict[str, Any]:
        """格式化收藏条目（仅基础信息，不包含实时行情）。
        行情将在 get_user_favorites 中批量富集。
        """
        added_at = favorite.get("added_at")
        if isinstance(added_at, datetime):
            added_at = added_at.isoformat()
        rule_ids = dict(favorite.get("alert_rule_ids") or {})
        for field in LEGACY_ALERT_FIELDS:
            embedded = favorite.get(f"{field}_rule_id")
            if embedded:
                rule_ids[field] = str(embedded)
        return {
            "stock_code": favorite.get("stock_code"),
            "stock_name": favorite.get("stock_name"),
            "market": favorite.get("market", "A股"),
            "added_at": added_at,
            "tags": favorite.get("tags", []),
            "notes": favorite.get("notes", ""),
            "alert_price_high": favorite.get("alert_price_high"),
            "alert_price_low": favorite.get("alert_price_low"),
            "alert_rule_ids": rule_ids,
            "alert_price_high_rule_id": rule_ids.get("alert_price_high"),
            "alert_price_low_rule_id": rule_ids.get("alert_price_low"),
            # 行情占位，稍后填充
            "current_price": None,
            "change_percent": None,
            "volume": None,
        }

    async def get_user_favorites(self, user_id: str) -> List[Dict[str, Any]]:
        """获取用户自选股列表，并批量拉取实时行情进行富集（兼容字符串ID与ObjectId）。"""
        db = await self._get_db()

        favorites: List[Dict[str, Any]] = []
        if self._is_valid_object_id(user_id):
            # 先尝试使用 ObjectId 查询
            user = await db["users"].find_one({"_id": ObjectId(user_id)})
            # 如果 ObjectId 查询失败，尝试使用字符串查询
            if user is None:
                user = await db["users"].find_one({"_id": user_id})
            favorites = (user or {}).get("favorite_stocks", [])
        else:
            doc = await db["user_favorites"].find_one({"user_id": user_id})
            favorites = (doc or {}).get("favorites", [])

        # 先格式化基础字段
        items = [self._format_favorite(fav) for fav in favorites]

        # 批量获取股票基础信息（板块等）
        codes = [it.get("stock_code") for it in items if it.get("stock_code")]
        if codes:
            try:
                # 🔥 获取数据源优先级配置
                from app.core.unified_config import UnifiedConfigManager
                config = UnifiedConfigManager()
                data_source_configs = await config.get_data_source_configs_async()

                # 提取启用的数据源，按优先级排序
                enabled_sources = [
                    ds.type.lower() for ds in data_source_configs
                    if ds.enabled and ds.type.lower() in ['tushare', 'akshare', 'baostock']
                ]

                if not enabled_sources:
                    enabled_sources = ['tushare', 'akshare', 'baostock']

                preferred_source = enabled_sources[0] if enabled_sources else 'tushare'

                # 从 stock_basic_info 获取板块信息（只查询优先级最高的数据源）
                basic_info_coll = db["stock_basic_info"]
                cursor = basic_info_coll.find(
                    {"code": {"$in": codes}, "source": preferred_source},  # 🔥 添加数据源筛选
                    {"code": 1, "sse": 1, "market": 1, "_id": 0}
                )
                basic_docs = await cursor.to_list(length=None)
                basic_map = {str(d.get("code")).zfill(6): d for d in (basic_docs or [])}

                for it in items:
                    code = it.get("stock_code")
                    basic = basic_map.get(code)
                    if basic:
                        # market 字段表示板块（主板、创业板、科创板等）
                        it["board"] = basic.get("market", "-")
                        # sse 字段表示交易所（上海证券交易所、深圳证券交易所等）
                        it["exchange"] = basic.get("sse", "-")
                    else:
                        it["board"] = "-"
                        it["exchange"] = "-"
            except Exception as e:
                # 查询失败时设置默认值
                for it in items:
                    it["board"] = "-"
                    it["exchange"] = "-"

        # 批量获取行情（优先使用入库的 market_quotes，30秒更新）
        if codes:
            try:
                coll = db["market_quotes"]
                cursor = coll.find({"code": {"$in": codes}}, {"code": 1, "close": 1, "pct_chg": 1, "amount": 1})
                docs = await cursor.to_list(length=None)
                quotes_map = {str(d.get("code")).zfill(6): d for d in (docs or [])}
                for it in items:
                    code = it.get("stock_code")
                    q = quotes_map.get(code)
                    if q:
                        it["current_price"] = q.get("close")
                        it["change_percent"] = q.get("pct_chg")
                # 兜底：对未命中的代码使用在线源补齐（可选）
                missing = [c for c in codes if c not in quotes_map]
                if missing:
                    try:
                        quotes_online = await get_quotes_service().get_quotes(missing)
                        for it in items:
                            code = it.get("stock_code")
                            if it.get("current_price") is None:
                                q2 = quotes_online.get(code, {}) if quotes_online else {}
                                it["current_price"] = q2.get("close")
                                it["change_percent"] = q2.get("pct_chg")
                    except Exception:
                        pass
            except Exception:
                # 查询失败时保持占位 None，避免影响基础功能
                pass

        return items

    async def add_favorite(
        self,
        user_id: str,
        stock_code: str,
        stock_name: str,
        market: str = "A股",
        tags: List[str] = None,
        notes: str = "",
        alert_price_high: Optional[float] = None,
        alert_price_low: Optional[float] = None
    ) -> bool:
        """添加股票到自选股（兼容字符串ID与ObjectId）"""
        import logging
        logger = logging.getLogger("webapi")

        try:
            logger.info(f"🔧 [add_favorite] 开始添加自选股: user_id={user_id}, stock_code={stock_code}")

            db = await self._get_db()
            logger.info(f"🔧 [add_favorite] 数据库连接获取成功")

            favorite_stock = {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "market": market,
                "added_at": datetime.utcnow(),
                "tags": tags or [],
                "notes": notes,
                "alert_price_high": alert_price_high,
                "alert_price_low": alert_price_low
            }

            logger.info(f"🔧 [add_favorite] 自选股数据构建完成: {favorite_stock}")

            is_oid = self._is_valid_object_id(user_id)
            logger.info(f"🔧 [add_favorite] 用户ID类型检查: is_valid_object_id={is_oid}")

            if is_oid:
                logger.info(f"🔧 [add_favorite] 使用 ObjectId 方式添加到 users 集合")

                # 先尝试使用 ObjectId 查询
                result = await db["users"].update_one(
                    {"_id": ObjectId(user_id)},
                    {
                        "$push": {"favorite_stocks": favorite_stock},
                        "$setOnInsert": {"favorite_stocks": []}
                    }
                )
                logger.info(f"🔧 [add_favorite] ObjectId查询结果: matched_count={result.matched_count}, modified_count={result.modified_count}")

                # 如果 ObjectId 查询失败，尝试使用字符串查询
                if result.matched_count == 0:
                    logger.info(f"🔧 [add_favorite] ObjectId查询失败，尝试使用字符串ID查询")
                    result = await db["users"].update_one(
                        {"_id": user_id},
                        {
                            "$push": {"favorite_stocks": favorite_stock}
                        }
                    )
                    logger.info(f"🔧 [add_favorite] 字符串ID查询结果: matched_count={result.matched_count}, modified_count={result.modified_count}")

                success = result.matched_count > 0
                if success:
                    sync = await self.sync_legacy_alerts(user_id, favorite_stock)
                    await self._persist_rule_links(user_id, stock_code, sync.rule_ids)
                logger.info(f"🔧 [add_favorite] 返回结果: {success}")
                return success
            else:
                logger.info(f"🔧 [add_favorite] 使用字符串ID方式添加到 user_favorites 集合")
                result = await db["user_favorites"].update_one(
                    {"user_id": user_id},
                    {
                        "$setOnInsert": {"user_id": user_id, "created_at": datetime.utcnow()},
                        "$push": {"favorites": favorite_stock},
                        "$set": {"updated_at": datetime.utcnow()}
                    },
                    upsert=True
                )
                logger.info(f"🔧 [add_favorite] 更新结果: matched_count={result.matched_count}, modified_count={result.modified_count}, upserted_id={result.upserted_id}")
                sync = await self.sync_legacy_alerts(user_id, favorite_stock)
                await self._persist_rule_links(user_id, stock_code, sync.rule_ids)
                logger.info(f"🔧 [add_favorite] 返回结果: True")
                return True
        except Exception as e:
            logger.error(f"❌ [add_favorite] 添加自选股异常: {type(e).__name__}: {str(e)}", exc_info=True)
            raise

    async def remove_favorite(self, user_id: str, stock_code: str) -> bool:
        """从自选股中移除股票（兼容字符串ID与ObjectId）"""
        db = await self._get_db()
        favorite = await self._find_favorite(user_id, stock_code)
        if favorite is not None:
            tombstone = {
                **favorite,
                "alert_price_high": None,
                "alert_price_low": None,
            }
            await self.sync_legacy_alerts(user_id, tombstone)

        if self._is_valid_object_id(user_id):
            # 先尝试使用 ObjectId 查询
            result = await db["users"].update_one(
                {"_id": ObjectId(user_id)},
                {"$pull": {"favorite_stocks": {"stock_code": stock_code}}}
            )
            # 如果 ObjectId 查询失败，尝试使用字符串查询
            if result.matched_count == 0:
                result = await db["users"].update_one(
                    {"_id": user_id},
                    {"$pull": {"favorite_stocks": {"stock_code": stock_code}}}
                )
            return result.modified_count > 0
        else:
            result = await db["user_favorites"].update_one(
                {"user_id": user_id},
                {
                    "$pull": {"favorites": {"stock_code": stock_code}},
                    "$set": {"updated_at": datetime.utcnow()}
                }
            )
            return result.modified_count > 0

    async def update_favorite(
        self,
        user_id: str,
        stock_code: str,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None,
        alert_price_high: Optional[float] | object = _UNSET,
        alert_price_low: Optional[float] | object = _UNSET,
    ) -> bool:
        """更新自选股信息（兼容字符串ID与ObjectId）"""
        db = await self._get_db()

        # 统一构建更新字段（根据不同集合的字段路径设置前缀）
        is_oid = self._is_valid_object_id(user_id)
        prefix = "favorite_stocks.$." if is_oid else "favorites.$."
        update_fields: Dict[str, Any] = {}
        if tags is not None:
            update_fields[prefix + "tags"] = tags
        if notes is not None:
            update_fields[prefix + "notes"] = notes
        threshold_nulls_are_omitted = (
            alert_price_high is None
            and alert_price_low is None
            and (tags is not None or notes is not None)
        )
        high_provided = (
            alert_price_high is not _UNSET and not threshold_nulls_are_omitted
        )
        low_provided = (
            alert_price_low is not _UNSET and not threshold_nulls_are_omitted
        )
        if high_provided:
            update_fields[prefix + "alert_price_high"] = alert_price_high
        if low_provided:
            update_fields[prefix + "alert_price_low"] = alert_price_low

        if not update_fields:
            return True

        if is_oid:
            result = await db["users"].update_one(
                {
                    "_id": ObjectId(user_id),
                    "favorite_stocks.stock_code": stock_code
                },
                {"$set": update_fields}
            )
            success = result.matched_count > 0
        else:
            result = await db["user_favorites"].update_one(
                {
                    "user_id": user_id,
                    "favorites.stock_code": stock_code
                },
                {
                    "$set": {
                        **update_fields,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            success = result.matched_count > 0
        if success:
            favorite = await self._find_favorite(user_id, stock_code)
            if favorite is not None:
                sync = await self.sync_legacy_alerts(user_id, favorite)
                await self._persist_rule_links(user_id, stock_code, sync.rule_ids)
        return success

    async def sync_legacy_alerts(
        self,
        user_id: str,
        favorite: Dict[str, Any],
    ) -> FavoriteAlertSyncResult:
        db = await self._get_db()
        if self._alert_synchronizer is None:
            self._alert_synchronizer = FavoriteAlertRuleSynchronizer(db)
        return await self._alert_synchronizer.synchronize(user_id, favorite)

    async def _find_favorite(
        self,
        user_id: str,
        stock_code: str,
    ) -> Dict[str, Any] | None:
        db = await self._get_db()
        if self._is_valid_object_id(user_id):
            document = await db["users"].find_one(
                {
                    "_id": ObjectId(user_id),
                    "favorite_stocks.stock_code": stock_code,
                },
                {"favorite_stocks": 1},
            )
            entries = (document or {}).get("favorite_stocks", [])
        else:
            document = await db["user_favorites"].find_one(
                {"user_id": user_id, "favorites.stock_code": stock_code},
                {"favorites": 1},
            )
            entries = (document or {}).get("favorites", [])
        return next(
            (item for item in entries if item.get("stock_code") == stock_code),
            None,
        )

    async def _persist_rule_links(
        self,
        user_id: str,
        stock_code: str,
        rule_ids: dict[str, str],
    ) -> None:
        if not rule_ids:
            return
        db = await self._get_db()
        if self._is_valid_object_id(user_id):
            query = {
                "_id": ObjectId(user_id),
                "favorite_stocks.stock_code": stock_code,
            }
            prefix = "favorite_stocks.$."
            collection = db["users"]
        else:
            query = {
                "user_id": user_id,
                "favorites.stock_code": stock_code,
            }
            prefix = "favorites.$."
            collection = db["user_favorites"]
        values: dict[str, Any] = {
            prefix + "alert_rule_ids": rule_ids,
            prefix + "alert_rules_source": LEGACY_ALERT_SOURCE,
        }
        for field, rule_id in rule_ids.items():
            values[prefix + f"{field}_rule_id"] = rule_id
        await collection.update_one(query, {"$set": values})

    async def is_favorite(self, user_id: str, stock_code: str) -> bool:
        """检查股票是否在自选股中（兼容字符串ID与ObjectId）"""
        import logging
        logger = logging.getLogger("webapi")

        try:
            logger.info(f"🔧 [is_favorite] 检查自选股: user_id={user_id}, stock_code={stock_code}")

            db = await self._get_db()

            is_oid = self._is_valid_object_id(user_id)
            logger.info(f"🔧 [is_favorite] 用户ID类型: is_valid_object_id={is_oid}")

            if is_oid:
                # 先尝试使用 ObjectId 查询
                user = await db["users"].find_one(
                    {
                        "_id": ObjectId(user_id),
                        "favorite_stocks.stock_code": stock_code
                    }
                )

                # 如果 ObjectId 查询失败，尝试使用字符串查询
                if user is None:
                    logger.info(f"🔧 [is_favorite] ObjectId查询未找到，尝试使用字符串ID查询")
                    user = await db["users"].find_one(
                        {
                            "_id": user_id,
                            "favorite_stocks.stock_code": stock_code
                        }
                    )

                result = user is not None
                logger.info(f"🔧 [is_favorite] 查询结果: {result}")
                return result
            else:
                doc = await db["user_favorites"].find_one(
                    {
                        "user_id": user_id,
                        "favorites.stock_code": stock_code
                    }
                )
                result = doc is not None
                logger.info(f"🔧 [is_favorite] 字符串ID查询结果: {result}")
                return result
        except Exception as e:
            logger.error(f"❌ [is_favorite] 检查自选股异常: {type(e).__name__}: {str(e)}", exc_info=True)
            raise

    async def get_user_tags(self, user_id: str) -> List[str]:
        """获取用户使用的所有标签（兼容字符串ID与ObjectId）"""
        db = await self._get_db()

        if self._is_valid_object_id(user_id):
            pipeline = [
                {"$match": {"_id": ObjectId(user_id)}},
                {"$unwind": "$favorite_stocks"},
                {"$unwind": "$favorite_stocks.tags"},
                {"$group": {"_id": "$favorite_stocks.tags"}},
                {"$sort": {"_id": 1}}
            ]
            result = await db["users"].aggregate(pipeline).to_list(None)
        else:
            pipeline = [
                {"$match": {"user_id": user_id}},
                {"$unwind": "$favorites"},
                {"$unwind": "$favorites.tags"},
                {"$group": {"_id": "$favorites.tags"}},
                {"$sort": {"_id": 1}}
            ]
            result = await db["user_favorites"].aggregate(pipeline).to_list(None)

        return [item["_id"] for item in result if item.get("_id")]

    def _get_mock_price(self, stock_code: str) -> float:
        """获取模拟股价"""
        # 基于股票代码生成模拟价格
        base_price = hash(stock_code) % 100 + 10
        return round(base_price + (hash(stock_code) % 1000) / 100, 2)
    
    def _get_mock_change(self, stock_code: str) -> float:
        """获取模拟涨跌幅"""
        # 基于股票代码生成模拟涨跌幅
        change = (hash(stock_code) % 2000 - 1000) / 100
        return round(change, 2)
    
    def _get_mock_volume(self, stock_code: str) -> int:
        """获取模拟成交量"""
        # 基于股票代码生成模拟成交量
        return (hash(stock_code) % 10000 + 1000) * 100


def _threshold_decimal(value: Any, field: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a positive finite number")
    try:
        threshold = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a positive finite number") from exc
    if not threshold.is_finite() or threshold <= 0:
        raise ValueError(f"{field} must be a positive finite number")
    return threshold


def _favorite_created_at(favorite: Dict[str, Any]) -> datetime:
    value = favorite.get("added_at")
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            value = None
    if not isinstance(value, datetime):
        value = datetime(1970, 1, 1, tzinfo=timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _rule_matches_threshold(
    rule: AlertRule,
    field: str,
    threshold: Decimal,
) -> bool:
    condition = rule.trigger.condition
    high = field == "alert_price_high"
    return bool(
        rule.enabled
        and rule.alert_type
        == (AlertType.PRICE_ABOVE if high else AlertType.PRICE_BELOW)
        and isinstance(condition, CompareAlertCondition)
        and isinstance(condition.left, CurrentValueOperand)
        and isinstance(condition.right, ConstantOperand)
        and condition.operator
        == (AlertCompareOperator.GT if high else AlertCompareOperator.LT)
        and condition.right.value == threshold
    )


# 创建全局实例
favorites_service = FavoritesService()
