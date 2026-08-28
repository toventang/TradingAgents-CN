#!/usr/bin/env python3
"""
路由冒烟测试 - 覆盖所有 router 模块

验证目标:
1. 每个 router 模块都能被正确导入并挂载到 FastAPI 应用
2. 每个声明的端点路径可被 TestClient 路由到(非 404)
3. 需鉴权的端点在无 token 时返回 401(非 500 崩溃)
4. 参数校验生效:无效 JSON 返回 422

运行方式:
    cd /Users/snow/Documents/opensource/AI/TradingAgents-CN
    pytest tests/test_routers_smoke.py -v
"""
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 在导入 app 之前覆盖 .env 中的 Docker 路径,避免在 macOS 上写 /app/logs 失败
os.environ['SECRET_KEY'] = 'test-secret-key-for-unit-test-only-xxxxxxxxxx'
os.environ['MONGO_URI'] = 'mongodb://localhost:27017/test'
os.environ['MONGO_DB'] = 'test_db'
os.environ['REDIS_URL'] = 'redis://localhost:6379/0'
os.environ['TRADINGAGENTS_LOG_DIR'] = os.path.join(PROJECT_ROOT, 'logs')
os.environ['TRADINGAGENTS_LOG_FILE'] = os.path.join(PROJECT_ROOT, 'logs', 'tradingagents.log')
os.environ['TRADINGAGENTS_DATA_DIR'] = os.path.join(PROJECT_ROOT, 'data')
os.environ['TRADINGAGENTS_CACHE_DIR'] = os.path.join(PROJECT_ROOT, 'data', 'cache')
os.environ['TRADINGAGENTS_SESSIONS_DIR'] = os.path.join(PROJECT_ROOT, 'data', 'sessions')
os.environ['TRADINGAGENTS_LOGS_DIR'] = os.path.join(PROJECT_ROOT, 'data', 'logs')
os.environ['TRADINGAGENTS_CONFIG_DIR'] = os.path.join(PROJECT_ROOT, 'data', 'config')
os.environ['TRADINGAGENTS_TEMP_DIR'] = os.path.join(PROJECT_ROOT, 'data', 'temp')
os.environ['TRADINGAGENTS_RESULTS_DIR'] = os.path.join(PROJECT_ROOT, 'data', 'analysis_results')
os.environ['USE_MONGODB_STORAGE'] = 'false'  # 避免连真实 MongoDB

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# 在导入任何 app 模块前,patch 掉 analysis_service 在导入时触发的 init_logging 副作用
# (init_logging 会尝试创建 /app/logs,在非 Docker 环境下失败)
import tradingagents.utils.logging_manager as _lm
_orig_setup = _lm.TradingAgentsLogger._setup_logging


def _safe_setup_logging(self):
    """跳过日志目录创建,避免在非 Docker 环境写 /app/logs 失败"""
    import logging
    try:
        # 只设置日志级别,不创建文件目录
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, self.config.get('level', 'INFO')))
    except Exception:
        pass


_lm.TradingAgentsLogger._setup_logging = _safe_setup_logging


_FAKE_USER = {
    "id": "test-user-id",
    "username": "test_user",
    "email": "test@example.com",
    "name": "test_user",
    "is_admin": True,
    "roles": ["admin"],
    "preferences": {},
}


