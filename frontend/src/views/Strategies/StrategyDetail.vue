<template>
  <section class="strategy-page" v-loading="loading">
    <header class="page-header" v-if="detail">
      <div>
        <el-button link @click="router.push('/strategies')">← 返回策略中心</el-button>
        <div class="title-row"><h1>{{ detail.strategy.name }}</h1><el-tag :type="detail.strategy.archived_at ? 'info' : 'success'">{{ detail.strategy.archived_at ? '已归档' : '有效' }}</el-tag></div>
        <p>{{ detail.strategy.description || '暂无说明' }}</p>
      </div>
      <el-space wrap>
        <el-button v-if="draftVersion && !detail.strategy.archived_at" @click="router.push(`/strategies/${detail.strategy.strategy_id}/edit`)">编辑草稿</el-button>
        <el-button v-if="!draftVersion && latestPublished && !detail.strategy.archived_at" type="primary" :loading="creatingVersion" @click="createNextVersion">新建版本</el-button>
      </el-space>
    </header>

    <el-tabs v-if="detail" v-model="activeTab" class="detail-tabs">
      <el-tab-pane label="版本与依赖" name="versions">
        <el-table :data="detail.versions" row-key="strategy_version_id" stripe>
          <el-table-column label="版本" width="90"><template #default="{ row }"><strong>v{{ row.version }}</strong></template></el-table-column>
          <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
          <el-table-column prop="change_summary" label="变更说明" min-width="220" show-overflow-tooltip />
          <el-table-column label="依赖" min-width="250"><template #default="{ row }"><span>{{ row.factor_dependencies.map((item: FrozenFactorDependency) => `${item.factor_id}@${item.version}`).join('、') || '校验后冻结' }}</span></template></el-table-column>
          <el-table-column label="创建时间" width="180"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column>
          <el-table-column label="操作" width="210" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="selectedVersion = row; treeDrawer = true">结构</el-button>
              <el-button link type="success" :loading="validatingId === row.strategy_version_id" @click="validate(row)">校验</el-button>
              <el-button v-if="row.status === 'draft'" link type="warning" :disabled="!validationByVersion[row.strategy_version_id]?.valid" @click="openPublish(row)">发布</el-button>
            </template>
          </el-table-column>
        </el-table>

        <section v-if="selectedValidation" class="validation-panel" aria-live="polite">
          <div class="panel-heading"><h2>校验与冻结依赖</h2><el-tag :type="selectedValidation.valid ? 'success' : 'danger'">{{ selectedValidation.valid ? '通过' : '失败' }}</el-tag></div>
          <el-alert v-for="issue in [...selectedValidation.errors, ...selectedValidation.warnings]" :key="`${issue.code}-${issue.path}`" :title="`${issue.code}: ${issue.message}`" :type="selectedValidation.errors.includes(issue) ? 'error' : 'warning'" :closable="false" />
          <el-descriptions :column="1" border>
            <el-descriptions-item label="因子依赖">{{ selectedValidation.factor_dependencies.map(item => `${item.factor_id}@${item.version}`).join('、') || '无' }}</el-descriptions-item>
            <el-descriptions-item label="Skill 依赖">{{ selectedValidation.skill_dependencies.map(item => `${item.skill_id}@${item.version}`).join('、') || '无' }}</el-descriptions-item>
          </el-descriptions>
        </section>
      </el-tab-pane>

      <el-tab-pane label="版本差异" name="diff">
        <div class="diff-toolbar">
          <el-select v-model="baseVersionId" placeholder="基准版本"><el-option v-for="version in detail.versions" :key="version.strategy_version_id" :label="`v${version.version} · ${statusLabel(version.status)}`" :value="version.strategy_version_id" /></el-select>
          <span>对比</span>
          <el-select v-model="targetVersionId" placeholder="目标版本"><el-option v-for="version in detail.versions" :key="version.strategy_version_id" :label="`v${version.version} · ${statusLabel(version.status)}`" :value="version.strategy_version_id" /></el-select>
        </div>
        <el-table :data="versionDiff" row-key="path" border>
          <el-table-column prop="path" label="字段路径" min-width="230"><template #default="{ row }"><code>{{ row.path }}</code></template></el-table-column>
          <el-table-column prop="before" label="基准值" min-width="260" show-overflow-tooltip />
          <el-table-column prop="after" label="目标值" min-width="260" show-overflow-tooltip />
          <template #empty><el-empty description="两个版本的结构化定义没有差异" /></template>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="最近信号" name="signals">
        <div class="signal-toolbar">
          <div><el-select v-model="signalVersionId" placeholder="策略版本" @change="loadSignals"><el-option v-for="version in detail.versions" :key="version.strategy_version_id" :label="`v${version.version}`" :value="version.strategy_version_id" /></el-select><el-date-picker v-model="signalDate" value-format="YYYY-MM-DD" clearable placeholder="信号日期" @change="loadSignals" /></div>
          <el-button v-if="signalVersionId" type="primary" @click="signalDialog = true">生成信号</el-button>
        </div>
        <el-skeleton v-if="signalsLoading" :rows="5" animated />
        <el-table v-else :data="signals.items" row-key="signal_id" stripe>
          <el-table-column prop="signal_date" label="日期" width="120" /><el-table-column prop="market" label="市场" width="80" /><el-table-column prop="symbol" label="代码" width="120" /><el-table-column prop="signal_type" label="信号" width="100" /><el-table-column prop="score" label="分数" width="100" /><el-table-column prop="rank" label="排名" width="80" /><el-table-column label="理由" min-width="260"><template #default="{ row }">{{ row.reason_codes.join('、') }}</template></el-table-column>
          <template #empty><el-empty description="暂无信号。选择已发布版本并提交快照即可创建持久化信号任务。" /></template>
        </el-table>
        <el-pagination v-if="signals.total" v-model:current-page="signalPage" :page-size="20" :total="signals.total" layout="total, prev, pager, next" @current-change="loadSignals" />
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="treeDrawer" title="只读结构化定义" size="min(680px, 96vw)">
      <el-alert title="此视图仅展示白名单结构，不执行也不接受任意代码。" type="info" :closable="false" />
      <el-tree v-if="selectedVersion" :data="toTree(selectedVersion.definition)" :props="{ label: 'label', children: 'children' }" default-expand-all class="definition-tree" />
    </el-drawer>

    <el-dialog v-model="publishDialog" title="确认发布不可变版本" width="min(620px, 94vw)">
      <template v-if="publishVersion">
        <el-alert title="发布后此版本不可修改；后续变更必须创建新版本。" type="warning" :closable="false" show-icon />
        <el-descriptions :column="1" border class="publish-summary">
          <el-descriptions-item label="不可变版本">v{{ publishVersion.version }} · {{ publishVersion.strategy_version_id }}</el-descriptions-item>
          <el-descriptions-item label="数据需求">{{ dataRequirements(publishVersion) }}</el-descriptions-item>
          <el-descriptions-item label="估算成本">{{ costEstimate(publishVersion) }}</el-descriptions-item>
          <el-descriptions-item label="风控规则">{{ riskRules(publishVersion) }}</el-descriptions-item>
        </el-descriptions>
        <el-checkbox v-model="publishConfirmed">我已核对数据、成本、执行时点和风险规则</el-checkbox>
      </template>
      <template #footer><el-button @click="publishDialog = false">取消</el-button><el-button type="warning" :disabled="!publishConfirmed" :loading="publishing" @click="publish">发布 v{{ publishVersion?.version }}</el-button></template>
    </el-dialog>

    <el-dialog v-model="signalDialog" title="创建持久化信号任务" width="min(560px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="股票池快照 ID" required><el-input v-model="signalForm.universe_snapshot_id" /></el-form-item>
        <el-form-item label="因子快照 ID" required><el-select v-model="signalForm.factor_snapshot_ids" multiple allow-create filterable default-first-option /></el-form-item>
        <el-form-item label="数据截止时点" required><el-date-picker v-model="signalForm.as_of" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" /></el-form-item>
        <el-form-item label="幂等键" required><el-input v-model="signalForm.idempotency_key" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="signalDialog = false">取消</el-button><el-button type="primary" :loading="submittingSignal" :disabled="!signalFormValid" @click="submitSignal">提交任务</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { strategyApi } from '@/api/strategies'
