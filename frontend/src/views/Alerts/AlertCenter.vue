<template>
  <div class="alert-center" data-design-seed="alert-ops-console-j44">
    <!--
      THESIS: Put evidence and control in one monitoring console, not a dashboard of disconnected metric cards.
      OWN-WORLD: Inherit Element Plus with an ink-blue operations strip, quiet dividers, compact status dots, and tabular evidence.
      STORY: Confirm system health, manage deterministic rules, then inspect and acknowledge their events.
      FIRST VIEWPORT: Title and primary action lead into a full-width health strip; rules and live events share the workspace below.
      FORM: Established-world operations console, alert-ops-console-j44.
      FINISH: reviewed against the incumbent responsive, accessibility, and operations-console conventions; no raster assets ship in this task.
    -->
    <header class="page-heading">
      <div>
        <h1>预警中心</h1>
        <p>用确定性条件持续监控行情、因子和模拟账户；AI 不参与阈值计算。</p>
      </div>
      <el-button type="primary" size="large" @click="openCreateWizard()">
        <el-icon><Plus /></el-icon>创建预警规则
      </el-button>
    </header>

    <AlertHealthOverview :health="health" :loading="healthLoading" @refresh="loadHealth" />

    <div class="workspace-tabs" role="tablist" aria-label="预警中心视图">
      <button
        type="button"
        role="tab"
        :aria-selected="activeTab === 'rules'"
        :class="{ active: activeTab === 'rules' }"
        @click="switchTab('rules')"
      >
        规则
        <span>{{ rules.length }}</span>
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="activeTab === 'events'"
        :class="{ active: activeTab === 'events' }"
        @click="switchTab('events')"
      >
        事件
        <span>{{ recentEvents.length }}</span>
      </button>
    </div>

    <main class="alert-workspace">
      <AlertRuleList
        v-show="activeTab === 'rules'"
        :rules="rules"
        :events="recentEvents"
        :loading="rulesLoading"
        :pending-ids="pendingIds"
        @refresh="loadRules"
        @create="openCreateWizard()"
        @edit="openEditWizard"
        @toggle="toggleRule"
        @test="sendTestNotification"
        @delete="deleteRule"
        @events="showRuleEvents"
      />
      <AlertEventCenter
        v-show="activeTab === 'events'"
        ref="eventCenter"
        :rules="rules"
        @recent="events => recentEvents = events"
      />
    </main>

    <AlertRuleWizard
      v-model="wizardVisible"
      :rule="editingRule"
      :prefill="wizardPrefill"
      @saved="handleRuleSaved"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { alertsApi } from '@/api/alerts'
import type { AlertEvent, AlertHealth, AlertRule } from '@/types/alert'
import AlertEventCenter from './AlertEventCenter.vue'
import AlertHealthOverview from './AlertHealthOverview.vue'
import AlertRuleList from './AlertRuleList.vue'
import AlertRuleWizard from './AlertRuleWizard.vue'

const route = useRoute()
const router = useRouter()
const activeTab = ref<'rules' | 'events'>('rules')
const health = ref<AlertHealth | null>(null)
const healthLoading = ref(false)
const rules = ref<AlertRule[]>([])
const rulesLoading = ref(false)
const recentEvents = ref<AlertEvent[]>([])
const pendingIds = ref(new Set<string>())
const wizardVisible = ref(false)
const editingRule = ref<AlertRule | null>(null)
const wizardPrefill = ref<{ market?: string; symbol?: string }>({})
const eventCenter = ref<InstanceType<typeof AlertEventCenter> | null>(null)
let healthTimer: ReturnType<typeof setInterval> | null = null

watch(
  () => route.query.tab,
  tab => { activeTab.value = tab === 'events' ? 'events' : 'rules' },
  { immediate: true }
)

watch(
  () => route.query.create,
  create => {
    if (create === '1') {
      openCreateWizard({
        market: String(route.query.market || ''),
        symbol: String(route.query.symbol || '')
      })
      const query = { ...route.query }
      delete query.create
      router.replace({ query })
    }
  },
  { immediate: true }
)

onMounted(() => {
  Promise.all([loadHealth(), loadRules()])
  healthTimer = setInterval(loadHealth, 30000)
})

onUnmounted(() => {
  if (healthTimer) clearInterval(healthTimer)
})

async function loadHealth() {
  healthLoading.value = true
  try {
    health.value = await alertsApi.health()
  } catch (error) {
    ElMessage.error(apiMessage(error, '监控状态加载失败，请稍后刷新'))
  } finally {
    healthLoading.value = false
  }
}

async function loadRules() {
  rulesLoading.value = true
  try {
    const result = await alertsApi.listRules({ page: 1, page_size: 100 })
    rules.value = result.items
  } catch (error) {
    ElMessage.error(apiMessage(error, '规则加载失败，请稍后刷新'))
  } finally {
    rulesLoading.value = false
  }
}

