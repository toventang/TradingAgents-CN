<template>
  <section class="factor-page">
    <FactorPageHeader
      title="因子快照"
      description="按版本检查不可变计算结果、数据截止时间、覆盖率与逐行质量标记。数值始终由服务端分页返回。"
    />

    <el-alert
      v-if="featureDisabled"
      class="feature-alert"
      title="因子功能当前未启用"
      description="管理员需启用 FACTOR_FEATURE_ENABLED 后才能查询快照。"
      type="info"
      :closable="false"
      show-icon
    />

    <template v-else>
      <el-card shadow="never" class="surface filter-card">
        <div class="filter-grid">
          <el-select v-model="filters.market" clearable placeholder="全部市场">
            <el-option v-for="(label, value) in marketLabels" :key="value" :label="label" :value="value" />
          </el-select>
          <el-date-picker v-model="filters.tradeDate" type="date" value-format="YYYY-MM-DD" clearable placeholder="交易日期" />
          <el-select v-model="filters.status" placeholder="快照状态">
            <el-option v-for="(label, value) in snapshotStatusLabels" :key="value" :label="label" :value="value" />
          </el-select>
          <el-button type="primary" :icon="Search" @click="applyFilters">查询</el-button>
          <el-button :icon="Refresh" @click="resetFilters">重置</el-button>
        </div>
      </el-card>

      <el-card shadow="never" class="surface table-card">
        <template #header>
          <div class="card-header">
            <div><strong>已持久化快照</strong><span>共 {{ total }} 个</span></div>
            <el-button text :icon="Refresh" :loading="loading" @click="loadSnapshots">刷新</el-button>
          </div>
        </template>
        <el-table v-loading="loading" :data="snapshots" row-key="snapshot_id" stripe>
          <el-table-column label="快照 / 市场" min-width="190">
            <template #default="{ row }">
              <button type="button" class="snapshot-link" @click="openSnapshot(row)">
                <code>{{ compactHash(row.snapshot_id) }}</code>
                <span>{{ marketLabel(row.market) }} · {{ row.trade_date }}</span>
              </button>
            </template>
          </el-table-column>
          <el-table-column label="数据截止时间" min-width="175">
            <template #default="{ row }">{{ formatDateTime(row.as_of) }}</template>
          </el-table-column>
          <el-table-column label="数据源版本" min-width="210">
            <template #default="{ row }">
              <div v-for="(version, source) in row.source_versions" :key="source" class="version-line">
                <span>{{ source }}</span><code>{{ version }}</code>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="覆盖率" min-width="165">
            <template #default="{ row }">
              <el-progress :percentage="coverage(row)" :stroke-width="7" />
              <div class="small muted">{{ row.row_count }} / {{ row.expected_row_count }} 行 · {{ row.factor_count }} / {{ row.expected_factor_count }} 因子</div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="snapshotTagType(row.status)" size="small">{{ snapshotStatusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="发布时间" min-width="170">
            <template #default="{ row }">{{ formatDateTime(row.published_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="105" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openSnapshot(row)">检查数据</el-button>
            </template>
          </el-table-column>
          <template #empty><el-empty :description="loadError || '没有符合条件的快照'" /></template>
        </el-table>
        <div class="pagination-row">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="total"
            :page-sizes="[10, 20, 50, 100]"
            layout="total, sizes, prev, pager, next"
            background
            @current-change="loadSnapshots"
            @size-change="changePageSize"
          />
        </div>
      </el-card>
    </template>

    <el-drawer v-model="drawerVisible" title="快照与质量详情" size="min(1080px, 96vw)">
      <template v-if="selectedSnapshot">
        <div class="snapshot-summary">
          <div>
            <div class="summary-label">SNAPSHOT</div>
            <code class="snapshot-id">{{ selectedSnapshot.snapshot_id }}</code>
          </div>
          <el-tag :type="snapshotTagType(selectedSnapshot.status)">{{ snapshotStatusLabels[selectedSnapshot.status] }}</el-tag>
        </div>

        <div class="metric-grid">
          <div><span>市场 / 交易日</span><strong>{{ marketLabels[selectedSnapshot.market] }} · {{ selectedSnapshot.trade_date }}</strong></div>
          <div><span>数据截止时间</span><strong>{{ formatDateTime(selectedSnapshot.as_of) }}</strong></div>
          <div><span>股票覆盖</span><strong>{{ selectedSnapshot.row_count }} / {{ selectedSnapshot.expected_row_count }}</strong></div>
          <div><span>因子覆盖</span><strong>{{ selectedSnapshot.factor_count }} / {{ selectedSnapshot.expected_factor_count }}</strong></div>
        </div>

        <el-descriptions class="snapshot-descriptions" :column="2" border>
          <el-descriptions-item label="股票池版本">{{ selectedSnapshot.universe_snapshot_id }}</el-descriptions-item>
          <el-descriptions-item label="发布时间">{{ formatDateTime(selectedSnapshot.published_at) }}</el-descriptions-item>
          <el-descriptions-item label="数值校验和"><code>{{ compactHash(selectedSnapshot.values_checksum) }}</code></el-descriptions-item>
          <el-descriptions-item label="因子集校验和"><code>{{ compactHash(selectedSnapshot.factor_set_checksum) }}</code></el-descriptions-item>
          <el-descriptions-item label="数据源版本" :span="2">
            <el-tag v-for="(version, source) in selectedSnapshot.source_versions" :key="source" class="source-tag" effect="plain">
              {{ source }}: {{ version }}
            </el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <el-alert
          v-if="selectedSnapshot.error"
          class="section-gap"
          type="error"
          title="快照失败摘要"
          :description="errorSummary(selectedSnapshot.error)"
          :closable="false"
          show-icon
        />

        <div v-if="selectedSnapshot.status === 'ready'" class="values-section">
          <div class="values-toolbar">
            <div>
              <h3>分页数值与质量</h3>
              <p>仅加载当前服务端页；异常代码也只统计当前页。</p>
            </div>
            <el-button :icon="Download" :disabled="!values.length" @click="downloadCurrentPage">导出当前页 CSV</el-button>
          </div>
          <div class="value-filters">
            <el-input v-model="valueFilters.symbol" clearable placeholder="按股票代码精确筛选" @keyup.enter="applyValueFilters" />
            <el-input v-model="valueFilters.factorsText" clearable placeholder="因子 ID，逗号分隔" @keyup.enter="applyValueFilters" />
            <el-button type="primary" :icon="Search" @click="applyValueFilters">筛选当前快照</el-button>
          </div>

          <el-alert
            v-if="problemSymbols.length"
            class="section-gap"
            type="warning"
            :closable="false"
            show-icon
          >
            <template #title>当前页异常代码（{{ problemSymbols.length }}）</template>
            <el-tag v-for="symbol in problemSymbols" :key="symbol" class="problem-tag" type="warning" effect="plain">{{ symbol }}</el-tag>
          </el-alert>

          <el-table v-loading="valuesLoading" :data="values" border stripe row-key="symbol">
            <el-table-column prop="symbol" label="代码" fixed min-width="105" />
            <el-table-column prop="trade_date" label="交易日" width="115" />
            <el-table-column v-for="factorId in visibleFactorIds" :key="factorId" :label="factorId" min-width="135">
              <template #default="{ row }">
                <span v-if="row.values[factorId] !== null && row.values[factorId] !== undefined" class="numeric">
                  {{ formatNumber(row.values[factorId]) }}
                </span>
                <el-tag v-else size="small" type="info">缺失</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="质量详情" min-width="220" fixed="right">
              <template #default="{ row }">
                <div v-if="qualityEntries(row).length" class="quality-list">
                  <el-tag v-for="item in qualityEntries(row)" :key="item" size="small" type="warning" effect="plain">{{ item }}</el-tag>
                </div>
                <span v-else class="quality-ok">通过</span>
              </template>
            </el-table-column>
            <template #empty><el-empty :description="valueError || '当前筛选没有数值行'" /></template>
          </el-table>
          <div class="pagination-row">
            <el-pagination
              v-model:current-page="valuePage"
              v-model:page-size="valuePageSize"
              :total="valueTotal"
              :page-sizes="[25, 50, 100, 200]"
              layout="total, sizes, prev, pager, next"
              background
              @current-change="loadValues"
              @size-change="changeValuePageSize"
            />
          </div>
        </div>
        <el-empty v-else description="只有状态为“可用”的已发布快照才能读取数值" />
      </template>
    </el-drawer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { Download, Refresh, Search } from '@element-plus/icons-vue'
import { factorApi } from '@/api/factors'
import type {
  FactorMarket,
  FactorSnapshot,
  FactorSnapshotStatus,
  FactorValueRow
} from '@/types/factor'
import FactorPageHeader from './components/FactorPageHeader.vue'
import {
  compactHash,
  formatDateTime,
  getErrorMessage,
  isFeatureDisabled,
  marketLabels,
  snapshotStatusLabels
} from './factorPresentation'

const route = useRoute()
const router = useRouter()
const snapshots = ref<FactorSnapshot[]>([])
const loading = ref(false)
const featureDisabled = ref(false)
const loadError = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const filters = reactive<{
  market?: FactorMarket
  tradeDate?: string
  status: FactorSnapshotStatus
}>({ status: 'ready' })

const drawerVisible = ref(false)
const selectedSnapshot = ref<FactorSnapshot | null>(null)
const values = ref<FactorValueRow[]>([])
const valuesLoading = ref(false)
const valueError = ref('')
const valuePage = ref(1)
const valuePageSize = ref(50)
const valueTotal = ref(0)
const valueFilters = reactive({ symbol: '', factorsText: '' })

const requestedFactors = computed(() => Array.from(new Set(
  valueFilters.factorsText.split(/[\s,，;；]+/).map((item) => item.trim()).filter(Boolean)
)))
const visibleFactorIds = computed(() => {
  if (requestedFactors.value.length) return requestedFactors.value
  return Array.from(new Set(values.value.flatMap((row) => Object.keys(row.values)))).sort()
})
const problemSymbols = computed(() => values.value
  .filter((row) => Object.values(row.values).some((value) => value === null) || Object.values(row.quality).some(Boolean))
  .map((row) => row.symbol))

function coverage(snapshot: FactorSnapshot): number {
  return snapshot.expected_row_count
    ? Math.round((snapshot.row_count / snapshot.expected_row_count) * 100)
    : 0
}

function snapshotTagType(status: FactorSnapshotStatus): 'success' | 'danger' | 'warning' | 'info' {
  if (status === 'ready') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'building') return 'warning'
  return 'info'
}

function marketLabel(market: FactorMarket): string {
  return marketLabels[market]
}

function snapshotStatusLabel(status: FactorSnapshotStatus): string {
  return snapshotStatusLabels[status]
}

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return new Intl.NumberFormat('zh-CN', { maximumSignificantDigits: 8 }).format(value)
}

