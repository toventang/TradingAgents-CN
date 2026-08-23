<template>
  <div class="backtest-comparison p-6">
    <h1 class="text-2xl font-bold mb-6">多回测定量横向对比</h1>

    <div class="bg-white p-4 border rounded shadow mb-6 space-y-3">
      <label class="block font-medium">输入要对比的回测 ID (逗号分隔):</label>
      <div class="flex gap-2">
        <input v-model="idsInput" type="text" class="flex-1 border rounded p-2" placeholder="e.g. bt_001, bt_002" />
        <button @click="onCompare" class="px-6 py-2 bg-blue-600 text-white font-medium rounded hover:bg-blue-700">
          开始对比
        </button>
      </div>
    </div>

    <div v-if="comparisonData" class="space-y-6">
      <div class="bg-white p-6 border rounded shadow">
        <h2 class="text-lg font-semibold mb-4">绩效指标横向对比</h2>
        <table class="w-full text-left border-collapse text-sm">
          <thead>
            <tr class="border-b bg-gray-50">
              <th class="p-2">回测 ID</th>
              <th class="p-2">累计收益率</th>
              <th class="p-2">年化收益率</th>
              <th class="p-2">最大回撤</th>
              <th class="p-2">夏普比率</th>
              <th class="p-2">换手率</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in comparisonData.summary" :key="item.backtest_id" class="border-b">
              <td class="p-2 font-mono font-medium">{{ item.backtest_id }}</td>
              <td class="p-2 font-bold text-green-600">{{ (item.total_return * 100).toFixed(2) }}%</td>
              <td class="p-2 text-green-600">{{ (item.annualized_return * 100).toFixed(2) }}%</td>
              <td class="p-2 text-red-600">{{ (item.max_drawdown * 100).toFixed(2) }}%</td>
              <td class="p-2 text-blue-600">{{ item.sharpe_ratio.toFixed(2) }}</td>
              <td class="p-2">{{ item.turnover_rate.toFixed(2) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { compareBacktests } from '../../api/backtests';

const idsInput = ref('');
const comparisonData = ref<any>(null);

const onCompare = async () => {
  const ids = idsInput.value.split(',').map(s => s.trim()).filter(Boolean);
  if (!ids.length) return;
  try {
    comparisonData.value = await compareBacktests(ids);
  } catch (err) {
    console.error('Failed to compare backtests:', err);
  }
};
</script>
