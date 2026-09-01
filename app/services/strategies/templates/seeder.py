"""Idempotent persistence for immutable system strategy templates."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from app.models.strategy import (
    SYSTEM_USER_ID,
    Strategy,
    StrategyVersion,
    StrategyVersionStatus,
    StrategyVisibility,
)
from app.repositories.strategy_repository import StrategyConflict, StrategyRepository
from app.services.strategies.templates.catalog import (
    SYSTEM_STRATEGY_TEMPLATES,
    SystemStrategyTemplate,
)
from app.services.strategies.validator import StrategyDSLValidator
from app.services.strategies.version_service import StrategyVersionService


TEMPLATE_SEEDED_AT = datetime(2025, 1, 1, tzinfo=timezone.utc)


class SystemTemplateSeedConflict(StrategyConflict):
    """A stable system-template identity already contains different content."""


async def seed_system_strategy_templates(
    repository: StrategyRepository,
    *,
    validator: StrategyDSLValidator | None = None,
    clock: Callable[[], datetime] = lambda: TEMPLATE_SEEDED_AT,
) -> tuple[tuple[Strategy, StrategyVersion], ...]:
    """Create missing templates and verify existing ones without mutating them.

    Stable strategy/version IDs make retries and concurrent migration runners
    converge on one resource.  Existing published content is verified rather
    than overwritten because published definitions are immutable.
    """

    await repository.ensure_indexes()
    dsl_validator = validator or StrategyDSLValidator(clock=clock)
    seeded: list[tuple[Strategy, StrategyVersion]] = []
    for template in SYSTEM_STRATEGY_TEMPLATES:
        report = dsl_validator.validate(
            template.definition_copy(), market=template.market, user_id=SYSTEM_USER_ID
        )
        if not report.valid:
            details = "; ".join(issue.message for issue in report.errors)
            raise RuntimeError(f"invalid system template {template.template_id}: {details}")
        existing = await _load_existing(repository, template)
        if existing is not None:
            seeded.append(_verify_existing(template, existing, report.factor_dependencies))
            continue

        identifiers = iter((template.strategy_id, template.strategy_version_id))
        service = StrategyVersionService(
            repository,
            clock=clock,
            id_factory=lambda: next(identifiers),
        )
        try:
            pair = await service.create_system_template(
                name=template.name,
                description=template.description,
                tags=("system-template", template.template_id, "v1"),
                kind=template.kind,
                market=template.market,
                definition=template.definition_copy(),
                validation_result=report.as_lifecycle_result(),
                factor_dependencies=report.factor_dependencies,
                change_summary=f"Seed system template {template.template_id} v1",
            )
        except StrategyConflict:
            # Another migration runner may have inserted the stable ID between
            # our read and create.  Reload and accept only byte-equivalent
            # immutable content.
            existing = await _load_existing(repository, template)
            if existing is None:
                raise
            pair = _verify_existing(template, existing, report.factor_dependencies)
        seeded.append(pair)
    return tuple(seeded)


async def _load_existing(
    repository: StrategyRepository, template: SystemStrategyTemplate
) -> tuple[Strategy, StrategyVersion] | None:
    strategy = await repository.get_strategy(
        template.strategy_id,
        user_id=SYSTEM_USER_ID,
        include_archived=True,
        include_readonly=False,
    )
    if strategy is None:
        return None
    version = await repository.get_version(
        template.strategy_version_id,
        user_id=SYSTEM_USER_ID,
        include_system=True,
    )
    if version is None:
        raise SystemTemplateSeedConflict(
            f"{template.template_id} exists without its stable v1 resource"
        )
    return strategy, version


def _verify_existing(
    template: SystemStrategyTemplate,
    pair: tuple[Strategy, StrategyVersion],
    factor_dependencies,
) -> tuple[Strategy, StrategyVersion]:
    strategy, version = pair
    expected_header = {
        "strategy_id": template.strategy_id,
        "user_id": SYSTEM_USER_ID,
        "name": template.name,
        "description": template.description,
        "tags": ("system-template", template.template_id, "v1"),
        "kind": template.kind,
        "visibility": StrategyVisibility.SYSTEM,
        "current_draft_version_id": None,
        "latest_published_version_id": template.strategy_version_id,
        "archived_at": None,
    }
    actual_header = {key: getattr(strategy, key) for key in expected_header}
    expected_version = {
        "strategy_version_id": template.strategy_version_id,
        "strategy_id": template.strategy_id,
        "user_id": SYSTEM_USER_ID,
        "version": template.version,
        "status": StrategyVersionStatus.PUBLISHED,
        "market": template.market,
        "definition": template.definition_copy(),
        "factor_dependencies": tuple(factor_dependencies),
        "skill_dependencies": (),
        "created_by": SYSTEM_USER_ID,
        "change_summary": f"Seed system template {template.template_id} v1",
    }
    actual_version = {key: getattr(version, key) for key in expected_version}
    if actual_header != expected_header or actual_version != expected_version:
        raise SystemTemplateSeedConflict(
            f"immutable system template {template.template_id} conflicts with catalog v1"
        )
    return strategy, version
