<template>
  <section class="strategy-page">
    <div class="page-header">
      <div>
        <el-button link @click="router.push('/strategies')">← 返回策略中心</el-button>
        <h1>{{ editing ? '编辑结构化策略草稿' : '结构化策略向导' }}</h1>
        <p>通过白名单字段生成策略定义；页面不接受脚本、函数或自由代码。</p>
      </div>
      <el-tag type="success" effect="plain">安全 DSL</el-tag>
    </div>

    <el-alert
      title="执行时点约束"
      description="日线收盘生成的信号不得在同一收盘价成交。向导默认使用下一交易日开盘执行。"
      type="warning"
      :closable="false"
      show-icon
    />

    <el-card shadow="never" class="surface wizard-card">
      <el-steps :active="activeStep" finish-status="success" align-center>
        <el-step v-for="step in steps" :key="step" :title="step" />
      </el-steps>

      <div class="step-body">
        <template v-if="activeStep === 0">
          <h2>股票池与基本信息</h2>
          <div class="form-grid">
            <el-form-item label="策略名称" required><el-input v-model="model.name" maxlength="200" /></el-form-item>
            <el-form-item label="策略类型"><el-select v-model="model.kind"><el-option label="组合" value="portfolio" /><el-option label="排序" value="ranking" /><el-option label="筛选" value="screening" /></el-select></el-form-item>
            <el-form-item label="市场"><el-select v-model="model.market"><el-option label="A 股" value="CN" /><el-option label="港股" value="HK" /><el-option label="美股" value="US" /></el-select></el-form-item>
            <el-form-item label="标签"><el-select v-model="model.tags" multiple allow-create filterable default-first-option /></el-form-item>
            <el-form-item label="股票池快照 ID"><el-input v-model="model.snapshotId" placeholder="可留空，在运行时指定" /></el-form-item>
            <el-form-item label="最少上市天数"><el-input-number v-model="model.minimumListingDays" :min="0" :max="100000" /></el-form-item>
            <el-form-item label="最小市值"><el-input-number v-model="model.minimumMarketCap" :min="0" clearable /></el-form-item>
            <el-form-item label="最大市值"><el-input-number v-model="model.maximumMarketCap" :min="0" clearable /></el-form-item>
          </div>
          <el-form-item label="说明"><el-input v-model="model.description" type="textarea" :rows="3" maxlength="4000" show-word-limit /></el-form-item>
          <el-space wrap>
            <el-checkbox v-model="model.excludeSt">排除 ST</el-checkbox>
            <el-checkbox v-model="model.excludeDelisting">排除退市整理</el-checkbox>
            <el-checkbox v-model="model.excludeSuspended">排除停牌</el-checkbox>
          </el-space>
        </template>

        <template v-else-if="activeStep === 1">
          <h2>因子与数据要求</h2>
          <div class="form-grid">
            <el-form-item label="因子 ID" required>
              <el-select v-model="model.factors" multiple allow-create filterable default-first-option placeholder="输入已注册因子 ID" />
            </el-form-item>
            <el-form-item label="因子版本"><el-input-number v-model="model.factorVersion" :min="1" /></el-form-item>
            <el-form-item label="复权"><el-select v-model="model.adjustment"><el-option label="前复权" value="qfq" /><el-option label="后复权" value="hfq" /><el-option label="不复权" value="none" /></el-select></el-form-item>
            <el-form-item label="最短历史"><el-input-number v-model="model.minimumHistory" :min="1" :max="5000" /></el-form-item>
          </div>
          <el-alert title="数据可见性" description="所有因子必须使用 point-in-time 快照；财报数据从发布时间开始可见，而不是从报告期开始可见。" type="info" :closable="false" />
        </template>

        <template v-else-if="activeStep === 2">
          <h2>入场规则</h2>
          <p class="muted">当前向导使用一个确定性的因子比较条件。高级树仅用于查看，不提供代码编辑。</p>
          <div class="condition-row">
            <el-select v-model="model.entryFactor" filterable allow-create>
              <el-option v-for="factor in model.factors" :key="factor" :label="factor" :value="factor" />
            </el-select>
            <el-select v-model="model.entryOperator">
              <el-option label=">" value="gt" /><el-option label="≥" value="gte" />
              <el-option label="<" value="lt" /><el-option label="≤" value="lte" />
            </el-select>
            <el-input-number v-model="model.entryThreshold" />
          </div>
        </template>

        <template v-else-if="activeStep === 3">
          <h2>退出规则</h2>
          <div class="form-grid">
            <el-form-item label="止盈比例"><el-input-number v-model="model.takeProfit" :min="0.001" :max="10" :step="0.01" /></el-form-item>
            <el-form-item label="止损比例"><el-input-number v-model="model.stopLoss" :min="0.001" :max="0.999" :step="0.01" /></el-form-item>
            <el-form-item label="最长持有期"><el-input-number v-model="model.maxHoldingPeriods" :min="1" :max="100000" /></el-form-item>
          </div>
          <el-alert v-if="!hasExitRule" title="至少配置一项退出规则" type="error" :closable="false" show-icon />
        </template>

        <template v-else-if="activeStep === 4">
          <h2>仓位与再平衡</h2>
          <div class="form-grid">
            <el-form-item label="权重方式"><el-select v-model="model.weighting"><el-option label="等权" value="equal_weight" /><el-option label="按分数加权" value="score_weight" /></el-select></el-form-item>
            <el-form-item label="最大持仓数"><el-input-number v-model="model.maxPositions" :min="1" :max="200" /></el-form-item>
            <el-form-item label="单股上限"><el-input-number v-model="model.maxPositionWeight" :min="0.01" :max="1" :step="0.01" /></el-form-item>
            <el-form-item label="行业上限"><el-input-number v-model="model.maxIndustryWeight" :min="0.05" :max="1" :step="0.01" /></el-form-item>
            <el-form-item label="最低现金比例"><el-input-number v-model="model.minCashRatio" :min="0" :max="0.9" :step="0.01" /></el-form-item>
            <el-form-item label="再平衡"><el-select v-model="model.rebalanceFrequency"><el-option label="每日" value="daily" /><el-option label="每周" value="weekly" /><el-option label="每月" value="monthly" /></el-select></el-form-item>
            <el-form-item v-if="model.rebalanceFrequency === 'weekly'" label="交易日"><el-select v-model="model.weekday"><el-option v-for="day in weekdays" :key="day.value" :label="day.label" :value="day.value" /></el-select></el-form-item>
            <el-form-item v-if="model.rebalanceFrequency === 'monthly'" label="每月日期"><el-input-number v-model="model.dayOfMonth" :min="1" :max="31" /></el-form-item>
          </div>
        </template>

        <template v-else-if="activeStep === 5">
          <h2>执行规则</h2>
          <div class="form-grid">
            <el-form-item label="信号时点"><el-select v-model="model.signalTime"><el-option label="开盘" value="open" /><el-option label="收盘" value="close" /></el-select></el-form-item>
            <el-form-item label="执行时点"><el-select v-model="model.executionTime"><el-option label="当日开盘" value="same_open" /><el-option label="当日收盘" value="same_close" /><el-option label="次日开盘" value="next_open" /><el-option label="次日收盘" value="next_close" /></el-select></el-form-item>
            <el-form-item label="成交价格"><el-select v-model="model.price"><el-option label="开盘价" value="open" /><el-option label="收盘价" value="close" /><el-option label="VWAP" value="vwap" /></el-select></el-form-item>
            <el-form-item label="滑点 (bps)"><el-input-number v-model="model.slippageBps" :min="0" :max="10000" /></el-form-item>
            <el-form-item label="费率版本"><el-input v-model="model.feeModelVersion" /></el-form-item>
          </div>
          <el-alert v-if="illegalTiming" title="执行时点可能产生未来数据或同价成交偏差，请选择下一合法执行点。" type="error" :closable="false" show-icon />
        </template>

        <template v-else-if="activeStep === 6">
          <h2>风控与分析上下文</h2>
          <div class="form-grid">
            <el-form-item label="最大回撤停止"><el-input-number v-model="model.maxDrawdownStop" :min="0.001" :max="0.999" :step="0.01" /></el-form-item>
            <el-form-item label="波动率目标"><el-input-number v-model="model.volatilityTarget" :min="0.001" :max="5" :step="0.01" /></el-form-item>
            <el-form-item label="冷静期"><el-input-number v-model="model.cooldownPeriods" :min="0" :max="10000" /></el-form-item>
            <el-form-item label="基准代码"><el-input v-model="model.benchmarkSymbol" /></el-form-item>
            <el-form-item label="AnalysisProfile 版本"><el-select v-model="model.analysisProfileVersionId" clearable filterable><el-option v-for="option in profileOptions" :key="option.value" :label="option.label" :value="option.value" /></el-select></el-form-item>
            <el-form-item label="Skill 版本"><el-select v-model="model.skillVersionIds" multiple allow-create filterable default-first-option /></el-form-item>
          </div>
          <el-checkbox v-model="model.requireExplanation">要求结构化解释</el-checkbox>
        </template>

        <template v-else>
          <h2>校验与确认</h2>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="数据需求">{{ dataRequirement }}</el-descriptions-item>
            <el-descriptions-item label="估算成本">{{ estimatedCost }}</el-descriptions-item>
            <el-descriptions-item label="执行">{{ model.signalTime }} → {{ model.executionTime }} / {{ model.price }}</el-descriptions-item>
            <el-descriptions-item label="风控">{{ riskSummary }}</el-descriptions-item>
          </el-descriptions>
          <div class="review-actions">
            <el-button type="primary" :loading="validating" @click="validateDefinition">运行服务端校验</el-button>
            <el-switch v-model="advancedMode" active-text="查看结构化树" />
          </div>
          <el-tree v-if="advancedMode" :data="treeData" :props="{ label: 'label', children: 'children' }" default-expand-all class="definition-tree" />
          <div v-if="validation" class="validation-result">
            <el-result :icon="validation.valid ? 'success' : 'error'" :title="validation.valid ? '校验通过' : '校验失败'" :sub-title="validation.valid ? '可保存为草稿' : '请修正以下问题'" />
            <el-alert v-for="issue in [...validation.errors, ...validation.warnings]" :key="`${issue.code}-${issue.path}`" :title="`${issue.code}: ${issue.message}`" :type="validation.errors.includes(issue) ? 'error' : 'warning'" :closable="false" />
            <el-card shadow="never" class="dependency-card">
              <strong>冻结依赖</strong>
              <p>因子：{{ validation.factor_dependencies.map(item => `${item.factor_id}@${item.version}`).join('、') || '无' }}</p>
              <p>Skill：{{ validation.skill_dependencies.map(item => `${item.skill_id}@${item.version}`).join('、') || '无' }}</p>
            </el-card>
          </div>
          <el-form-item label="版本说明"><el-input v-model="model.changeSummary" maxlength="2000" /></el-form-item>
        </template>
      </div>

      <div class="wizard-footer">
        <el-button :disabled="activeStep === 0" @click="activeStep--">上一步</el-button>
        <el-button v-if="activeStep < steps.length - 1" type="primary" :disabled="!canContinue" @click="activeStep++">下一步</el-button>
        <el-button v-else type="success" :disabled="!validation?.valid" :loading="saving" @click="saveDraft">保存草稿</el-button>
      </div>
    </el-card>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { strategyApi } from '@/api/strategies'
