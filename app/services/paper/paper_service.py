import re
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from app.core.database import get_mongo_db

logger = logging.getLogger("app.services.paper")

INITIAL_CASH_BY_MARKET = {
    "CNY": 1_000_000.0,
    "HKD": 1_000_000.0,
    "USD": 100_000.0
}


def detect_market_and_code(code: str) -> Tuple[str, str]:
    """检测股票代码的市场类型并标准化代码"""
    code = code.strip().upper()

    if code.endswith(".HK"):
        return ("HK", code[:-3].zfill(5))

    if re.match(r"^[A-Z]+$", code):
        return ("US", code)

    if re.match(r"^\d{4,5}$", code):
        return ("HK", code.zfill(5))

    if re.match(r"^\d{6}$", code):
        return ("CN", code)

    return ("CN", code.zfill(6))


class PaperTradingService:
    """模拟交易领域服务类"""

    def __init__(self, db=None):
        self._db = db

    def get_db(self):
        return self._db if self._db is not None else get_mongo_db()

    async def get_or_create_account(self, user_id: str) -> Dict[str, Any]:
        """获取或创建账户（多货币与结构迁移）"""
        db = self.get_db()
        acc = await db["paper_accounts"].find_one({"user_id": user_id})
        if not acc:
            now = datetime.utcnow().isoformat()
            acc = {
                "user_id": user_id,
                "cash": {
                    "CNY": INITIAL_CASH_BY_MARKET["CNY"],
                    "HKD": INITIAL_CASH_BY_MARKET["HKD"],
                    "USD": INITIAL_CASH_BY_MARKET["USD"]
                },
                "realized_pnl": {
                    "CNY": 0.0,
                    "HKD": 0.0,
                    "USD": 0.0
                },
                "settings": {
                    "auto_currency_conversion": False,
                    "default_market": "CN"
                },
                "created_at": now,
                "updated_at": now,
            }
            await db["paper_accounts"].insert_one(acc)
        else:
            updates: Dict[str, Any] = {}
            try:
                cash_val = acc.get("cash")
                if not isinstance(cash_val, dict):
                    base_cash = float(cash_val or 0.0)
                    updates["cash"] = {"CNY": base_cash, "HKD": 0.0, "USD": 0.0}

                pnl_val = acc.get("realized_pnl")
                if not isinstance(pnl_val, dict):
                    base_pnl = float(pnl_val or 0.0)
                    updates["realized_pnl"] = {"CNY": base_pnl, "HKD": 0.0, "USD": 0.0}

                if updates:
                    updates["updated_at"] = datetime.utcnow().isoformat()
                    await db["paper_accounts"].update_one({"user_id": user_id}, {"$set": updates})
                    acc = await db["paper_accounts"].find_one({"user_id": user_id})
            except Exception as e:
                logger.error(f"❌ 账户结构迁移失败 user_id={user_id}: {e}")
        return acc

    async def get_market_rules(self, market: str) -> Optional[Dict[str, Any]]:
        """获取市场规则配置"""
        db = self.get_db()
        rules_doc = await db["paper_market_rules"].find_one({"market": market})
        if rules_doc:
            return rules_doc.get("rules", {})
        return None

    def calculate_commission(self, market: str, side: str, amount: float, rules: Optional[Dict[str, Any]]) -> float:
        """计算手续费"""
        if not rules or "commission" not in rules:
            return 0.0

        commission_config = rules["commission"]
        commission = 0.0

        comm_rate = commission_config.get("rate", 0.0)
        comm_min = commission_config.get("min", 0.0)
        commission += max(amount * comm_rate, comm_min)

        if side == "sell" and "stamp_duty_rate" in commission_config:
            commission += amount * commission_config["stamp_duty_rate"]

        if market == "HK":
            if "transaction_levy_rate" in commission_config:
                commission += amount * commission_config["transaction_levy_rate"]
            if "trading_fee_rate" in commission_config:
                commission += amount * commission_config["trading_fee_rate"]
            if "settlement_fee_rate" in commission_config:
                commission += amount * commission_config["settlement_fee_rate"]

        if market == "US" and side == "sell" and "sec_fee_rate" in commission_config:
            commission += amount * commission_config["sec_fee_rate"]

        return round(commission, 2)

    async def get_available_quantity(self, user_id: str, code: str, market: str) -> int:
        """获取可用数量（考虑T+1限制）"""
        db = self.get_db()
        pos = await db["paper_positions"].find_one({"user_id": user_id, "code": code})
        if not pos:
            return 0

        total_qty = pos.get("quantity", 0)

        if market == "CN":
            rules = await self.get_market_rules(market)
            if rules and rules.get("t_plus", 0) > 0:
                today = datetime.utcnow().date().isoformat()
                pipeline = [
                    {"$match": {
                        "user_id": user_id,
                        "code": code,
                        "side": "buy",
                        "timestamp": {"$gte": today}
                    }},
                    {"$group": {"_id": None, "total": {"$sum": "$quantity"}}}
                ]
                today_buy = await db["paper_trades"].aggregate(pipeline).to_list(1) if hasattr(db["paper_trades"], "aggregate") else []
                today_buy_qty = today_buy[0]["total"] if today_buy else 0
                return max(0, total_qty - today_buy_qty)

        return total_qty

    async def get_last_price(self, code: str, market: str) -> Optional[float]:
        """获取股票最新价格"""
        db = self.get_db()

        if market == "CN":
            q = await db["market_quotes"].find_one(
                {"$or": [{"code": code}, {"symbol": code}]},
                {"_id": 0, "close": 1}
            )
            if q and q.get("close") is not None:
                try:
                    price = float(q["close"])
                    if price > 0:
                        return price
                except Exception as e:
                    logger.warning(f"⚠️ market_quotes 价格转换失败 {code}: {e}")

            basic_info = await db["stock_basic_info"].find_one(
                {"$or": [{"code": code}, {"symbol": code}]},
                {"_id": 0, "current_price": 1}
            )
            if basic_info and basic_info.get("current_price") is not None:
                try:
                    price = float(basic_info["current_price"])
                    if price > 0:
                        return price
                except Exception as e:
                    logger.warning(f"⚠️ stock_basic_info 价格转换失败 {code}: {e}")

            return None

        elif market in ["HK", "US"]:
            try:
                from app.services.foreign_stock_service import ForeignStockService
                service = ForeignStockService(db=db)
                quote = await service.get_quote(market, code, force_refresh=False)
                if quote:
                    price = quote.get("price") or quote.get("current_price") or quote.get("close")
                    if price and float(price) > 0:
                        return float(price)
            except Exception as e:
                logger.error(f"❌ 获取{market}股价格失败 {code}: {e}")
                return None

        return None

    async def get_account_summary(self, user_id: str) -> Dict[str, Any]:
        """获取账户资金与持仓估值汇总"""
        db = self.get_db()
        acc = await self.get_or_create_account(user_id)

        positions = await db["paper_positions"].find({"user_id": user_id}).to_list(None) if hasattr(db["paper_positions"].find({"user_id": user_id}), "to_list") else await db["paper_positions"].find({"user_id": user_id})

        positions_value_by_currency = {"CNY": 0.0, "HKD": 0.0, "USD": 0.0}
        detailed_positions: List[Dict[str, Any]] = []

        for p in positions:
            code = p.get("code")
            market = p.get("market", "CN")
            currency = p.get("currency", "CNY")
            qty = int(p.get("quantity", 0))
            avg_cost = float(p.get("avg_cost", 0.0))
            available_qty = p.get("available_qty", qty)

            last = await self.get_last_price(code, market)
            mkt_value = round((last or 0.0) * qty, 2)
            positions_value_by_currency[currency] += mkt_value

            detailed_positions.append({
                "code": code,
                "market": market,
                "currency": currency,
                "quantity": qty,
                "available_qty": available_qty,
                "avg_cost": avg_cost,
                "last_price": last,
                "market_value": mkt_value,
                "unrealized_pnl": None if last is None else round((last - avg_cost) * qty, 2)
            })

        cash = acc.get("cash", {})
        realized_pnl = acc.get("realized_pnl", {})

        if not isinstance(cash, dict):
            cash = {"CNY": float(cash), "HKD": 0.0, "USD": 0.0}
        if not isinstance(realized_pnl, dict):
            realized_pnl = {"CNY": float(realized_pnl), "HKD": 0.0, "USD": 0.0}

        summary = {
            "cash": {
                "CNY": round(float(cash.get("CNY", 0.0)), 2),
                "HKD": round(float(cash.get("HKD", 0.0)), 2),
                "USD": round(float(cash.get("USD", 0.0)), 2)
            },
            "realized_pnl": {
                "CNY": round(float(realized_pnl.get("CNY", 0.0)), 2),
                "HKD": round(float(realized_pnl.get("HKD", 0.0)), 2),
                "USD": round(float(realized_pnl.get("USD", 0.0)), 2)
            },
            "positions_value": positions_value_by_currency,
            "equity": {
                "CNY": round(float(cash.get("CNY", 0.0)) + positions_value_by_currency["CNY"], 2),
                "HKD": round(float(cash.get("HKD", 0.0)) + positions_value_by_currency["HKD"], 2),
                "USD": round(float(cash.get("USD", 0.0)) + positions_value_by_currency["USD"], 2)
            },
            "updated_at": acc.get("updated_at"),
        }

        return {"account": summary, "positions": detailed_positions}

    async def place_order(
        self,
        user_id: str,
        code: str,
        side: str,
        quantity: int,
        market: Optional[str] = None,
        analysis_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """处理下订单逻辑"""
        db = self.get_db()

        if market:
            market_type = market.upper()
            normalized_code = code
        else:
            market_type, normalized_code = detect_market_and_code(code)

        currency_map = {"CN": "CNY", "HK": "HKD", "US": "USD"}
        currency = currency_map.get(market_type, "CNY")

        acc = await self.get_or_create_account(user_id)

        price = await self.get_last_price(normalized_code, market_type)
        if price is None or price <= 0:
            raise ValueError(f"无法获取股票 {normalized_code} ({market_type}) 的最新价格")

        notional = round(price * quantity, 2)
        rules = await self.get_market_rules(market_type)
        commission = self.calculate_commission(market_type, side, notional, rules)
        total_cost = notional + commission

        pos = await db["paper_positions"].find_one({"user_id": user_id, "code": normalized_code})
        now_iso = datetime.utcnow().isoformat()
        realized_pnl_delta = 0.0

        try:
            if side == "buy":
                cash = acc.get("cash", {})
                available_cash = float(cash.get(currency, 0.0)) if isinstance(cash, dict) else (float(cash) if currency == "CNY" else 0.0)

                if available_cash < total_cost:
                    raise ValueError(f"可用{currency}不足：需要 {total_cost:.2f}，可用 {available_cash:.2f}")

                new_cash = round(available_cash - total_cost, 2)
                await db["paper_accounts"].update_one(
                    {"user_id": user_id},
                    {"$set": {f"cash.{currency}": new_cash, "updated_at": now_iso}}
                )

                if not pos:
                    new_pos = {
                        "user_id": user_id,
                        "code": normalized_code,
                        "market": market_type,
                        "currency": currency,
                        "quantity": quantity,
                        "available_qty": quantity if market_type != "CN" else 0,
                        "frozen_qty": 0,
                        "avg_cost": price,
                        "updated_at": now_iso
                    }
                    await db["paper_positions"].insert_one(new_pos)
                else:
                    old_qty = int(pos.get("quantity", 0))
                    old_cost = float(pos.get("avg_cost", 0.0))
                    new_qty = old_qty + quantity
                    new_avg = round((old_cost * old_qty + price * quantity) / new_qty, 4) if new_qty > 0 else price
                    new_available = pos.get("available_qty", old_qty) if market_type == "CN" else new_qty

                    await db["paper_positions"].update_one(
                        {"_id": pos["_id"]},
                        {"$set": {
                            "quantity": new_qty,
                            "available_qty": new_available,
                            "avg_cost": new_avg,
                            "updated_at": now_iso
                        }}
                    )

            else:  # sell
                available_qty = await self.get_available_quantity(user_id, normalized_code, market_type)
                if available_qty < quantity:
                    raise ValueError(f"可用持仓不足：需要 {quantity}，可用 {available_qty}")

                old_qty = int(pos.get("quantity", 0))
                avg_cost = float(pos.get("avg_cost", 0.0))
                new_qty = old_qty - quantity
                realized_pnl_delta = round((price - avg_cost) * quantity, 2)

                net_proceeds = notional - commission
                await db["paper_accounts"].update_one(
                    {"user_id": user_id},
                    {
                        "$inc": {
                            f"cash.{currency}": net_proceeds,
                            f"realized_pnl.{currency}": realized_pnl_delta
                        },
                        "$set": {"updated_at": now_iso}
                    }
                )

                if new_qty == 0:
                    await db["paper_positions"].delete_one({"_id": pos["_id"]})
                else:
                    new_available = max(0, pos.get("available_qty", old_qty) - quantity)
                    await db["paper_positions"].update_one(
                        {"_id": pos["_id"]},
                        {"$set": {
                            "quantity": new_qty,
                            "available_qty": new_available,
                            "updated_at": now_iso
                        }}
                    )

            order_doc = {
                "user_id": user_id,
                "code": normalized_code,
                "market": market_type,
                "currency": currency,
                "side": side,
                "quantity": quantity,
                "price": price,
                "amount": notional,
                "commission": commission,
                "status": "filled",
                "created_at": now_iso,
                "filled_at": now_iso,
            }
            if analysis_id:
                order_doc["analysis_id"] = analysis_id
            await db["paper_orders"].insert_one(order_doc)

            trade_doc = {
                "user_id": user_id,
                "code": normalized_code,
                "market": market_type,
                "currency": currency,
                "side": side,
                "quantity": quantity,
                "price": price,
                "amount": notional,
                "commission": commission,
                "pnl": realized_pnl_delta if side == "sell" else 0.0,
                "timestamp": now_iso,
            }
            if analysis_id:
                trade_doc["analysis_id"] = analysis_id
            await db["paper_trades"].insert_one(trade_doc)

            return {k: v for k, v in order_doc.items() if k != "_id"}

        except Exception as e:
            # 记录多集合一致性更新边界记录
            logger.error(f"❌ 多集合更新存在一致性风险 user_id={user_id}, code={normalized_code}: {e}")
            await db["paper_consistency_logs"].insert_one({
                "user_id": user_id,
                "code": normalized_code,
                "error": str(e),
                "timestamp": now_iso
            })
            raise

    async def list_positions(self, user_id: str) -> List[Dict[str, Any]]:
        """列出用户持仓"""
        db = self.get_db()
        items = await db["paper_positions"].find({"user_id": user_id}).to_list(None) if hasattr(db["paper_positions"].find({"user_id": user_id}), "to_list") else await db["paper_positions"].find({"user_id": user_id})
        enriched: List[Dict[str, Any]] = []
        for p in items:
            code = p.get("code")
            market = p.get("market", "CN")
            currency = p.get("currency", "CNY")
            qty = int(p.get("quantity", 0))
            available_qty = p.get("available_qty", qty)
            avg_cost = float(p.get("avg_cost", 0.0))

            last = await self.get_last_price(code, market)
            mkt = round((last or 0.0) * qty, 2)
            enriched.append({
                "code": code,
                "market": market,
                "currency": currency,
                "quantity": qty,
                "available_qty": available_qty,
                "avg_cost": avg_cost,
                "last_price": last,
                "market_value": mkt,
                "unrealized_pnl": None if last is None else round((last - avg_cost) * qty, 2)
            })
        return enriched

    async def list_orders(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """列出用户订单历史"""
        db = self.get_db()
        cursor = db["paper_orders"].find({"user_id": user_id}).sort("created_at", -1).limit(limit)
        items = await cursor.to_list(None) if hasattr(cursor, "to_list") else await cursor
        return [{k: v for k, v in it.items() if k != "_id"} for it in items]

    async def reset_account(self, user_id: str) -> Dict[str, Any]:
        """重置用户账户"""
        db = self.get_db()
        await db["paper_accounts"].delete_many({"user_id": user_id})
        await db["paper_positions"].delete_many({"user_id": user_id})
        await db["paper_orders"].delete_many({"user_id": user_id})
        await db["paper_trades"].delete_many({"user_id": user_id})
        acc = await self.get_or_create_account(user_id)
        return acc
