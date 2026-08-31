<template>
  <section class="factor-page">
    <FactorPageHeader
      title="因子实验室"
      description="基于不可变快照创建无未来数据泄漏的研究任务，并审阅 IC、分层收益、相关性、暴露与衰减。"
    />

    <el-alert
      v-if="featureDisabled"
      class="section-gap"
      type="warning"
      title="因子功能尚未启用"
      description="管理员启用 FACTOR_FEATURE_ENABLED 后可使用研究任务。"
      :closable="false"
      show-icon
    />
    <el-alert v-else-if="pageError" class="section-gap" type="error" :title="pageError" :closable="false" show-icon />

    <div class="workspace-grid">
      <el-card class="surface" shadow="never">
        <template #header><div class="card-title"><span>01 · 研究配置</span><el-tag effect="plain">无泄漏标签</el-tag></div></template>
        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="市场">
              <el-select v-model="form.market" @change="changeMarket">
                <el-option v-for="(label, value) in marketLabels" :key="value" :label="label" :value="value" />
              </el-select>
            </el-form-item>
            <el-form-item label="分层数量">
              <el-radio-group v-model="form.quantiles" @change="syncCrossSectionMinimum">
                <el-radio-button :value="5">Q5</el-radio-button>
                <el-radio-button :value="10">Q10</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </div>
          <el-form-item label="研究因子">
            <el-select v-model="form.factorIds" multiple filterable collapse-tags :max-collapse-tags="4" placeholder="选择因子">
              <el-option
                v-for="factor in definitions"
                :key="factor.factor_id"
                :label="`${factor.display_name} · v${factor.version}`"
                :value="factor.factor_id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="未来收益周期">
            <el-checkbox-group v-model="form.horizons">
              <el-checkbox v-for="horizon in horizonOptions" :key="horizon" :value="horizon">{{ horizon }} 日</el-checkbox>
            </el-checkbox-group>
          </el-form-item>
          <div class="form-grid">
            <el-form-item label="标签数据截止时间">
              <el-date-picker v-model="form.labelAsOf" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" />
            </el-form-item>
            <el-form-item label="标签数据版本">
              <el-input v-model="form.labelSourceVersion" maxlength="200" placeholder="例如 bars-2025-01" />
            </el-form-item>
          </div>
          <div class="form-grid three">
            <el-form-item label="最小有效样本">
              <el-input-number v-model="form.minSamples" :min="2" :max="1000000" controls-position="right" />
            </el-form-item>
            <el-form-item label="最小横截面">
              <el-input-number v-model="form.minCrossSection" :min="form.quantiles" :max="10000" controls-position="right" />
            </el-form-item>
            <el-form-item label="交易成本（bps）">
              <el-input-number v-model="form.transactionCostBps" :min="0" :max="1000" :precision="2" controls-position="right" />
            </el-form-item>
          </div>
          <el-form-item label="高相关告警阈值">
            <el-slider v-model="form.correlationThreshold" :min="0.5" :max="1" :step="0.01" show-input />
          </el-form-item>
          <el-alert
            type="info"
            :closable="false"
            title="标签只由独立行情序列向前偏移生成；特征始终来自下方已发布快照。"
          />
        </el-form>
      </el-card>

      <el-card class="surface" shadow="never">
        <template #header>
          <div class="card-title">
            <span>02 · 快照样本</span>
            <el-tag type="success" effect="plain">已选 {{ selectedSnapshotIds.length }}</el-tag>
          </div>
        </template>
        <div class="snapshot-toolbar">
          <span>服务端分页，每页仅加载 {{ snapshotPageSize }} 条</span>
          <el-button :icon="Refresh" circle @click="loadSnapshots" />
        </div>
        <el-table v-loading="snapshotsLoading" :data="snapshots" size="small" height="390" row-key="snapshot_id">
          <el-table-column width="48">
            <template #default="{ row }">
              <el-checkbox :model-value="selectedSnapshotIds.includes(row.snapshot_id)" @change="toggleSnapshot(row.snapshot_id)" />
            </template>
          </el-table-column>
          <el-table-column prop="trade_date" label="交易日" width="112" />
          <el-table-column label="数据截止" min-width="155">
            <template #default="{ row }">{{ formatDateTime(row.as_of) }}</template>
          </el-table-column>
          <el-table-column label="有效行" width="92">
            <template #default="{ row }">{{ row.row_count }}</template>
          </el-table-column>
          <el-table-column label="股票池" min-width="135" show-overflow-tooltip>
            <template #default="{ row }"><code>{{ row.universe_snapshot_id }}</code></template>
          </el-table-column>
          <template #empty><el-empty description="当前页没有可用快照" /></template>
        </el-table>
        <div class="pagination-row">
          <el-pagination
            v-model:current-page="snapshotPage"
            :page-size="snapshotPageSize"
            :total="snapshotTotal"
            layout="total, prev, pager, next"
            small
            @current-change="loadSnapshots"
          />
        </div>
        <el-button class="run-button" type="primary" size="large" :loading="submitting" :disabled="!canSubmit" @click="submitAnalysis">
          创建持久研究任务
        </el-button>
      </el-card>
    </div>

    <el-card v-if="task" class="surface task-card" shadow="never">
      <div class="task-line">
        <div>
          <span class="eyebrow">DURABLE TASK</span>
          <strong>{{ taskStatusLabels[task.status] }} · {{ task.stage }}</strong>
          <small>{{ task.message || task.task_id }}</small>
        </div>
        <el-progress type="dashboard" :percentage="Math.round(task.progress * 100)" :status="task.status === 'failed' ? 'exception' : undefined" :width="92" />
      </div>
      <el-alert v-if="task.error" type="error" :title="`${task.error.code} · ${task.error.message}`" :closable="false" show-icon />
    </el-card>

    <template v-if="result">
      <el-card class="surface result-summary" shadow="never">
        <div class="summary-heading">
          <div>
            <span class="eyebrow">REPRODUCIBLE RESULT</span>
            <h2>{{ marketLabels[result.market] }} · {{ result.feature_start }} 至 {{ result.feature_end }}</h2>
            <p>股票池 {{ result.universe_snapshot_id }} · {{ result.transaction_cost_included ? '已计交易成本' : '未计交易成本' }}</p>
          </div>
          <code>{{ compactHash(result.result_checksum) }}</code>
        </div>
        <div class="metric-grid">
          <div><span>快照</span><strong>{{ result.quality.snapshot_count }}</strong></div>
          <div><span>有效行</span><strong>{{ result.quality.row_count }}</strong></div>
          <div><span>质量排除</span><strong>{{ result.quality.excluded_quality_values }}</strong></div>
          <div><span>缺失因子值</span><strong>{{ result.quality.missing_factor_values }}</strong></div>
        </div>
        <div class="quality-tags">
          <el-tag v-for="(count, horizon) in result.quality.missing_labels_by_horizon" :key="horizon" type="warning" effect="plain">
            {{ horizon }} 日标签缺失 {{ count }}
          </el-tag>
          <el-tag v-for="version in result.quality.label_source_versions" :key="version" effect="plain">
            标签版本 {{ version }}
          </el-tag>
        </div>
        <div class="selector-row">
          <el-select v-model="activeFactor" placeholder="选择展示因子">
            <el-option v-for="factorId in result.request.factor_ids" :key="factorId" :label="factorId" :value="factorId" />
          </el-select>
          <el-select v-model="activeHorizon" placeholder="未来周期">
            <el-option v-for="horizon in result.request.horizons" :key="horizon" :label="`${horizon} 日`" :value="horizon" />
          </el-select>
        </div>
      </el-card>

      <el-tabs class="result-tabs" type="border-card">
        <el-tab-pane label="分布与时序">
          <div class="chart-grid">
            <el-card shadow="never"><template #header>分位点分布</template><FactorChart :option="distributionOption" /></el-card>
            <el-card shadow="never"><template #header>截面均值时序</template><FactorChart :option="timeSeriesOption" /></el-card>
          </div>
          <el-table :data="result.distributions" size="small" border>
            <el-table-column prop="factor_id" label="因子" min-width="140" />
            <el-table-column prop="valid_observations" label="有效样本" width="105" />
            <el-table-column label="缺失率" width="100"><template #default="{ row }">{{ percent(row.missing_rate) }}</template></el-table-column>
            <el-table-column label="极值率" width="100"><template #default="{ row }">{{ percent(row.extreme_rate) }}</template></el-table-column>
            <el-table-column prop="coverage_symbols" label="覆盖股票" width="105" />
            <el-table-column label="均值" width="110"><template #default="{ row }">{{ number(row.mean) }}</template></el-table-column>
            <el-table-column label="标准差" width="110"><template #default="{ row }">{{ number(row.std) }}</template></el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="IC 与衰减">
          <div class="chart-grid">
            <el-card shadow="never"><template #header>平均 IC</template><FactorChart :option="icOption" /></el-card>
            <el-card shadow="never"><template #header>Rank IC 衰减</template><FactorChart :option="decayOption" /></el-card>
          </div>
          <el-table :data="result.ic" size="small" border>
            <el-table-column prop="factor_id" label="因子" min-width="130" />
            <el-table-column prop="horizon" label="周期" width="75" />
            <el-table-column prop="sample_count" label="有效样本" width="100" />
            <el-table-column prop="period_count" label="有效截面" width="100" />
            <el-table-column label="样本区间" min-width="190"><template #default="{ row }">{{ row.sample_start }} ～ {{ row.sample_end }}</template></el-table-column>
            <el-table-column label="Rank IC" width="105"><template #default="{ row }">{{ number(row.rank_mean) }}</template></el-table-column>
            <el-table-column label="Rank ICIR" width="110"><template #default="{ row }">{{ number(row.rank_icir) }}</template></el-table-column>
            <el-table-column label="正 IC 比例" width="110"><template #default="{ row }">{{ percent(row.rank_positive_ratio) }}</template></el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="分层收益">
          <div class="chart-grid single">
            <el-card shadow="never"><template #header>{{ activeFactor }} · 未来 {{ activeHorizon }} 日</template><FactorChart :option="quantileOption" /></el-card>
          </div>
          <el-table :data="activeQuantileRows" size="small" border>
            <el-table-column prop="factor_id" label="因子" min-width="140" />
            <el-table-column prop="horizon" label="周期" width="75" />
            <el-table-column prop="sample_count" label="样本" width="95" />
            <el-table-column label="单调性" width="100"><template #default="{ row }">{{ number(row.monotonicity) }}</template></el-table-column>
            <el-table-column label="多空毛收益" width="120"><template #default="{ row }">{{ percent(row.gross_long_short_return) }}</template></el-table-column>
            <el-table-column label="多空净收益" width="120"><template #default="{ row }">{{ percent(row.net_long_short_return) }}</template></el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="相关与暴露">
          <div class="chart-grid">
            <el-card shadow="never"><template #header>相关矩阵</template><FactorChart :option="correlationOption" /></el-card>
            <el-card shadow="never"><template #header>市值 / Beta 暴露</template><FactorChart :option="exposureOption" /></el-card>
          </div>
          <el-alert v-if="!result.correlation_warnings.length" type="success" title="未触发高相关告警" :closable="false" show-icon />
          <el-alert
            v-for="warning in result.correlation_warnings"
            v-else
            :key="`${warning.factor_a}-${warning.factor_b}`"
            class="warning-row"
            type="warning"
            :title="`${warning.factor_a} / ${warning.factor_b}：${number(warning.correlation)}，超过阈值 ${warning.threshold}`"
            :closable="false"
            show-icon
          />
          <el-table :data="result.exposures" class="section-gap" size="small" border>
            <el-table-column prop="factor_id" label="因子" min-width="140" />
            <el-table-column label="市值相关" width="110"><template #default="{ row }">{{ number(row.market_cap_correlation) }}</template></el-table-column>
            <el-table-column prop="market_cap_sample_count" label="市值样本" width="105" />
            <el-table-column label="Beta 相关" width="110"><template #default="{ row }">{{ number(row.beta_correlation) }}</template></el-table-column>
            <el-table-column prop="beta_sample_count" label="Beta 样本" width="105" />
            <el-table-column label="行业暴露" min-width="250">
              <template #default="{ row }">
                <el-tag v-for="(value, industry) in row.industry_exposure" :key="industry" class="exposure-tag" effect="plain">
                  {{ industry }} {{ number(value) }} (n={{ row.industry_sample_counts[industry] }})
                </el-tag>
                <span v-if="!Object.keys(row.industry_exposure).length" class="muted">本次请求未提供版本化行业映射</span>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import type { EChartsOption } from 'echarts'