import { analysisProfileApi } from '@/api/analysisProfiles'
import type { StrategyValidationResponse, StrategyWizardModel } from '@/types/strategy'
import { buildCreatePayload, buildDefinition, modelFromVersion, newWizardModel } from './wizardModel'

interface TreeNode { label: string; children?: TreeNode[] }

const router = useRouter()
const route = useRoute()
const steps = ['股票池', '因子', '入场', '退出', '仓位', '执行', '风控', '校验']
const weekdays = [
  { label: '周一', value: 0 }, { label: '周二', value: 1 }, { label: '周三', value: 2 },
  { label: '周四', value: 3 }, { label: '周五', value: 4 }
]
const activeStep = ref(0)
const model = ref<StrategyWizardModel>(newWizardModel())
const validation = ref<StrategyValidationResponse | null>(null)
const validating = ref(false)
const saving = ref(false)
const advancedMode = ref(false)
const profileOptions = ref<Array<{ label: string; value: string }>>([])
const editing = computed(() => Boolean(route.params.strategyId))
const editingVersionId = ref('')
const editingChecksum = ref('')

const factorPattern = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/
const hasExitRule = computed(() => model.value.takeProfit !== null || model.value.stopLoss !== null || model.value.maxHoldingPeriods !== null)
const illegalTiming = computed(() =>
  (model.value.signalTime === 'close' && model.value.executionTime === 'same_close') ||
  (model.value.signalTime === 'close' && model.value.executionTime === 'same_open') ||
  (model.value.signalTime === 'open' && model.value.executionTime === 'same_open')
)
const canContinue = computed(() => {
  if (activeStep.value === 0) return Boolean(model.value.name.trim())
  if (activeStep.value === 1) return model.value.factors.length > 0 && model.value.factors.every(item => factorPattern.test(item))
  if (activeStep.value === 2) return model.value.factors.includes(model.value.entryFactor)
  if (activeStep.value === 3) return hasExitRule.value
  if (activeStep.value === 5) return !illegalTiming.value && Boolean(model.value.feeModelVersion.trim())
  return true
})
const dataRequirement = computed(() => `${model.value.market} · 日线 · ${model.value.minimumHistory} 个交易日 · ${model.value.factors.length} 个因子`)
const estimatedCost = computed(() => {
  const units = model.value.minimumHistory * model.value.factors.length * Math.max(model.value.maxPositions, 1)
  return `约 ${units.toLocaleString()} 因子观测单元（实际以股票池规模为准）`
})
const riskSummary = computed(() => `止损 ${percent(model.value.stopLoss)}；止盈 ${percent(model.value.takeProfit)}；最大回撤 ${percent(model.value.maxDrawdownStop)}`)
const treeData = computed(() => toTree(buildDefinition(model.value)))

