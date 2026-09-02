<template>
  <section class="backtest-page">
    <header class="page-header">
      <div>
        <h1>历史回测</h1>
        <p>管理确定性回测任务，检查数据质量、交易明细与可复现指标。</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="router.push('/backtests/new')">创建回测</el-button>
    </header>

    <div class="toolbar">
      <div class="filters">
        <el-select v-model="statusFilter" clearable placeholder="全部状态" @change="changeFilter">
          <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-button :icon="Refresh" :loading="loading" @click="load()">刷新</el-button>
      </div>
      <div class="compare-actions">
        <span>已选 {{ selectedRunIds.length }}/10</span>
        <el-button :disabled="!selectedRunIds.length" :loading="comparing" @click="compareSelected">
          比较所选
        </el-button>
      </div>
    </div>

    <div class="table-surface">
      <el-skeleton v-if="loading && !pageData.items.length" :rows="8" animated />
      <el-table
        v-else
        :data="pageData.items"
        row-key="run_id"
        stripe
        @selection-change="selectionChanged"
      >
        <el-table-column type="selection" width="46" :selectable="selectable" reserve-selection />
        <el-table-column label="回测任务" min-width="255">
          <template #default="{ row }">
            <button class="run-link" type="button" @click="openRun(row.run_id)">
              <strong>{{ strategyName(row.strategy_version_id) }}</strong>
              <code>{{ row.run_id }}</code>
            </button>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="118">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" effect="light">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="市场 / 区间" min-width="190">
          <template #default="{ row }">
            <div class="stacked-cell"><span>{{ row.market }}</span><small>{{ row.request.start_date }} — {{ row.request.end_date }}</small></div>
          </template>
        </el-table-column>
        <el-table-column label="基准 / 初始资金" min-width="165">
          <template #default="{ row }">
            <div class="stacked-cell"><span>{{ row.request.benchmark }}</span><small>{{ money(row.request.initial_cash, row.market) }}</small></div>
          </template>
        </el-table-column>
        <el-table-column label="完成进度" min-width="150">
          <template #default="{ row }">
            <span v-if="row.status === 'succeeded'">已完成</span>
            <span v-else-if="row.last_completed_trade_date">截至 {{ row.last_completed_trade_date }}</span>
            <span v-else class="muted">等待执行</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ datetime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="92" fixed="right">
          <template #default="{ row }"><el-button link type="primary" @click="openRun(row.run_id)">查看</el-button></template>
        </el-table-column>
        <template #empty>
          <div class="teaching-empty">
            <strong>{{ statusFilter ? '当前状态下没有回测' : '还没有历史回测' }}</strong>
            <span>{{ statusFilter ? '清除状态筛选查看全部任务。' : '选择已发布策略，创建第一条可复现回测。' }}</span>
            <el-button v-if="!statusFilter" type="primary" link @click="router.push('/backtests/new')">创建回测</el-button>
          </div>
        </template>
      </el-table>
      <el-pagination
        v-if="pageData.total"
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="pageData.total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        class="pagination"
        @current-change="load()"
        @size-change="changePageSize"
      />
    </div>

    <el-drawer v-model="compareOpen" title="回测比较" size="min(980px, 96vw)">
      <el-skeleton v-if="comparing" :rows="9" animated />
      <template v-else-if="comparison">
        <el-alert
          v-if="!comparison.comparable"
          title="这些回测的市场、区间、基准、执行或参数口径不同"
          description="为避免误导，结果按选择顺序展示，不进行收益排名。"
          type="warning"
          :closable="false"
          show-icon
        />
        <el-alert
          v-else
          title="回测口径一致，可以进行横向比较"
          type="success"
          :closable="false"
          show-icon
        />
        <div class="comparison-table">
          <table>
            <thead><tr><th scope="col">指标</th><th v-for="item in comparison.items" :key="item.run_id" scope="col">{{ shortId(item.run_id) }}<small>{{ item.market }} · {{ item.start_date }} 至 {{ item.end_date }}</small></th></tr></thead>
            <tbody>
              <tr v-for="metric in comparisonMetrics" :key="metric.key">
                <th scope="row">{{ metric.label }}</th>
                <td v-for="item in comparison.items" :key="`${item.run_id}-${metric.key}`">{{ metric.format(item.metrics[metric.key]) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </el-drawer>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { backtestApi } from '@/api/backtests'
import { strategyApi } from '@/api/strategies'
import type {
  BacktestCompareResult,
  BacktestPage,
  BacktestPerformanceReport,
  BacktestRun,
  BacktestRunStatus
} from '@/types/backtest'

type MetricKey = keyof BacktestPerformanceReport

const router = useRouter()
const loading = ref(false)
const comparing = ref(false)
const compareOpen = ref(false)
const comparison = ref<BacktestCompareResult | null>(null)
const page = ref(1)
const pageSize = ref(20)
const statusFilter = ref<BacktestRunStatus | ''>('')
const selectedRunIds = ref<string[]>([])
const strategyNames = ref<Record<string, string>>({})
const pageData = ref<BacktestPage<BacktestRun>>({ items: [], page: 1, page_size: 20, total: 0 })
let refreshTimer: number | null = null

const statusOptions: Array<{ value: BacktestRunStatus; label: string }> = [
  { value: 'queued', label: '排队中' },
  { value: 'running', label: '运行中' },
  { value: 'succeeded', label: '已完成' },
  { value: 'cancelled', label: '已取消' },
  { value: 'failed', label: '失败' }
]
const comparisonMetrics: Array<{
  key: MetricKey
  label: string
  format: (value: BacktestPerformanceReport[MetricKey]) => string
}> = [
  { key: 'total_return', label: '总收益', format: percentValue },
  { key: 'cagr', label: '年化收益', format: percentValue },
  { key: 'max_drawdown', label: '最大回撤', format: percentValue },
  { key: 'annualized_volatility', label: '年化波动', format: percentValue },
  { key: 'sharpe_ratio', label: '夏普比率', format: decimalValue },
  { key: 'sortino_ratio', label: '索提诺比率', format: decimalValue },
  { key: 'win_rate', label: '胜率', format: percentValue },
  { key: 'total_fees', label: '总费用', format: numberValue }
]

onMounted(async () => {
  await Promise.all([load(), loadStrategyNames()])
  refreshTimer = window.setInterval(() => {
    if (pageData.value.items.some(item => ['queued', 'running'].includes(item.status))) load(true)
  }, 5000)
})
onBeforeUnmount(() => { if (refreshTimer !== null) window.clearInterval(refreshTimer) })

async function load(silent = false): Promise<void> {
  if (!silent) loading.value = true
  try {
    pageData.value = await backtestApi.list({
      status: statusFilter.value || undefined,
      page: page.value,
      page_size: pageSize.value
    })
  } finally {
    if (!silent) loading.value = false
  }
}

async function loadStrategyNames(): Promise<void> {
  const [strategies, templates] = await Promise.all([strategyApi.list(true), strategyApi.listTemplates()])
  const names: Record<string, string> = {}
  strategies.forEach(item => {
    if (item.latest_published_version_id) names[item.latest_published_version_id] = item.name
    if (item.current_draft_version_id) names[item.current_draft_version_id] = item.name
  })
  templates.forEach(item => { names[item.strategy_version_id] = item.name })
  strategyNames.value = names
}

function selectionChanged(rows: BacktestRun[]): void {
  selectedRunIds.value = rows.slice(0, 10).map(item => item.run_id)
  if (rows.length > 10) ElMessage.warning('一次最多比较 10 个回测')
}
function selectable(row: BacktestRun): boolean {
  return row.status === 'succeeded'
    && (selectedRunIds.value.includes(row.run_id) || selectedRunIds.value.length < 10)
}
async function compareSelected(): Promise<void> {
  comparing.value = true
  compareOpen.value = true
  comparison.value = null
  try { comparison.value = await backtestApi.compare(selectedRunIds.value) }
  finally { comparing.value = false }
}
function changeFilter(): void { page.value = 1; load() }
function changePageSize(): void { page.value = 1; load() }
function openRun(runId: string): void { router.push(`/backtests/${runId}`) }
function strategyName(versionId: string): string { return strategyNames.value[versionId] || `策略版本 ${shortId(versionId)}` }
function shortId(value: string): string { return value.length > 14 ? `${value.slice(0, 8)}…${value.slice(-5)}` : value }
function datetime(value: string): string { return new Date(value).toLocaleString('zh-CN', { hour12: false }) }
function money(value: string, market: string): string {
  const currency = ({ CN: 'CNY', HK: 'HKD', US: 'USD' } as Record<string, string>)[market] || 'CNY'
  return new Intl.NumberFormat('zh-CN', { style: 'currency', currency, maximumFractionDigits: 0 }).format(Number(value))
}
function statusLabel(value: BacktestRunStatus): string { return statusOptions.find(item => item.value === value)?.label || value }
function statusType(value: BacktestRunStatus): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  return ({ queued: 'info', running: 'primary', succeeded: 'success', cancelled: 'warning', failed: 'danger' } as const)[value]
}
function percentValue(value: BacktestPerformanceReport[MetricKey]): string {
  return value === null || typeof value === 'object' ? '—' : `${(Number(value) * 100).toFixed(2)}%`
}
function decimalValue(value: BacktestPerformanceReport[MetricKey]): string {
  return value === null || typeof value === 'object' ? '—' : Number(value).toFixed(3)
}
function numberValue(value: BacktestPerformanceReport[MetricKey]): string {
  return value === null || typeof value === 'object' ? '—' : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(Number(value))
}
</script>

<style scoped lang="scss">
.backtest-page { padding: 24px; }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 20px; }
.page-header h1 { margin: 0 0 8px; font-size: 28px; line-height: 1.25; }
.page-header p { margin: 0; color: var(--el-text-color-secondary); max-width: 70ch; }
.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 14px; }
.filters, .compare-actions { display: flex; align-items: center; gap: 10px; }
.filters .el-select { width: 150px; }
.compare-actions span { color: var(--el-text-color-secondary); font-size: 13px; }
.table-surface { padding: 16px; background: var(--el-bg-color); border-radius: 12px; }
.run-link { display: flex; flex-direction: column; gap: 4px; padding: 5px 0; border: 0; background: none; color: var(--el-text-color-primary); text-align: left; cursor: pointer; }
.run-link:hover strong, .run-link:focus-visible strong { color: var(--el-color-primary); }
.run-link:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.run-link code, .stacked-cell small { color: var(--el-text-color-secondary); font-size: 12px; }
.stacked-cell { display: flex; flex-direction: column; gap: 4px; }
.muted { color: var(--el-text-color-secondary); }
.pagination { justify-content: flex-end; margin-top: 18px; }
.teaching-empty { padding: 36px 16px; display: grid; justify-items: center; gap: 8px; color: var(--el-text-color-secondary); }
.teaching-empty strong { color: var(--el-text-color-primary); font-size: 16px; }
.comparison-table { margin-top: 20px; overflow-x: auto; }
.comparison-table table { width: 100%; min-width: 720px; border-collapse: collapse; }
.comparison-table th, .comparison-table td { padding: 13px 14px; border-bottom: 1px solid var(--el-border-color-lighter); text-align: right; white-space: nowrap; }
.comparison-table th:first-child { position: sticky; left: 0; z-index: 1; text-align: left; background: var(--el-bg-color); }
.comparison-table thead th { color: var(--el-text-color-primary); font-weight: 600; }
.comparison-table thead small { display: block; margin-top: 4px; color: var(--el-text-color-secondary); font-weight: 400; }
@media (max-width: 720px) {
  .backtest-page { padding: 16px; }
  .page-header, .toolbar { align-items: stretch; flex-direction: column; }
  .filters { flex-wrap: wrap; }
  .compare-actions { justify-content: space-between; }
  .pagination { justify-content: flex-start; overflow-x: auto; }
}
</style>
