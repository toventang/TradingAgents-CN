<template>
  <div class="trade-review-detail p-6 max-w-5xl mx-auto space-y-6">
    <h1 class="text-2xl font-bold">交易归因复盘与证据绑定</h1>

    <div v-if="review" class="bg-white p-6 border rounded shadow space-y-4">
      <div class="flex justify-between items-center border-b pb-3">
        <div>
          <span class="font-bold text-lg">{{ review.symbol }}</span>
          <span class="text-gray-500 text-sm ml-3">Trade ID: {{ review.trade_id }}</span>
        </div>
        <span class="px-3 py-1 rounded text-xs font-bold uppercase" :class="getConfidenceClass(review.confidence)">
          {{ review.confidence }}
        </span>
      </div>

      <div>
        <h3 class="font-semibold text-gray-700">AI 复盘摘要</h3>
        <p class="text-gray-800 text-sm mt-1 bg-gray-50 p-3 rounded">{{ review.summary }}</p>
      </div>

      <div>
        <h3 class="font-semibold text-gray-700">归因诊断与可控性评估 (Score: {{ (review.controllability_score * 100).toFixed(0) }}%)</h3>
        <p class="text-gray-800 text-sm mt-1 bg-gray-50 p-3 rounded">{{ review.diagnosis }}</p>
      </div>

      <div class="grid grid-cols-2 gap-4 border-t pt-4">
        <div>
          <h4 class="font-semibold text-green-700 text-sm mb-2">支持证据 (Supporting Evidence)</h4>
          <ul class="list-disc list-inside text-xs text-gray-700 space-y-1">
            <li v-for="(ev, idx) in review.grounding.supporting_evidence" :key="idx">{{ ev }}</li>
          </ul>
        </div>
        <div>
          <h4 class="font-semibold text-red-700 text-sm mb-2">反例基准 (Counter Evidence)</h4>
          <ul class="list-disc list-inside text-xs text-gray-700 space-y-1">
            <li v-for="(ev, idx) in review.grounding.counter_evidence" :key="idx">{{ ev }}</li>
            <li v-if="!review.grounding.counter_evidence?.length" class="text-gray-400">无反例基准</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import { getAITradeReview } from '../../api/learning';
import { AITradeReview } from '../../types/learning';

const route = useRoute();
const tradeId = route.params.id as string;
const review = ref<AITradeReview | null>(null);

onMounted(async () => {
  try {
    review.value = await getAITradeReview(tradeId);
  } catch (err) {
    console.error('Failed to load trade review:', err);
  }
});

const getConfidenceClass = (conf: string) => {
  switch (conf) {
    case 'high': return 'bg-green-100 text-green-800';
    case 'medium': return 'bg-blue-100 text-blue-800';
    case 'low': return 'bg-yellow-100 text-yellow-800';
    default: return 'bg-red-100 text-red-800';
  }
};
</script>
