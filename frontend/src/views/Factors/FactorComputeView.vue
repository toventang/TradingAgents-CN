<template>
  <section class="factor-page">
    <FactorPageHeader
      title="因子计算"
      description="固定股票池、数据截止时间与数据版本，提交可复现的异步计算任务。"
    />

    <el-alert
      v-if="featureDisabled"
      class="block-gap"
      title="因子功能当前未启用"
      description="管理员需启用 FACTOR_FEATURE_ENABLED 后才能提交计算。"
      type="info"
      :closable="false"
      show-icon
    />

    <div v-else class="compute-layout">
      <el-card shadow="never" class="surface form-card">
        <template #header>
          <div class="card-header">
            <div>
              <strong>计算请求</strong>
              <span>所有时点与版本字段都会写入快照</span>
            </div>
            <el-tag effect="plain">{{ estimateLabel }}</el-tag>
          </div>
        </template>

        <el-form label-position="top" @submit.prevent>
          <div class="form-grid three">
            <el-form-item label="市场" required>
              <el-select v-model="form.market" @change="changeMarket">
                <el-option v-for="(label, value) in marketLabels" :key="value" :label="label" :value="value" />
              </el-select>
            </el-form-item>
            <el-form-item label="开始日期" required>
              <el-date-picker v-model="form.startDate" type="date" value-format="YYYY-MM-DD" :clearable="false" />
            </el-form-item>
            <el-form-item label="结束日期（交易日）" required>
              <el-date-picker v-model="form.endDate" type="date" value-format="YYYY-MM-DD" :clearable="false" />
            </el-form-item>
          </div>

          <div class="form-grid two">
            <el-form-item label="股票池快照 ID" required>
              <el-input v-model="form.universeSnapshotId" placeholder="例如 cn-hs300-20260828" maxlength="200" />
              <div class="field-help">用于标识此次计算采用的固定股票池版本。</div>
            </el-form-item>
            <el-form-item label="数据截止时间（As of）" required>
              <el-date-picker
                v-model="form.asOf"
                type="datetime"
                :clearable="false"
                placeholder="请选择带时区转换的数据截止时间"
              />
              <div class="field-help">提交时转换为 UTC，结束日期不得晚于该时间。</div>
            </el-form-item>
          </div>

          <el-form-item label="股票代码" required>
            <el-input
              v-model="form.symbolsText"
              type="textarea"
              :rows="4"
              placeholder="每行一个，或使用逗号分隔。例如：600519, 000001"
            />
            <div class="field-help">
              已识别 {{ symbols.length }} 个去重代码；单次最多 5,000 个。市场由上方字段统一指定。
            </div>
          </el-form-item>

          <el-divider content-position="left">因子与参数</el-divider>
          <el-form-item label="因子版本" required>
            <el-select
              v-model="form.factorIds"
              multiple
              filterable
              collapse-tags
              collapse-tags-tooltip
              placeholder="选择一个或多个启用因子"
              :loading="definitionsLoading"
              @change="syncParameterDrafts"
            >
              <el-option
                v-for="definition in definitions"
                :key="definition.factor_id"
                :label="`${definition.display_name} · v${definition.version}`"
                :value="definition.factor_id"
              />
            </el-select>
          </el-form-item>

          <div v-if="selectedDefinitions.length" class="parameter-list">
            <div v-for="definition in selectedDefinitions" :key="definition.factor_id" class="parameter-card">
              <div class="parameter-heading">
                <div>
                  <strong>{{ definition.display_name }}</strong>
                  <code>{{ definition.factor_id }} · v{{ definition.version }}</code>
                </div>
                <el-tag size="small" effect="plain">{{ categoryLabels[definition.category] }}</el-tag>
              </div>
              <div v-if="Object.keys(definition.params_schema).length" class="parameter-grid">
                <el-form-item
                  v-for="(schema, name) in definition.params_schema"
                  :key="name"
                  :label="`${name}${schema.required ? ' *' : ''}`"
                >
                  <el-select
                    v-if="schema.choices.length"
                    :model-value="selectDraft(parameterDrafts[definition.factor_id]?.[name])"
                    clearable
                    @update:model-value="setParameter(definition.factor_id, name, $event)"
                  >
                    <el-option v-for="choice in schema.choices" :key="String(choice)" :label="String(choice)" :value="selectChoice(choice)" />
                  </el-select>
                  <el-switch
                    v-else-if="schema.type === 'boolean'"
                    :model-value="Boolean(parameterDrafts[definition.factor_id]?.[name])"
                    @update:model-value="setParameter(definition.factor_id, name, $event)"
                  />
                  <el-input-number
                    v-else-if="schema.type === 'integer' || schema.type === 'number'"
                    :model-value="numberDraft(parameterDrafts[definition.factor_id]?.[name])"
                    :min="schema.minimum ?? undefined"
                    :max="schema.maximum ?? undefined"
                    :step="schema.type === 'integer' ? 1 : 0.1"
                    @update:model-value="setParameter(definition.factor_id, name, $event)"
                  />
                  <el-input
                    v-else
                    :model-value="String(parameterDrafts[definition.factor_id]?.[name] ?? '')"
                    :type="schema.type === 'object' ? 'textarea' : 'text'"
                    :placeholder="schema.type === 'object' ? '输入 JSON 对象' : schema.description"
                    @update:model-value="setParameter(definition.factor_id, name, $event)"
                  />
                  <div v-if="schema.description" class="field-help">{{ schema.description }}</div>
                </el-form-item>
              </div>
              <div v-else class="no-params">该版本没有可配置参数。</div>
            </div>
          </div>

          <el-divider content-position="left">数据版本与执行设置</el-divider>
          <div class="form-grid three">
            <el-form-item label="日线数据版本" required>
              <el-input v-model="form.dailySourceVersion" placeholder="例如 bars-20260828-r1" />
            </el-form-item>
            <el-form-item label="财务数据版本">
              <el-input v-model="form.financialSourceVersion" placeholder="按需填写" />
            </el-form-item>
            <el-form-item label="新闻数据版本">
              <el-input v-model="form.newsSourceVersion" placeholder="按需填写" />
            </el-form-item>
          </div>
          <div class="form-grid four">
            <el-form-item label="复权方式">
              <el-select v-model="form.adjustment">
                <el-option label="前复权 qfq" value="qfq" />
                <el-option label="后复权 hfq" value="hfq" />
                <el-option label="不复权 none" value="none" />
              </el-select>
            </el-form-item>
            <el-form-item label="分块大小">
              <el-input-number v-model="form.chunkSize" :min="1" :max="1000" />
            </el-form-item>
            <el-form-item label="并发 Worker">
              <el-input-number v-model="form.workers" :min="1" :max="16" />
            </el-form-item>
            <el-form-item label="强制重算">
              <el-switch v-model="form.forceRecompute" />
              <div class="field-help">忽略相同语义请求的去重结果。</div>
            </el-form-item>
          </div>

          <el-alert
            v-if="validationIssues.length"
            class="block-gap"
            type="error"
            :closable="false"
            show-icon
          >
            <template #title>请求未通过校验</template>
            <ul class="issue-list">
              <li v-for="issue in validationIssues" :key="`${issue.code}-${issue.factor_id}`">
                {{ issue.factor_id ? `${issue.factor_id}：` : '' }}{{ issue.message }}
              </li>
            </ul>
          </el-alert>

          <div class="submit-row">
            <div class="submission-note">LLM 不参与因子值计算；任务由持久队列执行，页面关闭后仍会继续。</div>
            <el-button type="primary" size="large" :loading="submitting" @click="submitCompute">
              校验并提交任务
            </el-button>
          </div>
        </el-form>
      </el-card>

      <aside class="progress-column">
        <el-card shadow="never" class="surface progress-card">
          <template #header>
            <div class="card-header">
              <strong>最近计算任务</strong>
              <el-button v-if="factorStore.tracking" text :loading="factorStore.loading" @click="factorStore.refresh">刷新</el-button>
            </div>
          </template>

          <template v-if="factorStore.tracking">
            <div class="status-line">
              <el-tag :type="taskTagType">{{ currentStatusLabel }}</el-tag>
              <span>{{ factorStore.task?.stage || '正在恢复状态' }}</span>
            </div>
            <el-progress
              :percentage="factorStore.progressPercent"
              :status="progressStatus"
              :stroke-width="12"
            />
            <p class="task-message">{{ factorStore.task?.message || '正在读取持久任务状态…' }}</p>
            <dl class="task-meta">
              <div><dt>任务 ID</dt><dd><code>{{ factorStore.tracking.taskId }}</code></dd></div>
              <div><dt>作业 ID</dt><dd><code>{{ factorStore.tracking.jobId }}</code></dd></div>
              <div><dt>代码进度</dt><dd>{{ factorStore.job?.completed_symbols ?? 0 }} / {{ factorStore.job?.total_symbols ?? symbols.length }}</dd></div>
              <div><dt>尝试次数</dt><dd>{{ factorStore.task?.attempt ?? 0 }} / {{ factorStore.task?.max_attempts ?? '—' }}</dd></div>
              <div><dt>请求校验和</dt><dd><code>{{ compactHash(factorStore.tracking.requestChecksum) }}</code></dd></div>
            </dl>
            <el-alert
              v-if="factorStore.refreshError"
              :title="factorStore.refreshError"
              type="error"
              :closable="false"
              show-icon
            />
            <el-alert
              v-if="factorStore.task?.error"
              :title="factorStore.task.error.message"
              :description="`${factorStore.task.error.code} · ${factorStore.task.error.retryable ? '可重试' : '不可重试'}`"
              type="error"
              :closable="false"
              show-icon
            />
            <div class="task-actions">
              <el-button
                v-if="factorStore.job?.snapshot_id"
                type="primary"
                @click="openSnapshot(factorStore.job.snapshot_id)"
              >查看快照</el-button>
              <el-button :disabled="factorStore.isActive" @click="factorStore.clear">清除记录</el-button>
            </div>
          </template>
          <el-empty v-else description="尚未提交计算任务" :image-size="96" />
        </el-card>

        <el-card shadow="never" class="surface guardrail-card">
          <strong>复现性检查</strong>
          <ul>
            <li>股票池由快照 ID 与代码集合共同固定</li>
            <li>As of 控制数据可见截止时间</li>
            <li>因子版本与数据源版本随请求持久化</li>
            <li>计算结果只能从已发布快照分页读取</li>
          </ul>
        </el-card>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { factorApi } from '@/api/factors'
