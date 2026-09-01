import type {
  Strategy,
  StrategyCreatePayload,
  StrategyDefinition,
  StrategyVersion,
  StrategyWizardModel
} from '@/types/strategy'

export const newWizardModel = (): StrategyWizardModel => ({
  name: '',
  description: '',
  tags: [],
  kind: 'portfolio',
  market: 'CN',
  snapshotId: '',
  minimumListingDays: 120,
  excludeSt: true,
  excludeDelisting: true,
  excludeSuspended: true,
  minimumMarketCap: null,
  maximumMarketCap: null,
  adjustment: 'qfq',
  minimumHistory: 252,
  factors: ['ret_20d'],
  factorVersion: 1,
  entryFactor: 'ret_20d',
  entryOperator: 'gt',
  entryThreshold: 0,
  takeProfit: 0.2,
  stopLoss: 0.08,
  maxHoldingPeriods: 20,
  rebalanceFrequency: 'weekly',
  weekday: 0,
  dayOfMonth: 1,
  weighting: 'equal_weight',
  maxPositions: 20,
  maxPositionWeight: 0.1,
  maxIndustryWeight: 0.3,
  minCashRatio: 0.05,
  signalTime: 'close',
  executionTime: 'next_open',
  price: 'open',
  slippageBps: 5,
  feeModelVersion: 'cn-a-share-v1',
  maxDrawdownStop: 0.2,
  volatilityTarget: null,
  cooldownPeriods: 5,
  benchmarkSymbol: '000300',
  analysisProfileVersionId: '',
  skillVersionIds: [],
  requireExplanation: false,
  changeSummary: 'Initial structured strategy draft'
})

export const buildDefinition = (model: StrategyWizardModel): StrategyDefinition => {
  const rebalance: Record<string, unknown> = { frequency: model.rebalanceFrequency }
  if (model.rebalanceFrequency === 'weekly') rebalance.weekday = model.weekday
  if (model.rebalanceFrequency === 'monthly') rebalance.day_of_month = model.dayOfMonth

  return {
    universe: {
      snapshot_id: model.snapshotId || null,
      minimum_listing_days: model.minimumListingDays,
      exclude_st: model.excludeSt,
      exclude_delisting: model.excludeDelisting,
      exclude_suspended: model.excludeSuspended,
      include_industries: [],
      exclude_industries: [],
      minimum_market_cap: model.minimumMarketCap,
      maximum_market_cap: model.maximumMarketCap
    },
    data: {
      frequency: 'daily',
      adjustment: model.adjustment,
      minimum_history: model.minimumHistory,
      allowed_quality: ['ok', 'valid'],
      point_in_time: true
    },
    features: model.factors.map(factorId => ({
      factor_id: factorId,
      version: model.factorVersion,
      params: {}
    })),
    entry: {
      condition: {
        type: 'compare',
        left: { kind: 'factor', factor_id: model.entryFactor, version: model.factorVersion, lag: 0 },
        operator: model.entryOperator,
        right: { kind: 'constant', value: model.entryThreshold }
      },
      ranking: null
    },
    exit: {
      condition: null,
      take_profit: model.takeProfit,
      stop_loss: model.stopLoss,
      max_holding_periods: model.maxHoldingPeriods
    },
    rebalance,
    portfolio: {
      weighting: model.weighting,
      max_positions: model.maxPositions,
      max_position_weight: model.maxPositionWeight,
      max_industry_weight: model.maxIndustryWeight,
      min_cash_ratio: model.minCashRatio,
      volatility_factor: null,
      fixed_weights: {},
      minimum_lot: model.market === 'CN' ? 100 : 1,
      minimum_notional: 0
    },
    execution: {
      signal_time: model.signalTime,
      execution_time: model.executionTime,
      price: model.price,
      slippage_bps: model.slippageBps,
      fee_model_version: model.feeModelVersion
    },
    risk: {
      max_drawdown_stop: model.maxDrawdownStop,
      volatility_target: model.volatilityTarget,
      take_profit: model.takeProfit,
      stop_loss: model.stopLoss,
      cooldown_periods: model.cooldownPeriods
    },
    benchmark: { market: model.market, symbol: model.benchmarkSymbol },
    analysis: model.analysisProfileVersionId || model.skillVersionIds.length || model.requireExplanation
      ? {
          analysis_profile_version_id: model.analysisProfileVersionId || null,
          skill_version_ids: model.skillVersionIds,
          require_explanation: model.requireExplanation
        }
      : null
  }
}

