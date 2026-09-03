<template>
  <section class="parameter-lab" aria-labelledby="parameter-lab-title">
    <header class="lab-header">
      <div>
        <h2 id="parameter-lab-title">参数实验室</h2>
        <p>按验证集选择候选，同时强制展示留出测试集与参数稳定性。结果仅供研究，不会自动发布策略。</p>
      </div>
      <el-button :icon="Close" aria-label="关闭参数实验室" @click="emit('close')">关闭</el-button>
    </header>

    <el-alert
      title="研究结果不是发布指令"
      description="系统不会用全样本或训练集最高收益自动发布策略。候选仅按验证集排序，测试集始终作为独立证据展示。"
      type="warning"
      :closable="false"
      show-icon
    />

    <div class="lab-layout">
      <el-form label-position="top" class="experiment-form" @submit.prevent="submit">
        <div class="section-title">
          <h3>实验定义</h3>
          <span>{{ combinationCount }} / {{ form.combinationLimit }} 个组合</span>
        </div>
        <el-form-item label="实验名称" required>
          <el-input v-model="form.name" maxlength="120" show-word-limit />
        </el-form-item>
        <el-form-item label="已发布策略版本" required>
          <el-select
            v-model="form.strategyVersionId"
            class="full-width"
            filterable
            :loading="loadingStrategies"
            placeholder="选择已发布策略"
            @change="applyStrategy"
          >
            <el-option
              v-for="item in strategies"
              :key="item.strategy_version_id"
              :label="`${item.name} · ${item.market}`"
              :value="item.strategy_version_id"
            />
          </el-select>
        </el-form-item>

        <div class="two-columns">
          <el-form-item label="回测区间" required>
            <el-date-picker
              v-model="form.dateRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              unlink-panels
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              class="full-width"
            />
          </el-form-item>
          <el-form-item label="初始资金" required>
            <el-input v-model="form.initialCash" inputmode="decimal">
              <template #append>{{ currency }}</template>
            </el-input>
          </el-form-item>
          <el-form-item label="基准代码" required>
            <el-input v-model="form.benchmark" maxlength="128" />
          </el-form-item>
          <el-form-item label="成交模型">
            <el-select v-model="form.executionModelId" class="full-width">
              <el-option label="下一交易日开盘" value="next_open" />
              <el-option label="下一交易日收盘" value="next_close" />
            </el-select>
          </el-form-item>
        </div>

        <div class="section-title parameter-heading">
          <div>
            <h3>参数网格</h3>
            <small>1–3 个参数，逗号分隔候选值</small>
          </div>
          <el-button
            text
            type="primary"
            :disabled="form.axes.length >= 3"
            :icon="Plus"
            @click="addAxis"
          >增加参数</el-button>
        </div>
        <div v-for="(axis, index) in form.axes" :key="axis.key" class="axis-row">
          <el-input v-model="axis.name" :aria-label="`参数 ${index + 1} 名称`" placeholder="如 lookback" />
          <el-input
            v-model="axis.values"
            :aria-label="`参数 ${index + 1} 候选值`"
            placeholder="如 10, 20, 30"
          />
          <el-button
            :icon="Delete"
            circle
            plain
            :disabled="form.axes.length === 1"
            :aria-label="`删除参数 ${index + 1}`"
            @click="removeAxis(index)"
          />
        </div>
        <p class="field-note">名称只能包含字母、数字、下划线、点和连字符；每个参数值不可重复。</p>

        <div class="section-title evaluation-heading">
          <h3>评估方式</h3>
          <el-radio-group v-model="form.mode">
            <el-radio-button v-for="item in modeOptions" :key="item.value" :label="item.value">
              {{ item.label }}
            </el-radio-button>
          </el-radio-group>
        </div>
        <div v-if="form.mode === 'split'" class="two-columns">
          <el-form-item label="训练集结束日" required>
            <el-date-picker v-model="form.trainEnd" value-format="YYYY-MM-DD" class="full-width" />
          </el-form-item>
          <el-form-item label="验证集结束日" required>
            <el-date-picker v-model="form.validationEnd" value-format="YYYY-MM-DD" class="full-width" />
          </el-form-item>
        </div>
        <div v-else class="walk-grid">
          <el-form-item label="训练交易日">
            <el-input-number v-model="form.trainSessions" :min="20" :max="5000" />
          </el-form-item>
          <el-form-item label="验证交易日">
            <el-input-number v-model="form.validationSessions" :min="5" :max="1000" />
          </el-form-item>
          <el-form-item label="测试交易日">
            <el-input-number v-model="form.testSessions" :min="5" :max="1000" />
          </el-form-item>
          <el-form-item label="滚动步长">
            <el-input-number v-model="form.stepSessions" :min="1" :max="1000" />
          </el-form-item>
          <el-form-item label="最多折数">
            <el-input-number v-model="form.maxFolds" :min="1" :max="20" />
          </el-form-item>
        </div>

        <div class="submit-row">
          <div>
            <strong>{{ combinationCount }} 个独立子回测</strong>
            <span>默认上限 100，系统硬上限 500</span>
          </div>
          <el-button
            type="primary"
            native-type="submit"
            :loading="submitting"
            :disabled="combinationCount < 1 || combinationCount > form.combinationLimit"
          >开始实验</el-button>
        </div>
      </el-form>

      <aside class="research-pane" aria-label="参数实验记录">
        <div class="section-title">
          <h3>实验记录</h3>
          <el-button text :icon="Refresh" :loading="loadingSearches" @click="loadSearches">刷新</el-button>
        </div>
        <el-skeleton v-if="loadingSearches && !searches.length" :rows="5" animated />
        <div v-else-if="!searches.length" class="empty-state">
          <strong>尚无参数实验</strong>
          <span>定义参数网格和评估窗口后，实验进度会保存在这里。</span>
        </div>
        <template v-else>
          <button
            v-for="search in searches"
            :key="search.search_id"
            type="button"
            class="search-row"
            :class="{ active: selectedSearchId === search.search_id }"
            @click="selectSearch(search.search_id)"
          >
            <span class="search-row-top">
              <strong>{{ search.name }}</strong>
              <el-tag :type="statusType(search.status)" size="small">{{ statusLabel(search.status) }}</el-tag>
            </span>
            <span class="progress-copy">{{ search.completed_combinations }} / {{ search.total_combinations }} 个组合</span>
            <el-progress
              :percentage="progressPercent(search)"
              :show-text="false"
              :stroke-width="5"
              :status="search.status === 'failed' ? 'exception' : search.status === 'succeeded' ? 'success' : undefined"
            />
          </button>
        </template>
      </aside>
    </div>

    <section v-if="selectedSearch" class="result-section" aria-labelledby="parameter-results-title">
      <div class="result-header">
        <div>
          <h3 id="parameter-results-title">{{ selectedSearch.name }} · 评估结果</h3>
          <p>候选排序只读取验证集；测试集收益和稳定性不会参与选优。</p>
        </div>
        <el-button
          v-if="['queued', 'running'].includes(selectedSearch.status)"
          :loading="cancelling"
          @click="cancelSelected"
        >取消实验</el-button>
      </div>
      <el-skeleton v-if="loadingResults" :rows="6" animated />
      <div v-else-if="!results.length" class="empty-state result-empty">
        <strong>{{ selectedSearch.status === 'failed' ? '实验执行失败' : '等待首个组合完成' }}</strong>
        <span>{{ selectedSearch.status === 'failed' ? errorMessage(selectedSearch.error) : '每个参数组合完成后，样本外证据会逐条出现。' }}</span>
      </div>
      <template v-else>
        <div class="heatmap-heading">
          <div>
            <h4>验证集收益热力图</h4>
            <span>蓝色为正、红色为负；单元格下方同步显示留出测试集，避免只看样本内。</span>
          </div>
          <label v-if="heatmapSliceAxis" class="slice-control">
            <span>{{ heatmapSliceAxis.name }}</span>
            <el-select v-model="sliceValue" size="small">
              <el-option
                v-for="value in heatmapSliceAxis.values"
                :key="JSON.stringify(value)"
                :label="String(value)"
                :value="value"
              />
            </el-select>
          </label>
        </div>
        <div class="heatmap-scroll">
          <div
            class="heatmap"
            :style="{ gridTemplateColumns: `minmax(92px, auto) repeat(${heatmapColumns.length}, minmax(106px, 1fr))` }"
          >
            <div class="heatmap-corner">{{ heatmapYAxis?.name || '组合' }} \ {{ heatmapXAxis?.name }}</div>
            <div v-for="value in heatmapColumns" :key="`column-${JSON.stringify(value)}`" class="heatmap-axis">
              {{ value }}
            </div>
            <template v-for="rowValue in heatmapRows" :key="`row-${JSON.stringify(rowValue)}`">
              <div class="heatmap-axis row-axis">{{ rowValue ?? '收益' }}</div>
              <div
                v-for="columnValue in heatmapColumns"
                :key="`cell-${JSON.stringify(rowValue)}-${JSON.stringify(columnValue)}`"
                class="heatmap-cell"
                :class="{ selected: heatmapCell(columnValue, rowValue)?.selected_candidate }"
                :style="heatmapCellStyle(heatmapCell(columnValue, rowValue))"
              >
                <strong>{{ percent(heatmapCell(columnValue, rowValue)?.validation_mean_return) }}</strong>
                <span>测试 {{ percent(heatmapCell(columnValue, rowValue)?.test_mean_return) }}</span>
              </div>
            </template>
          </div>
        </div>

        <el-table :data="resultTableRows" stripe row-key="combination_index" class="result-table">
          <el-table-column label="验证排名" width="105">
            <template #default="{ row }">
              <span v-if="row.validation_rank">#{{ row.validation_rank }}</span>
              <span v-else>—</span>
              <el-tag v-if="row.selected_candidate" type="success" size="small" class="candidate-tag">候选</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="参数" min-width="220">
            <template #default="{ row }"><code class="parameter-values">{{ formatParameters(row.parameters) }}</code></template>
          </el-table-column>
          <el-table-column label="训练集" width="116">
            <template #default="{ row }">{{ percent(row.train_mean_return) }}</template>
          </el-table-column>
          <el-table-column label="验证集" width="116">
            <template #default="{ row }"><strong>{{ percent(row.validation_mean_return) }}</strong></template>
          </el-table-column>
          <el-table-column label="留出测试集" width="126">
            <template #default="{ row }">{{ percent(row.test_mean_return) }}</template>
          </el-table-column>
          <el-table-column label="稳定性" width="116">
            <template #default="{ row }">{{ stability(row.stability?.stability_score) }}</template>
          </el-table-column>
          <el-table-column label="测试折为正" width="120">
            <template #default="{ row }">{{ percent(row.stability?.positive_test_fold_ratio) }}</template>
          </el-table-column>
          <el-table-column label="子回测" width="92" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="router.push(`/backtests/${row.child_run_id}`)">查看</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-if="results.length > resultPageSize"
          v-model:current-page="resultPage"
          :page-size="resultPageSize"
          :total="results.length"
          layout="total, prev, pager, next"
          class="result-pagination"
        />
      </template>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Close, Delete, Plus, Refresh } from '@element-plus/icons-vue'