import { factorApi } from '@/api/factors'
import type {
  DomainTask,
  FactorAnalysisHorizon,
  FactorAnalysisResult,
  FactorDefinition,
  FactorMarket,
  FactorQuantileMetric,
  FactorSnapshot
} from '@/types/factor'
import FactorChart from './components/FactorChart.vue'
import FactorPageHeader from './components/FactorPageHeader.vue'
import {
  compactHash,
  formatDateTime,
  getErrorMessage,
  isFeatureDisabled,
  marketLabels,
  taskStatusLabels
} from './factorPresentation'

const STORAGE_KEY = 'factor-research-active-v1'
const horizonOptions: FactorAnalysisHorizon[] = [1, 5, 10, 20]
const definitions = ref<FactorDefinition[]>([])
const snapshots = ref<FactorSnapshot[]>([])
const selectedSnapshotIds = ref<string[]>([])
const snapshotPage = ref(1)
const snapshotPageSize = 20
const snapshotTotal = ref(0)
const snapshotsLoading = ref(false)
const submitting = ref(false)
const pageError = ref('')
const featureDisabled = ref(false)
const task = ref<DomainTask | null>(null)
const result = ref<FactorAnalysisResult | null>(null)
const activeFactor = ref('')
const activeHorizon = ref<FactorAnalysisHorizon>(1)
let pollTimer: number | null = null