import type { FrozenFactorDependency, PageResponse, StrategyDetail, StrategySignal, StrategyValidationResponse, StrategyVersion } from '@/types/strategy'

interface TreeNode { label: string; children?: TreeNode[] }
interface DiffRow { path: string; before: string; after: string }

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const creatingVersion = ref(false)
const detail = ref<StrategyDetail | null>(null)
const activeTab = ref('versions')
const selectedVersion = ref<StrategyVersion | null>(null)
const treeDrawer = ref(false)
const validatingId = ref('')
const validationByVersion = reactive<Record<string, StrategyValidationResponse>>({})
const selectedValidationId = ref('')
const baseVersionId = ref('')
const targetVersionId = ref('')
const publishDialog = ref(false)
const publishVersion = ref<StrategyVersion | null>(null)
const publishConfirmed = ref(false)
const publishing = ref(false)
const signalsLoading = ref(false)
const signalVersionId = ref('')
const signalDate = ref('')
const signalPage = ref(1)
const signals = ref<PageResponse<StrategySignal>>({ items: [], page: 1, page_size: 20, total: 0 })
const signalDialog = ref(false)
const submittingSignal = ref(false)
const signalForm = reactive({ universe_snapshot_id: '', factor_snapshot_ids: [] as string[], as_of: '', idempotency_key: '' })

