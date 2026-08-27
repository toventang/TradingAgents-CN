<template>
  <div class="strategy-catalog p-6">
    <h1 class="text-2xl font-bold mb-4">策略中心与模版目录</h1>
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div v-for="strat in strategies" :key="strat.strategy_id" class="border p-4 rounded shadow bg-white">
        <div class="flex justify-between items-center mb-2">
          <span class="font-semibold text-lg">{{ strat.name }}</span>
          <span v-if="strat.is_system_template" class="px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded">系统模版</span>
          <span v-else class="px-2 py-1 text-xs bg-green-100 text-green-800 rounded">自定义策略</span>
        </div>
        <p class="text-gray-600 text-sm mb-4">{{ strat.description || '无策略描述' }}</p>
        <div class="text-xs text-gray-500 mb-4">
          状态: {{ strat.status }} | 最新版本: v{{ strat.latest_version_num }}
        </div>
        <div class="flex gap-2">
          <button @click="onClone(strat.strategy_id)" class="px-3 py-1 bg-indigo-600 text-white text-xs rounded hover:bg-indigo-700">
            克隆此策略
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { listStrategies, cloneStrategy } from '../../api/strategies';
import { Strategy } from '../../types/strategy';

const strategies = ref<Strategy[]>([]);

const loadData = async () => {
  try {
    strategies.value = await listStrategies(true);
  } catch (err) {
    console.error('Failed to load strategies:', err);
  }
};

const onClone = async (stratId: string) => {
  try {
    await cloneStrategy(stratId, {});
    await loadData();
  } catch (err) {
    console.error('Failed to clone strategy:', err);
  }
};

onMounted(() => {
  loadData();
});
</script>
