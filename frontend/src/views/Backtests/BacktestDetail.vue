<template>
  <section class="detail-page">
    <el-skeleton v-if="loading && !detail" :rows="12" animated />
    <template v-else-if="detail">
      <header class="detail-header">
        <div>
          <el-button link :icon="ArrowLeft" @click="router.push('/backtests')">返回回测中心</el-button>
          <div class="title-line">
            <h1>回测 {{ shortId(detail.run.run_id) }}</h1>
            <el-tag :type="statusType(detail.run.status)" effect="light">{{ statusLabel(detail.run.status) }}</el-tag>
          </div>
          <p>{{ detail.run.market }} · {{ detail.run.request.start_date }} 至 {{ detail.run.request.end_date }} · 基准 {{ detail.run.request.benchmark }}</p>
        </div>
        <div class="header-actions">
          <el-dropdown v-if="detail.run.status === 'succeeded'" trigger="click" @command="exportResult">
            <el-button :loading="exporting"><el-icon><Download /></el-icon>导出<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="trades:csv">交易 CSV</el-dropdown-item>
                <el-dropdown-item command="positions:csv">持仓 CSV</el-dropdown-item>
                <el-dropdown-item command="equity:csv">净值 CSV</el-dropdown-item>
                <el-dropdown-item command="events:json">事件 JSON</el-dropdown-item>
                <el-dropdown-item command="metrics:json" divided>指标 JSON</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button
            v-if="canCancel"
            type="danger"
            plain
            :loading="cancelling"
            @click="cancelRun"
          >取消回测</el-button>
          <el-button :icon="Refresh" :loading="loading" @click="refresh()">刷新</el-button>
        </div>
      </header>

      <section v-if="isActive" class="progress-panel" aria-live="polite">
        <div class="progress-copy">
          <div><strong>{{ stageLabel }}</strong><span>{{ progressPercent }}%</span></div>
          <p>{{ detail.task?.message || '任务正在等待可用的执行资源' }}</p>
        </div>
        <el-progress :percentage="progressPercent" :stroke-width="10" :show-text="false" />
        <dl>
          <div><dt>任务状态</dt><dd>{{ taskStatusLabel }}</dd></div>
          <div><dt>已完成日期</dt><dd>{{ detail.run.last_completed_trade_date || '尚未开始逐日计算' }}</dd></div>
          <div><dt>尝试次数</dt><dd>{{ detail.task ? `${detail.task.attempt}/${detail.task.max_attempts}` : '—' }}</dd></div>
        </dl>
      </section>

      <el-alert
        v-if="detail.run.status === 'failed'"
        :title="runErrorTitle"
        :description="runErrorDescription"
        type="error"
        :closable="false"
        show-icon
        class="state-alert"
      />
      <el-alert
        v-else-if="detail.run.status === 'cancelled'"
        title="回测已取消"
        description="取消后的账本数据保持只读，不会再产生新的订单或交易。"
        type="warning"
        :closable="false"
        show-icon
        class="state-alert"
      />

      <section v-if="allWarnings.length" class="warning-panel" aria-labelledby="warning-heading">
        <div class="section-title"><h2 id="warning-heading">数据质量与口径警告</h2><el-tag type="warning" effect="plain">{{ allWarnings.length }}</el-tag></div>
        <ul><li v-for="(warning, index) in allWarnings" :key="`${warning}-${index}`">{{ warning }}</li></ul>
      </section>

      <el-tabs v-if="detail.run.status === 'succeeded'" v-model="activeTab" class="result-tabs" @tab-change="tabChanged">
        <el-tab-pane label="结果总览" name="overview">
          <el-skeleton v-if="resultLoading && !metrics" :rows="10" animated />
          <template v-else-if="metrics">
            <div class="metric-strip">
              <div><span>总收益</span><strong :class="returnClass(metrics.total_return)">{{ percent(metrics.total_return) }}</strong></div>
              <div><span>年化收益</span><strong :class="returnClass(metrics.cagr)">{{ percent(metrics.cagr) }}</strong></div>
              <div><span>最大回撤</span><strong class="negative">{{ percent(metrics.max_drawdown) }}</strong></div>
              <div><span>夏普比率</span><strong>{{ decimal(metrics.sharpe_ratio) }}</strong></div>
              <div><span>胜率</span><strong>{{ percent(metrics.win_rate) }}</strong></div>
              <div><span>总费用</span><strong>{{ number(metrics.total_fees) }}</strong></div>
            </div>

            <section class="result-section" aria-labelledby="equity-heading">
              <div class="section-title">
                <div><h2 id="equity-heading">净值与回撤</h2><p>{{ equityDownsample === 'weekly' ? '数据点较多，已按周末值降采样' : '逐交易日展示' }}</p></div>
              </div>
              <EquityDrawdownChart :points="equity" />
            </section>

            <div class="analysis-grid">
              <section class="result-section" aria-labelledby="monthly-heading">
                <div class="section-title"><h2 id="monthly-heading">月度收益</h2></div>
                <div v-if="metrics.monthly_returns.length" class="return-heatmap">
                  <div
                    v-for="item in metrics.monthly_returns"
                    :key="item.period"
                    class="return-cell"
                    :style="returnCellStyle(item.return_rate)"
                    :title="`${item.start_date} 至 ${item.end_date}`"
                  ><span>{{ item.period }}</span><strong>{{ percent(item.return_rate) }}</strong></div>
                </div>
                <el-empty v-else description="暂无完整月度收益" :image-size="64" />
              </section>

              <section class="result-section" aria-labelledby="risk-heading">
                <div class="section-title"><h2 id="risk-heading">风险与基准</h2></div>
                <dl class="data-list">
                  <div><dt>年化波动率</dt><dd>{{ percent(metrics.annualized_volatility) }}</dd></div>
                  <div><dt>索提诺比率</dt><dd>{{ decimal(metrics.sortino_ratio) }}</dd></div>
                  <div><dt>Calmar 比率</dt><dd>{{ decimal(metrics.calmar_ratio) }}</dd></div>
                  <div><dt>基准总收益</dt><dd>{{ percent(metrics.benchmark_total_return) }}</dd></div>
                  <div><dt>相对收益</dt><dd>{{ percent(metrics.relative_total_return) }}</dd></div>
                  <div><dt>信息比率</dt><dd>{{ decimal(metrics.information_ratio) }}</dd></div>
                </dl>
              </section>
            </div>

            <div class="analysis-grid">
              <section class="result-section" aria-labelledby="position-heading">
                <div class="section-title"><h2 id="position-heading">持仓与暴露</h2></div>
                <dl class="data-list">
                  <div><dt>平均总暴露</dt><dd>{{ percent(metrics.average_gross_exposure) }}</dd></div>
                  <div><dt>最大总暴露</dt><dd>{{ percent(metrics.maximum_gross_exposure) }}</dd></div>
                  <div><dt>最终现金比例</dt><dd>{{ percent(metrics.final_cash_ratio) }}</dd></div>
                  <div><dt>最大个股集中度</dt><dd>{{ percent(metrics.maximum_stock_concentration) }}</dd></div>
                  <div><dt>最大行业集中度</dt><dd>{{ percent(metrics.maximum_industry_concentration) }}</dd></div>
                  <div><dt>平均日换手</dt><dd>{{ percent(metrics.average_daily_turnover) }}</dd></div>
                </dl>
              </section>
              <section class="result-section" aria-labelledby="trade-heading">
                <div class="section-title"><h2 id="trade-heading">交易质量</h2></div>
                <dl class="data-list">
                  <div><dt>成交笔数</dt><dd>{{ metrics.trade_count }}</dd></div>
                  <div><dt>已闭合批次</dt><dd>{{ metrics.closed_lot_count }}</dd></div>
                  <div><dt>盈亏比</dt><dd>{{ decimal(metrics.profit_loss_ratio) }}</dd></div>
                  <div><dt>Profit Factor</dt><dd>{{ decimal(metrics.profit_factor) }}</dd></div>
                  <div><dt>拒单数</dt><dd>{{ metrics.rejected_order_count }}</dd></div>
                  <div><dt>部分成交订单</dt><dd>{{ metrics.partially_filled_order_count }}</dd></div>
                </dl>
              </section>
            </div>
          </template>
        </el-tab-pane>

        <el-tab-pane label="交易复盘" name="trades">
          <div class="tab-toolbar">
            <el-date-picker v-model="tradeDates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" @change="resetTrades" />
            <span>费用与滑点均来自不可变成交账本</span>
          </div>
          <el-table v-loading="tradesLoading" :data="trades.items" stripe>
            <el-table-column prop="trade_date" label="日期" width="112" />
            <el-table-column prop="symbol" label="股票" width="115" />
            <el-table-column label="方向" width="82"><template #default="{ row }"><el-tag :type="row.side === 'buy' ? 'danger' : 'success'" effect="plain">{{ row.side === 'buy' ? '买入' : '卖出' }}</el-tag></template></el-table-column>
            <el-table-column prop="quantity" label="数量" width="100" align="right" />
            <el-table-column label="成交价" width="120" align="right"><template #default="{ row }">{{ number(row.fill_price, 4) }}</template></el-table-column>
            <el-table-column label="成交额" width="130" align="right"><template #default="{ row }">{{ number(row.notional) }}</template></el-table-column>
            <el-table-column label="费用" width="110" align="right"><template #default="{ row }">{{ number(row.fees.total) }}</template></el-table-column>
            <el-table-column label="滑点" width="110" align="right"><template #default="{ row }">{{ number(row.slippage, 4) }}</template></el-table-column>
            <el-table-column label="已实现盈亏" width="135" align="right"><template #default="{ row }"><span :class="returnClass(row.realized_pnl)">{{ number(row.realized_pnl) }}</span></template></el-table-column>
            <el-table-column label="退出原因" min-width="150"><template #default="{ row }">{{ exitReason(row.trade_id) }}</template></el-table-column>
            <template #empty><el-empty description="此区间没有成交记录" /></template>
          </el-table>
          <ResultPagination v-model:page="tradePage" :total="trades.total" @change="loadTrades" />
        </el-tab-pane>

        <el-tab-pane label="持仓分析" name="positions">
          <div class="tab-toolbar">
            <el-radio-group v-model="positionMode" @change="resetPositions">
              <el-radio-button label="day">指定日期</el-radio-button><el-radio-button label="range">日期区间</el-radio-button>
            </el-radio-group>
            <el-date-picker v-if="positionMode === 'day'" v-model="positionDay" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" @change="resetPositions" />
            <el-date-picker v-else v-model="positionDates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" @change="resetPositions" />
          </div>
          <el-table v-loading="positionsLoading" :data="positions.items" stripe>
            <el-table-column prop="trade_date" label="日期" width="112" />
            <el-table-column prop="symbol" label="股票" width="120" />
            <el-table-column prop="quantity" label="持仓" width="105" align="right" />
            <el-table-column prop="available_qty" label="可卖" width="105" align="right" />
            <el-table-column label="成本价" width="115" align="right"><template #default="{ row }">{{ number(row.avg_cost, 4) }}</template></el-table-column>
            <el-table-column label="收盘价" width="115" align="right"><template #default="{ row }">{{ number(row.close, 4) }}</template></el-table-column>
            <el-table-column label="市值" width="135" align="right"><template #default="{ row }">{{ number(row.market_value) }}</template></el-table-column>
            <el-table-column label="未实现盈亏" width="140" align="right"><template #default="{ row }"><span :class="returnClass(row.unrealized_pnl)">{{ number(row.unrealized_pnl) }}</span></template></el-table-column>
            <el-table-column label="权重" width="105" align="right"><template #default="{ row }">{{ percent(row.weight) }}</template></el-table-column>
            <el-table-column prop="holding_days" label="持有日" width="95" align="right" />
            <template #empty><el-empty description="所选日期没有持仓快照" /></template>
          </el-table>
          <ResultPagination v-model:page="positionPage" :total="positions.total" @change="loadPositions" />
        </el-tab-pane>

        <el-tab-pane label="事件与审计" name="events">
          <div class="tab-toolbar">
            <el-date-picker v-model="eventDates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" @change="resetEvents" />
            <span>按交易日、执行步骤和序号排序</span>
          </div>
          <el-table v-loading="eventsLoading" :data="events.items" stripe>
            <el-table-column type="expand"><template #default="{ row }"><pre class="event-data">{{ prettyJson(row.data) }}</pre></template></el-table-column>
            <el-table-column prop="trade_date" label="日期" width="112" />
            <el-table-column prop="step" label="步骤" width="75" align="center" />
            <el-table-column prop="sequence" label="序号" width="75" align="center" />
            <el-table-column prop="event_type" label="事件类型" min-width="240" />
            <el-table-column prop="symbol" label="股票" width="120"><template #default="{ row }">{{ row.symbol || '—' }}</template></el-table-column>
            <template #empty><el-empty description="此区间没有审计事件" /></template>
          </el-table>
          <ResultPagination v-model:page="eventPage" :total="events.total" @change="loadEvents" />
        </el-tab-pane>

        <el-tab-pane label="配置与版本" name="configuration">
          <section class="config-section">
            <h2>运行配置</h2>
            <el-descriptions :column="2" border>
              <el-descriptions-item label="策略版本">{{ detail.run.strategy_version_id }}</el-descriptions-item>
              <el-descriptions-item label="市场">{{ detail.run.market }}</el-descriptions-item>
              <el-descriptions-item label="区间">{{ detail.run.request.start_date }} 至 {{ detail.run.request.end_date }}</el-descriptions-item>
              <el-descriptions-item label="初始资金">{{ number(detail.run.request.initial_cash) }} {{ detail.run.request.base_currency }}</el-descriptions-item>
              <el-descriptions-item label="基准">{{ detail.run.request.benchmark }}</el-descriptions-item>
              <el-descriptions-item label="成交模型">{{ detail.run.request.execution_model_id }}</el-descriptions-item>
              <el-descriptions-item label="随机种子">{{ detail.run.request.seed }}</el-descriptions-item>
              <el-descriptions-item label="每日持仓">{{ detail.run.request.save_daily_positions ? '保存' : '不保存' }}</el-descriptions-item>
              <el-descriptions-item label="参数覆盖" :span="2"><pre>{{ prettyJson(detail.run.request.parameter_overrides) }}</pre></el-descriptions-item>
              <el-descriptions-item label="备注" :span="2">{{ detail.run.request.notes || '—' }}</el-descriptions-item>
            </el-descriptions>
          </section>
          <section class="config-section">
            <h2>冻结输入版本</h2>
            <dl class="version-list">
              <div v-for="(values, key) in detail.run.input_versions" :key="key"><dt>{{ key }}</dt><dd><code v-for="value in values" :key="value">{{ value }}</code><span v-if="!values.length">无</span></dd></div>
            </dl>
          </section>
        </el-tab-pane>
      </el-tabs>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElButton, ElMessage, ElMessageBox, ElPagination } from 'element-plus'