import { useFactorStore } from '@/stores/factors'
import type {
  FactorComputeRequest,
  FactorDefinition,
  FactorMarket,
  FactorValidationIssue,
  FactorVersionRef
} from '@/types/factor'
import FactorPageHeader from './components/FactorPageHeader.vue'
import {
  categoryLabels,
  compactHash,
  getErrorMessage,
  isFeatureDisabled,
  marketLabels,
  taskStatusLabels
} from './factorPresentation'

const route = useRoute()
const router = useRouter()
const factorStore = useFactorStore()
const definitions = ref<FactorDefinition[]>([])
const definitionsLoading = ref(false)
const featureDisabled = ref(false)
const submitting = ref(false)
const validationIssues = ref<FactorValidationIssue[]>([])
const parameterDrafts = reactive<Record<string, Record<string, unknown>>>({})

const today = new Date()
const prior = new Date(today)
prior.setDate(prior.getDate() - 90)
const isoDate = (value: Date) => value.toISOString().slice(0, 10)

const form = reactive({
  market: 'CN' as FactorMarket,
  startDate: isoDate(prior),
  endDate: isoDate(today),
  asOf: today,
  universeSnapshotId: '',
  symbolsText: '',
  factorIds: [] as string[],
  dailySourceVersion: '',
  financialSourceVersion: '',
  newsSourceVersion: '',
  adjustment: 'qfq' as 'qfq' | 'hfq' | 'none',
  chunkSize: 100,
  workers: 4,
  forceRecompute: false
})

