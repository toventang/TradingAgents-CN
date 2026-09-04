<template>
  <section class="event-section" aria-labelledby="alert-events-title">
    <div class="section-toolbar">
      <div>
        <div class="event-heading-line">
          <h2 id="alert-events-title">实时事件</h2>
          <span class="live-state" :class="{ connected: notificationStore.connected }">
            <i aria-hidden="true"></i>{{ notificationStore.connected ? '实时连接' : '定时同步' }}
          </span>
        </div>
        <p>结构化事件保留行情时间、评估时间、延迟与质量证据。</p>
      </div>
      <el-button :loading="loading" aria-label="刷新预警事件" @click="loadEvents(false)">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
    </div>

    <div class="event-filters">
      <el-input v-model.trim="filters.symbol" clearable placeholder="股票代码" aria-label="按股票代码筛选" @keyup.enter="applyFilters">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="filters.severity" clearable placeholder="严重性" aria-label="按严重性筛选">
        <el-option label="提示" value="info" />
        <el-option label="警告" value="warning" />
        <el-option label="严重" value="critical" />
      </el-select>
      <el-select v-model="qualityFilter" clearable placeholder="数据质量" aria-label="按数据质量筛选">
        <el-option v-for="(label, value) in qualityLabel" :key="value" :label="label" :value="value" />
      </el-select>
      <el-date-picker
        v-model="dateRange"
        type="datetimerange"
        start-placeholder="开始时间"
        end-placeholder="结束时间"
        range-separator="至"
        value-format="YYYY-MM-DDTHH:mm:ssZ"
        aria-label="按事件时间筛选"
      />
      <el-button type="primary" plain @click="applyFilters">应用筛选</el-button>
      <el-button text @click="clearFilters">清空</el-button>
    </div>

    <div v-loading="loading" class="event-stream" aria-live="polite">
      <el-empty v-if="!loading && visibleEvents.length === 0" description="当前筛选条件下暂无事件" />

      <article
        v-for="event in visibleEvents"
        :key="event.event_id"
        class="event-row"
        :class="[`severity-${event.severity}`, { acknowledged: event.acknowledged_at }]"
      >
        <div class="severity-mark" aria-hidden="true"></div>
        <div class="event-identity">
          <div class="event-title-line">
            <button type="button" class="event-target" @click="navigate(event)">{{ eventTarget(event) }}</button>
            <el-tag :type="severityTag(event.severity)" size="small" :effect="event.severity === 'critical' ? 'dark' : 'plain'">
              {{ severityLabel[event.severity] }}
            </el-tag>
            <el-tag v-if="event.kind === 'recovered'" size="small" type="success" effect="plain">已恢复</el-tag>
          </div>
          <p>{{ eventSummary(event) }}</p>
          <div class="event-evidence">
            <span>来源 {{ event.source }}</span>
            <span>规则 v{{ event.rule_version }}</span>
            <span>指纹 {{ event.fingerprint.slice(0, 10) }}</span>
          </div>
        </div>
        <div class="event-measure">
          <span>观测值</span>
          <strong>{{ event.current_value ?? '—' }}</strong>
          <small v-if="event.previous_value !== null">前值 {{ event.previous_value }}</small>
        </div>
        <div class="event-measure quality">
          <span>数据质量</span>
          <strong :class="`quality-${event.quality_status}`">{{ qualityLabel[event.quality_status] }}</strong>
          <small>{{ formatLatency(event.latency_seconds) }}</small>
        </div>
        <div class="event-times">
          <div><span>行情</span><time :datetime="event.quote_time">{{ formatDateTime(event.quote_time) }}</time></div>
          <div><span>评估</span><time :datetime="event.evaluated_at">{{ formatDateTime(event.evaluated_at) }}</time></div>
        </div>
        <div class="event-action">
          <el-button
            v-if="event.severity === 'critical' && !event.acknowledged_at"
            type="danger"
            plain
            size="small"
            :loading="acknowledging.has(event.event_id)"
            @click="acknowledge(event)"
          >
            确认
          </el-button>
          <span v-else-if="event.acknowledged_at" class="acknowledged-label">
            <el-icon><CircleCheck /></el-icon>已确认
          </span>
          <el-button v-else text size="small" @click="navigate(event)">查看</el-button>
        </div>
      </article>
    </div>

    <div v-if="total > pageSize" class="event-pagination">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="prev, pager, next, total"
        @current-change="loadEvents(false)"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { CircleCheck, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElNotification } from 'element-plus'
import { alertsApi } from '@/api/alerts'
import { useNotificationStore } from '@/stores/notifications'
import type { AlertEvent, AlertQualityStatus, AlertRule, AlertSeverity } from '@/types/alert'
import {
  eventTarget,
  formatDateTime,
  formatLatency,
  qualityLabel,
  severityLabel
} from './alertUi'

