<template>
  <el-drawer
    :model-value="modelValue"
    :title="draft.rule_id ? '编辑预警规则' : '创建预警规则'"
    size="min(760px, 100%)"
    destroy-on-close
    class="alert-rule-drawer"
    @close="close"
  >
    <div class="wizard-shell">
      <nav class="wizard-steps" aria-label="规则创建进度">
        <button
          v-for="(label, index) in stepLabels"
          :key="label"
          type="button"
          :class="{ active: step === index, complete: step > index }"
          :aria-current="step === index ? 'step' : undefined"
          @click="goToCompletedStep(index)"
        >
          <span>{{ index + 1 }}</span>{{ label }}
        </button>
      </nav>

      <el-alert
        v-if="errorMessage"
        class="wizard-error"
        type="error"
        :title="errorMessage"
        :description="errorDetails"
        show-icon
        :closable="false"
      />

      <section v-show="step === 0" class="wizard-panel" aria-labelledby="wizard-target-title">
        <header>
          <h2 id="wizard-target-title">监控什么</h2>
          <p>先确定市场和监控对象。动态范围会在每次评估时按当前归属重新解析。</p>
        </header>

        <el-form label-position="top" class="wizard-form">
          <el-form-item label="规则名称" required>
            <el-input v-model="draft.name" maxlength="120" show-word-limit placeholder="例如：浦发银行突破 12 元" />
          </el-form-item>
          <div class="form-grid">
            <el-form-item label="市场" required>
              <el-segmented v-model="draft.market" :options="marketOptions" />
            </el-form-item>
            <el-form-item label="监控范围" required>
              <el-select v-model="scopeType" style="width: 100%">
                <el-option label="单只股票" value="symbol" />
                <el-option label="固定股票列表" value="watchlist" />
                <el-option label="策略股票池" value="strategy_universe" />
                <el-option label="模拟持仓" value="paper_position" />
                <el-option label="模拟账户" value="paper_account" />
              </el-select>
            </el-form-item>
          </div>
          <el-form-item v-if="scopeType === 'symbol'" label="股票代码" required>
            <el-input v-model.trim="scopeSymbol" placeholder="A 股 600000 / 港股 00700 / 美股 AAPL" />
          </el-form-item>
          <el-form-item v-else-if="scopeType === 'watchlist'" label="股票代码列表" required>
            <el-input
              v-model="scopeSymbolsText"
              type="textarea"
              :rows="3"
              placeholder="使用逗号或换行分隔，例如 600000, 000001"
            />
            <div class="field-help">保存时会去重并移除空值；最多 5000 只。</div>
          </el-form-item>
          <el-form-item
            v-else
            :label="scopeType === 'strategy_universe' ? '不可变策略版本 ID' : '模拟账户 ID'"
            required
          >
            <el-input v-model.trim="scopeReference" placeholder="输入精确版本或账户标识" />
          </el-form-item>
          <el-form-item label="说明">
            <el-input v-model="draft.description" type="textarea" :rows="2" maxlength="2000" show-word-limit />
          </el-form-item>
        </el-form>
      </section>

      <section v-show="step === 1" class="wizard-panel" aria-labelledby="wizard-condition-title">
        <header>
          <h2 id="wizard-condition-title">触发条件</h2>
          <p>条件由确定性规则计算。预警只负责通知，不会提交任何交易。</p>
        </header>

        <div class="type-grid" role="radiogroup" aria-label="预警类型">
          <button
            v-for="item in alertTypeOptions"
            :key="item.value"
            type="button"
            role="radio"
            :aria-checked="draft.alert_type === item.value"
            :class="{ selected: draft.alert_type === item.value }"
            @click="selectAlertType(item.value)"
          >
            <strong>{{ item.label }}</strong>
            <span>{{ item.description }}</span>
          </button>
        </div>

        <el-form label-position="top" class="wizard-form condition-form">
          <div v-if="draft.left_kind === 'factor'" class="form-grid three">
            <el-form-item label="因子 ID" required>
              <el-input v-model.trim="draft.factor_id" placeholder="例如 ret_20d" />
            </el-form-item>
            <el-form-item label="版本">
              <el-input-number v-model="draft.factor_version" :min="1" :max="9999" controls-position="right" />
            </el-form-item>
            <el-form-item label="滞后期">
              <el-input-number v-model="draft.factor_lag" :min="0" :max="252" controls-position="right" />
            </el-form-item>
          </div>
          <el-form-item v-if="draft.left_kind === 'change_rate'" label="变化窗口">
            <el-select v-model="draft.change_window_seconds">
              <el-option label="1 分钟" :value="60" />
              <el-option label="5 分钟" :value="300" />
              <el-option label="15 分钟" :value="900" />
              <el-option label="1 小时" :value="3600" />
              <el-option label="1 个交易日" :value="86400" />
            </el-select>
          </el-form-item>
          <div class="form-grid">
            <el-form-item label="阈值" required>
              <el-input v-model.trim="draft.threshold" inputmode="decimal" placeholder="输入有限数值" />
            </el-form-item>
            <el-form-item v-if="draft.operator === 'between'" label="区间上限" required>
              <el-input v-model.trim="draft.upper_threshold" inputmode="decimal" placeholder="必须不低于阈值" />
            </el-form-item>
          </div>
          <div class="condition-summary" aria-live="polite">
            <el-icon><Aim /></el-icon>
            <span>{{ conditionSummary }}</span>
          </div>
        </el-form>
      </section>

      <section v-show="step === 2" class="wizard-panel" aria-labelledby="wizard-timing-title">
        <header>
          <h2 id="wizard-timing-title">持续时间与冷却</h2>
          <p>用持续条件过滤瞬时噪声，用冷却时间限制重复提醒。</p>
        </header>

        <el-form label-position="top" class="wizard-form">
          <div class="form-grid">
            <el-form-item label="评估模式">
              <el-select v-model="draft.evaluation_mode">
                <el-option label="边沿触发 — 仅状态变化时" value="edge" />
                <el-option label="持续触发 — 条件成立即触发" value="level" />
                <el-option label="一次触发 — 首次触发后停用" value="once" />
              </el-select>
            </el-form-item>
            <el-form-item label="评估频率">
              <el-select v-model="draft.frequency_seconds">
                <el-option label="每 30 秒" :value="30" />
                <el-option label="每 1 分钟" :value="60" />
                <el-option label="每 5 分钟" :value="300" />
                <el-option label="每 15 分钟" :value="900" />
                <el-option label="每小时" :value="3600" />
              </el-select>
            </el-form-item>
          </div>
          <div class="duration-row">
            <el-form-item label="条件持续">
              <el-radio-group v-model="draft.duration_mode">
                <el-radio-button label="none">无需持续</el-radio-button>
                <el-radio-button label="seconds">持续秒数</el-radio-button>
                <el-radio-button label="evaluations">连续次数</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-if="draft.duration_mode !== 'none'" label="持续值">
              <el-input-number v-model="draft.duration_value" :min="1" :max="10000" controls-position="right" />
            </el-form-item>
          </div>
          <div class="form-grid">
            <el-form-item label="有效时段">
              <el-select v-model="draft.schedule_type">
                <el-option label="市场交易时段" value="market_hours" />
                <el-option label="全天" value="all_day" />
              </el-select>
            </el-form-item>
            <el-form-item label="冷却时间">
              <el-select v-model="draft.cooldown_seconds">
                <el-option label="不冷却" :value="0" />
                <el-option label="5 分钟" :value="300" />
                <el-option label="15 分钟" :value="900" />
                <el-option label="1 小时" :value="3600" />
                <el-option label="1 天" :value="86400" />
              </el-select>
            </el-form-item>
          </div>
        </el-form>
      </section>

      <section v-show="step === 3" class="wizard-panel" aria-labelledby="wizard-delivery-title">
        <header>
          <h2 id="wizard-delivery-title">通知与预览</h2>
          <p>确认严重性、通知渠道和每日上限，再用当前快照验证条件。</p>
        </header>

        <el-form label-position="top" class="wizard-form">
          <div class="form-grid">
            <el-form-item label="严重性">
              <el-radio-group v-model="draft.severity">
                <el-radio-button label="info">提示</el-radio-button>
                <el-radio-button label="warning">警告</el-radio-button>
                <el-radio-button label="critical">严重</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="每日事件上限">
              <el-input-number v-model="draft.max_events_per_day" :min="1" :max="1000" controls-position="right" />
            </el-form-item>
          </div>
          <el-form-item label="通知渠道">
            <el-checkbox-group v-model="draft.channels">
              <el-checkbox label="in_app">消息中心与历史记录</el-checkbox>
              <el-checkbox label="websocket">页面实时推送</el-checkbox>
            </el-checkbox-group>
          </el-form-item>
          <el-form-item>
            <el-checkbox v-model="draft.recovery_enabled">条件恢复时生成恢复事件</el-checkbox>
          </el-form-item>

          <div class="preview-bar">
            <div>
              <strong>当前快照预览</strong>
              <span>不会写入规则状态，也不会发送通知</span>
            </div>
            <el-button :loading="previewing" @click="previewRule">
              <el-icon><View /></el-icon>运行预览
            </el-button>
          </div>

          <div v-if="preview" class="preview-results">
            <div v-if="preview.results.length === 0" class="preview-empty">当前范围没有可评估对象</div>
            <div v-for="item in preview.results" :key="item.symbol || 'scope'" class="preview-item">
              <div>
                <strong>{{ item.symbol || '账户范围' }}</strong>
                <span>{{ item.source }}</span>
              </div>
              <el-tag :type="stateTagType(item.condition_state)" effect="plain">
                {{ stateLabel(item.condition_state) }}
              </el-tag>
              <div class="preview-value">{{ item.value ?? '—' }}</div>
              <div class="preview-time">{{ formatDateTime(item.quote_time) }}</div>
            </div>
          </div>
        </el-form>
      </section>
    </div>

    <template #footer>
      <div class="wizard-footer">
        <el-button v-if="step > 0" @click="step--">上一步</el-button>
        <span class="footer-spacer"></span>
        <el-button @click="close">取消</el-button>
        <el-button v-if="step < stepLabels.length - 1" type="primary" @click="nextStep">下一步</el-button>
        <el-button v-else type="primary" :loading="saving" @click="saveRule">
          {{ draft.rule_id ? '保存规则' : '创建规则' }}
        </el-button>
      </div>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Aim, View } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { alertsApi } from '@/api/alerts'