import {
  backtestApi,
  type ParameterCombinationResult,
  type ParameterSearchMode,
  type ParameterSearchRecord,
  type ParameterSearchRequest,
  type ParameterSearchStatus,
  type ParameterValue
} from '@/api/backtests'
import { strategyApi } from '@/api/strategies'
import type { BacktestMarket, PublishedStrategyOption } from '@/types/backtest'
import type { StrategyDefinition, StrategyVersion } from '@/types/strategy'

interface AxisForm { key: number; name: string; values: string }

const emit = defineEmits<{ close: [] }>()
const router = useRouter()
const today = new Date()
const oneYearAgo = new Date(today.getFullYear() - 1, today.getMonth(), today.getDate())
const dateText = (value: Date): string => [
  value.getFullYear(),
  String(value.getMonth() + 1).padStart(2, '0'),
  String(value.getDate()).padStart(2, '0')
].join('-')
let axisKey = 1
let pollTimer: number | null = null

const strategies = ref<PublishedStrategyOption[]>([])
const searches = ref<ParameterSearchRecord[]>([])
const results = ref<ParameterCombinationResult[]>([])
const selectedSearchId = ref('')
const loadingStrategies = ref(false)
const loadingSearches = ref(false)
const loadingResults = ref(false)
const submitting = ref(false)
const cancelling = ref(false)
const idempotencyKey = ref(newKey())
const sliceValue = ref<ParameterValue | null>(null)
const resultPage = ref(1)
const resultPageSize = 50

