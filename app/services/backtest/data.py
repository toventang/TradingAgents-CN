"""Point-in-time daily input assembly for the backtest engine."""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable

from app.models.backtest import (
    BacktestRequest,
    BacktestInputBundle,
    BiasWarning,
    BiasWarningCode,
    DailyBacktestInput,
)
from app.models.market_data import DataQualityStatus, NewsSocialInput, PointInTimeFact
from app.models.symbol import Market
from app.repositories.backtest_repository import BacktestInputRepository
from app.services.calendars.market_calendar import DateLike, MarketCalendarService
from app.services.market_data.market_data_service import MarketDataReadService


class PointInTimeBacktestDataService:
    """Resolve each daily slice using only information known by that close."""

    def __init__(
        self,
        *,
        repository: BacktestInputRepository | None = None,
        market_data: MarketDataReadService | None = None,
        calendar: type[MarketCalendarService] = MarketCalendarService,
    ):
        self._repository = repository or BacktestInputRepository()
        self._market_data = market_data or MarketDataReadService()
        self._calendar = calendar

    def validate_request_window(
        self,
        request: BacktestRequest,
        *,
        holidays: Iterable[DateLike] = (),
        minimum_sessions: int = 60,
    ) -> tuple[date, ...]:
        """Validate the deterministic calendar portion of section 2.3."""

        if minimum_sessions < 1:
            raise ValueError("minimum_sessions must be positive")
        trade_dates = tuple(
            date.fromisoformat(item)
            for item in self._calendar.get_trading_days(
                request.market,
                request.start_date,
                request.end_date,
                holidays=holidays,
            )
        )
        if len(trade_dates) < minimum_sessions:
            raise ValueError(
                f"backtest requires at least {minimum_sessions} trading sessions; "
                f"found {len(trade_dates)}"
            )
        return trade_dates

    async def build_bundle(
        self,
        *,
        market: Market | str,
        universe_id: str,
        benchmark_id: str,
        start_date: date,
        end_date: date,
        holidays: Iterable[DateLike] = (),
    ) -> BacktestInputBundle:
        normalized_market = Market(market)
        await self._repository.ensure_indexes()
        trade_dates = tuple(
            date.fromisoformat(item)
            for item in self._calendar.get_trading_days(
                normalized_market, start_date, end_date, holidays=holidays
            )
        )
        days = []
        for trade_date in trade_dates:
            days.append(
                await self.build_day(
                    market=normalized_market,
                    universe_id=universe_id,
                    benchmark_id=benchmark_id,
                    trade_date=trade_date,
                    holidays=holidays,
                )
            )
        bundle_warnings: tuple[BiasWarning, ...] = ()
        if not days:
            bundle_warnings = (
                BiasWarning(
                    code=BiasWarningCode.MISSING_POINT_IN_TIME,
                    message="requested interval contains no trading sessions",
                    market=normalized_market,
                ),
            )
        return BacktestInputBundle(
            market=normalized_market,
            start_date=start_date,
            end_date=end_date,
            days=tuple(days),
            bias_warnings=bundle_warnings,
        )

    async def build_day(
        self,
        *,
        market: Market | str,
        universe_id: str,
        benchmark_id: str,
        trade_date: date,
        holidays: Iterable[DateLike] = (),
    ) -> DailyBacktestInput:
        normalized_market = Market(market)
        signal_as_of = self._calendar.daily_as_of(
            normalized_market, trade_date, holidays=holidays
        )
        memberships = await self._repository.list_universe_memberships(
            universe_id,
            normalized_market,
            trade_date=trade_date,
            as_of=signal_as_of,
        )
        warnings: list[BiasWarning] = []
        if not memberships:
            warnings.append(
                BiasWarning(
                    code=BiasWarningCode.MISSING_UNIVERSE_HISTORY,
                    message=(
                        "no point-in-time universe membership exists for this date; "
                        "current constituents were not substituted"
                    ),
                    market=normalized_market,
                    trade_date=trade_date,
                    source=universe_id,
                )
            )

        bars = []
        facts: list[PointInTimeFact] = []
        news: list[NewsSocialInput] = []
        social: list[NewsSocialInput] = []
        source_versions: dict[str, set[str]] = {
            "universe": {item.source_version for item in memberships}
        }
        for membership in memberships:
            symbol = membership.symbol
            bar_batch = await self._market_data.read_daily_bars(
                symbol,
                normalized_market,
                start_date=trade_date,
                end_date=trade_date,
                as_of=signal_as_of,
            )
            matching_bars = [item for item in bar_batch.items if item.trade_date == trade_date]
            if bar_batch.quality.status not in {
                DataQualityStatus.VALID,
                DataQualityStatus.PARTIAL,
            }:
                warnings.append(
                    BiasWarning(
                        code=BiasWarningCode.UNSAFE_DATA_QUALITY,
                        message=(
                            "daily bar quality is not safe for automated decisions: "
                            f"{bar_batch.quality.reason_code}"
                        ),
                        market=normalized_market,
                        trade_date=trade_date,
                        symbol=symbol,
                    )
                )
                matching_bars = []
            if not matching_bars:
                warnings.append(
                    BiasWarning(
                        code=BiasWarningCode.MISSING_DAILY_BAR,
                        message="historical universe member has no daily bar",
                        market=normalized_market,
                        trade_date=trade_date,
                        symbol=symbol,
                    )
                )
            else:
                bars.extend(matching_bars)
                source_versions.setdefault("daily_bars", set()).update(
                    item.source_version for item in matching_bars
                )

            fact_batch = await self._market_data.read_point_in_time_facts(
                symbol, normalized_market, as_of=signal_as_of
            )
            visible_facts = self.financial_facts_visible_on(
                fact_batch.items,
                market=normalized_market,
                trade_date=trade_date,
                holidays=holidays,
            )
            facts.extend(visible_facts)
            source_versions.setdefault("financial_facts", set()).update(
                item.source_version for item in visible_facts
            )
            if fact_batch.quality.reason_code == "PUBLICATION_TIME_MISSING":
                warnings.append(
                    BiasWarning(
                        code=BiasWarningCode.MISSING_PUBLICATION_TIME,
                        message="financial records without publication time were excluded",
                        market=normalized_market,
                        trade_date=trade_date,
                        symbol=symbol,
                    )
                )

            for kind, reader, target in (
                ("news", self._market_data.read_news_inputs, news),
                ("social", self._market_data.read_social_inputs, social),
            ):
                batch = await reader(symbol, normalized_market, as_of=signal_as_of)
                visible_items = self.event_inputs_visible_at(batch.items, signal_as_of)
                target.extend(visible_items)
                source_versions.setdefault(kind, set()).update(
                    item.source_version for item in visible_items
                )
                if batch.quality.reason_code == "VISIBILITY_TIMESTAMP_MISSING":
                    warnings.append(
                        BiasWarning(
                            code=BiasWarningCode.MISSING_INGESTION_TIME,
                            message=f"{kind} records without complete visibility times were excluded",
                            market=normalized_market,
                            trade_date=trade_date,
                            symbol=symbol,
                        )
                    )

        actions = await self._repository.list_corporate_actions(
            normalized_market,
            symbols=(item.symbol for item in memberships),
            start_date=trade_date,
            end_date=trade_date,
            as_of=signal_as_of,
        )
        benchmark = await self._repository.get_benchmark_bar(
            benchmark_id,
            normalized_market,
            trade_date=trade_date,
            as_of=signal_as_of,
        )
        if benchmark is None:
            warnings.append(
                BiasWarning(
                    code=BiasWarningCode.MISSING_BENCHMARK,
                    message="benchmark bar is unavailable at the daily cutoff",
                    market=normalized_market,
                    trade_date=trade_date,
                    source=benchmark_id,
                )
            )
        else:
            source_versions.setdefault("benchmark", set()).add(benchmark.source_version)
        market_rule = await self._repository.get_market_rule(
            normalized_market, trade_date=trade_date, as_of=signal_as_of
        )
        if market_rule is None:
            warnings.append(
                BiasWarning(
                    code=BiasWarningCode.MISSING_MARKET_RULE,
                    message="no dated market-rule version is visible for this session",
                    market=normalized_market,
                    trade_date=trade_date,
                )
            )
        else:
            source_versions.setdefault("market_rules", set()).add(
                market_rule.rule_version_id
            )
        source_versions.setdefault("corporate_actions", set()).update(
            item.source_version for item in actions
        )

        return DailyBacktestInput(
            market=normalized_market,
            trade_date=trade_date,
            signal_as_of=signal_as_of,
            universe_id=universe_id,
            universe=memberships,
            bars=tuple(sorted(bars, key=lambda item: item.symbol)),
            financial_facts=tuple(sorted(facts, key=lambda item: (item.symbol, item.fact_id))),
            news=tuple(sorted(news, key=lambda item: (item.symbol, item.news_id))),
            social=tuple(sorted(social, key=lambda item: (item.symbol, item.news_id))),
            corporate_actions=actions,
            benchmark=benchmark,
            market_rule=market_rule,
            source_versions={
                key: tuple(sorted(values))
                for key, values in sorted(source_versions.items())
            },
            bias_warnings=tuple(warnings),
        )

    def financial_facts_visible_on(
        self,
        facts: Iterable[PointInTimeFact],
        *,
        market: Market | str,
        trade_date: date,
        holidays: Iterable[DateLike] = (),
    ) -> tuple[PointInTimeFact, ...]:
        """Financial facts become visible on the first session after release."""

        normalized_market = Market(market)
        visible = []
        for fact in facts:
            available_at = max(
                fact.publish_at,
                fact.ingested_at or fact.publish_at,
            ).astimezone(self._calendar.timezone(normalized_market))
            first_visible = date.fromisoformat(
                self._calendar.get_next_trade_day(
                    normalized_market, available_at.date(), holidays=holidays
                )
            )
            if first_visible <= trade_date:
                visible.append(fact)
        return tuple(sorted(visible, key=lambda item: (item.publish_at, item.fact_id)))

    @staticmethod
    def event_inputs_visible_at(
        items: Iterable[NewsSocialInput], signal_as_of: datetime
    ) -> tuple[NewsSocialInput, ...]:
        """Use an event only in a signal window strictly after both timestamps."""

        if signal_as_of.tzinfo is None or signal_as_of.utcoffset() is None:
            raise ValueError("signal_as_of must be timezone-aware")
        return tuple(
            sorted(
                (
                    item
                    for item in items
                    if max(item.published_at, item.ingested_at) < signal_as_of
                ),
                key=lambda item: (item.published_at, item.news_id),
            )
        )


# Concise alias for callers that do not need the implementation qualifier.
BacktestDataService = PointInTimeBacktestDataService
PointInTimeDataService = PointInTimeBacktestDataService