import type {
  AlertConditionState,
  AlertPreviewResult,
  AlertRule,
  AlertRuleDraft,
  AlertScope,
  AlertType
} from '@/types/alert'
import {
  alertTypeOptions,
  draftFromRule,
  emptyRuleDraft,
  formatDateTime,
  payloadForDraft
} from './alertUi'

const props = defineProps<{
  modelValue: boolean
  rule?: AlertRule | null
  prefill?: { market?: string; symbol?: string }
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [rule: AlertRule]
}>()

const stepLabels = ['对象', '条件', '节奏', '通知']
const marketOptions = [
  { label: 'A 股', value: 'CN' },
  { label: '港股', value: 'HK' },
  { label: '美股', value: 'US' }
]

const step = ref(0)
const draft = ref<AlertRuleDraft>(emptyRuleDraft())
const saving = ref(false)
const previewing = ref(false)
const preview = ref<AlertPreviewResult | null>(null)
const errorMessage = ref('')
const errorDetails = ref('')

watch(
  () => props.modelValue,
  value => {
    if (!value) return
    draft.value = props.rule ? draftFromRule(props.rule) : emptyRuleDraft(props.prefill)
    step.value = 0
    preview.value = null
    clearError()
  },
  { immediate: true }
)

const scopeType = computed({
  get: () => draft.value.scope.scope_type,
  set: (value: AlertScope['scope_type']) => {
    if (value === 'symbol') draft.value.scope = { scope_type: 'symbol', symbol: '' }
    if (value === 'watchlist') draft.value.scope = { scope_type: 'watchlist', symbols: [] }
    if (value === 'strategy_universe') draft.value.scope = { scope_type: 'strategy_universe', strategy_version_id: '' }
    if (value === 'paper_position') draft.value.scope = { scope_type: 'paper_position', account_id: '' }
    if (value === 'paper_account') draft.value.scope = { scope_type: 'paper_account', account_id: '' }
  }
})

