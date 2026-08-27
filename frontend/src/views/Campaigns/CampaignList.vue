<template>
  <div class="campaign-list p-6">
    <div class="flex justify-between items-center mb-6">
      <h1 class="text-2xl font-bold">实盘/模拟 Campaign 运行面板</h1>
      <router-link to="/campaigns/create" class="px-4 py-2 bg-blue-600 text-white font-medium rounded hover:bg-blue-700 text-sm">
        创建新 Campaign
      </router-link>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div v-for="c in campaigns" :key="c.campaign_id" class="border p-4 rounded shadow bg-white">
        <div class="flex justify-between items-center mb-2">
          <span class="font-semibold text-lg">{{ c.name }}</span>
          <span class="px-2 py-0.5 text-xs font-bold rounded uppercase" :class="getStatusClass(c.status)">{{ c.status }}</span>
        </div>
        <p class="text-gray-600 text-sm mb-3">{{ c.description || '无描述' }}</p>
        <div class="text-xs text-gray-500 mb-4 space-y-1">
          <p>策略 ID: <span class="font-mono">{{ c.strategy_id }} (v{{ c.strategy_version_num }})</span></p>
          <p>分配资金: ¥{{ c.initial_allocation_cash.toLocaleString() }}</p>
          <p>开始日期: {{ c.start_date }}</p>
        </div>
        <div>
          <router-link :to="`/campaigns/${c.campaign_id}`" class="block text-center px-3 py-1.5 bg-indigo-600 text-white text-xs rounded hover:bg-indigo-700">
            查看详情与运行控制
          </router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { listCampaigns } from '../../api/campaigns';
import { Campaign } from '../../types/campaign';

const campaigns = ref<Campaign[]>([]);

onMounted(async () => {
  try {
    campaigns.value = await listCampaigns();
  } catch (err) {
    console.error('Failed to load campaigns:', err);
  }
});

const getStatusClass = (status: string) => {
  switch (status) {
    case 'activated': return 'bg-green-100 text-green-800';
    case 'paused': return 'bg-yellow-100 text-yellow-800';
    case 'stopped': return 'bg-red-100 text-red-800';
    default: return 'bg-gray-100 text-gray-800';
  }
};
</script>
