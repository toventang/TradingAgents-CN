import pytest
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from app.middleware.operation_log_middleware import OperationLogMiddleware
from app.services.auth_service import AuthService

app = FastAPI()
app.add_middleware(OperationLogMiddleware)

@app.post("/api/analysis/test")
async def dummy_endpoint(request: Request):
    return {"status": "ok"}

def test_operation_log_uses_real_user_identity_and_redacts_tokens():
    client = TestClient(app)

    user_token = AuthService.create_access_token(sub="real_user_123")

    with patch("app.middleware.operation_log_middleware.log_operation", new_callable=AsyncMock) as mock_log:
        response = client.post(
            f"/api/analysis/test?token={user_token}&secret=hidden_value",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200

        mock_log.assert_called_once()
        kwargs = mock_log.call_args.kwargs

        # Real user identity check
        assert kwargs["user_id"] == "real_user_123"
        assert kwargs["username"] == "real_user_123"

        # Token redaction check
        query_params = kwargs["details"]["query_params"]
        assert query_params["token"] == "[REDACTED]"
        assert query_params["secret"] == "[REDACTED]"