const form = reactive({
  market: 'CN' as FactorMarket,
  factorIds: [] as string[],
  horizons: [1, 5, 10, 20] as FactorAnalysisHorizon[],
  quantiles: 5 as 5 | 10,
  minSamples: 20,
  minCrossSection: 5,
  labelAsOf: new Date().toISOString().slice(0, 19) + 'Z',
  labelSourceVersion: '',
  transactionCostBps: 0,
  correlationThreshold: 0.85
})

const canSubmit = computed(() =>
  selectedSnapshotIds.value.length > 0 &&
  form.factorIds.length > 0 &&
  form.horizons.length > 0 &&
  Boolean(form.labelAsOf && form.labelSourceVersion.trim()) &&
  form.minCrossSection >= form.quantiles
)

const activeQuantileRows = computed<FactorQuantileMetric[]>(() => {
  if (!result.value) return []
  return result.value.quantile_returns.filter((item) =>
    item.factor_id === activeFactor.value && item.horizon === activeHorizon.value
  )
})

const baseChart = {
  tooltip: { trigger: 'axis' },
  grid: { left: 52, right: 22, top: 34, bottom: 48 },
  textStyle: { fontFamily: 'Inter, system-ui, sans-serif' }
} satisfies EChartsOption

const distributionOption = computed<EChartsOption>(() => ({
  ...baseChart,
  legend: { data: ['P25', '中位数', 'P75'] },
  xAxis: { type: 'category', data: result.value?.distributions.map((item) => item.factor_id) || [], axisLabel: { rotate: 24 } },
  yAxis: { type: 'value', scale: true },
  series: [
    { name: 'P25', type: 'bar', data: result.value?.distributions.map((item) => item.p25) || [] },
    { name: '中位数', type: 'bar', data: result.value?.distributions.map((item) => item.median) || [] },
    { name: 'P75', type: 'bar', data: result.value?.distributions.map((item) => item.p75) || [] }
  ]
}))