const sortedVersions = computed(() => [...(detail.value?.versions || [])].sort((a, b) => b.version - a.version))
const draftVersion = computed(() => sortedVersions.value.find(item => item.status === 'draft') || null)
const latestPublished = computed(() => sortedVersions.value.find(item => item.status === 'published') || null)
const selectedValidation = computed(() => validationByVersion[selectedValidationId.value] || null)
const versionDiff = computed<DiffRow[]>(() => {
  const before = detail.value?.versions.find(item => item.strategy_version_id === baseVersionId.value)
  const after = detail.value?.versions.find(item => item.strategy_version_id === targetVersionId.value)
  if (!before || !after) return []
  const left = flatten(before.definition)
  const right = flatten(after.definition)
  return [...new Set([...Object.keys(left), ...Object.keys(right)])].sort().filter(path => left[path] !== right[path]).map(path => ({ path, before: left[path] ?? '—', after: right[path] ?? '—' }))
})
const signalFormValid = computed(() => Boolean(signalForm.universe_snapshot_id.trim() && signalForm.factor_snapshot_ids.length && signalForm.as_of && signalForm.idempotency_key.trim()))

onMounted(load)

async function load(): Promise<void> {
  loading.value = true
  try {
    detail.value = await strategyApi.get(String(route.params.strategyId))
    const versions = sortedVersions.value
    targetVersionId.value = versions[0]?.strategy_version_id || ''
    baseVersionId.value = versions[1]?.strategy_version_id || versions[0]?.strategy_version_id || ''
    signalVersionId.value = latestPublished.value?.strategy_version_id || versions[0]?.strategy_version_id || ''
    if (signalVersionId.value) await loadSignals()
  } finally { loading.value = false }
}
function statusLabel(status: string): string { return ({ draft: '草稿', validating: '校验中', published: '已发布', deprecated: '已弃用' } as Record<string, string>)[status] || status }
function statusType(status: string): 'success' | 'warning' | 'info' { return status === 'published' ? 'success' : status === 'draft' ? 'warning' : 'info' }
function formatTime(value: string): string { return new Date(value).toLocaleString() }
function flatten(value: unknown, path = 'definition', output: Record<string, string> = {}): Record<string, string> {
  if (value !== null && typeof value === 'object' && !Array.isArray(value)) Object.entries(value as Record<string, unknown>).forEach(([key, child]) => flatten(child, `${path}.${key}`, output))
  else output[path] = JSON.stringify(value)
  return output
}
function toTree(value: unknown, key = 'definition'): TreeNode[] {
  if (Array.isArray(value)) return [{ label: `${key} [${value.length}]`, children: value.flatMap((item, index) => toTree(item, String(index))) }]
  if (value !== null && typeof value === 'object') return [{ label: key, children: Object.entries(value as Record<string, unknown>).flatMap(([childKey, child]) => toTree(child, childKey)) }]
  return [{ label: `${key}: ${String(value)}` }]
}
async function validate(version: StrategyVersion): Promise<void> {
  validatingId.value = version.strategy_version_id
  selectedValidationId.value = version.strategy_version_id
  try { validationByVersion[version.strategy_version_id] = await strategyApi.validateVersion(version.strategy_version_id); ElMessage.success(validationByVersion[version.strategy_version_id].valid ? '校验通过' : '校验完成，请检查问题') }
  finally { validatingId.value = '' }
}
function openPublish(version: StrategyVersion): void { publishVersion.value = version; publishConfirmed.value = false; publishDialog.value = true }
async function publish(): Promise<void> {
  if (!detail.value || !publishVersion.value || !publishConfirmed.value) return
  publishing.value = true
  try { await strategyApi.publish(detail.value.strategy.strategy_id, publishVersion.value.strategy_version_id); ElMessage.success(`v${publishVersion.value.version} 已发布并冻结`); publishDialog.value = false; await load() }
  finally { publishing.value = false }
}
function dataRequirements(version: StrategyVersion): string { const data = version.definition.data; return `${version.market} 日线，最少 ${data.minimum_history} 个交易日，${version.definition.features.length} 个因子，point-in-time 数据` }
function costEstimate(version: StrategyVersion): string { return `约 ${Number(version.definition.data.minimum_history * version.definition.features.length).toLocaleString()} × 股票池规模的因子观测单元` }
function riskRules(version: StrategyVersion): string { const risk = version.definition.risk as Record<string, unknown>; return `最大回撤 ${renderPercent(risk.max_drawdown_stop)}，止损 ${renderPercent(risk.stop_loss)}，止盈 ${renderPercent(risk.take_profit)}` }
function renderPercent(value: unknown): string { return typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '未设置' }
async function createNextVersion(): Promise<void> {
  if (!detail.value || !latestPublished.value) return
  creatingVersion.value = true
  try { await strategyApi.createVersion(detail.value.strategy.strategy_id, latestPublished.value.strategy_version_id, `Create v${detail.value.strategy.version_sequence + 1} draft`); ElMessage.success('新草稿版本已创建'); await load() }
  finally { creatingVersion.value = false }
}
async function loadSignals(): Promise<void> {
  if (!signalVersionId.value) return
  signalsLoading.value = true
  try { signals.value = await strategyApi.listSignals({ strategy_version_id: signalVersionId.value, signal_date: signalDate.value || undefined, page: signalPage.value, page_size: 20 }) }
  finally { signalsLoading.value = false }
}
async function submitSignal(): Promise<void> {
  if (!signalFormValid.value) return
  submittingSignal.value = true
  try { const task = await strategyApi.createSignalTask(signalVersionId.value, { ...signalForm }); ElMessage.success(`任务 ${task.task_id} 已进入持久化队列`); signalDialog.value = false }
  finally { submittingSignal.value = false }
}
</script>