import { ArrowDown, ArrowLeft, Download, Refresh } from '@element-plus/icons-vue'
import { backtestApi } from '@/api/backtests'
import type {
  BacktestEquityPoint,
  BacktestEvent,
  BacktestExportFormat,
  BacktestExportResource,
  BacktestPage,
  BacktestPerformanceReport,
  BacktestPosition,
  BacktestRunDetail,
  BacktestRunStatus,
  BacktestTrade,
  EquityDownsample
} from '@/types/backtest'
import EquityDrawdownChart from './components/EquityDrawdownChart.vue'

const ResultPagination = defineComponent({
  props: { page: { type: Number, required: true }, total: { type: Number, required: true } },
  emits: ['update:page', 'change'],
  setup(props, { emit }) {
    return () => props.total > 0 ? h(ElPagination, {
      currentPage: props.page,
      pageSize: 50,
      total: props.total,
      layout: 'total, prev, pager, next',
      class: 'result-pagination',
      'onUpdate:currentPage': (value: number) => emit('update:page', value),
      onCurrentChange: () => emit('change')
    }) : null
  }
})

const route = useRoute()
const router = useRouter()
const runId = computed(() => String(route.params.runId))
const detail = ref<BacktestRunDetail | null>(null)
const metrics = ref<BacktestPerformanceReport | null>(null)
const equity = ref<BacktestEquityPoint[]>([])
const equityDownsample = ref<EquityDownsample>('none')
const loading = ref(true)
const resultLoading = ref(false)
const cancelling = ref(false)
const exporting = ref(false)
const activeTab = ref('overview')
const trades = ref<BacktestPage<BacktestTrade>>(emptyPage())
const positions = ref<BacktestPage<BacktestPosition>>(emptyPage())
const events = ref<BacktestPage<BacktestEvent>>(emptyPage())
const tradePage = ref(1)
const positionPage = ref(1)
const eventPage = ref(1)
const tradeDates = ref<string[]>([])
const eventDates = ref<string[]>([])
const positionMode = ref<'day' | 'range'>('day')
const positionDay = ref('')
const positionDates = ref<string[]>([])
const tradesLoading = ref(false)
const positionsLoading = ref(false)
const eventsLoading = ref(false)
let pollTimer: number | null = null
let resultsLoaded = false

