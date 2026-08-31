<template>
  <section class="factor-page">
    <FactorPageHeader
      title="组合因子编辑器"
      description="通过固定操作、版本化依赖和可审计权重构建组合因子；发布版本不可原地修改。"
    />

    <el-alert
      v-if="featureDisabled"
      class="section-gap"
      type="warning"
      title="因子功能尚未启用"
      :closable="false"
      show-icon
    />
    <el-alert v-else-if="pageError" class="section-gap" type="error" :title="pageError" :closable="false" show-icon />

    <div class="editor-grid">
      <div class="editor-column">
        <el-card class="surface" shadow="never">
          <template #header>
            <div class="card-title">
              <span>01 · 基本信息</span>
              <el-tag v-if="resource" :type="resource.status === 'published' ? 'success' : 'warning'">
                v{{ resource.version }} · {{ resource.status === 'published' ? '已发布' : '草稿' }}
              </el-tag>
            </div>
          </template>
          <el-form label-position="top">
            <div class="form-grid">
              <el-form-item label="名称"><el-input v-model="draft.name" maxlength="120" show-word-limit /></el-form-item>
              <el-form-item label="市场">
                <el-select v-model="draft.market" @change="changeMarket">
                  <el-option v-for="(label, value) in marketLabels" :key="value" :label="label" :value="value" />
                </el-select>
              </el-form-item>
            </div>
            <el-form-item label="说明"><el-input v-model="draft.description" type="textarea" :rows="2" maxlength="2000" show-word-limit /></el-form-item>
          </el-form>
          <el-alert
            type="info"
            title="编辑器只生成结构化 JSON；所有操作均来自下拉白名单。"
            :closable="false"
            show-icon
          />
        </el-card>

        <el-card class="surface section-gap" shadow="never">
          <template #header>
            <div class="card-title">
              <span>02 · 因子项与变换</span>
              <el-button type="primary" plain :icon="Plus" @click="addTerm">添加因子</el-button>
            </div>
          </template>
          <div v-for="(term, index) in draft.definition.terms" :key="index" class="term-card">
            <div class="term-heading">
              <strong>因子 {{ index + 1 }}</strong>
              <el-button link type="danger" :disabled="draft.definition.terms.length === 1" @click="removeTerm(index)">移除</el-button>
            </div>
            <div class="term-grid">
              <el-form-item label="固定版本因子">
                <el-select v-model="term.factor.factor_id" filterable @change="selectFactor(index)">
                  <el-option
                    v-for="factor in definitions"
                    :key="factor.factor_id"
                    :label="`${factor.display_name} · v${factor.version}`"
                    :value="factor.factor_id"
                    :disabled="isFactorSelectedElsewhere(factor.factor_id, index)"
                  />
                </el-select>
              </el-form-item>
              <el-form-item label="原始权重">
                <el-input-number v-model="term.weight" :min="-1000000" :max="1000000" :precision="4" controls-position="right" />
              </el-form-item>
              <el-form-item label="截面变换">
                <el-select v-model="term.transform.kind" @change="resetTransformParams(term)">
                  <el-option v-for="option in transformOptions" :key="option.value" :label="option.label" :value="option.value" />
                </el-select>
              </el-form-item>
            </div>
            <div v-if="term.transform.kind === 'winsorize_mad'" class="parameter-strip">
              <span>MAD 倍数</span><el-input-number v-model="term.transform.mad_scale" :min="0.1" :max="20" :step="0.1" />
            </div>
            <div v-else-if="term.transform.kind === 'winsorize_quantile'" class="parameter-strip two">
              <span>下分位</span><el-input-number v-model="term.transform.lower_quantile" :min="0" :max="0.49" :step="0.01" />
              <span>上分位</span><el-input-number v-model="term.transform.upper_quantile" :min="0.51" :max="1" :step="0.01" />
            </div>
            <div v-if="definitionFor(term.factor.factor_id)?.params_schema && Object.keys(definitionFor(term.factor.factor_id)!.params_schema).length" class="factor-params">
              <div class="params-title">版本化参数</div>
              <div class="params-grid">
                <el-form-item v-for="(schema, paramName) in definitionFor(term.factor.factor_id)!.params_schema" :key="paramName" :label="String(paramName)">
                  <el-select v-if="schema.choices.length" v-model="term.factor.params[paramName]">
                    <el-option v-for="choice in schema.choices" :key="String(choice)" :label="String(choice)" :value="choice" />
                  </el-select>
                  <el-switch v-else-if="schema.type === 'boolean'" v-model="term.factor.params[paramName]" />
                  <el-input-number
                    v-else-if="schema.type === 'integer' || schema.type === 'number'"
                    v-model="term.factor.params[paramName]"
                    :min="schema.minimum ?? undefined"
                    :max="schema.maximum ?? undefined"
                    :precision="schema.type === 'integer' ? 0 : undefined"
                  />
                  <el-input v-else-if="schema.type === 'string'" v-model="term.factor.params[paramName]" />
                  <el-input v-else :model-value="JSON.stringify(term.factor.params[paramName] ?? {})" disabled />
                </el-form-item>
              </div>
            </div>
          </div>
        </el-card>

        <el-card class="surface section-gap" shadow="never">
          <template #header><div class="card-title"><span>03 · 组合与缺失语义</span><span class="weight-sum">Σ|w| = {{ rawWeightSum.toFixed(4) }}</span></div></template>
          <div class="form-grid">
            <el-form-item label="算术方式">
              <el-select v-model="draft.definition.arithmetic">
                <el-option label="加权求和" value="weighted_sum" />
                <el-option label="等权平均" value="mean" />
                <el-option label="同号几何平均" value="geometric_mean" />
              </el-select>
            </el-form-item>
            <el-form-item label="中性化">
              <el-select v-model="draft.definition.neutralize">
                <el-option label="不处理" value="none" />
                <el-option label="行业中性" value="industry" />
                <el-option label="市值中性" value="market_cap" />
                <el-option label="行业 + 市值中性" value="industry_and_market_cap" />
              </el-select>
            </el-form-item>
            <el-form-item label="缺失策略">
              <el-select v-model="draft.definition.missing">
                <el-option label="缺一即剔除股票" value="drop_symbol" />
                <el-option label="剩余权重重新归一" value="renormalize_weights" />
                <el-option label="缺失项使用中性分 0" value="neutral_score" />
              </el-select>
            </el-form-item>
            <el-form-item label="按因子方向自动调整">
              <el-switch v-model="draft.definition.auto_direction" active-text="仅自动反向 negative 因子" />
            </el-form-item>
          </div>
          <el-alert
            v-if="draft.definition.missing === 'renormalize_weights'"
            type="warning"
            title="只有剩余绝对权重达到原权重 60% 时才会生成分数。"
            :closable="false"
            show-icon
          />
          <el-alert
            v-if="draft.definition.arithmetic === 'geometric_mean'"
            class="section-gap"
            type="info"
            title="几何平均要求剩余分量同号；异号样本不会生成结果。"
            :closable="false"
          />
        </el-card>

        <el-card class="surface section-gap" shadow="never">
          <template #header><div class="card-title"><span>04 · 股票过滤白名单</span><el-tag effect="plain">固定字段</el-tag></div></template>
          <div class="form-grid three">
            <el-form-item label="最低因子覆盖率"><el-input-number v-model="draft.definition.filters.minimum_factor_coverage" :min="0" :max="1" :step="0.05" /></el-form-item>
            <el-form-item label="最低 log 市值"><el-input-number v-model="draft.definition.filters.minimum_market_cap_log" :precision="4" /></el-form-item>
            <el-form-item label="最高 log 市值"><el-input-number v-model="draft.definition.filters.maximum_market_cap_log" :precision="4" /></el-form-item>
            <el-form-item label="最低上市天数"><el-input-number v-model="draft.definition.filters.minimum_listing_days" :min="0" :precision="0" /></el-form-item>
            <el-form-item label="包含行业"><el-select v-model="draft.definition.filters.include_industries" multiple filterable allow-create default-first-option /></el-form-item>
            <el-form-item label="排除行业"><el-select v-model="draft.definition.filters.exclude_industries" multiple filterable allow-create default-first-option /></el-form-item>
          </div>
          <div class="status-switches">
            <el-checkbox v-model="draft.definition.filters.exclude_st">排除 ST</el-checkbox>
            <el-checkbox v-model="draft.definition.filters.exclude_delisting">排除退市状态</el-checkbox>
            <el-checkbox v-model="draft.definition.filters.exclude_suspended">排除停牌</el-checkbox>
          </div>
        </el-card>
      </div>

      <aside class="preview-column">
        <el-card class="surface sticky-card" shadow="never">
          <template #header><div class="card-title"><span>结构贡献预览</span><el-tag :type="validation?.valid ? 'success' : 'info'">{{ validation?.valid ? '已验证' : '待验证' }}</el-tag></div></template>
          <div v-if="contributionRows.length" class="contribution-list">
            <div v-for="row in contributionRows" :key="row.factorId" class="contribution-row">
              <div class="contribution-heading">
                <div><strong>{{ row.factorId }}</strong><small>v{{ row.version }} · {{ row.direction }}</small></div>
                <span :class="{ negative: row.effectiveWeight < 0 }">{{ signed(row.effectiveWeight) }}</span>
              </div>
              <div class="contribution-track"><i :style="{ width: `${Math.min(Math.abs(row.effectiveWeight) * 100, 100)}%` }" /></div>
              <div class="contribution-meta">原始 {{ row.rawWeight }} · 归一 {{ signed(row.normalizedWeight) }} · {{ transformLabel(row.transform) }}</div>
            </div>
          </div>
          <el-empty v-else description="添加因子后显示贡献结构" />

          <el-divider />
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="组合方式">{{ arithmeticLabels[draft.definition.arithmetic] }}</el-descriptions-item>
            <el-descriptions-item label="中性化">{{ neutralizeLabels[draft.definition.neutralize] }}</el-descriptions-item>
            <el-descriptions-item label="缺失策略">{{ missingLabels[draft.definition.missing] }}</el-descriptions-item>
            <el-descriptions-item label="依赖数">{{ validation?.dependencies.length ?? draft.definition.terms.length }}</el-descriptions-item>
          </el-descriptions>

          <div v-if="validation?.issues.length" class="issues">
            <el-alert v-for="issue in validation.issues" :key="`${issue.code}-${issue.factor_id}`" type="error" :title="issue.code" :description="issue.message" :closable="false" show-icon />
          </div>
          <el-alert
            v-if="draft.definition.neutralize !== 'none'"
            class="section-gap"
            type="warning"
            title="执行快照必须包含对应行业或 market_cap_log 控制列。"
            :closable="false"
          />

          <div class="action-stack">
            <el-button :loading="validating" @click="validateDraft">校验结构与依赖版本</el-button>
            <el-button type="primary" :loading="saving" :disabled="!canSave" @click="saveDraft">
              {{ resource?.status === 'published' ? '创建下一版草稿' : resource ? '更新草稿' : '保存草稿' }}
            </el-button>
            <el-button type="success" :loading="publishing" :disabled="resource?.status !== 'draft'" @click="publishDraft">发布不可变版本</el-button>
          </div>

          <template v-if="resource">
            <el-divider />
            <div class="resource-meta">
              <span>COMPOSITE ID</span><code>{{ resource.composite_id }}</code>
              <span>DEFINITION CHECKSUM</span><code>{{ compactHash(resource.definition_checksum) }}</code>
              <span>更新时间</span><strong>{{ formatDateTime(resource.updated_at) }}</strong>
              <span>发布时间</span><strong>{{ formatDateTime(resource.published_at) }}</strong>
            </div>
          </template>
        </el-card>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, toRaw, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { factorApi } from '@/api/factors'