<style scoped lang="scss">
.strategy-page { padding: 24px; min-height: 100%; }
.page-header { display: flex; justify-content: space-between; gap: 20px; align-items: flex-end; margin-bottom: 20px; }
.page-header h1 { margin: 8px 0; font-size: 28px; }.page-header p { margin: 0; color: var(--el-text-color-secondary); max-width: 68ch; }
.title-row { display: flex; align-items: center; gap: 12px; }
.detail-tabs { background: var(--el-bg-color); border-radius: 12px; padding: 6px 20px 22px; }
.validation-panel { margin-top: 20px; display: grid; gap: 10px; padding: 20px; background: var(--el-fill-color-light); border-radius: 10px; }
.panel-heading { display: flex; justify-content: space-between; align-items: center; }.panel-heading h2 { margin: 0; font-size: 18px; }
.diff-toolbar, .signal-toolbar { display: flex; align-items: center; gap: 12px; margin: 14px 0 18px; }.signal-toolbar { justify-content: space-between; }.signal-toolbar > div { display: flex; gap: 10px; }
.definition-tree { margin-top: 16px; max-height: calc(100vh - 180px); overflow: auto; }.publish-summary { margin: 18px 0; }
.el-pagination { justify-content: flex-end; margin-top: 18px; }
@media (max-width: 760px) { .strategy-page { padding: 16px; } .page-header, .signal-toolbar, .signal-toolbar > div { align-items: stretch; flex-direction: column; } .diff-toolbar { align-items: stretch; flex-direction: column; } }
</style>