const form = reactive({
  name: '稳健参数实验',
  strategyVersionId: '',
  market: 'CN' as BacktestMarket,
  dateRange: [dateText(oneYearAgo), dateText(today)] as string[],
  initialCash: '1000000',
  benchmark: '000300',
  executionModelId: 'next_open',
  axes: [{ key: axisKey, name: 'lookback', values: '10, 20, 30' }] as AxisForm[],
  mode: 'split' as ParameterSearchMode,
  trainEnd: dateText(new Date(today.getFullYear() - 1, today.getMonth() + 7, today.getDate())),
  validationEnd: dateText(new Date(today.getFullYear() - 1, today.getMonth() + 10, today.getDate())),
  trainSessions: 120,
  validationSessions: 30,
  testSessions: 30,
  stepSessions: 30,
  maxFolds: 10,
  combinationLimit: 100
})

const modeOptions = [
  { label: '固定拆分', value: 'split' },
  { label: '滚动前推', value: 'walk_forward' }
]
const selectedSearch = computed(() => searches.value.find(item => item.search_id === selectedSearchId.value))
const selectedStrategy = computed(() => strategies.value.find(item => item.strategy_version_id === form.strategyVersionId))
const currency = computed(() => ({ CN: 'CNY', HK: 'HKD', US: 'USD' })[form.market])
const parsedAxes = computed(() => form.axes.map(axis => ({
  name: axis.name.trim(),
  values: parseValues(axis.values)
})))
const combinationCount = computed(() => parsedAxes.value.reduce(
  (count, axis) => count * axis.values.length, 1
))
const heatmapXAxis = computed(() => selectedSearch.value?.request.axes[0])
const heatmapYAxis = computed(() => selectedSearch.value?.request.axes[1])
const heatmapSliceAxis = computed(() => selectedSearch.value?.request.axes[2])
const heatmapColumns = computed(() => heatmapXAxis.value?.values || [])
const heatmapRows = computed<Array<ParameterValue | null>>(() => heatmapYAxis.value?.values || [null])
const resultTableRows = computed(() => results.value.slice(
  (resultPage.value - 1) * resultPageSize,
  resultPage.value * resultPageSize
))