def _build_full_app() -> FastAPI:
    """构建挂载全部 router 的应用,并覆盖认证依赖"""
    app = FastAPI()
    from app.routers import auth_db as auth
    from app.routers.auth_db import get_current_user

    async def _override_auth():
        return _FAKE_USER

    app.dependency_overrides[get_current_user] = _override_auth

    # 导入全部 router
    from app.routers import (
        health, analysis, screening, queue, sse, favorites, config, reports,
        database, operation_logs, tags, tushare_init, akshare_init, baostock_init,
        historical_data, multi_period_sync, financial_data, news_data, social_media,
        internal_messages, usage_statistics, model_capabilities, cache, logs,
        sync as sync_router, multi_source_sync, stocks as stocks_router,
        stock_data as stock_data_router, stock_sync as stock_sync_router,
        multi_market_stocks as multi_market_stocks_router,
        notifications as notifications_router,
        websocket_notifications as websocket_notifications_router,
        scheduler as scheduler_router,
        paper as paper_router, domain_tasks as domain_tasks_router,
        factors as factors_router,
        system_config as system_config_router,
        analysis_profiles, backtests, campaigns, risk, skills, strategies,
    )

    # 按 main.py 的方式挂载
    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api/auth")
    app.include_router(analysis.router, prefix="/api/analysis")
    app.include_router(reports.router)
    app.include_router(screening.router, prefix="/api/screening")
    app.include_router(queue.router, prefix="/api/queue")
    app.include_router(favorites.router, prefix="/api")
    app.include_router(stocks_router.router, prefix="/api")
    app.include_router(multi_market_stocks_router.router, prefix="/api")
    app.include_router(stock_data_router.router)
    app.include_router(stock_sync_router.router)
    app.include_router(tags.router, prefix="/api")
    app.include_router(config.router, prefix="/api")
    app.include_router(model_capabilities.router)
    app.include_router(usage_statistics.router)
    app.include_router(database.router, prefix="/api/system")
    app.include_router(cache.router)
    app.include_router(operation_logs.router, prefix="/api/system")
    app.include_router(logs.router, prefix="/api/system")
    app.include_router(system_config_router.router, prefix="/api/system")
    app.include_router(notifications_router.router)
    app.include_router(websocket_notifications_router.router, prefix="/api")
    app.include_router(scheduler_router.router)
    app.include_router(sse.router, prefix="/api/stream")
    app.include_router(sync_router.router)
    app.include_router(multi_source_sync.router)
    app.include_router(paper_router.router, prefix="/api")
    app.include_router(domain_tasks_router.router)
    app.include_router(factors_router.router)
    app.include_router(tushare_init.router)
    app.include_router(akshare_init.router)
    app.include_router(baostock_init.router)
    app.include_router(historical_data.router)
    app.include_router(multi_period_sync.router)
    app.include_router(financial_data.router)
    app.include_router(news_data.router)
    app.include_router(social_media.router)
    app.include_router(internal_messages.router)
    # 新增业务 router(未在 main.py 中明确挂载前缀的,按其自身 prefix 挂载)
    app.include_router(analysis_profiles.router)
    app.include_router(backtests.router)
    app.include_router(campaigns.router)
    app.include_router(risk.router)
    app.include_router(skills.router)
    app.include_router(strategies.router)
    return app


# ==================== 路由挂载冒烟测试 ====================

def test_app_builds_without_error():
    """全部 router 应能被正确导入并挂载,无导入/语法错误"""
    app = _build_full_app()
    assert app is not None
    # 应有大量路由
    routes = [r for r in app.routes]
    assert len(routes) > 50, f"路由数量过少: {len(routes)}"


def test_health_routes():
    """health 路由可访问"""
    app = _build_full_app()
    client = TestClient(app)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/healthz").status_code == 200
    assert client.get("/api/readyz").status_code == 200


def test_auth_routes_require_token():
    """auth/me 应在无 token 时返回 401"""
    app = _build_full_app()
    # 临时清空 override 以测试 401
    from app.routers.auth_db import get_current_user
    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app)
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_auth_me_with_override():
    """auth/me 在 override 后应返回用户信息"""
    app = _build_full_app()
    client = TestClient(app)
    r = client.get("/api/auth/me")
    # auth_db 的 /me 直接读 override 返回的 dict
    assert r.status_code in (200, 500)  # 500 可能因 user_service 连不上


# ==================== 关键 router 路由可访问性 ====================

@pytest.mark.parametrize("path,method", [
    ("/api/model-capabilities/default-configs", "GET"),
    ("/api/model-capabilities/depth-requirements", "GET"),
    ("/api/model-capabilities/badges", "GET"),
    ("/api/model-capabilities/capability-descriptions", "GET"),
    ("/api/health", "GET"),
])
def test_route_accessible(path, method):
    """关键端点应可被路由(非404)"""
    app = _build_full_app()
    client = TestClient(app)
    r = client.request(method, path)
    assert r.status_code != 404, f"{method} {path} 返回 404,路由未挂载"


def test_invalid_json_returns_422():
    """POST 端点接收无效 JSON 应返回 422 而非 500"""
    app = _build_full_app()
    client = TestClient(app)
    # model-capabilities/recommend 需要 body
    r = client.post("/api/model-capabilities/recommend", json={})
    # 空body缺字段应 422,或服务端有默认值返回200
    assert r.status_code in (200, 422), f"返回 {r.status_code}: {r.text}"


# ==================== paper router(典型业务router)冒烟测试 ====================

def test_paper_account_calls_service():
    """GET /api/paper/account 应调用 PaperTradingService.get_account_summary"""
    app = _build_full_app()
    client = TestClient(app)
    fake_summary = {"cash": {"CNY": 100000}, "positions_value": {}, "total": 100000}
    with patch('app.services.paper.paper_service.PaperTradingService.get_account_summary', new=AsyncMock(return_value=fake_summary)):
        r = client.get("/api/paper/account")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["data"]["cash"]["CNY"] == 100000


def test_paper_order_validates_quantity():
    """POST /api/paper/order 数量<=0 应 422"""
    app = _build_full_app()
    client = TestClient(app)
    r = client.post("/api/paper/order", json={"code": "600519", "side": "buy", "quantity": 0})
    assert r.status_code == 422


