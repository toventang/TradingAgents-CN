<template>
  <section class="create-page">
    <header class="page-header">
      <div>
        <el-button link :icon="ArrowLeft" @click="router.push('/backtests')">返回回测中心</el-button>
        <h1>创建历史回测</h1>
        <p>基于已发布、不可变的策略版本运行。信号、成交、费用和指标均由后端确定性计算。</p>
      </div>
    </header>

    <el-skeleton v-if="loadingStrategies" :rows="9" animated />
    <div v-else class="create-layout">
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        class="form-surface"
        @submit.prevent="submit"
      >
        <section class="form-section" aria-labelledby="strategy-heading">
          <div class="section-heading">
            <h2 id="strategy-heading">策略与市场</h2>
            <span>仅列出已发布版本</span>
          </div>
          <el-form-item label="策略版本" prop="strategyVersionId">
            <el-select
              v-model="form.strategyVersionId"
              filterable
              placeholder="选择已发布策略"
              class="full-width"
              @change="applyStrategy"
            >
              <el-option
                v-for="item in strategies"
                :key="item.strategy_version_id"
                :label="`${item.name} · ${item.market}`"
                :value="item.strategy_version_id"
              >
                <div class="strategy-option">
                  <span>{{ item.name }}</span>
                  <small>{{ item.market }} · {{ item.strategy_version_id }}</small>
                </div>
              </el-option>
            </el-select>
            <div v-if="!strategies.length" class="field-help">
              暂无可用版本，请先在策略中心完成校验并发布策略。
            </div>
          </el-form-item>
          <div class="field-grid">
            <el-form-item label="市场">
              <el-input :model-value="form.market" disabled />
            </el-form-item>
            <el-form-item label="成本口径">
              <el-input :model-value="selectedStrategy?.fee_model_version || '随策略发布版本冻结'" disabled />
            </el-form-item>
          </div>
        </section>

        <section class="form-section" aria-labelledby="period-heading">
          <div class="section-heading">
            <h2 id="period-heading">时间与资金</h2>
            <span>最少 60 个交易日</span>
          </div>
          <div class="field-grid">
            <el-form-item label="回测区间" prop="dateRange">
              <el-date-picker
                v-model="form.dateRange"
                type="daterange"
                unlink-panels
                value-format="YYYY-MM-DD"
                start-placeholder="开始日期"
                end-placeholder="结束日期"
                class="full-width"
              />
            </el-form-item>
            <el-form-item label="初始资金" prop="initialCash">
              <el-input v-model="form.initialCash" inputmode="decimal" placeholder="1000000">
                <template #append>{{ currencyLabel }}</template>
              </el-input>
            </el-form-item>
          </div>
          <div class="field-grid">
            <el-form-item label="基准代码" prop="benchmark">
              <el-input v-model="form.benchmark" maxlength="128" placeholder="例如 000300" />
            </el-form-item>
            <el-form-item label="随机种子">
              <el-input-number v-model="form.seed" :min="0" :max="2147483647" controls-position="right" class="full-width" />
            </el-form-item>
          </div>
        </section>

        <section class="form-section" aria-labelledby="execution-heading">
          <div class="section-heading">
            <h2 id="execution-heading">执行口径</h2>
            <span>收盘信号不会在同一收盘价成交</span>
          </div>
          <div class="field-grid">
            <el-form-item label="成交模型" prop="executionModelId">
              <el-select v-model="form.executionModelId" class="full-width">
                <el-option label="下一交易日开盘价" value="next_open" />
                <el-option label="下一交易日收盘价" value="next_close" />
              </el-select>
            </el-form-item>
            <el-form-item label="持仓快照">
              <el-switch
                v-model="form.saveDailyPositions"
                active-text="保存每日持仓"
                inactive-text="仅保存交易与净值"
              />
            </el-form-item>
          </div>
          <el-form-item label="参数覆盖（JSON，可选）" :error="parameterError">
            <el-input
              v-model="form.parameterOverrides"
              type="textarea"
              :rows="5"
              spellcheck="false"
              placeholder='例如 {"max_positions": 10}'
            />
            <div class="field-help">仅覆盖策略已声明的参数；不执行任意代码。</div>
          </el-form-item>
          <el-form-item label="运行备注">
            <el-input v-model="form.notes" type="textarea" :rows="3" maxlength="4000" show-word-limit />
          </el-form-item>
        </section>

        <div class="form-actions">
          <el-button @click="router.push('/backtests')">取消</el-button>
          <el-button
            type="primary"
            native-type="submit"
            :loading="submitting"
            :disabled="!strategies.length"
          >
            创建回测
          </el-button>
        </div>
      </el-form>

      <aside class="run-notes" aria-label="运行说明">
        <h2>提交前确认</h2>
        <dl>
          <div><dt>策略</dt><dd>{{ selectedStrategy?.name || '未选择' }}</dd></div>
          <div><dt>版本</dt><dd>{{ selectedStrategy?.strategy_version_id || '—' }}</dd></div>
          <div><dt>市场</dt><dd>{{ form.market }}</dd></div>
          <div><dt>基准</dt><dd>{{ form.benchmark || '—' }}</dd></div>
          <div><dt>成交</dt><dd>{{ executionLabel }}</dd></div>
        </dl>
        <el-alert
          title="历史结果不代表未来收益"
          description="系统会按数据发布时间、交易规则和冻结费用版本执行，缺失或无效数据不会触发自动买入。"
          type="warning"
          :closable="false"
          show-icon
        />
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import { backtestApi } from '@/api/backtests'
import { strategyApi } from '@/api/strategies'
import type { BacktestMarket, BacktestRequest, PublishedStrategyOption } from '@/types/backtest'
import type { StrategyDefinition, StrategyVersion } from '@/types/strategy'