const timeSeriesOption = computed<EChartsOption>(() => {
  const points = result.value?.time_series.filter((item) => item.factor_id === activeFactor.value) || []
  return {
    ...baseChart,
    xAxis: { type: 'category', data: points.map((item) => item.trade_date) },
    yAxis: { type: 'value', scale: true },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16 }],
    series: [{ name: '截面均值', type: 'line', smooth: true, showSymbol: false, data: points.map((item) => item.mean) }]
  }
})

const icOption = computed<EChartsOption>(() => ({
  ...baseChart,
  legend: { data: ['Rank IC', 'Pearson IC'] },
  xAxis: { type: 'category', data: result.value?.ic.map((item) => `${item.factor_id}/${item.horizon}d`) || [], axisLabel: { rotate: 30 } },
  yAxis: { type: 'value', min: -1, max: 1 },
  series: [
    { name: 'Rank IC', type: 'line', data: result.value?.ic.map((item) => item.rank_mean) || [] },
    { name: 'Pearson IC', type: 'line', data: result.value?.ic.map((item) => item.pearson_mean) || [] }
  ]
}))

const decayOption = computed<EChartsOption>(() => ({
  ...baseChart,
  legend: { type: 'scroll' },
  xAxis: { type: 'category', data: (result.value?.request.horizons || []).map((item) => `${item}d`) },
  yAxis: { type: 'value', min: -1, max: 1 },
  series: (result.value?.decay || []).map((item) => ({
    name: item.factor_id,
    type: 'line',
    data: (result.value?.request.horizons || []).map((horizon) => item.rank_ic_by_horizon[String(horizon)])
  }))
}))