export const buildCreatePayload = (model: StrategyWizardModel): StrategyCreatePayload => ({
  name: model.name.trim(),
  description: model.description.trim(),
  tags: model.tags,
  kind: model.kind,
  market: model.market,
  definition: buildDefinition(model),
  analysis_profile_version_id: model.analysisProfileVersionId || null,
  change_summary: model.changeSummary.trim()
})

export const modelFromVersion = (
  strategy: Strategy,
  version: StrategyVersion
): StrategyWizardModel => {
  const model = newWizardModel()
  const definition = version.definition
  const entry = definition.entry as Record<string, unknown>
  const condition = (entry.condition || {}) as Record<string, unknown>
  const left = (condition.left || {}) as Record<string, unknown>
  const right = (condition.right || {}) as Record<string, unknown>
  const exit = definition.exit as Record<string, unknown>
  const rebalance = definition.rebalance as Record<string, unknown>
  const portfolio = definition.portfolio as Record<string, unknown>
  const execution = definition.execution as Record<string, unknown>
  const risk = definition.risk as Record<string, unknown>
  const analysis = definition.analysis
  return {
    ...model,
    name: strategy.name,
    description: strategy.description,
    tags: [...strategy.tags],
    kind: strategy.kind,
    market: version.market,
    snapshotId: definition.universe.snapshot_id || '',
    minimumListingDays: definition.universe.minimum_listing_days,
    excludeSt: definition.universe.exclude_st,
    excludeDelisting: definition.universe.exclude_delisting,
    excludeSuspended: definition.universe.exclude_suspended,
    minimumMarketCap: definition.universe.minimum_market_cap,
    maximumMarketCap: definition.universe.maximum_market_cap,
    adjustment: definition.data.adjustment,
    minimumHistory: definition.data.minimum_history,
    factors: definition.features.map(item => item.factor_id),
    factorVersion: definition.features[0]?.version || 1,
    entryFactor: typeof left.factor_id === 'string' ? left.factor_id : definition.features[0]?.factor_id || '',
    entryOperator: ['gt', 'gte', 'lt', 'lte'].includes(String(condition.operator))
      ? condition.operator as StrategyWizardModel['entryOperator'] : 'gt',
    entryThreshold: typeof right.value === 'number' ? right.value : 0,
    takeProfit: numberOrNull(exit.take_profit),
    stopLoss: numberOrNull(exit.stop_loss),
    maxHoldingPeriods: numberOrNull(exit.max_holding_periods),
    rebalanceFrequency: ['daily', 'weekly', 'monthly'].includes(String(rebalance.frequency))
      ? rebalance.frequency as StrategyWizardModel['rebalanceFrequency'] : 'weekly',
    weekday: typeof rebalance.weekday === 'number' ? rebalance.weekday : 0,
    dayOfMonth: typeof rebalance.day_of_month === 'number' ? rebalance.day_of_month : 1,
    weighting: portfolio.weighting === 'score_weight' ? 'score_weight' : 'equal_weight',
    maxPositions: numberOr(portfolio.max_positions, 20),
    maxPositionWeight: numberOr(portfolio.max_position_weight, 0.1),
    maxIndustryWeight: numberOr(portfolio.max_industry_weight, 0.3),
    minCashRatio: numberOr(portfolio.min_cash_ratio, 0.05),
    signalTime: execution.signal_time === 'open' ? 'open' : 'close',
    executionTime: ['same_open', 'same_close', 'next_open', 'next_close'].includes(String(execution.execution_time))
      ? execution.execution_time as StrategyWizardModel['executionTime'] : 'next_open',
    price: ['open', 'close', 'vwap'].includes(String(execution.price))
      ? execution.price as StrategyWizardModel['price'] : 'open',
    slippageBps: numberOr(execution.slippage_bps, 0),
    feeModelVersion: typeof execution.fee_model_version === 'string' ? execution.fee_model_version : 'cn-a-share-v1',
    maxDrawdownStop: numberOrNull(risk.max_drawdown_stop),
    volatilityTarget: numberOrNull(risk.volatility_target),
    cooldownPeriods: numberOr(risk.cooldown_periods, 0),
    benchmarkSymbol: definition.benchmark.symbol,
    analysisProfileVersionId: analysis?.analysis_profile_version_id || version.analysis_profile_version_id || '',
    skillVersionIds: [...(analysis?.skill_version_ids || [])],
    requireExplanation: analysis?.require_explanation || false,
    changeSummary: version.change_summary || `Update v${version.version} draft`
  }
}

const numberOr = (value: unknown, fallback: number): number =>
  typeof value === 'number' ? value : fallback

const numberOrNull = (value: unknown): number | null =>
  typeof value === 'number' ? value : null
