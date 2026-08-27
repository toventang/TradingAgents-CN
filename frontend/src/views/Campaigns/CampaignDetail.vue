<template>
  <div class="campaign-detail p-6 max-w-5xl mx-auto space-y-6">
    <div v-if="campaign" class="bg-white p-6 border rounded shadow">
      <div class="flex justify-between items-center border-b pb-4 mb-4">
        <div>
          <h1 class="text-2xl font-bold">{{ campaign.name }}</h1>
          <p class="text-gray-500 text-sm mt-1">ID: {{ campaign.campaign_id }}</p>
        </div>
        <div class="flex items-center gap-3">
          <span class="px-3 py-1 rounded text-sm font-bold uppercase bg-blue-100 text-blue-800">{{ campaign.status }}</span>

          <button v-if="campaign.status === 'draft'" @click="onActivate" class="px-4 py-1.5 bg-green-600 text-white text-sm rounded hover:bg-green-700">
            校验并激活
          </button>
          <button v-if="campaign.status === 'activated'" @click="onPause" class="px-4 py-1.5 bg-yellow-600 text-white text-sm rounded hover:bg-yellow-700">
            暂停
          </button>
          <button v-if="campaign.status === 'paused'" @click="onResume" class="px-4 py-1.5 bg-green-600 text-white text-sm rounded hover:bg-green-700">
            确认恢复
          </button>
          <button v-if="campaign.status !== 'stopped'" @click="onStop" class="px-4 py-1.5 bg-red-600 text-white text-sm rounded hover:bg-red-700">
            终止
          </button>
        </div>
      </div>

      <div class="grid grid-cols-3 gap-4 text-sm">
        <div><span class="text-gray-500">绑定策略:</span> {{ campaign.strategy_id }} (v{{ campaign.strategy_version_num }})</div>
        <div><span class="text-gray-500">初始资金:</span> ¥{{ campaign.initial_allocation_cash.toLocaleString() }}</div>
        <div><span class="text-gray-500">开始日期:</span> {{ campaign.start_date }}</div>
      </div>
    </div>

    <!-- 绩效卡片 -->
    <div v-if="perf" class="bg-white p-6 border rounded shadow">
      <h2 class="text-lg font-semibold mb-4">定量绩效与机会成本分析</h2>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div class="p-3 border rounded">
          <div class="text-xs text-gray-500">累计收益率</div>
          <div class="text-lg font-bold text-green-600">{{ (perf.metrics.total_return * 100).toFixed(2) }}%</div>
        </div>
        <div class="p-3 border rounded">
          <div class="text-xs text-gray-500">最大回撤</div>
          <div class="text-lg font-bold text-red-600">{{ (perf.metrics.max_drawdown * 100).toFixed(2) }}%</div>
        </div>
        <div class="p-3 border rounded">
          <div class="text-xs text-gray-500">超越基准超额</div>
          <div class="text-lg font-bold text-blue-600">{{ (perf.opportunity_cost.benchmark_excess * 100).toFixed(2) }}%</div>
        </div>
        <div class="p-3 border rounded">
          <div class="text-xs text-gray-500">超越纯现金超额</div>
          <div class="text-lg font-bold text-indigo-600">{{ (perf.opportunity_cost.cash_baseline_excess * 100).toFixed(2) }}%</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import { getCampaign, activateCampaign, pauseCampaign, resumeCampaign, stopCampaign, getCampaignPerformance } from '../../api/campaigns';
import { Campaign } from '../../types/campaign';

const route = useRoute();
const campaignId = route.params.id as string;
const campaign = ref<Campaign | null>(null);
const perf = ref<any>(null);

const loadData = async () => {
  try {
    campaign.value = await getCampaign(campaignId);
    perf.value = await getCampaignPerformance(campaignId);
  } catch (err) {
    console.error('Failed to load campaign detail:', err);
  }
};

onMounted(() => {
  loadData();
});

const onActivate = async () => {
  try {
    await activateCampaign(campaignId);
    alert('Campaign 校验通过，已成功激活运行！');
    await loadData();
  } catch (err: any) {
    alert(`激活失败: ${err.response?.data?.detail || err.message}`);
  }
};

const onPause = async () => {
  try {
    await pauseCampaign(campaignId);
    await loadData();
  } catch (err) {
    console.error('Failed to pause campaign:', err);
  }
};

const onResume = async () => {
  const note = prompt('请输入恢复确认备注:');
  try {
    await resumeCampaign(campaignId, note || 'Owner confirmed');
    await loadData();
  } catch (err) {
    console.error('Failed to resume campaign:', err);
  }
};

const onStop = async () => {
  if (!confirm('确定要终止当前 Campaign 吗？')) return;
  try {
    await stopCampaign(campaignId);
    await loadData();
  } catch (err) {
    console.error('Failed to stop campaign:', err);
  }
};
</script>
