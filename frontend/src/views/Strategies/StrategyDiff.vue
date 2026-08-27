<template>
  <div class="strategy-diff p-6 max-w-4xl mx-auto">
    <h1 class="text-2xl font-bold mb-6">策略版本对比 (Diff)</h1>

    <div class="bg-white p-4 border rounded shadow mb-6 flex gap-4 items-center">
      <div>
        <label class="text-sm font-medium mr-2">基准版本 v1:</label>
        <input v-model.number="v1" type="number" class="border rounded p-1 w-20" />
      </div>
      <div>
        <label class="text-sm font-medium mr-2">对比版本 v2:</label>
        <input v-model.number="v2" type="number" class="border rounded p-1 w-20" />
      </div>
      <button @click="onCompare" class="px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
        开始对比
      </button>
    </div>

    <div v-if="diffResult" class="bg-white p-6 border rounded shadow space-y-6">
      <div>
        <h2 class="font-semibold text-lg border-b pb-2 mb-3">参数差异 (Parameters)</h2>
        <pre class="bg-gray-50 p-3 rounded text-sm">{{ JSON.stringify(diffResult.parameter_diffs, null, 2) }}</pre>
      </div>

      <div>
        <h2 class="font-semibold text-lg border-b pb-2 mb-3">选购规则差异 (Rules)</h2>
        <pre class="bg-gray-50 p-3 rounded text-sm">{{ JSON.stringify(diffResult.rule_diffs, null, 2) }}</pre>
      </div>

      <div>
        <h2 class="font-semibold text-lg border-b pb-2 mb-3">选股宇宙差异 (Universe)</h2>
        <div class="text-sm">
          <p><span class="font-medium">新增股票:</span> {{ diffResult.universe_diffs.added_symbols.join(', ') || '无' }}</p>
          <p><span class="font-medium">移除股票:</span> {{ diffResult.universe_diffs.removed_symbols.join(', ') || '无' }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRoute } from 'vue-router';
import { diffVersions } from '../../api/strategies';

const route = useRoute();
const strategyId = route.params.id as string;
const v1 = ref(1);
const v2 = ref(2);
const diffResult = ref<any>(null);

const onCompare = async () => {
  try {
    diffResult.value = await diffVersions(strategyId, v1.value, v2.value);
  } catch (err) {
    console.error('Failed to diff versions:', err);
  }
};
</script>
