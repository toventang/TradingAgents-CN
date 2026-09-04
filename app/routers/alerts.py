"""Authenticated alert rule, event, preview, and health endpoints."""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.core.database import get_mongo_db
from app.routers.auth_db import get_current_user
from app.services.alerts.api_service import AlertApiError, AlertApiService


router = APIRouter(prefix="/alerts", tags=["alerts"])


class RuleVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int | None = Field(default=None, ge=1)


def get_alert_api_service() -> AlertApiService:
    return AlertApiService(get_mongo_db())


def _raise_api_error(exc: AlertApiError) -> NoReturn:
    detail: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if exc.details is not None:
        detail["details"] = exc.details
    raise HTTPException(status_code=exc.status_code, detail=detail) from exc


def _expected_version(if_match: str | None, body_version: int | None = None) -> int:
    if if_match is None:
        if body_version is not None:
            return body_version
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ALERT_RULE_VERSION_CONFLICT",
                "message": "If-Match or a version value is required",
            },
        )
    value = if_match.strip()
    if value.startswith("W/"):
        value = value[2:].strip()
    value = value.strip('"')
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ALERT_RULE_VERSION_CONFLICT",
                "message": "If-Match must contain a positive rule version",
            },
        ) from exc
    if parsed < 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ALERT_RULE_VERSION_CONFLICT",
                "message": "If-Match must contain a positive rule version",
            },
        )
    return parsed


@router.post("/rules", status_code=status.HTTP_201_CREATED)
async def create_alert_rule(
    payload: dict[str, Any],
    current_user: dict = Depends(get_current_user),
    service: AlertApiService = Depends(get_alert_api_service),
) -> dict[str, Any]:
    try:
        rule = await service.create_rule(user_id=current_user["id"], payload=payload)
        return rule.model_dump(mode="json")
    except AlertApiError as exc:
        _raise_api_error(exc)


@router.get("/rules")
async def list_alert_rules(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    enabled: bool | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
    service: AlertApiService = Depends(get_alert_api_service),
) -> dict[str, Any]:
    return await service.list_rules(
        user_id=current_user["id"], page=page, page_size=page_size, enabled=enabled
    )


@router.get("/rules/{rule_id}")
async def get_alert_rule(
    rule_id: str,
    current_user: dict = Depends(get_current_user),
    service: AlertApiService = Depends(get_alert_api_service),
) -> dict[str, Any]:
    try:
        return await service.get_rule_detail(user_id=current_user["id"], rule_id=rule_id)
    except AlertApiError as exc:
        _raise_api_error(exc)


@router.put("/rules/{rule_id}")
async def update_alert_rule(
    rule_id: str,
    payload: dict[str, Any],
    if_match: str | None = Header(default=None, alias="If-Match"),
    current_user: dict = Depends(get_current_user),
    service: AlertApiService = Depends(get_alert_api_service),
) -> dict[str, Any]:
    expected = _expected_version(if_match, payload.pop("version", None))
    try:
        rule = await service.update_rule(
            user_id=current_user["id"],
            rule_id=rule_id,
            expected_version=expected,
            payload=payload,
        )
        return rule.model_dump(mode="json")
    except AlertApiError as exc:
        _raise_api_error(exc)


@router.post("/rules/{rule_id}/enable")
async def enable_alert_rule(
    rule_id: str,
    payload: RuleVersionRequest = RuleVersionRequest(),
    if_match: str | None = Header(default=None, alias="If-Match"),
    current_user: dict = Depends(get_current_user),
    service: AlertApiService = Depends(get_alert_api_service),
) -> dict[str, Any]:
    try:
        rule = await service.set_enabled(
            user_id=current_user["id"],
            rule_id=rule_id,
            expected_version=_expected_version(if_match, payload.version),
            enabled=True,
        )
        return rule.model_dump(mode="json")
    except AlertApiError as exc:
        _raise_api_error(exc)


@router.post("/rules/{rule_id}/disable")
async def disable_alert_rule(
    rule_id: str,
    payload: RuleVersionRequest = RuleVersionRequest(),
    if_match: str | None = Header(default=None, alias="If-Match"),
    current_user: dict = Depends(get_current_user),
    service: AlertApiService = Depends(get_alert_api_service),
) -> dict[str, Any]:
    try:
        rule = await service.set_enabled(
            user_id=current_user["id"],
            rule_id=rule_id,
            expected_version=_expected_version(if_match, payload.version),
            enabled=False,
        )
        return rule.model_dump(mode="json")
    except AlertApiError as exc:
        _raise_api_error(exc)


@router.delete("/rules/{rule_id}")
async def delete_alert_rule(
    rule_id: str,
    version: int | None = Query(default=None, ge=1),
    if_match: str | None = Header(default=None, alias="If-Match"),
    current_user: dict = Depends(get_current_user),
    service: AlertApiService = Depends(get_alert_api_service),
) -> dict[str, Any]:
    try:
        return await service.delete_rule(
            user_id=current_user["id"],
            rule_id=rule_id,
            expected_version=_expected_version(if_match, version),
        )
    except AlertApiError as exc:
        _raise_api_error(exc)


@router.post("/validate")
async def validate_alert_rule(
    payload: dict[str, Any],
    current_user: dict = Depends(get_current_user),
    service: AlertApiService = Depends(get_alert_api_service),
) -> dict[str, Any]:
    try:
        return service.validate_payload(user_id=current_user["id"], payload=payload)
    except AlertApiError as exc:
        _raise_api_error(exc)


@router.post("/preview")
async def preview_alert_rule(
    payload: dict[str, Any],
    current_user: dict = Depends(get_current_user),
    service: AlertApiService = Depends(get_alert_api_service),
) -> dict[str, Any]:
    try:
        return await service.preview(user_id=current_user["id"], payload=payload)
    except AlertApiError as exc:
        _raise_api_error(exc)


@router.post("/rules/{rule_id}/test-notification")
async def test_alert_notification(
    rule_id: str,
    current_user: dict = Depends(get_current_user),
    service: AlertApiService = Depends(get_alert_api_service),
) -> dict[str, Any]:
    try:
        return await service.send_test_notification(
            user_id=current_user["id"], rule_id=rule_id
        )
    except AlertApiError as exc:
        _raise_api_error(exc)


@router.get("/events")
async def list_alert_events(
    rule_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    severity: str | None = Query(default=None, pattern="^(info|warning|critical)$"),
    start_at: AwareDatetime | None = Query(default=None),
    end_at: AwareDatetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    service: AlertApiService = Depends(get_alert_api_service),
) -> dict[str, Any]:
    if start_at is not None and end_at is not None and start_at > end_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "ALERT_INVALID_CONDITION",
                "message": "start_at cannot be after end_at",
            },
        )
    return await service.list_events(
        user_id=current_user["id"],
        page=page,
        page_size=page_size,
        rule_id=rule_id,
        symbol=symbol,
        severity=severity,
        start_at=start_at,
        end_at=end_at,
    )


@router.post("/events/{event_id}/ack")
async def acknowledge_alert_event(
    event_id: str,
    current_user: dict = Depends(get_current_user),
    service: AlertApiService = Depends(get_alert_api_service),
) -> dict[str, Any]:
    try:
        event = await service.acknowledge_event(
            user_id=current_user["id"], event_id=event_id
        )
        return event.model_dump(mode="json")
    except AlertApiError as exc:
        _raise_api_error(exc)


@router.get("/health")
async def get_alert_health(
    current_user: dict = Depends(get_current_user),
    service: AlertApiService = Depends(get_alert_api_service),
) -> dict[str, Any]:
    return await service.health(user_id=current_user["id"])