watch(model, () => { validation.value = null }, { deep: true })

onMounted(async () => {
  try {
    const page = await analysisProfileApi.list()
    const details = await Promise.all(page.items.map(item => analysisProfileApi.get(item.profile_id)))
    profileOptions.value = details.flatMap(detail => detail.versions
      .filter(version => version.status === 'published' || version.status === 'draft')
      .map(version => ({ label: `${detail.profile.name} · v${version.version} (${version.status})`, value: version.profile_version_id })))
  } catch {
    profileOptions.value = []
  }
  if (editing.value) {
    const detail = await strategyApi.get(String(route.params.strategyId))
    const draft = detail.versions.find(version => version.strategy_version_id === detail.strategy.current_draft_version_id)
    if (!draft || !draft.checksum) {
      ElMessage.error('当前策略没有可编辑草稿')
      await router.replace(`/strategies/${detail.strategy.strategy_id}`)
      return
    }
    editingVersionId.value = draft.strategy_version_id
    editingChecksum.value = draft.checksum
    model.value = modelFromVersion(detail.strategy, draft)
  }
})

function percent(value: number | null): string {
  return value === null ? '未设置' : `${(value * 100).toFixed(1)}%`
}

function toTree(value: unknown, key = 'definition'): TreeNode[] {
  if (Array.isArray(value)) {
    return [{ label: `${key} [${value.length}]`, children: value.flatMap((item, index) => toTree(item, String(index))) }]
  }
  if (value !== null && typeof value === 'object') {
    return [{ label: key, children: Object.entries(value as Record<string, unknown>).flatMap(([childKey, child]) => toTree(child, childKey)) }]
  }
  return [{ label: `${key}: ${String(value)}` }]
}

