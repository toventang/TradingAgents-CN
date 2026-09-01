"""Versioned, immutable built-in strategy templates."""

from app.services.strategies.templates.catalog import (
    SYSTEM_STRATEGY_TEMPLATES,
    SYSTEM_TEMPLATE_IDS,
    SystemStrategyTemplate,
    get_system_template,
)

__all__ = [
    "SYSTEM_STRATEGY_TEMPLATES",
    "SYSTEM_TEMPLATE_IDS",
    "SystemStrategyTemplate",
    "get_system_template",
]