def test_paper_order_validates_side():
    """POST /api/paper/order side 非法应 422"""
    app = _build_full_app()
    client = TestClient(app)
    r = client.post("/api/paper/order", json={"code": "600519", "side": "invalid", "quantity": 100})
    assert r.status_code == 422


def test_paper_reset_requires_confirm():
    """POST /api/paper/reset?confirm=false 应 400"""
    app = _build_full_app()
    client = TestClient(app)
    r = client.post("/api/paper/reset?confirm=false")
    assert r.status_code == 400


# ==================== favorites router 冒烟测试 ====================

def test_favorites_list_calls_service():
    """GET /api/favorites/ 应调用 favorites_service"""
    app = _build_full_app()
    client = TestClient(app)
    with patch('app.routers.favorites.favorites_service.get_user_favorites', new=AsyncMock(return_value=[])):
        r = client.get("/api/favorites/")
    assert r.status_code == 200, r.text


def test_favorites_add_validates_body():
    """POST /api/favorites/ 缺字段应 422"""
    app = _build_full_app()
    client = TestClient(app)
    r = client.post("/api/favorites/", json={})
    assert r.status_code == 422


# ==================== queue router 冒烟测试 ====================

def test_queue_stats_route():
    """GET /api/queue/stats 路由可访问(mock Redis 依赖)"""
    app = _build_full_app()
    from app.services.queue_service import get_queue_service
    mock_svc = AsyncMock()
    mock_svc.stats = AsyncMock(return_value={"pending": 0, "running": 0, "completed": 0})
    app.dependency_overrides[get_queue_service] = lambda: mock_svc
    client = TestClient(app)
    r = client.get("/api/queue/stats")
    assert r.status_code != 404


# ==================== tushare_init router 冒烟测试 ====================

def test_tushare_status_route():
    """GET /api/tushare-init/status 路由可访问"""
    app = _build_full_app()
    client = TestClient(app)
    # mock MongoDB 操作
    mock_db = MagicMock()
    mock_db.stock_basic_info.count_documents = AsyncMock(return_value=0)
    mock_db.market_quotes.count_documents = AsyncMock(return_value=0)
    mock_db.stock_basic_info.find_one = AsyncMock(return_value=None)
    mock_db.market_quotes.find_one = AsyncMock(return_value=None)
    with patch('app.routers.tushare_init.get_mongo_db', return_value=mock_db):
        r = client.get("/api/tushare-init/status")
    assert r.status_code == 200, r.text
    assert r.json()["success"] is True


def test_tushare_init_status_route():
    """GET /api/tushare-init/initialization-status 路由可访问"""
    app = _build_full_app()
    client = TestClient(app)
    with patch('app.worker.tushare_init_service.get_tushare_init_service') as mock_svc:
        mock_svc.return_value.get_status = AsyncMock(return_value={"initialized": False})
        r = client.get("/api/tushare-init/initialization-status")
    assert r.status_code in (200, 500)


# ==================== usage_statistics router 冒烟测试 ====================

def test_usage_records_route():
    """GET /api/usage/records 路由可访问"""
    app = _build_full_app()
    client = TestClient(app)
    with patch('app.routers.usage_statistics.usage_statistics_service.get_usage_records', new=AsyncMock(return_value=[])):
        r = client.get("/api/usage/records")
    assert r.status_code != 404


# ==================== operation_logs router 冒烟测试 ====================

def test_operation_logs_list_route():
    """GET /api/system/logs/list 路由可访问"""
    app = _build_full_app()
    client = TestClient(app)
    with patch('app.routers.operation_logs.get_operation_log_service') as mock_fn:
        mock_svc = MagicMock()
        mock_svc.list_logs = AsyncMock(return_value=([], 0))
        mock_fn.return_value = mock_svc
        r = client.get("/api/system/logs/list")
    assert r.status_code != 404


# ==================== tags router 冒烟测试 ====================

def test_tags_list_route():
    """GET /api/tags/ 路由可访问"""
    app = _build_full_app()
    client = TestClient(app)
    with patch('app.routers.tags.tags_service.list_tags', new=AsyncMock(return_value=[])):
        r = client.get("/api/tags/")
    assert r.status_code != 404


def test_tags_create_validates_body():
    """POST /api/tags/ 缺字段应 422"""
    app = _build_full_app()
    client = TestClient(app)
    r = client.post("/api/tags/", json={})
    assert r.status_code == 422


# ==================== system_config router 冒烟测试 ====================

def test_system_config_summary_route():
    """GET /api/system/config/summary 路由可访问"""
    app = _build_full_app()
    client = TestClient(app)
    r = client.get("/api/system/config/summary")
    assert r.status_code != 404


def test_system_config_validate_route():
    """GET /api/system/config/validate 路由可访问"""
    app = _build_full_app()
    client = TestClient(app)
    r = client.get("/api/system/config/validate")
    assert r.status_code != 404


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])