const quantileOption = computed<EChartsOption>(() => {
  const metric = activeQuantileRows.value[0]
  const labels = metric ? Object.keys(metric.returns) : []
  return {
    ...baseChart,
    xAxis: { type: 'category', data: labels },
    yAxis: { type: 'value', axisLabel: { formatter: (value: number) => `${(value * 100).toFixed(1)}%` } },
    series: [{ name: '未来收益', type: 'bar', data: labels.map((label) => metric?.returns[label] ?? null), itemStyle: { color: '#409eff' } }]
  }
})

const correlationOption = computed<EChartsOption>(() => {
  const factors = result.value?.request.factor_ids || []
  const values: Array<[number, number, number | null]> = []
  const correlations = result.value?.correlations || []
  for (const metric of correlations) {
    const a = factors.indexOf(metric.factor_a)
    const b = factors.indexOf(metric.factor_b)
    values.push([a, b, metric.correlation])
    if (a !== b) values.push([b, a, metric.correlation])
  }
  return {
    tooltip: { position: 'top' },
    grid: { left: 80, right: 24, top: 20, bottom: 72 },
    xAxis: { type: 'category', data: factors, axisLabel: { rotate: 30 } },
    yAxis: { type: 'category', data: factors },
    visualMap: { min: -1, max: 1, calculable: true, orient: 'horizontal', left: 'center', bottom: 0 },
    series: [{ type: 'heatmap', data: values, label: { show: factors.length <= 8, formatter: '{@[2]}' } }]
  }
})

const exposureOption = computed<EChartsOption>(() => ({
  ...baseChart,
  legend: { data: ['市值相关', 'Beta 相关'] },
  xAxis: { type: 'category', data: result.value?.exposures.map((item) => item.factor_id) || [], axisLabel: { rotate: 24 } },
  yAxis: { type: 'value', min: -1, max: 1 },
  series: [
    { name: '市值相关', type: 'bar', data: result.value?.exposures.map((item) => item.market_cap_correlation) || [] },
    { name: 'Beta 相关', type: 'bar', data: result.value?.exposures.map((item) => item.beta_correlation) || [] }
  ]
}))

function number(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(value)
}

