<template>
  <div class="backtest-detail p-6">
    <h1 class="text-2xl font-bold mb-4">回测定量分析与收益曲线</h1>

    <div v-if="result" class="space-y-6">
      <!-- 绩效指标卡片 -->
      <div v-if="result.metrics" class="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div class="bg-white p-4 border rounded shadow">
          <div class="text-gray-500 text-sm">累计收益率</div>
          <div class="text-xl font-bold text-green-600">{{ (result.metrics.total_return * 100).toFixed(2) }}%</div>
        </div>
        <div class="bg-white p-4 border rounded shadow">
          <div class="text-gray-500 text-sm">年化收益率</div>
          <div class="text-xl font-bold text-green-600">{{ (result.metrics.annualized_return * 100).toFixed(2) }}%</div>
        </div>
        <div class="bg-white p-4 border rounded shadow">
          <div class="text-gray-500 text-sm">最大回撤</div>
          <div class="text-xl font-bold text-red-600">{{ (result.metrics.max_drawdown * 100).toFixed(2) }}%</div>
        </div>
        <div class="bg-white p-4 border rounded shadow">
          <div class="text-gray-500 text-sm">夏普比率</div>
          <div class="text-xl font-bold text-blue-600">{{ result.metrics.sharpe_ratio.toFixed(2) }}</div>
        </div>
      </div>

      <!-- 成交记录明细表格 -->
      <div class="bg-white p-6 border rounded shadow">
        <h2 class="text-lg font-semibold mb-4">成交撮合明细</h2>
        <table class="w-full text-left border-collapse text-sm">
          <thead>
            <tr class="border-b bg-gray-50">
              <th class="p-2">交易日期</th>
              <th class="p-2">代码</th>
              <th class="p-2">方向</th>
              <th class="p-2">数量</th>
              <th class="p-2">成交价</th>
              <th class="p-2">手续费/规费</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="fill in result.fills" :key="fill.fill_id" class="border-b">
              <td class="p-2">{{ fill.trade_date }}</td>
              <td class="p-2 font-mono">{{ fill.symbol }}</td>
              <td class="p-2 uppercase font-semibold" :class="fill.side === 'buy' ? 'text-red-600' : 'text-green-600'">{{ fill.side }}</td>
              <td class="p-2">{{ fill.quantity }}</td>
              <td class="p-2">¥{{ fill.execution_price.toFixed(2) }}</td>
              <td class="p-2">¥{{ fill.total_cost.toFixed(2) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import { getBacktestResult } from '../../api/backtests';

const route = useRoute();
const result = ref<any>(null);

onMounted(async () => {
  const btId = route.params.id as string;
  try {
    result.value = await getBacktestResult(btId);
  } catch (err) {
    console.error('Failed to load backtest result:', err);
  }
});
</script>