const isActive = computed(() => detail.value
  ? ['queued', 'running'].includes(detail.value.run.status)
    || detail.value.task?.status === 'cancelling'
  : false)
const canCancel = computed(() => detail.value
  ? ['queued', 'running'].includes(detail.value.run.status)
    && detail.value.task?.status !== 'cancelling'
  : false)
const progressPercent = computed(() => Math.round((detail.value?.task?.progress || 0) * 100))
const stageLabel = computed(() => stageNames[detail.value?.task?.stage || ''] || detail.value?.task?.stage || '等待执行')
const taskStatusLabel = computed(() => taskStatusNames[detail.value?.task?.status || ''] || detail.value?.task?.status || '任务信息暂不可用')
const runErrorTitle = computed(() => String(detail.value?.run.error?.code || detail.value?.task?.error?.code || '回测执行失败'))
const runErrorDescription = computed(() => String(detail.value?.run.error?.message || detail.value?.task?.error?.message || '请检查配置、数据覆盖范围和任务日志。'))
const allWarnings = computed(() => {
  const warnings = detail.value?.run.bias_warnings.map(item => String(item.message || item.code || prettyJson(item))) || []
  return Array.from(new Set([...warnings, ...(metrics.value?.warnings || [])]))
})

const stageNames: Record<string, string> = {
  queued: '排队中', backtest_queued: '回测已入队', initializing: '初始化账本',
  loading_data: '加载时间点数据', generating_signals: '生成信号', executing_orders: '执行订单',
  reconciling: '核对账本', finalizing: '生成结果'
}
const taskStatusNames: Record<string, string> = {
  queued: '排队中', running: '运行中', retry_wait: '等待重试', cancelling: '正在取消',
  succeeded: '已完成', cancelled: '已取消', failed: '失败'
}