import type {
  CompositeDefinitionPayload,
  CompositeFactorResource,
  CompositeFactorTerm,
  CompositeTransformKind,
  CompositeValidationResponse,
  FactorDefinition
} from '@/types/factor'
import FactorPageHeader from './components/FactorPageHeader.vue'
import {
  compactHash,
  formatDateTime,
  getErrorMessage,
  isFeatureDisabled,
  marketLabels
} from './factorPresentation'

const STORAGE_KEY = 'factor-composite-editor-v1'
const definitions = ref<FactorDefinition[]>([])
const validation = ref<CompositeValidationResponse | null>(null)
const resource = ref<CompositeFactorResource | null>(null)
const pageError = ref('')
const featureDisabled = ref(false)
const validating = ref(false)
const saving = ref(false)
const publishing = ref(false)

const transformOptions: Array<{ value: CompositeTransformKind; label: string }> = [
  { value: 'identity', label: '原值' },
  { value: 'negate', label: '取反' },
  { value: 'log1p_abs', label: '符号 log1p(abs)' },
  { value: 'winsorize_mad', label: 'MAD 去极值' },
  { value: 'winsorize_quantile', label: '分位数去极值' },
  { value: 'zscore', label: 'Z-Score' },
  { value: 'robust_zscore', label: '稳健 Z-Score' },
  { value: 'percentile_rank', label: '百分位排名' }
]
const arithmeticLabels = { weighted_sum: '加权求和', mean: '等权平均', geometric_mean: '同号几何平均' }
const neutralizeLabels = { none: '不处理', industry: '行业中性', market_cap: '市值中性', industry_and_market_cap: '行业 + 市值' }
const missingLabels = { drop_symbol: '缺一剔除', renormalize_weights: '60% 阈值重归一', neutral_score: '缺失置 0' }