onMounted(async () => {
  await Promise.all([loadStrategies(), loadSearches()])
  pollTimer = window.setInterval(refreshActive, 4000)
})
onBeforeUnmount(() => { if (pollTimer !== null) window.clearInterval(pollTimer) })

async function loadStrategies(): Promise<void> {
  loadingStrategies.value = true
  try {
    const [owned, templates] = await Promise.all([strategyApi.list(), strategyApi.listTemplates()])
    const details = await Promise.all(
      owned.filter(item => item.latest_published_version_id).map(item => strategyApi.get(item.strategy_id))
    )
    const options = new Map<string, PublishedStrategyOption>()
    templates.forEach(item => options.set(item.strategy_version_id, {
      strategy_id: item.strategy_id,
      strategy_version_id: item.strategy_version_id,
      name: item.name,
      market: item.market,
      fee_model_version: feeModel(item.definition)
    }))
    details.forEach(detail => {
      const version = detail.versions.find(item => item.strategy_version_id === detail.strategy.latest_published_version_id)
      if (version) options.set(version.strategy_version_id, versionOption(detail.strategy.strategy_id, detail.strategy.name, version))
    })
    strategies.value = [...options.values()].sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
  } catch {
    ElMessage.error('已发布策略加载失败，请稍后重试')
  } finally { loadingStrategies.value = false }
}

async function loadSearches(): Promise<void> {
  loadingSearches.value = true
  try {
    const page = await backtestApi.listParameterSearches({ page: 1, page_size: 50 })
    searches.value = page.items
    if (!selectedSearchId.value && page.items.length) await selectSearch(page.items[0].search_id)
  } catch {
    ElMessage.error('参数实验记录加载失败，请稍后重试')
  } finally { loadingSearches.value = false }
}

async function selectSearch(searchId: string): Promise<void> {
  selectedSearchId.value = searchId
  resultPage.value = 1
  sliceValue.value = selectedSearch.value?.request.axes[2]?.values[0] ?? null
  await loadResults()
}

async function loadResults(): Promise<void> {
  if (!selectedSearchId.value) return
  loadingResults.value = true
  try {
    const [detail, firstPage] = await Promise.all([
      backtestApi.getParameterSearch(selectedSearchId.value),
      backtestApi.getParameterSearchResults(selectedSearchId.value, { page: 1, page_size: 200 })
    ])
    const remainingPages = Array.from(
      { length: Math.max(0, Math.ceil(firstPage.total / 200) - 1) },
      (_, index) => index + 2
    )
    const remaining = await Promise.all(remainingPages.map(page => (
      backtestApi.getParameterSearchResults(selectedSearchId.value, { page, page_size: 200 })
    )))
    const index = searches.value.findIndex(item => item.search_id === detail.search.search_id)
    if (index >= 0) searches.value[index] = detail.search
    results.value = [firstPage, ...remaining].flatMap(page => page.items)
  } catch {
    ElMessage.error('参数实验结果加载失败，请稍后重试')
  } finally { loadingResults.value = false }
}