const symbols = computed(() => Array.from(new Set(
  form.symbolsText
    .split(/[\s,，;；]+/)
    .map((item) => item.trim().toUpperCase())
    .filter(Boolean)
)))
const selectedDefinitions = computed(() => form.factorIds
  .map((id) => definitions.value.find((item) => item.factor_id === id))
  .filter((item): item is FactorDefinition => Boolean(item)))
const estimateCells = computed(() => {
  const start = new Date(`${form.startDate}T00:00:00Z`).getTime()
  const end = new Date(`${form.endDate}T00:00:00Z`).getTime()
  const days = Number.isFinite(start) && Number.isFinite(end)
    ? Math.max(1, Math.floor((end - start) / 86_400_000) + 1)
    : 0
  return days * symbols.value.length * selectedDefinitions.value.length
})
const estimateLabel = computed(() => `预估最多 ${estimateCells.value.toLocaleString()} 个观测单元`)
const currentStatusLabel = computed(() => factorStore.task
  ? taskStatusLabels[factorStore.task.status]
  : '恢复中')
const taskTagType = computed((): 'success' | 'danger' | 'warning' | 'info' => {
  const status = factorStore.task?.status
  if (status === 'succeeded') return 'success'
  if (status === 'failed' || status === 'cancelled') return 'danger'
  if (status === 'retry_wait' || status === 'cancelling') return 'warning'
  return 'info'
})
const progressStatus = computed((): 'success' | 'exception' | undefined => {
  if (factorStore.task?.status === 'succeeded') return 'success'
  if (factorStore.task?.status === 'failed' || factorStore.task?.status === 'cancelled') return 'exception'
  return undefined
})