const props = defineProps<{ rules: AlertRule[] }>()
const emit = defineEmits<{ recent: [events: AlertEvent[]] }>()
const router = useRouter()
const notificationStore = useNotificationStore()
const { items: notifications } = storeToRefs(notificationStore)

const loading = ref(false)
const events = ref<AlertEvent[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 30
const qualityFilter = ref<AlertQualityStatus | ''>('')
const dateRange = ref<[string, string] | null>(null)
const filters = reactive<{
  rule_id: string
  symbol: string
  severity: AlertSeverity | ''
}>({ rule_id: '', symbol: '', severity: '' })
const acknowledging = ref(new Set<string>())
const initialized = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

const visibleEvents = computed(() => qualityFilter.value
  ? events.value.filter(event => event.quality_status === qualityFilter.value)
  : events.value)

watch(
  () => notifications.value[0]?.id,
  (current, previous) => {
    const newest = notifications.value[0]
    if (current && current !== previous && newest?.type === 'alert') loadEvents(true)
  }
)

watch(() => filters.severity, applyFilters)

onMounted(() => {
  if (!notificationStore.connected) notificationStore.connect()
  loadEvents(false)
  pollTimer = setInterval(() => loadEvents(true), 15000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

async function loadEvents(silent: boolean) {
  if (!silent) loading.value = true
  try {
    const result = await alertsApi.listEvents({
      rule_id: filters.rule_id || undefined,
      symbol: filters.symbol || undefined,
      severity: filters.severity || undefined,
      start_at: dateRange.value?.[0],
      end_at: dateRange.value?.[1],
      page: page.value,
      page_size: pageSize
    })
    events.value = result.items
    total.value = result.total
    if (!filters.rule_id && !filters.symbol && !filters.severity && !dateRange.value) {
      emit('recent', result.items)
    }
    presentNewCriticalEvents(result.items)
  } catch (error) {
    if (!silent) ElMessage.error(errorMessage(error, '事件加载失败，请稍后重试'))
  } finally {
    if (!silent) loading.value = false
  }
}

function presentNewCriticalEvents(incoming: AlertEvent[]) {
  const storageKey = 'alerts-critical-fingerprints-v1'
  let storedFingerprints: string[] = []
  try {
    const parsed = JSON.parse(sessionStorage.getItem(storageKey) || '[]')
    storedFingerprints = Array.isArray(parsed)
      ? parsed.filter((fingerprint): fingerprint is string => typeof fingerprint === 'string')
      : []
  } catch {
    sessionStorage.removeItem(storageKey)
  }
  const remembered = new Set<string>(storedFingerprints)
  const critical = incoming.filter(event => event.severity === 'critical' && !event.acknowledged_at)
  if (initialized.value) {
    for (const event of [...critical].reverse()) {
      if (remembered.has(event.fingerprint)) continue
      ElNotification({
        title: `严重预警 · ${eventTarget(event)}`,
        message: eventSummary(event),
        type: 'error',
        duration: 8000,
        showClose: true,
        position: 'bottom-right',
        onClick: () => navigate(event)
      })
    }
  }
  for (const event of critical) remembered.add(event.fingerprint)
  sessionStorage.setItem(storageKey, JSON.stringify([...remembered].slice(-200)))
  initialized.value = true
}

function applyFilters() {
  page.value = 1
  loadEvents(false)
}

function clearFilters() {
  filters.rule_id = ''
  filters.symbol = ''
  filters.severity = ''
  qualityFilter.value = ''
  dateRange.value = null
  page.value = 1
  loadEvents(false)
}

async function acknowledge(event: AlertEvent) {
  acknowledging.value = new Set(acknowledging.value).add(event.event_id)
  try {
    const updated = await alertsApi.acknowledgeEvent(event.event_id)
    const index = events.value.findIndex(item => item.event_id === event.event_id)
    if (index >= 0) events.value[index] = updated
    ElMessage.success('严重预警已确认，事件记录已更新')
  } catch (error) {
    ElMessage.error(errorMessage(error, '确认失败，请重试'))
  } finally {
    const next = new Set(acknowledging.value)
    next.delete(event.event_id)
    acknowledging.value = next
  }
}

function navigate(event: AlertEvent) {
  const rule = props.rules.find(item => item.rule_id === event.rule_id)
  if (rule?.scope.scope_type === 'strategy_universe') {
    router.push({ path: '/strategies', query: { version_id: rule.scope.strategy_version_id, alert_event_id: event.event_id } })
  } else if (rule?.scope.scope_type === 'paper_position' || rule?.scope.scope_type === 'paper_account') {
    router.push({ path: '/paper', query: { account_id: rule.scope.account_id, alert_event_id: event.event_id } })
  } else if (event.symbol) {
    router.push({ name: 'StockDetail', params: { code: event.symbol }, query: { alert_event_id: event.event_id } })
  } else if (event.scope_key.startsWith('paper_')) {
    router.push({ path: '/paper', query: { alert_event_id: event.event_id } })
  }
}

function focusRule(ruleId: string) {
  filters.rule_id = ruleId
  page.value = 1
  loadEvents(false)
}

function severityTag(severity: AlertSeverity) {
  return severity === 'critical' ? 'danger' : severity === 'warning' ? 'warning' : 'info'
}

function eventSummary(event: AlertEvent) {
  const kind = event.kind === 'recovered' ? '条件已恢复' : event.kind === 'rule_health' ? '规则健康状态变化' : '条件已触发'
  return `${kind}，当前值 ${event.current_value ?? '不可用'}，状态 ${event.condition_state === 'unknown' ? '数据不足' : event.condition_state === 'true' ? '成立' : '不成立'}`
}

function errorMessage(error: unknown, fallback: string) {
  return (error as any)?.response?.data?.detail?.message || fallback
}

defineExpose({ refresh: () => loadEvents(true), focusRule })
</script>

<style scoped lang="scss">
.section-toolbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  h2 { margin: 0; font-size: 20px; letter-spacing: -0.02em; }
  p { margin: 6px 0 0; color: var(--el-text-color-secondary); font-size: 13px; }
}
.event-heading-line { display: flex; align-items: center; gap: 12px; }
.live-state { display: inline-flex; align-items: center; gap: 6px; color: var(--el-text-color-secondary); font-size: 12px; }
.live-state i { width: 7px; height: 7px; border-radius: 50%; background: var(--el-color-warning); }
.live-state.connected i { background: var(--el-color-success); box-shadow: 0 2px 9px rgba(103, 194, 58, 0.4); }
.event-filters {
  display: grid;
  grid-template-columns: 150px 120px 140px minmax(260px, 1fr) auto auto;
  gap: 8px;
  padding: 12px;
  border-radius: 12px;
  background: var(--el-fill-color-light);
}
.event-stream { min-height: 180px; margin-top: 12px; }
.event-row {
  display: grid;
  grid-template-columns: 4px minmax(260px, 1.5fr) 110px 120px minmax(190px, 0.9fr) 78px;
  align-items: center;
  gap: 14px;
  min-height: 112px;
  padding: 12px 8px 12px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.severity-mark { align-self: stretch; width: 1px; background: var(--el-color-info-light-5); }
.severity-warning .severity-mark { background: var(--el-color-warning); }
.severity-critical .severity-mark { background: var(--el-color-danger); }
.event-row.acknowledged { opacity: 0.72; }
.event-title-line { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }
.event-target { padding: 0; border: 0; background: none; color: var(--el-text-color-primary); font: inherit; font-weight: 700; cursor: pointer; }
.event-target:hover { color: var(--el-color-primary); text-decoration: underline; text-underline-offset: 3px; }
.event-identity p { margin: 7px 0; color: var(--el-text-color-regular); font-size: 13px; line-height: 1.5; }
.event-evidence { display: flex; flex-wrap: wrap; gap: 5px 12px; color: var(--el-text-color-secondary); font-size: 11px; font-variant-numeric: tabular-nums; }
.event-measure > span, .event-times span { display: block; color: var(--el-text-color-secondary); font-size: 11px; }
.event-measure strong { display: block; margin: 5px 0; font-size: 17px; font-variant-numeric: tabular-nums; }
.event-measure small { color: var(--el-text-color-secondary); font-size: 11px; }
.event-measure.quality strong { font-size: 13px; }
.quality-valid { color: var(--el-color-success); }
.quality-partial, .quality-stale { color: var(--el-color-warning); }
.quality-missing, .quality-error { color: var(--el-color-danger); }
.event-times { display: grid; gap: 8px; }
.event-times div { display: grid; grid-template-columns: 34px 1fr; align-items: baseline; gap: 6px; }
.event-times time { color: var(--el-text-color-regular); font-size: 11px; font-variant-numeric: tabular-nums; }
.event-action { display: flex; justify-content: flex-end; }
.acknowledged-label { display: flex; align-items: center; gap: 4px; color: var(--el-color-success); font-size: 12px; }
.event-pagination { display: flex; justify-content: flex-end; margin-top: 18px; }

@media (max-width: 1180px) {
  .event-filters { grid-template-columns: repeat(3, 1fr); }
  .event-row { grid-template-columns: 3px minmax(240px, 1fr) 100px 120px 78px; }
  .event-times { display: none; }
}

@media (max-width: 760px) {
  .section-toolbar { align-items: stretch; }
  .section-toolbar p { max-width: 34ch; }
  .event-filters { grid-template-columns: 1fr 1fr; }
  .event-filters :deep(.el-date-editor) { grid-column: 1 / -1; width: 100%; }
  .event-row { grid-template-columns: 3px 1fr auto; align-items: start; padding: 14px 2px 14px 0; }
  .event-measure, .event-times { display: none; }
  .event-action { padding-top: 2px; }
}
</style>
