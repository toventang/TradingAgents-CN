<template>
  <div class="chart-shell">
    <div
      ref="chartElement"
      class="chart"
      role="img"
      :aria-label="chartDescription"
    />
    <div v-if="!points.length" class="chart-empty">暂无净值数据</div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'
import type { BacktestEquityPoint } from '@/types/backtest'

const props = defineProps<{ points: BacktestEquityPoint[] }>()
const chartElement = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null

const chartDescription = computed(() => {
  if (!props.points.length) return '回测净值与回撤图，暂无数据'
  const first = props.points[0]
  const last = props.points[props.points.length - 1]
  return `回测净值、基准与回撤图，日期从 ${first.trade_date} 到 ${last.trade_date}`
})

const option = computed<EChartsOption>(() => ({
  animationDuration: 180,
  animationEasing: 'quarticOut',
  aria: { enabled: true, decal: { show: false } },
  grid: { left: 18, right: 22, top: 48, bottom: 26, containLabel: true },
  legend: { top: 8, left: 8, itemWidth: 18, textStyle: { color: '#606266' } },
  tooltip: {
    trigger: 'axis',
    valueFormatter: value => `${(Number(value) * 100).toFixed(2)}%`
  },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: props.points.map(point => point.trade_date),
    axisLine: { lineStyle: { color: '#dcdfe6' } },
    axisLabel: { color: '#606266', hideOverlap: true }
  },
  yAxis: [
    {
      type: 'value',
      axisLabel: { formatter: (value: number) => `${(value * 100).toFixed(0)}%` },
      splitLine: { lineStyle: { color: '#ebeef5' } }
    },
    {
      type: 'value',
      min: value => Math.min(value.min, -0.01),
      max: 0,
      axisLabel: { formatter: (value: number) => `${(value * 100).toFixed(0)}%` },
      splitLine: { show: false }
    }
  ],
  series: [
    {
      name: '策略收益',
      type: 'line',
      showSymbol: false,
      smooth: false,
      lineStyle: { width: 2, color: '#337ecc' },
      itemStyle: { color: '#337ecc' },
      data: props.points.map(point => Number(point.cumulative_return))
    },
    {
      name: '基准收益',
      type: 'line',
      showSymbol: false,
      connectNulls: true,
      lineStyle: { width: 1.5, color: '#67c23a', type: 'dashed' },
      itemStyle: { color: '#67c23a' },
      data: benchmarkReturns(props.points)
    },
    {
      name: '回撤',
      type: 'line',
      yAxisIndex: 1,
      showSymbol: false,
      lineStyle: { width: 1.5, color: '#e6a23c' },
      areaStyle: { color: 'rgba(230, 162, 60, 0.12)' },
      data: props.points.map(point => Number(point.drawdown))
    }
  ]
}))

watch(option, render, { deep: true })

onMounted(() => {
  if (!chartElement.value) return
  chart = echarts.init(chartElement.value)
  render()
  resizeObserver = new ResizeObserver(() => chart?.resize())
  resizeObserver.observe(chartElement.value)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
})

async function render(): Promise<void> {
  await nextTick()
  if (!chart && chartElement.value) chart = echarts.init(chartElement.value)
  chart?.setOption(option.value, true)
}

function benchmarkReturns(points: BacktestEquityPoint[]): Array<number | null> {
  const first = points.find(point => point.benchmark_equity !== null)?.benchmark_equity
  if (!first || Number(first) === 0) return points.map(() => null)
  const base = Number(first)
  return points.map(point => point.benchmark_equity === null
    ? null
    : Number(point.benchmark_equity) / base - 1)
}
</script>

<style scoped lang="scss">
.chart-shell { position: relative; min-height: 360px; }
.chart { width: 100%; height: 360px; }
.chart-empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-blank);
}
@media (max-width: 720px) {
  .chart-shell, .chart { min-height: 300px; height: 300px; }
}
@media (prefers-reduced-motion: reduce) {
  .chart { scroll-behavior: auto; }
}
</style>
