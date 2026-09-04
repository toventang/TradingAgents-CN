<template>
  <section class="rule-section" aria-labelledby="alert-rules-title">
    <div class="section-toolbar">
      <div>
        <h2 id="alert-rules-title">监控规则</h2>
        <p>{{ rules.length }} 条规则，启用 {{ enabledCount }} 条</p>
      </div>
      <div class="toolbar-actions">
        <el-input v-model="keyword" clearable placeholder="搜索名称、代码或类型" aria-label="搜索预警规则">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="statusFilter" aria-label="按启用状态筛选">
          <el-option label="全部状态" value="all" />
          <el-option label="仅启用" value="enabled" />
          <el-option label="仅停用" value="disabled" />
        </el-select>
        <el-button :loading="loading" aria-label="刷新规则" @click="$emit('refresh')">
          <el-icon><Refresh /></el-icon>
        </el-button>
        <el-button type="primary" @click="$emit('create')">
          <el-icon><Plus /></el-icon>创建规则
        </el-button>
      </div>
    </div>

    <div v-loading="loading" class="rule-list" aria-live="polite">
      <el-empty v-if="!loading && filteredRules.length === 0" description="没有符合条件的规则">
        <el-button v-if="rules.length === 0" type="primary" @click="$emit('create')">创建第一条规则</el-button>
      </el-empty>

      <article v-for="rule in filteredRules" :key="rule.rule_id" class="rule-row">
        <div class="rule-switch">
          <el-switch
            :model-value="rule.enabled"
            :loading="pendingIds.has(rule.rule_id)"
            :disabled="rule.origin !== 'user'"
            :aria-label="`${rule.enabled ? '停用' : '启用'} ${rule.name}`"
            @change="$emit('toggle', rule)"
          />
        </div>
        <div class="rule-main">
          <div class="rule-name-line">
            <button v-if="rule.origin === 'user'" type="button" class="rule-name" @click="$emit('edit', rule)">{{ rule.name }}</button>
            <span v-else class="rule-name readonly">{{ rule.name }}</span>
            <el-tag size="small" effect="plain">{{ alertTypeLabel(rule.alert_type) }}</el-tag>
            <el-tag v-if="rule.origin !== 'user'" size="small" type="info" effect="plain">
              {{ rule.origin === 'automation' ? '自动化管理' : '系统管理' }}
            </el-tag>
            <el-tag v-if="rule.severity === 'critical'" size="small" type="danger" effect="dark">严重</el-tag>
          </div>
          <div class="rule-context">
            <span>{{ marketLabel[rule.market] }}</span>
            <span>{{ ruleTarget(rule) }}</span>
            <span>每 {{ frequencyLabel(rule.frequency_seconds) }}</span>
            <span>v{{ rule.version }}</span>
          </div>
        </div>
        <div class="rule-health">
          <span class="health-label">健康</span>
          <strong :class="healthFor(rule).className">
            <i aria-hidden="true"></i>{{ healthFor(rule).label }}
          </strong>
        </div>
        <div class="rule-time">
          <span>上次评估</span>
          <strong>{{ formatDateTime(rule.state.last_evaluated_at) }}</strong>
        </div>
        <div class="rule-time">
          <span>上次触发</span>
          <strong>{{ formatDateTime(lastEvent(rule.rule_id)?.evaluated_at) }}</strong>
        </div>
        <el-dropdown trigger="click" @command="handleCommand($event, rule)">
          <el-button text aria-label="规则操作"><el-icon><MoreFilled /></el-icon></el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-if="rule.origin === 'user'" command="edit">编辑规则</el-dropdown-item>
              <el-dropdown-item v-if="rule.origin === 'user'" command="test">发送测试通知</el-dropdown-item>
              <el-dropdown-item command="events">查看相关事件</el-dropdown-item>
              <el-dropdown-item v-if="rule.origin === 'user'" command="delete" divided>删除规则</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { MoreFilled, Plus, Refresh, Search } from '@element-plus/icons-vue'
import type { AlertEvent, AlertRule } from '@/types/alert'
import {
  alertTypeLabel,
  formatDateTime,
  marketLabel,
  ruleTarget
} from './alertUi'

const props = defineProps<{
  rules: AlertRule[]
  events: AlertEvent[]
  loading: boolean
  pendingIds: Set<string>
}>()

const emit = defineEmits<{
  refresh: []
  create: []
  edit: [rule: AlertRule]
  toggle: [rule: AlertRule]
  test: [rule: AlertRule]
  delete: [rule: AlertRule]
  events: [rule: AlertRule]
}>()

const keyword = ref('')
const statusFilter = ref<'all' | 'enabled' | 'disabled'>('all')