function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${(value * 100).toFixed(2)}%`
}

function syncCrossSectionMinimum() {
  if (form.minCrossSection < form.quantiles) form.minCrossSection = form.quantiles
}

function toggleSnapshot(snapshotId: string) {
  selectedSnapshotIds.value = selectedSnapshotIds.value.includes(snapshotId)
    ? selectedSnapshotIds.value.filter((item) => item !== snapshotId)
    : [...selectedSnapshotIds.value, snapshotId]
}

async function loadDefinitions() {
  const response = await factorApi.listDefinitions({ market: form.market, status: 'active', page: 1, page_size: 200 })
  definitions.value = response.items
  form.factorIds = form.factorIds.filter((factorId) => response.items.some((item) => item.factor_id === factorId))
}

async function loadSnapshots() {
  try {
    snapshotsLoading.value = true
    const response = await factorApi.listSnapshots({ market: form.market, status: 'ready', page: snapshotPage.value, page_size: snapshotPageSize })
    snapshots.value = response.items
    snapshotTotal.value = response.total
    featureDisabled.value = false
  } catch (error) {
    featureDisabled.value = isFeatureDisabled(error)
    pageError.value = getErrorMessage(error, '快照加载失败')
    snapshots.value = []
  } finally {
    snapshotsLoading.value = false
  }
}

async function changeMarket() {
  snapshotPage.value = 1
  selectedSnapshotIds.value = []
  await Promise.all([loadDefinitions(), loadSnapshots()])
}

async function submitAnalysis() {
  if (!canSubmit.value) return
  try {
    submitting.value = true
    pageError.value = ''
    result.value = null
    const accepted = await factorApi.analyze({
      snapshot_ids: selectedSnapshotIds.value,
      factor_ids: form.factorIds,
      horizons: [...form.horizons].sort((a, b) => a - b),
      quantiles: form.quantiles,
      min_samples: form.minSamples,
      min_cross_section: form.minCrossSection,
      label_as_of: new Date(form.labelAsOf).toISOString(),
      label_source_version: form.labelSourceVersion.trim(),
      transaction_cost_bps: form.transactionCostBps,
      correlation_threshold: form.correlationThreshold,
      industry_by_symbol: {}
    })
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ analysisId: accepted.analysis_id, taskId: accepted.task_id }))
    ElMessage.success(accepted.deduplicated ? '已恢复相同研究任务' : '研究任务已创建')
    await pollTask(accepted.task_id, accepted.analysis_id)
  } catch (error) {
    pageError.value = getErrorMessage(error, '研究任务创建失败')
    ElMessage.error(pageError.value)
  } finally {
    submitting.value = false
  }
}

async function pollTask(taskId: string, analysisId: string) {
  if (pollTimer !== null) window.clearTimeout(pollTimer)
  try {
    task.value = await factorApi.getTask(taskId)
    if (task.value.status === 'succeeded') {
      result.value = await factorApi.getAnalysis(analysisId)
      activeFactor.value = result.value.request.factor_ids[0] || ''
      activeHorizon.value = result.value.request.horizons[0] || 1
      return
    }
    if (['failed', 'cancelled'].includes(task.value.status)) return
    pollTimer = window.setTimeout(() => void pollTask(taskId, analysisId), 2000)
  } catch (error) {
    pageError.value = getErrorMessage(error, '研究任务状态加载失败')
  }
}

async function restoreTask() {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (!saved) return
  try {
    const parsed = JSON.parse(saved) as { analysisId?: string; taskId?: string }
    if (parsed.analysisId && parsed.taskId) await pollTask(parsed.taskId, parsed.analysisId)
  } catch {
    localStorage.removeItem(STORAGE_KEY)
  }
}

onMounted(async () => {
  try {
    await Promise.all([loadDefinitions(), loadSnapshots()])
    await nextTick()
    await restoreTask()
  } catch (error) {
    featureDisabled.value = isFeatureDisabled(error)
    pageError.value = getErrorMessage(error, '因子实验室初始化失败')
  }
})

onBeforeUnmount(() => {
  if (pollTimer !== null) window.clearTimeout(pollTimer)
})
</script>

<style scoped lang="scss">
.factor-page { min-width: 0; }
.section-gap { margin: 16px 0; }
.surface { border: 1px solid var(--el-border-color-lighter); border-radius: 14px; }
.workspace-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(420px, .95fr); gap: 16px; align-items: start; }
.card-title, .snapshot-toolbar, .task-line, .summary-heading, .selector-row { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.card-title { font-weight: 700; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.form-grid.three { grid-template-columns: repeat(3, 1fr); }
:deep(.el-select), :deep(.el-date-editor), :deep(.el-input-number) { width: 100%; }
.snapshot-toolbar { margin-bottom: 10px; color: var(--el-text-color-secondary); font-size: 12px; }
.pagination-row { display: flex; justify-content: flex-end; margin-top: 12px; overflow-x: auto; }
.run-button { width: 100%; margin-top: 18px; }
.task-card, .result-summary, .result-tabs { margin-top: 16px; }
.task-line > div:first-child { display: flex; flex-direction: column; gap: 5px; }
.task-line small, .summary-heading p, .muted { color: var(--el-text-color-secondary); }
.eyebrow { color: var(--el-color-primary); font-size: 10px; font-weight: 750; letter-spacing: .16em; }
.summary-heading h2 { margin: 5px 0; font-size: 20px; }
.summary-heading p { margin: 0; font-size: 12px; }
.metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 18px; }
.metric-grid div { padding: 13px; border-radius: 10px; background: var(--el-fill-color-extra-light); }
.metric-grid span, .metric-grid strong { display: block; }
.metric-grid span { margin-bottom: 6px; color: var(--el-text-color-secondary); font-size: 11px; }
.quality-tags { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 12px; }
.selector-row { justify-content: flex-start; margin-top: 16px; }
.selector-row :deep(.el-select) { width: 220px; }
.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 16px; }
.chart-grid.single { grid-template-columns: 1fr; }
.warning-row { margin-bottom: 8px; }
.exposure-tag { margin: 2px 5px 2px 0; }

@media (max-width: 1080px) {
  .workspace-grid, .chart-grid { grid-template-columns: 1fr; }
}
@media (max-width: 700px) {
  .form-grid, .form-grid.three, .metric-grid { grid-template-columns: 1fr 1fr; }
  .summary-heading, .task-line { align-items: flex-start; flex-direction: column; }
}
</style>