const emptyTerm = (): CompositeFactorTerm => ({
  factor: { factor_id: '', version: 1, params: {} },
  weight: 1,
  transform: { kind: 'identity' }
})

const draft = reactive<CompositeDefinitionPayload>({
  name: '',
  description: '',
  market: 'CN',
  definition: {
    terms: [emptyTerm()],
    auto_direction: true,
    neutralize: 'none',
    arithmetic: 'weighted_sum',
    missing: 'renormalize_weights',
    filters: {
      minimum_factor_coverage: 0,
      include_industries: [],
      exclude_industries: [],
      exclude_st: true,
      exclude_delisting: true,
      exclude_suspended: true
    }
  }
})

const rawWeightSum = computed(() => draft.definition.terms.reduce((sum, term) => sum + Math.abs(term.weight || 0), 0))
const canSave = computed(() =>
  Boolean(draft.name.trim()) &&
  draft.definition.terms.every((term) => term.factor.factor_id) &&
  rawWeightSum.value > 0 &&
  validation.value?.valid === true
)

const contributionRows = computed(() => {
  const denominator = rawWeightSum.value || 1
  return draft.definition.terms.filter((term) => term.factor.factor_id).map((term) => {
    const factor = definitionFor(term.factor.factor_id)
    const normalizedWeight = term.weight / denominator
    const direction = factor?.direction || 'neutral'
    const multiplier = draft.definition.auto_direction && direction === 'negative' ? -1 : 1
    const equalWeight = 1 / draft.definition.terms.length
    return {
      factorId: term.factor.factor_id,
      version: term.factor.version,
      direction,
      rawWeight: term.weight,
      normalizedWeight,
      effectiveWeight: draft.definition.arithmetic === 'weighted_sum' ? normalizedWeight * multiplier : equalWeight * multiplier,
      transform: term.transform.kind
    }
  })
})