async function refreshActive(): Promise<void> {
  if (!searches.value.some(item => ['queued', 'running'].includes(item.status))) return
  await loadSearches()
  if (selectedSearch.value && ['queued', 'running'].includes(selectedSearch.value.status)) await loadResults()
}

function addAxis(): void {
  if (form.axes.length >= 3) return
  axisKey += 1
  form.axes.push({ key: axisKey, name: '', values: '' })
}
function removeAxis(index: number): void { if (form.axes.length > 1) form.axes.splice(index, 1) }

async function submit(): Promise<void> {
  const error = validateForm()
  if (error) { ElMessage.warning(error); return }
  submitting.value = true
  try {
    const request: ParameterSearchRequest = {
      name: form.name.trim(),
      base_request: {
        strategy_version_id: form.strategyVersionId,
        market: form.market,
        start_date: form.dateRange[0],
        end_date: form.dateRange[1],
        initial_cash: form.initialCash,
        benchmark: form.benchmark.trim(),
        execution_model_id: form.executionModelId,
        parameter_overrides: {},
        seed: 0,
        save_daily_positions: true,
        notes: `参数实验：${form.name.trim()}`
      },
      axes: parsedAxes.value,
      mode: form.mode,
      split: form.mode === 'split' ? { train_end: form.trainEnd, validation_end: form.validationEnd } : null,
      walk_forward: form.mode === 'walk_forward' ? {
        train_sessions: form.trainSessions,
        validation_sessions: form.validationSessions,
        test_sessions: form.testSessions,
        step_sessions: form.stepSessions,
        max_folds: form.maxFolds
      } : null,
      combination_limit: form.combinationLimit
    }
    const accepted = await backtestApi.createParameterSearch(request, idempotencyKey.value)
    ElMessage.success(accepted.deduplicated ? '已打开相同实验' : '参数实验已创建')
    idempotencyKey.value = newKey()
    await loadSearches()
    await selectSearch(accepted.search_id)
  } catch {
    ElMessage.error('参数实验创建失败，请检查网格和评估区间')
  } finally { submitting.value = false }
}

async function cancelSelected(): Promise<void> {
  if (!selectedSearch.value) return
  cancelling.value = true
  try {
    await backtestApi.cancelParameterSearch(selectedSearch.value.search_id)
    ElMessage.success('已提交取消请求')
    await loadSearches()
    await loadResults()
  } catch {
    ElMessage.error('取消请求未能提交，请刷新后重试')
  } finally { cancelling.value = false }
}

function validateForm(): string | null {
  if (!form.name.trim()) return '请输入实验名称'
  if (!selectedStrategy.value) return '请选择已发布策略版本'
  if (form.dateRange.length !== 2) return '请选择完整回测区间'
  if (!(Number(form.initialCash) > 0)) return '初始资金必须大于 0'
  if (!form.benchmark.trim()) return '请输入基准代码'
  if (form.axes.some(axis => !/^[A-Za-z_][A-Za-z0-9_.-]*$/.test(axis.name.trim()))) return '参数名称格式不正确'
  if (parsedAxes.value.some(axis => !axis.values.length)) return '每个参数至少需要一个候选值'
  if (new Set(parsedAxes.value.map(axis => axis.name)).size !== parsedAxes.value.length) return '参数名称不可重复'
  if (parsedAxes.value.some(axis => new Set(axis.values.map(value => JSON.stringify(value))).size !== axis.values.length)) return '同一参数的候选值不可重复'
  if (combinationCount.value > form.combinationLimit) return `组合数不能超过 ${form.combinationLimit}`
  if (form.mode === 'split' && !(form.dateRange[0] < form.trainEnd && form.trainEnd < form.validationEnd && form.validationEnd < form.dateRange[1])) return '训练、验证、测试日期必须严格按顺序排列'
  return null
}