onMounted(refresh)
onBeforeUnmount(stopPolling)

async function refresh(silent = false): Promise<void> {
  if (!silent) loading.value = true
  try {
    const previousStatus = detail.value?.run.status
    detail.value = await backtestApi.get(runId.value)
    if (!positionDay.value) {
      positionDay.value = detail.value.run.last_completed_trade_date || detail.value.run.request.end_date
    }
    if (isActive.value) startPolling()
    else stopPolling()
    if (detail.value.run.status === 'succeeded' && (!resultsLoaded || previousStatus !== 'succeeded')) {
      await loadOverview()
    }
  } finally {
    if (!silent) loading.value = false
  }
}

function startPolling(): void {
  if (pollTimer !== null) return
  pollTimer = window.setInterval(() => refresh(true), 3000)
}
function stopPolling(): void {
  if (pollTimer !== null) window.clearInterval(pollTimer)
  pollTimer = null
}

async function loadOverview(): Promise<void> {
  if (resultLoading.value) return
  resultLoading.value = true
  try {
    const [report, first] = await Promise.all([
      backtestApi.metrics(runId.value),
      backtestApi.equity(runId.value, { page: 1, page_size: 200, downsample: 'none' })
    ])
    metrics.value = report
    equityDownsample.value = first.total > 500 ? 'weekly' : 'none'
    equity.value = await loadEquityPages(equityDownsample.value, first.total > 500 ? undefined : first)
    resultsLoaded = true
  } finally { resultLoading.value = false }
}