interface CreateForm {
  strategyVersionId: string
  market: BacktestMarket
  dateRange: string[]
  initialCash: string
  benchmark: string
  executionModelId: string
  parameterOverrides: string
  seed: number
  saveDailyPositions: boolean
  notes: string
}

const router = useRouter()
const formRef = ref<FormInstance>()
const strategies = ref<PublishedStrategyOption[]>([])
const loadingStrategies = ref(true)
const submitting = ref(false)
const parameterError = ref('')
const idempotencyKey = ref(createIdempotencyKey())

const form = reactive<CreateForm>({
  strategyVersionId: '',
  market: 'CN',
  dateRange: [],
  initialCash: '1000000',
  benchmark: '000300',
  executionModelId: 'next_open',
  parameterOverrides: '{}',
  seed: 0,
  saveDailyPositions: true,
  notes: ''
})

const rules: FormRules<CreateForm> = {
  strategyVersionId: [{ required: true, message: '请选择已发布策略', trigger: 'change' }],
  dateRange: [{ type: 'array', required: true, len: 2, message: '请选择完整回测区间', trigger: 'change' }],
  initialCash: [{
    validator: (_rule, value, callback) => Number(value) > 0
      ? callback()
      : callback(new Error('初始资金必须大于 0')),
    trigger: 'blur'
  }],
  benchmark: [{ required: true, message: '请输入基准代码', trigger: 'blur' }],
  executionModelId: [{ required: true, message: '请选择成交模型', trigger: 'change' }]
}

const selectedStrategy = computed(() => strategies.value.find(
  item => item.strategy_version_id === form.strategyVersionId
))
const currencyLabel = computed(() => ({ CN: 'CNY', HK: 'HKD', US: 'USD' })[form.market])
const executionLabel = computed(() => form.executionModelId === 'next_close' ? '下一交易日收盘' : '下一交易日开盘')

watch(form, () => { idempotencyKey.value = createIdempotencyKey() }, { deep: true })
onMounted(loadStrategies)

async function loadStrategies(): Promise<void> {
  loadingStrategies.value = true
  try {
    const [owned, templates] = await Promise.all([strategyApi.list(), strategyApi.listTemplates()])
    const published = owned.filter(item => item.latest_published_version_id)
    const details = await Promise.all(published.map(item => strategyApi.get(item.strategy_id)))
    const options = new Map<string, PublishedStrategyOption>()
    templates.forEach(item => options.set(item.strategy_version_id, {
      strategy_id: item.strategy_id,
      strategy_version_id: item.strategy_version_id,
      name: item.name,
      market: item.market,
      fee_model_version: feeModel(item.definition)
    }))
    details.forEach(detail => {
      const strategy = detail.strategy
      const version = detail.versions.find(item => item.strategy_version_id === strategy.latest_published_version_id)
      if (!version) return
      options.set(version.strategy_version_id, versionOption(strategy.strategy_id, strategy.name, version))
    })
    strategies.value = Array.from(options.values()).sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
  } finally {
    loadingStrategies.value = false
  }
}