function parseValues(source: string): ParameterValue[] {
  return source.split(',').map(item => item.trim()).filter(Boolean).map(item => {
    if (item === 'true') return true
    if (item === 'false') return false
    if (/^-?(?:\d+\.?\d*|\.\d+)$/.test(item)) return Number(item)
    return item
  })
}
function applyStrategy(): void {
  const strategy = selectedStrategy.value
  if (!strategy) return
  form.market = strategy.market
  form.benchmark = ({ CN: '000300', HK: 'HSI', US: 'SPY' })[strategy.market]
}
function versionOption(strategyId: string, name: string, version: StrategyVersion): PublishedStrategyOption {
  return { strategy_id: strategyId, strategy_version_id: version.strategy_version_id, name, market: version.market, fee_model_version: feeModel(version.definition) }
}
function feeModel(definition: StrategyDefinition): string {
  const execution = definition.execution as Record<string, unknown>
  return String(execution.fee_model_version || execution.feeModelVersion || '随发布版本冻结')
}
function statusLabel(value: ParameterSearchStatus): string {
  return ({ queued: '排队中', running: '运行中', succeeded: '已完成', cancelled: '已取消', failed: '失败' } as const)[value]
}
function statusType(value: ParameterSearchStatus): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  return ({ queued: 'info', running: 'primary', succeeded: 'success', cancelled: 'warning', failed: 'danger' } as const)[value]
}
function progressPercent(search: ParameterSearchRecord): number {
  return Math.round(search.completed_combinations / search.total_combinations * 100)
}
function percent(value: string | null | undefined): string {
  return value == null ? '—' : `${(Number(value) * 100).toFixed(2)}%`
}
function stability(value: string | null | undefined): string {
  return value == null ? '—' : `${(Number(value) * 100).toFixed(1)} / 100`
}
function formatParameters(parameters: Record<string, ParameterValue>): string {
  return Object.entries(parameters).map(([key, value]) => `${key}=${String(value)}`).join(' · ')
}
function heatmapCell(
  columnValue: ParameterValue,
  rowValue: ParameterValue | null
): ParameterCombinationResult | undefined {
  const xAxis = heatmapXAxis.value
  if (!xAxis) return undefined
  return results.value.find(item => {
    if (!sameValue(item.parameters[xAxis.name], columnValue)) return false
    if (heatmapYAxis.value && !sameValue(item.parameters[heatmapYAxis.value.name], rowValue)) return false
    if (heatmapSliceAxis.value && !sameValue(item.parameters[heatmapSliceAxis.value.name], sliceValue.value)) return false
    return true
  })
}
function heatmapCellStyle(item: ParameterCombinationResult | undefined): Record<string, string> {
  if (!item?.validation_mean_return) return {}
  const visibleValues = results.value
    .filter(result => !heatmapSliceAxis.value || sameValue(result.parameters[heatmapSliceAxis.value.name], sliceValue.value))
    .map(result => Math.abs(Number(result.validation_mean_return || 0)))
  const maximum = Math.max(...visibleValues, 0.000001)
  const value = Number(item.validation_mean_return)
  const opacity = 0.12 + Math.min(Math.abs(value) / maximum, 1) * 0.42
  return { backgroundColor: value >= 0 ? `rgba(64, 158, 255, ${opacity})` : `rgba(245, 108, 108, ${opacity})` }
}
function sameValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}
function errorMessage(error: Record<string, unknown> | null): string {
  return String(error?.message || '没有组合产生有效的验证集证据。')
}
function newKey(): string {
  return globalThis.crypto?.randomUUID?.() || `parameter-search-${Date.now()}-${Math.random().toString(36).slice(2)}`
}
</script>