const scopeSymbol = computed({
  get: () => draft.value.scope.scope_type === 'symbol' ? draft.value.scope.symbol : '',
  set: (value: string) => { draft.value.scope = { scope_type: 'symbol', symbol: value.toUpperCase() } }
})

const scopeSymbolsText = computed({
  get: () => draft.value.scope.scope_type === 'watchlist' ? draft.value.scope.symbols.join(', ') : '',
  set: (value: string) => {
    const symbols = [...new Set(value.split(/[\s,，]+/).map(item => item.trim().toUpperCase()).filter(Boolean))]
    draft.value.scope = { scope_type: 'watchlist', symbols }
  }
})

const scopeReference = computed({
  get: () => {
    const scope = draft.value.scope
    if (scope.scope_type === 'strategy_universe') return scope.strategy_version_id
    if (scope.scope_type === 'paper_position' || scope.scope_type === 'paper_account') return scope.account_id
    return ''
  },
  set: (value: string) => {
    if (scopeType.value === 'strategy_universe') {
      draft.value.scope = { scope_type: 'strategy_universe', strategy_version_id: value }
    } else if (scopeType.value === 'paper_position') {
      draft.value.scope = { scope_type: 'paper_position', account_id: value }
    } else if (scopeType.value === 'paper_account') {
      draft.value.scope = { scope_type: 'paper_account', account_id: value }
    }
  }
})