const enabledCount = computed(() => props.rules.filter(rule => rule.enabled).length)
const filteredRules = computed(() => {
  const term = keyword.value.trim().toLowerCase()
  return props.rules.filter(rule => {
    if (statusFilter.value === 'enabled' && !rule.enabled) return false
    if (statusFilter.value === 'disabled' && rule.enabled) return false
    if (!term) return true
    return [rule.name, rule.description, rule.alert_type, ruleTarget(rule)]
      .some(value => value.toLowerCase().includes(term))
  })
})

function lastEvent(ruleId: string) {
  return props.events.find(event => event.rule_id === ruleId && event.kind === 'triggered')
}

function healthFor(rule: AlertRule) {
  if (!rule.enabled) return { label: '已停用', className: 'muted' }
  const event = lastEvent(rule.rule_id)
  if (event?.quality_status === 'error' || event?.quality_status === 'missing') {
    return { label: '数据异常', className: 'danger' }
  }
  if (event?.quality_status === 'stale') return { label: '数据过期', className: 'warning' }
  if (!rule.state.last_evaluated_at) return { label: '等待评估', className: 'waiting' }
  return { label: '正常', className: 'healthy' }
}

function frequencyLabel(seconds: number) {
  if (seconds < 60) return `${seconds} 秒`
  if (seconds < 3600) return `${seconds / 60} 分钟`
  return `${seconds / 3600} 小时`
}

function handleCommand(command: string | number | object, rule: AlertRule) {
  if (command === 'edit') emit('edit', rule)
  if (command === 'test') emit('test', rule)
  if (command === 'events') emit('events', rule)
  if (command === 'delete') emit('delete', rule)
}
</script>

<style scoped lang="scss">
.rule-section { min-width: 0; }
.section-toolbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 16px;

  h2 { margin: 0 0 4px; font-size: 20px; letter-spacing: -0.02em; }
  p { margin: 0; color: var(--el-text-color-secondary); font-size: 13px; }
}
.toolbar-actions { display: flex; align-items: center; gap: 8px; }
.toolbar-actions .el-input { width: 220px; }
.toolbar-actions .el-select { width: 120px; }
.rule-list { min-height: 180px; }

.rule-row {
  display: grid;
  grid-template-columns: 46px minmax(220px, 1.5fr) 110px minmax(150px, 0.8fr) minmax(150px, 0.8fr) 38px;
  align-items: center;
  gap: 14px;
  min-height: 84px;
  padding: 11px 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.rule-row:hover { background: var(--el-fill-color-lighter); }
.rule-switch { display: flex; justify-content: center; }
.rule-name-line { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }
.rule-name {
  max-width: 320px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--el-text-color-primary);
  font: inherit;
  font-weight: 650;
  text-align: left;
  cursor: pointer;
}
.rule-name:hover { color: var(--el-color-primary); text-decoration: underline; text-underline-offset: 3px; }
.rule-name.readonly { cursor: default; }
.rule-name.readonly:hover { color: var(--el-text-color-primary); text-decoration: none; }
.rule-context { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 7px; color: var(--el-text-color-secondary); font-size: 12px; }
.rule-context span { font-variant-numeric: tabular-nums; }
.rule-health, .rule-time { min-width: 0; }
.health-label, .rule-time span { display: block; margin-bottom: 5px; color: var(--el-text-color-secondary); font-size: 11px; }
.rule-time strong { display: block; overflow: hidden; font-size: 12px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; font-variant-numeric: tabular-nums; }
.rule-health strong { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.rule-health i { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.healthy { color: var(--el-color-success); }
.warning { color: var(--el-color-warning); }
.danger { color: var(--el-color-danger); }
.waiting { color: var(--el-color-primary); }
.muted { color: var(--el-text-color-placeholder); }

@media (max-width: 1120px) {
  .rule-row { grid-template-columns: 40px minmax(220px, 1fr) 100px minmax(130px, 0.6fr) 38px; }
  .rule-time:nth-of-type(2) { display: none; }
}

@media (max-width: 760px) {
  .section-toolbar { align-items: stretch; flex-direction: column; }
  .toolbar-actions { display: grid; grid-template-columns: 1fr auto auto; }
  .toolbar-actions .el-input { width: auto; grid-column: 1 / -1; }
  .toolbar-actions .el-select { width: auto; }
  .rule-row { grid-template-columns: 38px 1fr 34px; gap: 8px; padding: 14px 2px; }
  .rule-health, .rule-time { display: none; }
  .rule-main { min-width: 0; }
  .rule-name { max-width: 210px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
}
</style>
