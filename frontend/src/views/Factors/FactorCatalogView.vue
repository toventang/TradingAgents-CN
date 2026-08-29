<template>
  <section class="factor-page">
    <FactorPageHeader
      title="因子目录"
      description="检索已注册的静态因子定义，核对公式版本、依赖、数据要求与适用市场。"
    />

    <el-alert
      v-if="featureDisabled"
      class="feature-alert"
      title="因子功能当前未启用"
      description="管理员需启用 FACTOR_FEATURE_ENABLED 后才能加载因子目录。"
      type="info"
      :closable="false"
      show-icon
    />

    <el-card v-else shadow="never" class="surface filter-card">
      <div class="filter-grid">
        <el-input
          v-model="filters.search"
          clearable
          placeholder="搜索名称、ID 或描述"
          @keyup.enter="applyFilters"
          @clear="applyFilters"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="filters.category" clearable placeholder="全部类别">
          <el-option
            v-for="(label, value) in categoryLabels"
            :key="value"
            :label="label"
            :value="value"
          />
        </el-select>
        <el-select v-model="filters.market" clearable placeholder="全部市场">
          <el-option
            v-for="(label, value) in marketLabels"
            :key="value"
            :label="label"
            :value="value"
          />
        </el-select>
        <el-select v-model="filters.status" clearable placeholder="全部状态">
          <el-option
            v-for="(label, value) in factorStatusLabels"
            :key="value"
            :label="label"
            :value="value"
          />
        </el-select>
        <el-button type="primary" :icon="Search" @click="applyFilters">查询</el-button>
        <el-button :icon="Refresh" @click="resetFilters">重置</el-button>
      </div>
    </el-card>

    <el-card v-if="!featureDisabled" shadow="never" class="surface table-card">
      <template #header>
        <div class="card-header">
          <div>
            <span class="card-title">注册定义</span>
            <span class="muted">共 {{ total }} 个版本</span>
          </div>
          <el-button :icon="Refresh" text :loading="loading" @click="loadDefinitions">刷新</el-button>
        </div>
      </template>

      <el-table v-loading="loading" :data="definitions" row-key="checksum" stripe>
        <el-table-column label="因子" min-width="220">
          <template #default="{ row }">
            <button class="factor-link" type="button" @click="openDetail(row.factor_id)">
              <span>{{ row.display_name }}</span>
              <code>{{ row.factor_id }}</code>
            </button>
          </template>
        </el-table-column>
        <el-table-column label="类别" width="105">
          <template #default="{ row }">
            <el-tag effect="plain" size="small">{{ categoryLabel(row.category) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="市场" min-width="150">
          <template #default="{ row }">
            <el-tag
              v-for="market in row.supported_markets"
              :key="market"
              class="market-tag"
              size="small"
              type="info"
              effect="plain"
            >{{ marketLabel(market) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="依赖" min-width="150">
          <template #default="{ row }">
            <span v-if="row.dependencies.length" class="mono muted">{{ row.dependencies.join(', ') }}</span>
            <span v-else class="muted">无</span>
          </template>
        </el-table-column>
        <el-table-column label="公式 / 输出" min-width="190">
          <template #default="{ row }">
            <div class="mono">{{ row.formula_ref }}</div>
            <div class="muted small">→ {{ row.output_column }}</div>
          </template>
        </el-table-column>
        <el-table-column label="版本" width="90" align="center">
          <template #default="{ row }"><strong>v{{ row.version }}</strong></template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row.factor_id)">详情</el-button>
            <el-button
              link
              type="success"
              :disabled="row.status !== 'active'"
              @click="useFactor(row.factor_id)"
            >计算</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="loadError || '没有符合条件的因子定义'" />
        </template>
      </el-table>

      <div class="pagination-row">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          background
          @current-change="loadDefinitions"
          @size-change="changePageSize"
        />
      </div>
    </el-card>

    <el-drawer v-model="drawerVisible" title="因子定义详情" size="min(620px, 94vw)">
      <div v-loading="detailLoading">
        <template v-if="selected">
          <div class="detail-title">
            <div>
              <h2>{{ selected.display_name }}</h2>
              <code>{{ selected.factor_id }} · v{{ selected.version }}</code>
            </div>
            <el-tag :type="statusType(selected.status)">{{ factorStatusLabels[selected.status] }}</el-tag>
          </div>
          <p class="detail-description">{{ selected.description }}</p>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="公式注册项"><code>{{ selected.formula_ref }}</code></el-descriptions-item>
            <el-descriptions-item label="输出列"><code>{{ selected.output_column }}</code></el-descriptions-item>
            <el-descriptions-item label="方向 / 频率">{{ selected.direction }} / {{ selected.frequency }}</el-descriptions-item>
            <el-descriptions-item label="最短历史">{{ selected.min_history }} 个观测点</el-descriptions-item>
            <el-descriptions-item label="所需字段">{{ selected.required_columns.join(', ') || '无' }}</el-descriptions-item>
            <el-descriptions-item label="依赖因子">{{ selected.dependencies.join(', ') || '无' }}</el-descriptions-item>
            <el-descriptions-item label="默认处理">
              去极值 {{ selected.winsorize_default }}；标准化 {{ selected.normalize_default }}；缺失值 {{ selected.missing_policy }}
            </el-descriptions-item>
            <el-descriptions-item label="时点约束">{{ selected.point_in_time_required ? '要求 point-in-time 数据' : '无额外要求' }}</el-descriptions-item>
            <el-descriptions-item label="校验和"><code class="break-all">{{ selected.checksum }}</code></el-descriptions-item>
          </el-descriptions>

          <h3>参数定义</h3>
          <el-table :data="parameterRows" size="small" border>
            <el-table-column prop="name" label="参数" width="135" />
            <el-table-column prop="type" label="类型" width="90" />
            <el-table-column label="默认值" width="120">
              <template #default="{ row }"><code>{{ renderValue(row.defaultValue) }}</code></template>
            </el-table-column>
            <el-table-column prop="description" label="说明" min-width="180" />
          </el-table>
        </template>
      </div>
    </el-drawer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, Search } from '@element-plus/icons-vue'
import { factorApi } from '@/api/factors'
import type {
  FactorCategory,
  FactorDefinition,
  FactorMarket,
  FactorStatus
} from '@/types/factor'
import FactorPageHeader from './components/FactorPageHeader.vue'
import {
  categoryLabels,
  factorStatusLabels,
  getErrorMessage,
  isFeatureDisabled,
  marketLabels
} from './factorPresentation'

const router = useRouter()
const definitions = ref<FactorDefinition[]>([])
const selected = ref<FactorDefinition | null>(null)
const loading = ref(false)
const detailLoading = ref(false)
const featureDisabled = ref(false)
const loadError = ref('')
const drawerVisible = ref(false)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const filters = reactive<{
  search: string
  category?: FactorCategory
  market?: FactorMarket
  status?: FactorStatus
}>({ search: '', status: 'active' })

const parameterRows = computed(() => {
  if (!selected.value) return []
  return Object.entries(selected.value.params_schema).map(([name, schema]) => ({
    name,
    type: schema.type,
    defaultValue: selected.value?.default_params[name],
    description: schema.description || (schema.required ? '必填' : '可选')
  }))
})

function statusType(status: FactorStatus): 'success' | 'info' | 'warning' {
  return status === 'active' ? 'success' : status === 'deprecated' ? 'warning' : 'info'
}

function categoryLabel(category: FactorCategory): string {
  return categoryLabels[category]
}

function marketLabel(market: FactorMarket): string {
  return marketLabels[market]
}

function statusLabel(status: FactorStatus): string {
  return factorStatusLabels[status]
}

function renderValue(value: unknown): string {
  return value === undefined ? '—' : JSON.stringify(value)
}

async function loadDefinitions() {
  try {
    loading.value = true
    loadError.value = ''
    const result = await factorApi.listDefinitions({
      search: filters.search.trim() || undefined,
      category: filters.category,
      market: filters.market,
      status: filters.status,
      page: page.value,
      page_size: pageSize.value
    })
    definitions.value = result.items
    total.value = result.total
    featureDisabled.value = false
  } catch (error) {
    featureDisabled.value = isFeatureDisabled(error)
    loadError.value = getErrorMessage(error, '因子目录加载失败')
    definitions.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  void loadDefinitions()
}

function resetFilters() {
  filters.search = ''
  filters.category = undefined
  filters.market = undefined
  filters.status = 'active'
  applyFilters()
}

function changePageSize() {
  page.value = 1
  void loadDefinitions()
}

async function openDetail(factorId: string) {
  drawerVisible.value = true
  detailLoading.value = true
  selected.value = null
  try {
    selected.value = await factorApi.getDefinition(factorId)
  } catch (error) {
    loadError.value = getErrorMessage(error, '因子详情加载失败')
  } finally {
    detailLoading.value = false
  }
}

function useFactor(factorId: string) {
  void router.push({ path: '/factors/compute', query: { factor: factorId } })
}

onMounted(() => void loadDefinitions())
</script>

<style scoped lang="scss">
.factor-page { min-width: 0; }
.feature-alert { margin-bottom: 18px; }
.surface { border: 1px solid var(--el-border-color-lighter); border-radius: 14px; }
.filter-card { margin-bottom: 16px; }
.filter-grid {
  display: grid;
  grid-template-columns: minmax(220px, 2fr) repeat(3, minmax(120px, 1fr)) auto auto;
  gap: 10px;
}
.card-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.card-title { font-size: 16px; font-weight: 700; }
.muted { margin-left: 9px; color: var(--el-text-color-secondary); }
.small { font-size: 12px; }
.mono, code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.market-tag { margin: 2px 4px 2px 0; }
.factor-link {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 0;
  border: 0;
  background: none;
  color: var(--el-color-primary);
  cursor: pointer;
  text-align: left;

  span { font-weight: 650; }
  code { color: var(--el-text-color-secondary); font-size: 12px; }
}
.pagination-row { display: flex; justify-content: flex-end; margin-top: 18px; overflow-x: auto; }
.detail-title { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.detail-title h2 { margin: 0 0 5px; }
.detail-description { margin: 18px 0; color: var(--el-text-color-regular); line-height: 1.7; }
h3 { margin: 24px 0 12px; }
.break-all { word-break: break-all; }

@media (max-width: 1050px) {
  .filter-grid { grid-template-columns: 2fr 1fr 1fr; }
}
@media (max-width: 680px) {
  .filter-grid { grid-template-columns: 1fr 1fr; }
  .filter-grid > :first-child { grid-column: 1 / -1; }
}
</style>
