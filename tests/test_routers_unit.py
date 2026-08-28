#!/usr/bin/env python3
"""
路由单元测试 - 隔离外部依赖(MongoDB/Redis/外部API)

验证目标:
1. 所有路由可正确挂载
2. 接口参数校验生效
3. 已修复接口(model_capabilities批量初始化、stocks港股新闻)的核心逻辑正确
4. 响应格式符合 {success, data, message, timestamp} 契约

运行方式:
    cd /Users/snow/Documents/opensource/AI/TradingAgents-CN
    pytest tests/test_routers_unit.py -v
"""
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

# 确保项目根目录在 sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 在导入 app 模块前设置环境变量,避免 settings 校验失败与 Docker 路径
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-unit-test-only-xxxxxxxxxx')
os.environ.setdefault('MONGO_URI', 'mongodb://localhost:27017/test')
os.environ.setdefault('MONGO_DB', 'test_db')
os.environ.setdefault('REDIS_URL', 'redis://localhost:6379/0')
os.environ.setdefault('TRADINGAGENTS_LOG_DIR', os.path.join(PROJECT_ROOT, 'logs'))
os.environ.setdefault('TRADINGAGENTS_LOG_FILE', os.path.join(PROJECT_ROOT, 'logs', 'tradingagents.log'))
os.environ.setdefault('USE_MONGODB_STORAGE', 'false')

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ==================== 公共夹具 ====================

_FAKE_USER = {
    "id": "test-user-id",
    "username": "test_user",
    "email": "test@example.com",
    "name": "test_user",
    "is_admin": True,
    "roles": ["admin"],
    "preferences": {},
}


def _build_app() -> FastAPI:
    """构建一个最小化的 FastAPI 应用,仅挂载被测路由"""
    app = FastAPI()
    from app.routers import health, model_capabilities, stocks
    from app.routers.auth_db import get_current_user

    # 用 dependency_overrides 替换认证依赖,避免触发真实 token 校验与 MongoDB
    async def _override_auth():
        return _FAKE_USER

    app.dependency_overrides[get_current_user] = _override_auth
    app.include_router(health.router, prefix="/api")
    app.include_router(model_capabilities.router)
    app.include_router(stocks.router, prefix="/api")
    return app


# ==================== health 路由测试(无外部依赖) ====================

def test_health_endpoint():
    """健康检查接口应返回 200 且包含版本字段"""
    app = _build_app()
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"
    assert "version" in body["data"]
    assert "timestamp" in body["data"]


def test_healthz_and_readyz():
    """K8s 健康检查端点"""
    app = _build_app()
    client = TestClient(app)
    assert client.get("/api/healthz").json()["status"] == "ok"
    assert client.get("/api/readyz").json()["ready"] is True


# ==================== model_capabilities 路由测试 ====================

def test_get_default_model_configs():
    """GET /api/model-capabilities/default-configs 应返回预置配置"""
    app = _build_app()
    client = TestClient(app)
    r = client.get("/api/model-capabilities/default-configs")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert isinstance(body["data"], dict)
    assert len(body["data"]) > 0
    # 每个配置项都应包含必需字段
    for name, cfg in body["data"].items():
        assert "capability_level" in cfg
        assert "suitable_roles" in cfg
        assert "features" in cfg
        assert "recommended_depths" in cfg


def test_get_depth_requirements():
    """GET /api/model-capabilities/depth-requirements 应返回深度要求"""
    app = _build_app()
    client = TestClient(app)
    r = client.get("/api/model-capabilities/depth-requirements")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "快速" in body["data"]
    assert "标准" in body["data"]
    assert "深度" in body["data"]
    # 校验字段完整性
    for depth, req in body["data"].items():
        assert {"min_capability", "quick_model_min", "deep_model_min", "required_features", "description"} <= set(req.keys())


def test_get_capability_descriptions():
    """GET /api/model-capabilities/capability-descriptions"""
    app = _build_app()
    client = TestClient(app)
    r = client.get("/api/model-capabilities/capability-descriptions")
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_get_all_badges():
    """GET /api/model-capabilities/badges 应返回徽章配置"""
    app = _build_app()
    client = TestClient(app)
    r = client.get("/api/model-capabilities/badges")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "capability_levels" in body["data"]
    assert "roles" in body["data"]
    assert "features" in body["data"]


