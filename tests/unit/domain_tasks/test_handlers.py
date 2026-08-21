import pytest

from app.models.domain_task import DomainTaskResultRef, DomainTaskType
from app.services.domain_tasks import (
    DomainTaskHandlerRegistry,
    UnknownTaskHandlerError,
    domain_task_handler_registry,
)


async def handler(payload, context, report_progress, is_cancelled):
    return DomainTaskResultRef(collection="results", id="one")


def test_registry_is_explicit_and_rejects_duplicates():
    registry = DomainTaskHandlerRegistry()
    registry.register(DomainTaskType.BACKTEST, handler)

    assert registry.resolve("backtest") is handler
    assert registry.task_types == (DomainTaskType.BACKTEST,)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("backtest", handler)


def test_unknown_type_fails_without_importing_handler():
    registry = DomainTaskHandlerRegistry()

    with pytest.raises(UnknownTaskHandlerError) as exc_info:
        registry.resolve("factor_compute")

    assert exc_info.value.error_code == "TASK_HANDLER_NOT_REGISTERED"
    assert exc_info.value.details == {"task_type": "factor_compute"}


def test_j04_global_registry_has_no_feature_handlers():
    assert domain_task_handler_registry.task_types == ()
