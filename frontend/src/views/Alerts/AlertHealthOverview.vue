<template>
  <section class="health-strip" aria-labelledby="alert-health-title">
    <div class="health-lead">
      <div class="health-orbit" :class="health?.status || 'loading'" aria-hidden="true">
        <span></span>
      </div>
      <div>
        <h2 id="alert-health-title">监控状态</h2>
        <p>{{ healthMessage }}</p>
      </div>
      <el-button text :loading="loading" aria-label="刷新监控状态" @click="$emit('refresh')">
        <el-icon><Refresh /></el-icon>
      </el-button>
    </div>

    <div class="health-measures" aria-live="polite">
      <div class="measure">
        <span>启用规则</span>
        <strong>{{ health?.owner.enabled_rule_count ?? '—' }}</strong>
      </div>
      <div class="measure">
        <span>近期事件</span>
        <strong>{{ health?.owner.recent_event_count ?? '—' }}</strong>
      </div>
      <div class="measure">
        <span>平均延迟</span>
        <strong>{{ formatLatency(health?.latency_seconds.average) }}</strong>
      </div>
      <div class="measure">
        <span>数据源</span>
        <strong :class="{ danger: health && !health.data_sources.market_quotes.available }">
          {{ health ? (health.data_sources.market_quotes.available ? '可用' : '不可用') : '—' }}
        </strong>
      </div>
    </div>

    <div v-if="health" class="health-foot">
      <span>最近批次：{{ health.evaluation_batches.last_status || '暂无' }}</span>
      <span>失败批次：{{ health.evaluation_batches.failure_count }}</span>
      <span>行情更新：{{ formatDateTime(health.data_sources.market_quotes.last_ingested_at) }}</span>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import type { AlertHealth } from '@/types/alert'
import { formatDateTime, formatLatency } from './alertUi'

const props = defineProps<{
  health: AlertHealth | null
  loading: boolean
}>()

defineEmits<{ refresh: [] }>()

const healthMessage = computed(() => {
  if (!props.health) return props.loading ? '正在读取评估批次、事件延迟和行情新鲜度' : '暂时无法读取监控状态'
  if (props.health.status === 'degraded') return '部分批次或数据源需要关注，规则仍按可用数据继续监控'
  return '评估批次、事件投递与行情数据运行正常'
})
</script>

<style scoped lang="scss">
.health-strip {
  padding: 22px 24px 18px;
  color: #f4f8ff;
  background: #132238;
  border-radius: 16px;
  box-shadow: 0 14px 34px rgba(15, 34, 56, 0.18);
}

.health-lead {
  display: flex;
  align-items: center;
  gap: 14px;

  h2 { margin: 0 0 4px; font-size: 18px; letter-spacing: -0.01em; }
  p { margin: 0; color: #b8c8dc; font-size: 13px; }
  .el-button { margin-left: auto; color: #dbe9f8; }
}

.health-orbit {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(119, 226, 173, 0.38);
  border-radius: 50%;

  span { width: 10px; height: 10px; border-radius: 50%; background: #63d99c; box-shadow: 0 2px 12px rgba(99, 217, 156, 0.46); }
  &.degraded { border-color: rgba(255, 190, 92, 0.5); }
  &.degraded span { background: #ffbe5c; box-shadow: 0 2px 12px rgba(255, 190, 92, 0.4); }
  &.loading span { background: #7c91aa; box-shadow: none; }
}

.health-measures {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-top: 20px;
  border-top: 1px solid rgba(219, 233, 248, 0.12);
  border-bottom: 1px solid rgba(219, 233, 248, 0.12);
}

.measure {
  padding: 16px 18px;
  border-right: 1px solid rgba(219, 233, 248, 0.12);
  &:first-child { padding-left: 0; }
  &:last-child { border-right: 0; }
  span { display: block; color: #94a9c2; font-size: 12px; margin-bottom: 6px; }
  strong { font-size: 22px; font-variant-numeric: tabular-nums; }
  strong.danger { color: #ff8a86; }
}

.health-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 24px;
  margin-top: 14px;
  color: #94a9c2;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 760px) {
  .health-strip { padding: 18px; }
  .health-measures { grid-template-columns: repeat(2, 1fr); }
  .measure:nth-child(2) { border-right: 0; }
  .measure:nth-child(-n + 2) { border-bottom: 1px solid rgba(219, 233, 248, 0.12); }
  .measure:nth-child(3) { padding-left: 0; }
  .health-foot { flex-direction: column; gap: 5px; }
}
</style>