function numberDraft(value: unknown): number | undefined {
  return typeof value === 'number' ? value : undefined
}

function selectDraft(value: unknown): string | number | boolean | Record<string, unknown> | undefined {
  if (value === undefined || value === null) return undefined
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return value
  if (typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>
  return String(value)
}

function selectChoice(value: unknown): string | number | boolean | Record<string, unknown> {
  return selectDraft(value) ?? ''
}

function setParameter(factorId: string, name: string, value: unknown) {
  parameterDrafts[factorId] ||= {}
  parameterDrafts[factorId][name] = value
}

function syncParameterDrafts() {
  selectedDefinitions.value.forEach((definition) => {
    if (parameterDrafts[definition.factor_id]) return
    parameterDrafts[definition.factor_id] = {}
    Object.entries(definition.default_params).forEach(([name, value]) => {
      parameterDrafts[definition.factor_id][name] =
        definition.params_schema[name]?.type === 'object' ? JSON.stringify(value) : value
    })
  })
}

function buildFactorSpecs(): FactorVersionRef[] {
  return selectedDefinitions.value.map((definition) => {
    const params: Record<string, unknown> = {}
    Object.entries(parameterDrafts[definition.factor_id] || {}).forEach(([name, value]) => {
      if (value === '' || value === undefined || value === null) return
      if (definition.params_schema[name]?.type === 'object') {
        try {
          const parsed = typeof value === 'string' ? JSON.parse(value) : value
          if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error()
          params[name] = parsed
        } catch {
          throw new Error(`${definition.display_name} 的参数 ${name} 必须是 JSON 对象`)
        }
      } else {
        params[name] = value
      }
    })
    return { factor_id: definition.factor_id, version: definition.version, params }
  })
}

function validateForm(): string | null {
  if (!form.universeSnapshotId.trim()) return '请填写股票池快照 ID'
  if (!symbols.value.length) return '请至少填写一个股票代码'
  if (symbols.value.length > 5000) return '单次计算最多包含 5,000 个股票代码'
  if (!selectedDefinitions.value.length) return '请至少选择一个因子'
  if (!form.startDate || !form.endDate || form.startDate > form.endDate) return '日期范围无效'
  if (form.endDate > form.asOf.toISOString().slice(0, 10)) return '结束日期不能晚于数据截止时间'
  if (!form.dailySourceVersion.trim()) return '请填写日线数据版本'
  return null
}

async function loadDefinitions() {
  try {
    definitionsLoading.value = true
    const result = await factorApi.listDefinitions({
      market: form.market,
      status: 'active',
      page: 1,
      page_size: 200
    })
    definitions.value = result.items
    featureDisabled.value = false
    const requested = typeof route.query.factor === 'string' ? route.query.factor : ''
    if (requested && definitions.value.some((item) => item.factor_id === requested)) {
      form.factorIds = Array.from(new Set([...form.factorIds, requested]))
      syncParameterDrafts()
    }
  } catch (error) {
    featureDisabled.value = isFeatureDisabled(error)
    ElMessage.error(getErrorMessage(error, '因子定义加载失败'))
  } finally {
    definitionsLoading.value = false
  }
}

function changeMarket() {
  form.factorIds = []
  validationIssues.value = []
  void loadDefinitions()
}

async function submitCompute() {
  const formError = validateForm()
  if (formError) {
    ElMessage.warning(formError)
    return
  }

  try {
    submitting.value = true
    validationIssues.value = []
    const factorSpecs = buildFactorSpecs()
    const validation = await factorApi.validate(form.market, factorSpecs)
    if (!validation.valid) {
      validationIssues.value = validation.issues
      return
    }
    const sourceVersions: Record<string, string> = { daily_bars: form.dailySourceVersion.trim() }
    if (form.financialSourceVersion.trim()) sourceVersions.financials = form.financialSourceVersion.trim()
    if (form.newsSourceVersion.trim()) sourceVersions.news = form.newsSourceVersion.trim()
    const payload: FactorComputeRequest = {
      market: form.market,
      universe: {
        snapshot_id: form.universeSnapshotId.trim(),
        symbols: symbols.value
      },
      start_date: form.startDate,
      end_date: form.endDate,
      as_of: form.asOf.toISOString(),
      factor_specs: factorSpecs,
      source_versions: sourceVersions,
      adj: form.adjustment,
      force_recompute: form.forceRecompute,
      chunk_size: form.chunkSize,
      workers: form.workers
    }
    const accepted = await factorApi.compute(payload)
    await factorStore.track(accepted)
    ElMessage.success(accepted.deduplicated ? '已恢复相同请求的已有任务' : '因子计算任务已提交')
  } catch (error) {
    ElMessage.error(getErrorMessage(error, '计算任务提交失败'))
  } finally {
    submitting.value = false
  }
}

function openSnapshot(snapshotId: string) {
  void router.push({ path: '/factors/snapshots', query: { snapshot: snapshotId } })
}

onMounted(async () => {
  await Promise.all([loadDefinitions(), factorStore.restore()])
})
onUnmounted(() => factorStore.stopPolling())
</script>

<style scoped lang="scss">
.factor-page { min-width: 0; }
.compute-layout { display: grid; grid-template-columns: minmax(0, 1fr) 350px; gap: 18px; align-items: start; }
.surface { border: 1px solid var(--el-border-color-lighter); border-radius: 14px; }
.card-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.card-header span { margin-left: 10px; color: var(--el-text-color-secondary); font-size: 12px; }
.form-grid { display: grid; gap: 14px; }
.form-grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.form-grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.form-grid.four { grid-template-columns: repeat(4, minmax(0, 1fr)); }
:deep(.el-date-editor), :deep(.el-select), :deep(.el-input-number) { width: 100%; }
.field-help { margin-top: 5px; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.45; }
.parameter-list { display: grid; gap: 10px; margin: -3px 0 20px; }
.parameter-card { padding: 15px; border: 1px solid var(--el-border-color-lighter); border-radius: 10px; background: var(--el-fill-color-extra-light); }
.parameter-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.parameter-heading strong, .parameter-heading code { display: block; }
.parameter-heading code { margin-top: 3px; color: var(--el-text-color-secondary); font-size: 12px; }
.parameter-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 14px; margin-top: 14px; }
.parameter-grid :deep(.el-form-item) { margin-bottom: 3px; }
.no-params { margin-top: 10px; color: var(--el-text-color-secondary); font-size: 13px; }
.block-gap { margin-bottom: 18px; }
.issue-list { margin: 6px 0 0; padding-left: 18px; }
.submit-row { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding-top: 5px; }
.submission-note { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.5; }
.progress-column { display: grid; gap: 14px; position: sticky; top: 84px; }
.status-line { display: flex; align-items: center; gap: 9px; margin-bottom: 18px; }
.status-line span { color: var(--el-text-color-secondary); font-size: 13px; }
.task-message { min-height: 20px; color: var(--el-text-color-regular); line-height: 1.55; }
.task-meta { margin: 16px 0; }
.task-meta div { display: grid; grid-template-columns: 84px minmax(0, 1fr); gap: 9px; padding: 8px 0; border-bottom: 1px solid var(--el-border-color-extra-light); }
.task-meta dt { color: var(--el-text-color-secondary); font-size: 12px; }
.task-meta dd { min-width: 0; margin: 0; text-align: right; word-break: break-all; }
.task-meta code { font-size: 11px; }
.task-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.guardrail-card { color: var(--el-text-color-regular); }
.guardrail-card ul { margin: 12px 0 0; padding-left: 18px; color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.9; }

@media (max-width: 1100px) {
  .compute-layout { grid-template-columns: 1fr; }
  .progress-column { position: static; grid-row: 1; }
}
@media (max-width: 720px) {
  .form-grid.two, .form-grid.three, .form-grid.four, .parameter-grid { grid-template-columns: 1fr; }
  .submit-row { align-items: stretch; flex-direction: column; }
}
</style>
