import io
import logging

import pytest
from fastapi import Request, Response

from app.core.logging_context import LoggingContextFilter, REDACTED
from app.middleware import operation_log_middleware as middleware_module
from app.middleware.operation_log_middleware import OperationLogMiddleware
from app.services.auth_service import AuthService, AuthenticatedIdentity

pytestmark = pytest.mark.asyncio


async def asgi_app(_scope, _receive, _send):
    return None


def make_request(headers=None, query_string=b""):
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/analysis/single",
            "query_string": query_string,
            "headers": headers or [],
            "client": ("127.0.0.1", 12345),
            "server": ("test", 80),
            "scheme": "http",
        }
    )


async def test_authorization_header_resolves_real_user(monkeypatch):
    expected = AuthenticatedIdentity(user_id="user-a-id", username="alice")

    async def authenticate(token):
        assert token == "header-token"
        return expected

    monkeypatch.setattr(AuthService, "authenticate_token", staticmethod(authenticate))
    request = make_request(headers=[(b"authorization", b"Bearer header-token")])
    middleware = OperationLogMiddleware(asgi_app)

    user_info = await middleware._get_user_info(request)

    assert user_info["id"] == "user-a-id"
    assert user_info["username"] == "alice"


async def test_operation_log_uses_real_user_and_redacts_query_token(monkeypatch):
    captured = {}

    async def capture_log_operation(**kwargs):
        captured.update(kwargs)
        return "log-id"

    monkeypatch.setattr(middleware_module, "log_operation", capture_log_operation)
    request = make_request(query_string=b"token=complete-secret-token&safe=value")
    middleware = OperationLogMiddleware(asgi_app)

    await middleware._log_operation(
        user_info={"id": "user-a-id", "username": "alice"},
        method="POST",
        path="/api/analysis/single",
        response=Response(status_code=201),
        duration_ms=4,
        ip_address="127.0.0.1",
        user_agent="pytest",
        request=request,
    )

    assert captured["user_id"] == "user-a-id"
    assert captured["username"] == "alice"
    assert captured["details"]["query_params"] == {
        "token": REDACTED,
        "safe": "value",
    }


async def test_logging_filter_removes_bearer_query_and_jwt_values():
    secret = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhbGljZSJ9.signaturevalue"
    prefix_secret = "prefix-only-secret-123"
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(LoggingContextFilter())
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("test.j01.redaction")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    logger.info(
        "Authorization: Bearer %s ws://host/ws?token=%s",
        secret,
        secret,
    )
    logger.info("Authorization header: Bearer %s", prefix_secret)
    logger.info("Authorization header格式错误: %s", prefix_secret)
    logger.info("Token前20位: %s", prefix_secret)

    output = stream.getvalue()
    assert secret not in output
    assert prefix_secret not in output
    assert "[REDACTED]" in output
