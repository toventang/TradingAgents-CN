"""J22 migration: seed the fourteen immutable strategy templates.

The migration is intentionally callable by deployment tooling rather than
executing on import.  It is safe to retry and safe to run concurrently once
the strategy repository indexes exist.
"""

from __future__ import annotations

from app.repositories.strategy_repository import StrategyRepository
from app.services.strategies.templates.seeder import seed_system_strategy_templates


async def run(db=None):
    repository = StrategyRepository(db)
    return await seed_system_strategy_templates(repository)