async function loadEquityPages(mode: EquityDownsample, initial?: { items: BacktestEquityPoint[]; total: number }): Promise<BacktestEquityPoint[]> {
  const rows = initial ? [...initial.items] : []
  let page = initial ? 2 : 1
  let total = initial?.total || Number.POSITIVE_INFINITY
  while (rows.length < total && page <= 50) {
    const response = await backtestApi.equity(runId.value, { page, page_size: 200, downsample: mode })
    rows.push(...response.items)
    total = response.total
    if (!response.items.length) break
    page += 1
  }
  return rows
}

async function tabChanged(name: string | number): Promise<void> {
  if (name === 'trades' && !trades.value.total) await loadTrades()
  if (name === 'positions' && !positions.value.total) await loadPositions()
  if (name === 'events' && !events.value.total) await loadEvents()
}

async function loadTrades(): Promise<void> {
  tradesLoading.value = true
  try { trades.value = await backtestApi.trades(runId.value, { page: tradePage.value, page_size: 50, start_date: tradeDates.value[0], end_date: tradeDates.value[1] }) }
  finally { tradesLoading.value = false }
}
async function loadPositions(): Promise<void> {
  positionsLoading.value = true
  try {
    positions.value = await backtestApi.positions(runId.value, {
      page: positionPage.value, page_size: 50,
      trade_date: positionMode.value === 'day' ? positionDay.value || undefined : undefined,
      start_date: positionMode.value === 'range' ? positionDates.value[0] : undefined,
      end_date: positionMode.value === 'range' ? positionDates.value[1] : undefined
    })
  } finally { positionsLoading.value = false }
}
async function loadEvents(): Promise<void> {
  eventsLoading.value = true
  try { events.value = await backtestApi.events(runId.value, { page: eventPage.value, page_size: 50, start_date: eventDates.value[0], end_date: eventDates.value[1] }) }
  finally { eventsLoading.value = false }
}
function resetTrades(): void { tradePage.value = 1; loadTrades() }
function resetPositions(): void { positionPage.value = 1; loadPositions() }
function resetEvents(): void { eventPage.value = 1; loadEvents() }