const conditionSummary = computed(() => {
  const target = draft.value.left_kind === 'factor'
    ? `${draft.value.factor_id}@${draft.value.factor_version}`
    : draft.value.left_kind === 'change_rate'
      ? `${Math.round(draft.value.change_window_seconds / 60)} 分钟变化率`
      : '最新价格'
  const operation: Record<string, string> = {
    gt: '高于', gte: '不低于', lt: '低于', lte: '不高于', eq: '等于', neq: '不等于',
    between: '位于', cross_up: '向上穿越', cross_down: '向下穿越'
  }
  const range = draft.value.operator === 'between'
    ? `${draft.value.threshold} 至 ${draft.value.upper_threshold}`
    : draft.value.threshold || '待输入阈值'
  return `${target} ${operation[draft.value.operator]} ${range}`
})

function selectAlertType(value: AlertType) {
  const option = alertTypeOptions.find(item => item.value === value)
  if (!option) return
  draft.value.alert_type = value
  draft.value.left_kind = option.leftKind
  draft.value.operator = option.operator
}

function clearError() {
  errorMessage.value = ''
  errorDetails.value = ''
}

function validateStep(index: number): boolean {
  clearError()
  if (index === 0) {
    if (!draft.value.name.trim()) return showLocalError('请填写规则名称')
    const scope = draft.value.scope
    if (scope.scope_type === 'symbol' && !scope.symbol) return showLocalError('请填写股票代码')
    if (scope.scope_type === 'watchlist' && scope.symbols.length === 0) return showLocalError('请至少填写一个股票代码')
    if (scope.scope_type === 'strategy_universe' && !scope.strategy_version_id) return showLocalError('请填写策略版本 ID')
    if ((scope.scope_type === 'paper_position' || scope.scope_type === 'paper_account') && !scope.account_id) {
      return showLocalError('请填写模拟账户 ID')
    }
  }
  if (index === 1) {
    if (!draft.value.threshold || !Number.isFinite(Number(draft.value.threshold))) return showLocalError('请输入有效阈值')
    if (draft.value.operator === 'between') {
      if (!draft.value.upper_threshold || !Number.isFinite(Number(draft.value.upper_threshold))) return showLocalError('请输入有效区间上限')
      if (Number(draft.value.upper_threshold) < Number(draft.value.threshold)) return showLocalError('区间上限不能低于下限')
    }
    if (draft.value.left_kind === 'factor' && !draft.value.factor_id) return showLocalError('请填写因子 ID')
  }
  if (index === 3 && draft.value.channels.length === 0) return showLocalError('请至少选择一个通知渠道')
  return true
}

function showLocalError(message: string): false {
  errorMessage.value = message
  errorDetails.value = '补充后即可继续。'
  return false
}

function nextStep() {
  if (validateStep(step.value)) step.value += 1
}

function goToCompletedStep(index: number) {
  if (index <= step.value) step.value = index
}

async function previewRule() {
  if (![0, 1, 2, 3].every(validateStep)) return
  previewing.value = true
  clearError()
  try {
    preview.value = await alertsApi.preview(payloadForDraft(draft.value))
  } catch (error) {
    handleApiError(error, '预览失败，请检查规则依赖和当前数据。')
  } finally {
    previewing.value = false
  }
}

async function saveRule() {
  if (![0, 1, 2, 3].every(validateStep)) return
  saving.value = true
  clearError()
  const payload = payloadForDraft(draft.value)
  try {
    const validation = await alertsApi.validate(payload)
    if (!validation.valid) {
      errorMessage.value = '规则校验未通过'
      errorDetails.value = validation.errors.map(item => item.message).join('；')
      return
    }
    const saved = draft.value.rule_id && draft.value.version
      ? await alertsApi.updateRule(draft.value.rule_id, draft.value.version, payload)
      : await alertsApi.createRule(payload)
    ElMessage.success(draft.value.rule_id ? '规则已更新' : '规则已创建')
    emit('saved', saved)
    close()
  } catch (error) {
    handleApiError(error, '规则保存失败，请稍后重试。')
  } finally {
    saving.value = false
  }
}