async function validateDefinition(): Promise<void> {
  validating.value = true
  try {
    validation.value = await strategyApi.validateDefinition(model.value.market, buildDefinition(model.value))
    if (validation.value.valid) ElMessage.success('策略定义校验通过')
  } finally {
    validating.value = false
  }
}

async function saveDraft(): Promise<void> {
  if (!validation.value?.valid) return
  saving.value = true
  try {
    if (editing.value) {
      const payload = buildCreatePayload(model.value)
      await strategyApi.updateVersion(
        String(route.params.strategyId),
        editingVersionId.value,
        editingChecksum.value,
        payload.definition,
        payload.analysis_profile_version_id,
        payload.change_summary
      )
      ElMessage.success('策略草稿已更新')
      await router.push(`/strategies/${String(route.params.strategyId)}`)
    } else {
      const created = await strategyApi.create(buildCreatePayload(model.value))
      ElMessage.success('策略草稿已保存')
      await router.push(`/strategies/${created.strategy.strategy_id}`)
    }
  } finally {
    saving.value = false
  }
}
</script>

<style scoped lang="scss">
.strategy-page { padding: 24px; display: grid; gap: 18px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; }
.page-header h1 { margin: 8px 0; }
.page-header p, .muted { color: var(--el-text-color-secondary); }
.surface { border-radius: 12px; }
.wizard-card :deep(.el-card__body) { padding: 28px; }
.step-body { min-height: 420px; padding: 32px 8px 20px; }
.step-body h2 { margin-top: 0; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 28px; }
.form-grid :deep(.el-select), .form-grid :deep(.el-input-number) { width: 100%; }
.condition-row { display: grid; grid-template-columns: 2fr 120px 1fr; gap: 12px; max-width: 760px; }
.wizard-footer { display: flex; justify-content: flex-end; gap: 10px; border-top: 1px solid var(--el-border-color-lighter); padding-top: 18px; }
.review-actions { display: flex; justify-content: space-between; align-items: center; margin: 20px 0; }
.definition-tree { border: 1px solid var(--el-border-color); border-radius: 8px; padding: 12px; max-height: 360px; overflow: auto; }
.validation-result { display: grid; gap: 10px; margin-top: 18px; }
.dependency-card p { margin: 8px 0 0; color: var(--el-text-color-secondary); }
@media (max-width: 800px) { .form-grid { grid-template-columns: 1fr; } .condition-row { grid-template-columns: 1fr; } }
</style>