function switchTab(tab: 'rules' | 'events') {
  activeTab.value = tab
  router.replace({ query: { ...route.query, tab } })
}

function openCreateWizard(prefill: { market?: string; symbol?: string } = {}) {
  editingRule.value = null
  wizardPrefill.value = prefill
  wizardVisible.value = true
}

function openEditWizard(rule: AlertRule) {
  editingRule.value = rule
  wizardPrefill.value = {}
  wizardVisible.value = true
}

async function toggleRule(rule: AlertRule) {
  setPending(rule.rule_id, true)
  try {
    const updated = rule.enabled
      ? await alertsApi.disableRule(rule.rule_id, rule.version)
      : await alertsApi.enableRule(rule.rule_id, rule.version)
    replaceRule(updated)
    ElMessage.success(updated.enabled ? '规则已启用' : '规则已停用')
    await loadHealth()
  } catch (error) {
    const code = (error as any)?.response?.data?.detail?.code
    const recovery = code === 'ALERT_RULE_VERSION_CONFLICT' ? '规则已被其他操作更新，请刷新后重试。' : '请检查依赖或稍后重试。'
    ElMessage.error(`${apiMessage(error, '状态更新失败')} ${recovery}`)
    await loadRules()
  } finally {
    setPending(rule.rule_id, false)
  }
}

async function sendTestNotification(rule: AlertRule) {
  setPending(rule.rule_id, true)
  try {
    const result = await alertsApi.testNotification(rule.rule_id)
    if (result.is_test) ElMessage.success('测试通知已发送，并已明确标记为测试')
  } catch (error) {
    ElMessage.error(apiMessage(error, '测试通知发送失败'))
  } finally {
    setPending(rule.rule_id, false)
  }
}

async function deleteRule(rule: AlertRule) {
  try {
    await ElMessageBox.confirm(
      `删除“${rule.name}”后将停止监控，但历史事件会继续保留。`,
      '删除预警规则',
      { confirmButtonText: '删除规则', cancelButtonText: '取消', type: 'warning' }
    )
    setPending(rule.rule_id, true)
    await alertsApi.deleteRule(rule.rule_id, rule.version)
    rules.value = rules.value.filter(item => item.rule_id !== rule.rule_id)
    ElMessage.success('规则已删除，历史事件已保留')
    await loadHealth()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(apiMessage(error, '规则删除失败'))
  } finally {
    setPending(rule.rule_id, false)
  }
}

function showRuleEvents(rule: AlertRule) {
  switchTab('events')
  eventCenter.value?.focusRule(rule.rule_id)
}

function handleRuleSaved(rule: AlertRule) {
  replaceRule(rule)
  loadHealth()
  eventCenter.value?.refresh()
}

function replaceRule(rule: AlertRule) {
  const index = rules.value.findIndex(item => item.rule_id === rule.rule_id)
  if (index >= 0) rules.value.splice(index, 1, rule)
  else rules.value.unshift(rule)
}

function setPending(ruleId: string, value: boolean) {
  const next = new Set(pendingIds.value)
  if (value) next.add(ruleId)
  else next.delete(ruleId)
  pendingIds.value = next
}

function apiMessage(error: unknown, fallback: string) {
  return (error as any)?.response?.data?.detail?.message || fallback
}
</script>

<style scoped lang="scss">
.alert-center {
  --alert-ink: #132238;
  --alert-blue: #1d5f96;
  max-width: 1480px;
  margin: 0 auto;
  color: var(--el-text-color-primary);
}
.alert-center :deep(*:focus-visible) { outline: 2px solid var(--alert-blue); outline-offset: 2px; }
.alert-center ::selection { color: #fff; background: var(--alert-blue); }

.page-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin: 0 0 22px;
  h1 { margin: 0 0 8px; font-size: clamp(28px, 3vw, 40px); letter-spacing: -0.03em; }
  p { margin: 0; max-width: 68ch; color: var(--el-text-color-secondary); line-height: 1.6; }
}

.workspace-tabs {
  display: flex;
  gap: 28px;
  margin-top: 28px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  button {
    position: relative;
    display: flex;
    align-items: center;
    gap: 7px;
    min-height: 46px;
    padding: 0 2px;
    border: 0;
    background: transparent;
    color: var(--el-text-color-secondary);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }
  button::after { content: ''; position: absolute; right: 0; bottom: -1px; left: 0; height: 2px; background: transparent; }
  button.active { color: var(--alert-blue); }
  button.active::after { background: var(--alert-blue); }
  span { min-width: 22px; padding: 2px 6px; border-radius: 999px; background: var(--el-fill-color); font-size: 11px; font-variant-numeric: tabular-nums; }
}

.alert-workspace {
  min-height: 360px;
  padding: 24px 0 12px;
}

@media (max-width: 760px) {
  .page-heading { align-items: stretch; flex-direction: column; }
  .page-heading .el-button { width: 100%; }
  .workspace-tabs { margin-top: 22px; }
  .alert-workspace { padding-top: 20px; }
}
</style>