function handleApiError(error: unknown, fallback: string) {
  const response = (error as any)?.response?.data?.detail
  errorMessage.value = response?.message || fallback
  const details = response?.details
  errorDetails.value = Array.isArray(details)
    ? details.map(item => item.message || item.code).join('；')
    : response?.code || ''
}

function close() {
  emit('update:modelValue', false)
}

function stateLabel(state: AlertConditionState) {
  return { true: '条件成立', false: '条件未成立', unknown: '数据不足' }[state]
}

function stateTagType(state: AlertConditionState) {
  return state === 'true' ? 'success' : state === 'false' ? 'info' : 'warning'
}
</script>

<style scoped lang="scss">
.wizard-shell { max-width: 680px; margin: 0 auto; }

.wizard-steps {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin-bottom: 28px;

  button {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    min-height: 42px;
    border: 0;
    border-radius: 10px;
    color: var(--el-text-color-secondary);
    background: var(--el-fill-color-light);
    cursor: default;
  }
  button.complete { color: var(--el-color-primary); cursor: pointer; }
  button.active { color: #fff; background: #1d5f96; box-shadow: 0 7px 16px rgba(29, 95, 150, 0.22); }
  span { font-variant-numeric: tabular-nums; font-weight: 700; }
}

.wizard-error { margin-bottom: 20px; }
.wizard-panel > header { margin: 0 0 24px; }
.wizard-panel h2 { margin: 0 0 8px; font-size: 24px; letter-spacing: -0.02em; }
.wizard-panel header p { margin: 0; max-width: 68ch; color: var(--el-text-color-secondary); line-height: 1.65; }
.wizard-form { margin-top: 18px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.form-grid.three { grid-template-columns: 2fr 1fr 1fr; }
.field-help { margin-top: 6px; color: var(--el-text-color-secondary); font-size: 12px; }

.type-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;

  button {
    min-height: 86px;
    padding: 14px;
    text-align: left;
    border: 1px solid var(--el-border-color);
    border-radius: 12px;
    background: var(--el-bg-color);
    color: var(--el-text-color-primary);
    cursor: pointer;
    transition: border-color 160ms ease-out, background 160ms ease-out, box-shadow 160ms ease-out;
  }
  button:hover { border-color: var(--el-color-primary-light-5); }
  button.selected { border-color: #1d5f96; background: rgba(29, 95, 150, 0.07); box-shadow: 0 5px 14px rgba(29, 95, 150, 0.1); }
  strong, span { display: block; }
  strong { margin-bottom: 5px; font-size: 14px; }
  span { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.5; }
}

.condition-form { margin-top: 22px; }
.condition-summary {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 48px;
  padding: 0 14px;
  border-radius: 12px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
}
.duration-row { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; }

.preview-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 16px 0;
  border-top: 1px solid var(--el-border-color-lighter);
  border-bottom: 1px solid var(--el-border-color-lighter);
  strong, span { display: block; }
  span { margin-top: 4px; color: var(--el-text-color-secondary); font-size: 12px; }
}
.preview-results { margin-top: 12px; max-height: 240px; overflow: auto; }
.preview-item {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) auto 90px 160px;
  align-items: center;
  gap: 12px;
  padding: 11px 4px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  font-variant-numeric: tabular-nums;
  strong, span { display: block; }
  span { color: var(--el-text-color-secondary); font-size: 11px; }
}
.preview-value, .preview-time { text-align: right; font-size: 13px; }
.preview-time { color: var(--el-text-color-secondary); }
.preview-empty { padding: 20px 0; color: var(--el-text-color-secondary); text-align: center; }

.wizard-footer { display: flex; align-items: center; width: 100%; }
.footer-spacer { flex: 1; }

@media (max-width: 720px) {
  .wizard-steps button { font-size: 0; gap: 0; }
  .wizard-steps button span { font-size: 13px; }
  .type-grid { grid-template-columns: repeat(2, 1fr); }
  .form-grid, .form-grid.three, .duration-row { grid-template-columns: 1fr; gap: 0; }
  .preview-item { grid-template-columns: 1fr auto; }
  .preview-value, .preview-time { text-align: left; }
}

@media (prefers-reduced-motion: reduce) {
  .type-grid button { transition: none; }
}
</style>