async function cancelRun(): Promise<void> {
  await ElMessageBox.confirm('取消后不会再产生新交易，已经写入的账本和事件会保留。', '确认取消回测', { type: 'warning', confirmButtonText: '确认取消', cancelButtonText: '继续运行' })
  cancelling.value = true
  try { await backtestApi.cancel(runId.value); ElMessage.success('取消请求已提交'); await refresh(true) }
  finally { cancelling.value = false }
}

async function exportResult(command: string): Promise<void> {
  const [resource, format] = command.split(':') as [BacktestExportResource, BacktestExportFormat]
  exporting.value = true
  try {
    const result = await backtestApi.export(runId.value, resource, format)
    if (result.kind === 'deferred') {
      ElMessage.info(`数据量 ${result.estimated_rows} 行，超过同步上限，请使用异步导出流程`)
      return
    }
    const url = URL.createObjectURL(result.blob)
    const link = document.createElement('a')
    link.href = url
    link.download = result.filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } catch {
    ElMessage.error('导出失败，请刷新任务状态后重试')
  } finally { exporting.value = false }
}

function emptyPage<T>(): BacktestPage<T> { return { items: [], page: 1, page_size: 50, total: 0 } }
function shortId(value: string): string { return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value }
function statusLabel(value: BacktestRunStatus): string { return ({ queued: '排队中', running: '运行中', succeeded: '已完成', cancelled: '已取消', failed: '失败' })[value] }
function statusType(value: BacktestRunStatus): 'success' | 'warning' | 'danger' | 'info' | 'primary' { return ({ queued: 'info', running: 'primary', succeeded: 'success', cancelled: 'warning', failed: 'danger' } as const)[value] }
function percent(value: string | null): string { return value === null ? '—' : `${(Number(value) * 100).toFixed(2)}%` }
function decimal(value: string | null): string { return value === null ? '—' : Number(value).toFixed(3) }
function number(value: string | number | null, digits = 2): string { return value === null ? '—' : new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: digits }).format(Number(value)) }
function returnClass(value: string | number | null): string { if (value === null) return ''; return Number(value) > 0 ? 'positive' : Number(value) < 0 ? 'negative' : '' }
function prettyJson(value: unknown): string { return JSON.stringify(value, null, 2) }
function exitReason(tradeId: string): string { return metrics.value?.closed_lots.find(item => item.sell_trade_id === tradeId)?.exit_reason || '—' }
function returnCellStyle(value: string): Record<string, string> {
  const amount = Math.min(Math.abs(Number(value)) * 7, 0.34)
  return Number(value) >= 0
    ? { backgroundColor: `rgba(103, 194, 58, ${0.08 + amount})`, color: '#285a13' }
    : { backgroundColor: `rgba(245, 108, 108, ${0.08 + amount})`, color: '#8b2525' }
}
</script>