def test_recommend_models_success():
    """POST /api/model-capabilities/recommend 应返回推荐模型对"""
    app = _build_app()
    client = TestClient(app)
    r = client.post("/api/model-capabilities/recommend", json={"research_depth": "标准"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    assert "quick_model" in data
    assert "deep_model" in data
    assert "quick_model_info" in data
    assert "deep_model_info" in data
    assert "reason" in data


def test_recommend_models_invalid_depth():
    """无效的研究深度应仍能返回(后端有默认回退)"""
    app = _build_app()
    client = TestClient(app)
    r = client.post("/api/model-capabilities/recommend", json={"research_depth": "不存在的深度"})
    # 服务端会回退到"标准",不应返回 422/500
    assert r.status_code == 200, r.text


def test_validate_models():
    """POST /api/model-capabilities/validate 验证模型对"""
    app = _build_app()
    client = TestClient(app)
    r = client.post("/api/model-capabilities/validate", json={
        "quick_model": "qwen-turbo",
        "deep_model": "qwen-plus",
        "research_depth": "标准",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert "valid" in body["data"]
    assert "warnings" in body["data"]
    assert "recommendations" in body["data"]


def test_get_model_capability_by_name():
    """GET /api/model-capabilities/model/{model_name}"""
    app = _build_app()
    client = TestClient(app)
    # mock capability_service 避免连 MongoDB
    fake_cfg = {"model_name": "qwen-plus", "capability_level": 3, "suitable_roles": ["analyst"], "features": []}
    with patch('app.routers.model_capabilities.get_model_capability_service') as mock_svc:
        mock_svc.return_value.get_model_config.return_value = fake_cfg
        r = client.get("/api/model-capabilities/model/qwen-plus")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["data"]["model_name"] == "qwen-plus"
    assert body["data"]["capability_level"] == 3


def test_batch_init_saves_to_db():
    """
    POST /api/model-capabilities/batch-init 应真正调用 config_service.update_llm_config 持久化
    这是本次修复的核心断言:之前是 TODO 不保存
    """
    app = _build_app()
    client = TestClient(app)

    # 构造一个内存中的 LLMConfig 列表
    from app.models.config import LLMConfig
    fake_configs = [
        LLMConfig(provider="qwen", model_name="qwen-plus"),
        LLMConfig(provider="unknown", model_name="nonexistent-model"),
    ]

    with patch('app.routers.model_capabilities.unified_config.get_llm_configs', return_value=fake_configs):
        with patch('app.routers.model_capabilities.config_service.update_llm_config', new=AsyncMock(return_value=True)) as mock_save:
            r = client.post("/api/model-capabilities/batch-init", json={"overwrite": True})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    # qwen-plus 在 DEFAULT_MODEL_CAPABILITIES 中,应被更新;nonexistent 不在,应被跳过
    assert data["updated_count"] == 1
    assert data["skipped_count"] == 1
    assert data["total_count"] == 2
    # 核心断言:保存方法被调用过一次
    mock_save.assert_awaited_once()
    # 传入保存的应是已填充能力字段的 LLMConfig
    saved_arg = mock_save.await_args.args[0]
    assert saved_arg.model_name == "qwen-plus"
    assert saved_arg.capability_level is not None


def test_batch_init_save_failure_counts_as_skipped():
    """当 config_service.update_llm_config 返回 False 时,该模型应计入 skipped 而非 updated"""
    app = _build_app()
    client = TestClient(app)

    from app.models.config import LLMConfig
    fake_configs = [LLMConfig(provider="qwen", model_name="qwen-plus")]

    with patch('app.routers.model_capabilities.unified_config.get_llm_configs', return_value=fake_configs):
        with patch('app.routers.model_capabilities.config_service.update_llm_config', new=AsyncMock(return_value=False)):
            r = client.post("/api/model-capabilities/batch-init", json={"overwrite": True})

    assert r.status_code == 200
    body = r.json()
    assert body["data"]["updated_count"] == 0
    assert body["data"]["skipped_count"] == 1


# ==================== stocks 路由测试(港股新闻修复) ====================

def test_detect_market_and_code_logic():
    """直接测试市场识别函数,覆盖 A股/港股/美股"""
    from app.routers.stocks import _detect_market_and_code
    assert _detect_market_and_code("600519") == ("CN", "600519")
    assert _detect_market_and_code("00700") == ("HK", "00700")
    assert _detect_market_and_code("0700.HK") == ("HK", "00700")
    assert _detect_market_and_code("AAPL") == ("US", "AAPL")


def test_hk_news_calls_foreign_stock_service():
    """
    GET /api/stocks/{code}/news 对港股应调用 ForeignStockService.get_hk_news
    这是本次修复的核心断言:之前直接返回空数据
    """
    app = _build_app()
    client = TestClient(app)

    fake_result = {"code": "00700", "days": 30, "limit": 50, "source": "akshare", "items": [{"title": "x"}]}

    with patch('app.services.foreign_stock_service.ForeignStockService.get_hk_news', new=AsyncMock(return_value=fake_result)) as mock_hk:
        r = client.get("/api/stocks/0700.HK/news", params={"days": 30, "limit": 50})

    assert r.status_code == 200, r.text
    body = r.json()
    mock_hk.assert_awaited_once()
    # 返回的 data 应是 service 的真实结果(而非空 items)
    assert body["data"]["source"] == "akshare"
    assert len(body["data"]["items"]) == 1


def test_hk_news_not_returning_empty():
    """港股新闻不应再返回空 items(回归测试)"""
    app = _build_app()
    client = TestClient(app)
    fake_result = {"code": "00700", "days": 30, "limit": 50, "source": "akshare",
                   "items": [{"title": "tesla news", "url": "http://x"}]}

    with patch('app.services.foreign_stock_service.ForeignStockService.get_hk_news', new=AsyncMock(return_value=fake_result)):
        r = client.get("/api/stocks/00700/news")
    assert r.status_code == 200
    data = r.json()["data"]
    # 关键回归:不再返回 source='none' 和空 items
    assert data["source"] != "none"
    assert len(data["items"]) > 0


# ==================== 响应格式契约测试 ====================

def test_ok_response_contract():
    """ok() 辅助函数应返回统一契约"""
    from app.core.response import ok
    r = ok({"a": 1}, "msg")
    assert r["success"] is True
    assert r["data"] == {"a": 1}
    assert r["message"] == "msg"
    assert "timestamp" in r


def test_fail_response_contract():
    from app.core.response import fail
    r = fail("err", 400, {"b": 2})
    assert r["success"] is False
    assert r["message"] == "err"
    assert r["code"] == 400
    assert r["data"] == {"b": 2}


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])