function qualityEntries(row: FactorValueRow): string[] {
  return Object.entries(row.quality)
    .filter((entry): entry is [string, string] => Boolean(entry[1]))
    .map(([factorId, issue]) => `${factorId}: ${issue}`)
}

function errorSummary(error: Record<string, unknown>): string {
  const code = typeof error.code === 'string' ? error.code : 'UNKNOWN'
  const message = typeof error.message === 'string' ? error.message : JSON.stringify(error)
  return `${code} · ${message}`
}

async function loadSnapshots() {
  try {
    loading.value = true
    loadError.value = ''
    const result = await factorApi.listSnapshots({
      market: filters.market,
      trade_date: filters.tradeDate,
      status: filters.status,
      page: page.value,
      page_size: pageSize.value
    })
    snapshots.value = result.items
    total.value = result.total
    featureDisabled.value = false
  } catch (error) {
    featureDisabled.value = isFeatureDisabled(error)
    loadError.value = getErrorMessage(error, '快照列表加载失败')
    snapshots.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  void loadSnapshots()
}

function resetFilters() {
  filters.market = undefined
  filters.tradeDate = undefined
  filters.status = 'ready'
  applyFilters()
}

function changePageSize() {
  page.value = 1
  void loadSnapshots()
}

async function openSnapshot(snapshot: FactorSnapshot) {
  selectedSnapshot.value = snapshot
  drawerVisible.value = true
  valuePage.value = 1
  values.value = []
  void router.replace({ query: { ...route.query, snapshot: snapshot.snapshot_id } })
  if (snapshot.status === 'ready') await loadValues()
}

async function openSnapshotById(snapshotId: string) {
  drawerVisible.value = true
  valuesLoading.value = true
  try {
    const result = await factorApi.listValues(snapshotId, { page: 1, page_size: valuePageSize.value })
    selectedSnapshot.value = result.snapshot
    values.value = result.items
    valueTotal.value = result.total
  } catch (error) {
    valueError.value = getErrorMessage(error, '指定快照加载失败')
    drawerVisible.value = false
    ElMessage.error(valueError.value)
  } finally {
    valuesLoading.value = false
  }
}

async function loadValues() {
  if (!selectedSnapshot.value || selectedSnapshot.value.status !== 'ready') return
  try {
    valuesLoading.value = true
    valueError.value = ''
    const result = await factorApi.listValues(selectedSnapshot.value.snapshot_id, {
      symbol: valueFilters.symbol.trim() || undefined,
      factors: requestedFactors.value.length ? requestedFactors.value : undefined,
      page: valuePage.value,
      page_size: valuePageSize.value
    })
    selectedSnapshot.value = result.snapshot
    values.value = result.items
    valueTotal.value = result.total
  } catch (error) {
    valueError.value = getErrorMessage(error, '快照数值加载失败')
    values.value = []
    valueTotal.value = 0
  } finally {
    valuesLoading.value = false
  }
}

function applyValueFilters() {
  valuePage.value = 1
  void loadValues()
}

function changeValuePageSize() {
  valuePage.value = 1
  void loadValues()
}

function csvCell(value: unknown): string {
  const text = value === null || value === undefined ? '' : String(value)
  return `"${text.replace(/"/g, '""')}"`
}

function downloadCurrentPage() {
  const factorIds = visibleFactorIds.value
  const header = ['symbol', 'market', 'trade_date', ...factorIds, ...factorIds.map((id) => `${id}__quality`)]
  const rows = values.value.map((row) => [
    row.symbol,
    row.market,
    row.trade_date,
    ...factorIds.map((id) => row.values[id]),
    ...factorIds.map((id) => row.quality[id])
  ])
  const csv = [header, ...rows].map((row) => row.map(csvCell).join(',')).join('\r\n')
  const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `factor-snapshot-${selectedSnapshot.value?.snapshot_id.slice(0, 12)}-page-${valuePage.value}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

onMounted(async () => {
  await loadSnapshots()
  const snapshotId = typeof route.query.snapshot === 'string' ? route.query.snapshot : ''
  if (snapshotId) await openSnapshotById(snapshotId)
})
</script>

<style scoped lang="scss">
.factor-page { min-width: 0; }
.feature-alert, .filter-card { margin-bottom: 16px; }
.surface { border: 1px solid var(--el-border-color-lighter); border-radius: 14px; }
.filter-grid { display: grid; grid-template-columns: 1fr 1.2fr 1fr auto auto; gap: 10px; }
:deep(.el-date-editor), :deep(.el-select) { width: 100%; }
.card-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.card-header span { margin-left: 9px; color: var(--el-text-color-secondary); font-size: 12px; }
.snapshot-link { display: flex; flex-direction: column; gap: 5px; padding: 0; border: 0; background: none; color: var(--el-color-primary); cursor: pointer; text-align: left; }
.snapshot-link span { color: var(--el-text-color-secondary); font-size: 12px; }
.version-line { display: flex; justify-content: space-between; gap: 9px; margin: 3px 0; font-size: 12px; }
.version-line span { color: var(--el-text-color-secondary); }
.muted { color: var(--el-text-color-secondary); }
.small { margin-top: 4px; font-size: 11px; }
.pagination-row { display: flex; justify-content: flex-end; margin-top: 18px; overflow-x: auto; }
.snapshot-summary { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.summary-label { margin-bottom: 5px; color: var(--el-color-primary); font-size: 10px; font-weight: 750; letter-spacing: .16em; }
.snapshot-id { color: var(--el-text-color-primary); font-size: 12px; word-break: break-all; }
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 20px 0; }
.metric-grid div { padding: 13px; border: 1px solid var(--el-border-color-lighter); border-radius: 9px; background: var(--el-fill-color-extra-light); }
.metric-grid span, .metric-grid strong { display: block; }
.metric-grid span { margin-bottom: 7px; color: var(--el-text-color-secondary); font-size: 11px; }
.metric-grid strong { font-size: 13px; }
.source-tag, .problem-tag { margin: 2px 5px 2px 0; }
.section-gap { margin: 16px 0; }
.values-section { margin-top: 24px; }
.values-toolbar { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
.values-toolbar h3 { margin: 0; }
.values-toolbar p { margin: 5px 0 0; color: var(--el-text-color-secondary); font-size: 12px; }
.value-filters { display: grid; grid-template-columns: 1fr 1.5fr auto; gap: 10px; margin: 14px 0; }
.numeric { font-variant-numeric: tabular-nums; }
.quality-list { display: flex; flex-wrap: wrap; gap: 4px; }
.quality-ok { color: var(--el-color-success); font-size: 12px; }

@media (max-width: 760px) {
  .filter-grid, .value-filters { grid-template-columns: 1fr 1fr; }
  .metric-grid { grid-template-columns: 1fr 1fr; }
  .values-toolbar { align-items: stretch; flex-direction: column; }
}
</style>