<style scoped lang="scss">
.detail-page { padding: 24px; }
.detail-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 24px; margin-bottom: 20px; }
.title-line { display: flex; align-items: center; gap: 12px; margin-top: 8px; }
.title-line h1 { margin: 0; font-size: 28px; line-height: 1.25; }
.detail-header p { margin: 8px 0 0; color: var(--el-text-color-secondary); }
.header-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; padding-top: 30px; }
.progress-panel { padding: 22px 24px; margin-bottom: 20px; background: var(--el-bg-color); border: 1px solid var(--el-border-color-light); border-radius: 12px; }
.progress-copy div { display: flex; justify-content: space-between; gap: 16px; }
.progress-copy p { margin: 6px 0 14px; color: var(--el-text-color-secondary); }
.progress-panel dl { display: flex; flex-wrap: wrap; gap: 24px 48px; margin: 16px 0 0; }
.progress-panel dl div { display: flex; gap: 8px; }
.progress-panel dt { color: var(--el-text-color-secondary); }
.progress-panel dd { margin: 0; }
.state-alert, .warning-panel { margin-bottom: 20px; }
.warning-panel { padding: 18px 22px; border-radius: 12px; background: var(--el-color-warning-light-9); }
.warning-panel ul { margin: 12px 0 0; padding-left: 22px; line-height: 1.7; }
.result-tabs { padding: 6px 20px 24px; background: var(--el-bg-color); border-radius: 12px; }
.metric-strip { display: grid; grid-template-columns: repeat(6, minmax(130px, 1fr)); border-bottom: 1px solid var(--el-border-color-lighter); overflow-x: auto; }
.metric-strip div { min-width: 130px; padding: 22px 16px; }
.metric-strip span { display: block; margin-bottom: 7px; color: var(--el-text-color-secondary); font-size: 13px; }
.metric-strip strong { font-size: 22px; font-variant-numeric: tabular-nums; }
.result-section { padding: 24px 4px; }
.analysis-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 32px; border-top: 1px solid var(--el-border-color-lighter); }
.section-title { display: flex; align-items: center; gap: 10px; justify-content: space-between; margin-bottom: 14px; }
.section-title h2 { margin: 0; font-size: 18px; }
.section-title p { margin: 4px 0 0; color: var(--el-text-color-secondary); font-size: 13px; }
.data-list { margin: 0; }
.data-list div { display: flex; justify-content: space-between; gap: 18px; padding: 10px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.data-list dt { color: var(--el-text-color-secondary); }
.data-list dd { margin: 0; font-variant-numeric: tabular-nums; }
.return-heatmap { display: grid; grid-template-columns: repeat(auto-fit, minmax(90px, 1fr)); gap: 8px; }
.return-cell { display: flex; flex-direction: column; gap: 6px; min-height: 66px; padding: 11px; border-radius: 8px; }
.return-cell span { font-size: 12px; opacity: .86; }
.return-cell strong { font-variant-numeric: tabular-nums; }
.positive { color: var(--el-color-success-dark-2); }
.negative { color: var(--el-color-danger); }
.tab-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin: 12px 0 16px; }
.tab-toolbar > span { color: var(--el-text-color-secondary); font-size: 13px; }
:deep(.result-pagination) { justify-content: flex-end; margin-top: 18px; }
.event-data, .config-section pre { margin: 0; padding: 12px; overflow: auto; background: var(--el-fill-color-light); border-radius: 8px; font: 12px/1.6 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; word-break: break-word; }
.config-section { padding: 18px 0 24px; }
.config-section + .config-section { border-top: 1px solid var(--el-border-color-lighter); }
.config-section h2 { margin: 0 0 16px; font-size: 18px; }
.version-list { margin: 0; }
.version-list > div { display: grid; grid-template-columns: 140px minmax(0, 1fr); gap: 16px; padding: 11px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.version-list dt { color: var(--el-text-color-secondary); }
.version-list dd { display: flex; flex-direction: column; gap: 5px; margin: 0; overflow-wrap: anywhere; }
@media (max-width: 980px) {
  .metric-strip { grid-template-columns: repeat(3, minmax(130px, 1fr)); }
  .analysis-grid { grid-template-columns: 1fr; gap: 0; }
}
@media (max-width: 720px) {
  .detail-page { padding: 16px; }
  .detail-header { flex-direction: column; }
  .header-actions { justify-content: flex-start; padding-top: 0; }
  .progress-panel { padding: 18px 16px; }
  .progress-panel dl { display: grid; gap: 9px; }
  .result-tabs { padding: 4px 12px 18px; }
  .metric-strip { grid-template-columns: repeat(2, minmax(125px, 1fr)); }
  .version-list > div { grid-template-columns: 1fr; gap: 6px; }
  :deep(.el-descriptions__body) { overflow-x: auto; }
}
@media (prefers-reduced-motion: reduce) {
  :deep(*) { scroll-behavior: auto !important; transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; }
}
</style>