function versionOption(strategyId: string, name: string, version: StrategyVersion): PublishedStrategyOption {
  return {
    strategy_id: strategyId,
    strategy_version_id: version.strategy_version_id,
    name,
    market: version.market,
    fee_model_version: feeModel(version.definition)
  }
}

function feeModel(definition: StrategyDefinition): string {
  const execution = definition.execution as Record<string, unknown>
  return String(execution.fee_model_version || execution.feeModelVersion || '随发布版本冻结')
}

function applyStrategy(): void {
  const selected = selectedStrategy.value
  if (!selected) return
  form.market = selected.market
  form.benchmark = ({ CN: '000300', HK: 'HSI', US: 'SPY' })[selected.market]
}

async function submit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  parameterError.value = ''
  let overrides: Record<string, unknown>
  try {
    const parsed = JSON.parse(form.parameterOverrides || '{}')
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error()
    overrides = parsed as Record<string, unknown>
  } catch {
    parameterError.value = '参数覆盖必须是一个有效的 JSON 对象'
    return
  }
  submitting.value = true
  try {
    const payload: BacktestRequest = {
      strategy_version_id: form.strategyVersionId,
      market: form.market,
      start_date: form.dateRange[0],
      end_date: form.dateRange[1],
      initial_cash: form.initialCash,
      benchmark: form.benchmark.trim(),
      execution_model_id: form.executionModelId,
      parameter_overrides: overrides,
      seed: form.seed,
      save_daily_positions: form.saveDailyPositions,
      notes: form.notes.trim()
    }
    const accepted = await backtestApi.create(payload, idempotencyKey.value)
    ElMessage.success(accepted.deduplicated ? '已打开相同的回测任务' : '回测任务已创建')
    await router.push(`/backtests/${accepted.run_id}`)
  } finally {
    submitting.value = false
  }
}

function createIdempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() || `backtest-${Date.now()}-${Math.random().toString(36).slice(2)}`
}
</script>

<style scoped lang="scss">
.create-page { padding: 24px; max-width: 1280px; margin: 0 auto; }
.page-header { margin-bottom: 22px; }
.page-header h1 { margin: 8px 0 8px; font-size: 28px; line-height: 1.25; text-wrap: balance; }
.page-header p { margin: 0; max-width: 70ch; color: var(--el-text-color-secondary); line-height: 1.65; }
.create-layout { display: grid; grid-template-columns: minmax(0, 1fr) 310px; gap: 24px; align-items: start; }
.form-surface { background: var(--el-bg-color); border-radius: 12px; border: 1px solid var(--el-border-color-light); }
.form-section { padding: 24px; border-bottom: 1px solid var(--el-border-color-lighter); }
.section-heading { display: flex; justify-content: space-between; align-items: baseline; gap: 16px; margin-bottom: 18px; }
.section-heading h2 { margin: 0; font-size: 18px; }
.section-heading span, .field-help { color: var(--el-text-color-secondary); font-size: 13px; }
.field-help { margin-top: 7px; line-height: 1.5; }
.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 20px; }
.full-width { width: 100%; }
.strategy-option { display: flex; flex-direction: column; line-height: 1.45; }
.strategy-option small { color: var(--el-text-color-secondary); }
.form-actions { display: flex; justify-content: flex-end; gap: 10px; padding: 18px 24px; }
.run-notes { position: sticky; top: 20px; padding: 20px; border-radius: 12px; background: var(--el-fill-color-light); }
.run-notes h2 { margin: 0 0 16px; font-size: 17px; }
.run-notes dl { margin: 0 0 20px; }
.run-notes dl div { display: grid; grid-template-columns: 70px minmax(0, 1fr); gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.run-notes dt { color: var(--el-text-color-secondary); }
.run-notes dd { margin: 0; word-break: break-word; }
@media (max-width: 900px) {
  .create-layout { grid-template-columns: 1fr; }
  .run-notes { position: static; order: -1; }
}
@media (max-width: 640px) {
  .create-page { padding: 16px; }
  .field-grid { grid-template-columns: 1fr; }
  .form-section { padding: 20px 16px; }
  .section-heading { align-items: flex-start; flex-direction: column; gap: 5px; }
  .form-actions { padding: 16px; }
}
</style>