watch(draft, () => {
  validation.value = null
}, { deep: true, flush: 'sync' })

function definitionFor(factorId: string): FactorDefinition | undefined {
  return definitions.value.find((item) => item.factor_id === factorId)
}

function transformLabel(kind: CompositeTransformKind): string {
  return transformOptions.find((item) => item.value === kind)?.label || kind
}

function signed(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(4)}`
}

function addTerm() {
  draft.definition.terms.push(emptyTerm())
}

function removeTerm(index: number) {
  draft.definition.terms.splice(index, 1)
}

function isFactorSelectedElsewhere(factorId: string, currentIndex: number): boolean {
  return draft.definition.terms.some((term, index) => index !== currentIndex && term.factor.factor_id === factorId)
}

function selectFactor(index: number) {
  const term = draft.definition.terms[index]
  const factor = definitionFor(term.factor.factor_id)
  if (!factor) return
  term.factor.version = factor.version
  term.factor.params = structuredClone(factor.default_params)
}

function resetTransformParams(term: CompositeFactorTerm) {
  if (term.transform.kind === 'winsorize_mad') {
    term.transform = { kind: 'winsorize_mad', mad_scale: 3 }
  } else if (term.transform.kind === 'winsorize_quantile') {
    term.transform = { kind: 'winsorize_quantile', lower_quantile: 0.01, upper_quantile: 0.99 }
  } else {
    term.transform = { kind: term.transform.kind }
  }
}

function sanitizedPayload(): CompositeDefinitionPayload {
  const payload = structuredClone(toRaw(draft)) as CompositeDefinitionPayload
  payload.name = payload.name.trim()
  payload.description = payload.description.trim()
  payload.definition.terms = payload.definition.terms.map((term) => {
    if (term.transform.kind === 'winsorize_mad') {
      term.transform = { kind: term.transform.kind, mad_scale: term.transform.mad_scale ?? 3 }
    } else if (term.transform.kind === 'winsorize_quantile') {
      term.transform = {
        kind: term.transform.kind,
        lower_quantile: term.transform.lower_quantile ?? 0.01,
        upper_quantile: term.transform.upper_quantile ?? 0.99
      }
    } else {
      term.transform = { kind: term.transform.kind }
    }
    return term
  })
  return payload
}

async function loadDefinitions() {
  const response = await factorApi.listDefinitions({ market: draft.market, status: 'active', page: 1, page_size: 200 })
  definitions.value = response.items
}

async function changeMarket() {
  validation.value = null
  draft.definition.terms = [emptyTerm()]
  await loadDefinitions()
}

async function validateDraft(): Promise<boolean> {
  try {
    validating.value = true
    pageError.value = ''
    validation.value = await factorApi.validateComposite(draft.market, sanitizedPayload().definition)
    if (validation.value.valid) {
      ElMessage.success('结构、权重与依赖版本校验通过')
      return true
    }
    ElMessage.error(validation.value.issues[0]?.message || '组合结构无效')
    return false
  } catch (error) {
    pageError.value = getErrorMessage(error, '组合校验失败')
    ElMessage.error(pageError.value)
    return false
  } finally {
    validating.value = false
  }
}

async function saveDraft() {
  if (!validation.value?.valid && !(await validateDraft())) return
  try {
    saving.value = true
    const payload = sanitizedPayload()
    resource.value = resource.value
      ? await factorApi.updateComposite(resource.value.composite_id, payload)
      : await factorApi.createComposite(payload)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(resource.value))
    applyResourceToDraft(resource.value)
    ElMessage.success(`草稿 v${resource.value.version} 已保存`)
  } catch (error) {
    pageError.value = getErrorMessage(error, '草稿保存失败')
    ElMessage.error(pageError.value)
  } finally {
    saving.value = false
  }
}

async function publishDraft() {
  if (!resource.value || resource.value.status !== 'draft') return
  try {
    publishing.value = true
    resource.value = await factorApi.publishComposite(resource.value.composite_id)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(resource.value))
    ElMessage.success(`版本 v${resource.value.version} 已不可变发布`)
  } catch (error) {
    pageError.value = getErrorMessage(error, '组合发布失败')
    ElMessage.error(pageError.value)
  } finally {
    publishing.value = false
  }
}

function applyResourceToDraft(value: CompositeFactorResource) {
  draft.name = value.name
  draft.description = value.description
  draft.market = value.market
  draft.definition = structuredClone(value.definition)
  validation.value = {
    valid: true,
    issues: [],
    normalized_definition: structuredClone(value.definition),
    dependencies: structuredClone(value.dependencies),
    definition_checksum: value.definition_checksum
  }
}

function restoreResource() {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (!saved) return
  try {
    resource.value = JSON.parse(saved) as CompositeFactorResource
    applyResourceToDraft(resource.value)
  } catch {
    localStorage.removeItem(STORAGE_KEY)
  }
}

onMounted(async () => {
  restoreResource()
  try {
    await loadDefinitions()
    featureDisabled.value = false
  } catch (error) {
    featureDisabled.value = isFeatureDisabled(error)
    pageError.value = getErrorMessage(error, '组合编辑器初始化失败')
  }
})
</script>

<style scoped lang="scss">
.factor-page { min-width: 0; }
.section-gap { margin-top: 16px; }
.surface { border: 1px solid var(--el-border-color-lighter); border-radius: 14px; }
.editor-grid { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(340px, .75fr); gap: 16px; align-items: start; }
.card-title, .term-heading, .contribution-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.card-title { font-weight: 700; }
.form-grid, .term-grid, .params-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.form-grid.three, .term-grid { grid-template-columns: repeat(3, 1fr); }
:deep(.el-select), :deep(.el-input-number) { width: 100%; }
.term-card { margin-bottom: 12px; padding: 14px; border: 1px solid var(--el-border-color-lighter); border-radius: 11px; background: var(--el-fill-color-extra-light); }
.term-card:last-child { margin-bottom: 0; }
.term-heading { margin-bottom: 9px; }
.parameter-strip { display: grid; grid-template-columns: auto 180px; align-items: center; justify-content: end; gap: 9px; }
.parameter-strip.two { grid-template-columns: auto 140px auto 140px; }
.factor-params { margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--el-border-color); }
.params-title { margin-bottom: 9px; color: var(--el-text-color-secondary); font-size: 12px; font-weight: 650; }
.status-switches { display: flex; flex-wrap: wrap; gap: 16px; }
.weight-sum { color: var(--el-text-color-secondary); font-size: 12px; font-variant-numeric: tabular-nums; }
.sticky-card { position: sticky; top: 16px; }
.contribution-list { display: flex; flex-direction: column; gap: 15px; }
.contribution-heading > div { display: flex; flex-direction: column; }
.contribution-heading small { margin-top: 2px; color: var(--el-text-color-secondary); }
.contribution-heading > span { color: var(--el-color-success); font-weight: 750; font-variant-numeric: tabular-nums; }
.contribution-heading > span.negative { color: var(--el-color-danger); }
.contribution-track { height: 7px; margin: 7px 0; overflow: hidden; border-radius: 99px; background: var(--el-fill-color-dark); }
.contribution-track i { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--el-color-primary), var(--el-color-success)); }
.contribution-meta { color: var(--el-text-color-secondary); font-size: 11px; }
.issues { display: flex; flex-direction: column; gap: 8px; margin-top: 14px; }
.action-stack { display: grid; gap: 9px; margin-top: 18px; }
.action-stack :deep(.el-button) { width: 100%; margin-left: 0; }
.resource-meta { display: grid; gap: 5px; }
.resource-meta span { margin-top: 8px; color: var(--el-text-color-secondary); font-size: 10px; letter-spacing: .1em; }
.resource-meta code { word-break: break-all; }

@media (max-width: 1050px) {
  .editor-grid { grid-template-columns: 1fr; }
  .sticky-card { position: static; }
}
@media (max-width: 720px) {
  .form-grid, .form-grid.three, .term-grid, .params-grid { grid-template-columns: 1fr; }
  .parameter-strip, .parameter-strip.two { grid-template-columns: 1fr; justify-content: stretch; }
}
</style>