<style scoped lang="scss">
.parameter-lab { margin-bottom: 24px; padding: 22px; border-radius: 14px; background: var(--el-bg-color); border: 1px solid var(--el-border-color-light); }
.lab-header, .section-title, .result-header, .submit-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.lab-header { align-items: flex-start; margin-bottom: 16px; }
.lab-header h2 { margin: 0 0 7px; font-size: 22px; text-wrap: balance; }
.lab-header p, .result-header p { margin: 0; max-width: 72ch; color: var(--el-text-color-regular); line-height: 1.55; text-wrap: pretty; }
.lab-layout { display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(280px, .55fr); gap: 22px; margin-top: 22px; align-items: start; }
.experiment-form { min-width: 0; padding-right: 22px; border-right: 1px solid var(--el-border-color-lighter); }
.section-title { margin-bottom: 14px; }
.section-title h3, .result-header h3 { margin: 0; font-size: 17px; }
.section-title span, .section-title small, .field-note, .submit-row span, .progress-copy, .empty-state span { color: var(--el-text-color-regular); font-size: 13px; }
.section-title div { min-width: 0; }
.section-title small { display: block; margin-top: 3px; }
.two-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.full-width { width: 100%; }
.parameter-heading, .evaluation-heading { margin-top: 7px; }
.axis-row { display: grid; grid-template-columns: minmax(130px, .45fr) minmax(180px, 1fr) 34px; gap: 10px; margin-bottom: 10px; }
.field-note { margin: -2px 0 20px; line-height: 1.5; }
.walk-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(135px, 1fr)); gap: 0 12px; }
.walk-grid :deep(.el-input-number) { width: 100%; }
.submit-row { margin-top: 4px; padding: 16px; background: var(--el-fill-color-light); border-radius: 10px; }
.submit-row div { display: flex; flex-direction: column; gap: 3px; }
.research-pane { min-width: 0; }
.search-row { display: block; width: 100%; padding: 13px 12px; border: 0; border-bottom: 1px solid var(--el-border-color-lighter); background: transparent; color: var(--el-text-color-primary); text-align: left; cursor: pointer; transition: background-color 180ms ease-out; }
.search-row:hover, .search-row.active { background: var(--el-fill-color-light); }
.search-row:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: -2px; }
.search-row-top { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 7px; }
.search-row-top strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.progress-copy { display: block; margin-bottom: 7px; }
.empty-state { display: grid; gap: 6px; justify-items: start; padding: 28px 12px; }
.result-section { margin-top: 24px; padding-top: 22px; border-top: 1px solid var(--el-border-color-light); }
.result-header { align-items: flex-start; margin-bottom: 16px; }
.result-header h3 { margin-bottom: 5px; }
.result-empty { padding-block: 34px; }
.heatmap-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; margin: 6px 0 12px; }
.heatmap-heading h4 { margin: 0 0 4px; font-size: 15px; }
.heatmap-heading span { color: var(--el-text-color-regular); font-size: 13px; }
.slice-control { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.slice-control .el-select { width: 120px; }
.heatmap-scroll { overflow-x: auto; padding-bottom: 4px; }
.heatmap { display: grid; min-width: max-content; gap: 4px; }
.heatmap-axis, .heatmap-corner { display: flex; align-items: center; justify-content: center; min-height: 34px; padding: 6px 8px; color: var(--el-text-color-regular); font-size: 12px; font-weight: 600; }
.heatmap-corner { justify-content: flex-start; }
.row-axis { justify-content: flex-start; }
.heatmap-cell { display: grid; min-height: 64px; padding: 10px; align-content: center; justify-items: center; border-radius: 8px; background: var(--el-fill-color-light); color: var(--el-text-color-primary); }
.heatmap-cell.selected { outline: 2px solid var(--el-color-success); outline-offset: -2px; }
.heatmap-cell strong { font-size: 14px; }
.heatmap-cell span { margin-top: 3px; font-size: 11px; }
.result-table { margin-top: 20px; }
.result-pagination { justify-content: flex-end; margin-top: 16px; }
.candidate-tag { margin-left: 6px; }
.parameter-values { color: var(--el-text-color-primary); white-space: normal; word-break: break-word; }
@media (max-width: 960px) {
  .lab-layout { grid-template-columns: 1fr; }
  .experiment-form { padding-right: 0; padding-bottom: 22px; border-right: 0; border-bottom: 1px solid var(--el-border-color-lighter); }
  .research-pane { max-height: 360px; overflow-y: auto; }
}
@media (max-width: 640px) {
  .parameter-lab { padding: 16px; }
  .lab-header, .result-header, .submit-row { align-items: stretch; flex-direction: column; }
  .two-columns { grid-template-columns: 1fr; }
  .axis-row { grid-template-columns: 1fr 40px; }
  .axis-row :first-child { grid-column: 1 / -1; }
  .evaluation-heading { align-items: flex-start; flex-direction: column; }
  .heatmap-heading { align-items: stretch; flex-direction: column; }
  .result-pagination { justify-content: flex-start; overflow-x: auto; }
  .submit-row .el-button { width: 100%; }
}
@media (prefers-reduced-motion: reduce) { .search-row { transition: none; } }
</style>
