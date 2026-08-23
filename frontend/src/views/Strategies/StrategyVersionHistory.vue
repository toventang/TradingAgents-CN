<template>
  <div class="strategy-version-history p-6 max-w-4xl mx-auto">
    <h1 class="text-2xl font-bold mb-6">策略版本历史与回退</h1>

    <div v-if="versions.length" class="space-y-4">
      <div v-for="ver in versions" :key="ver.version_id" class="bg-white p-4 border rounded shadow flex justify-between items-center">
        <div>
          <div class="flex items-center gap-2">
            <span class="font-bold text-lg">v{{ ver.version_num }}</span>
            <span v-if="ver.is_published" class="px-2 py-0.5 text-xs bg-green-100 text-green-800 rounded">已发布</span>
            <span v-else class="px-2 py-0.5 text-xs bg-yellow-100 text-yellow-800 rounded">草稿</span>
          </div>
          <p class="text-gray-600 text-sm mt-1">{{ ver.commit_message || '无提交日志' }}</p>
          <p class="text-gray-400 text-xs mt-1">创建时间: {{ ver.created_at }}</p>
        </div>

        <div class="flex gap-2">
          <button @click="onRollback(ver.version_num)" class="px-3 py-1 bg-amber-600 text-white text-xs rounded hover:bg-amber-700">
            回退至此版本
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { getStrategy, rollbackVersion } from '../../api/strategies';
import { StrategyVersion } from '../../types/strategy';

const route = useRoute();
const router = useRouter();
const versions = ref<StrategyVersion[]>([]);
const strategyId = route.params.id as string;

const loadData = async () => {
  try {
    const res = await getStrategy(strategyId);
    versions.value = res.versions;
  } catch (err) {
    console.error('Failed to load version history:', err);
  }
};

const onRollback = async (verNum: number) => {
  if (!confirm(`确定要安全回退至版本 v${verNum} 吗？`)) return;
  try {
    await rollbackVersion(strategyId, verNum, `Rollback to v${verNum}`);
    alert(`成功回退至版本 v${verNum}！`);
    await loadData();
  } catch (err) {
    console.error('Failed to rollback version:', err);
  }
};

onMounted(() => {
  loadData();
});
</script>
