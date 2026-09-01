# J22 system strategy template contract

This package is the authoritative version-one catalog for the 14 templates in
strategy specification 1.4. Templates are system-owned, published, viewable and
cloneable, but their published version cannot be edited. A user changes a
template only by cloning it into a private strategy.

Every signal is calculated from point-in-time factor snapshots. A close signal
executes no earlier than the next open. The default benchmark is `CN:000300`,
the fee model is `cn-a-v1`, assumed slippage is 5 bps, the universe excludes ST,
delisting and suspended securities, and the minimum notional is CNY 5,000. All
templates carry this warning: historical signals do not guarantee future
returns; missing data, suspension, price limits and costs can prevent execution.

| Template | Entry formula (default) | Exit / risk | Rebalance | Minimum history |
|---|---|---|---|---:|
| `value_quality` | value > 0, quality > 0, operating cash-flow ratio > 0 | leave value top 40%, quality/cash-flow deterioration, 15% stop | monthly | 1 |
| `growth_quality` | growth > 0.2, quality > 0, earnings yield > -0.05 | growth negative or quality leaves top 40%, 18% stop | monthly | 5 |
| `momentum_20_60` | 20d return > 5%, 60d return > 10%, volume ratio > 0.8 | MA20/60 reversal, 10% stop | weekly | 61 |
| `low_volatility` | vol < 25%, beta < 0.9, 60d drawdown > -20% | leaves lowest-volatility 40%, 12% stop | monthly | 61 |
| `high_dividend_quality` | yield > 3%, 7/8 profitable quarters, 6/8 positive-CFO quarters | yield < 2% or CFO deterioration, 15% stop | monthly | 8 |
| `mean_reversion_rsi` | RSI14 < 30 and price/MA250 > 0.95 | RSI > 55, trend break, 8% stop, 10-day timeout | daily | 250 |
| `trend_following` | MA20/60/250 proxy levels positive and ADX > 25 | MA reversal, ATR risk ceiling, 10% stop | daily | 250 |
| `breakout_60` | within 0.5% of 60d high and volume ratio > 1.5 | 8% below high, ATR risk ceiling, 8% stop | daily | 61 |
| `volume_price_confirmation` | 20d return > 5%, volume ratio > 1.1, correlation > 0.2 | negative price-volume correlation, 10% stop | weekly | 21 |
| `sentiment_reversal` | 7d sentiment < -0.6 with quality/liquidity > 0 | sentiment/event-risk recovery rules, 8% stop, 10-day timeout | daily | 30 |
| `sentiment_momentum` | sentiment > 0.4, attention z-score > 1, 5d return > 0 | sentiment or attention turns negative, 10% stop, 15-day timeout | daily | 60 |
| `multi_factor_balanced` | equal value/quality/growth/momentum/low-vol weights | combined rank leaves top 40%, 15% stop | monthly | 121 |
| `industry_rotation` | industry rank >= 0.8, quality and momentum > 0 | industry rank < 0.5, 15% stop | monthly | 121 |
| `defensive_risk_off` | beta < 0.75, profit stability > 0.6, debt/assets < 0.45 | beta/leverage/profit deterioration, 12% stop | monthly | 61 |

## Sensitivity and applicability

The catalog's `parameter_ranges` is normative: it records a default, lower and
upper sensitivity bound, unit and expected trade-off for every template. These
are evaluation ranges, not optimized promises. `suitable_markets` and
`unsuitable_scenarios` define when a template may or may not be a reasonable
starting point. The exact dependency list is derived from the validated DSL and
frozen into the published version with factor version and checksum.

Each catalog item also contains two deterministic fixtures. `signal_fixture`
passes its entry rule and must create a BUY on a legal rebalance date;
`no_signal_fixture` fails entry and must create no BUY. These fixtures are
contract examples only, not forecasts or recommended securities.

## Idempotent seeding

`app.migrations.seed_system_strategy_templates.run(db)` creates stable IDs of
the form `system-template:<template_id>` and
`system-template:<template_id>:v1`. A retry verifies the immutable header,
definition and frozen factor dependencies. It never rewrites a published
version. If an existing stable ID differs, the migration raises
`SystemTemplateSeedConflict` so deployment stops instead of silently changing
financial behavior.
