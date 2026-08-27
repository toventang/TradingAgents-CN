<template>
  <div class="learning-proposals p-6 max-w-5xl mx-auto space-y-6">
    <h1 class="text-2xl font-bold">受控学习提议与策略优化草稿</h1>

    <div v-if="proposals.length" class="space-y-6">
      <div v-for="prop in proposals" :key="prop.proposal_id" class="bg-white p-6 border rounded shadow space-y-4">
        <div class="flex justify-between items-center border-b pb-3">
          <div>
            <span class="font-bold text-lg">提议 ID: {{ prop.proposal_id }}</span>
            <span class="text-gray-500 text-sm ml-3">绑定策略: {{ prop.strategy_id }}</span>
          </div>
          <span class="px-2.5 py-0.5 text-xs font-bold rounded uppercase bg-purple-100 text-purple-800">
            样本数: {{ prop.sample_count }} / 5
          </span>
        </div>

        <div>
          <h3 class="font-semibold text-sm text-gray-700 mb-2">白名单参数修订对比</h3>
          <table class="w-full text-left border-collapse text-xs">
            <thead>
              <tr class="border-b bg-gray-50">
                <th class="p-2">勾选批准</th>
                <th class="p-2">参数路径</th>
                <th class="p-2">当前值</th>
                <th class="p-2">建议优化值</th>
                <th class="p-2">优化说明</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in prop.diff_items" :key="item.parameter_path" class="border-b">
                <td class="p-2"><input type="checkbox" v-model="item.approved" /></td>
                <td class="p-2 font-mono font-bold">{{ item.parameter_path }}</td>
                <td class="p-2 text-gray-600">{{ item.current_value }}</td>
                <td class="p-2 text-green-600 font-bold">{{ item.proposed_value }}</td>
                <td class="p-2 text-gray-500">{{ item.reasoning }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="pt-2 flex justify-end">
          <button @click="onApplyDraft(prop)" class="px-4 py-2 bg-blue-600 text-white font-medium text-xs rounded hover:bg-blue-700">
            生成新策略草稿 (无自动发布/不修改实盘)
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { listLearningProposals, applyProposalDraft } from '../../api/learning';
import { LearningProposal } from '../../types/learning';

const proposals = ref<LearningProposal[]>([]);

onMounted(async () => {
  try {
    proposals.value = await listLearningProposals();
  } catch (err) {
    console.error('Failed to load learning proposals:', err);
  }
});

const onApplyDraft = async (prop: LearningProposal) => {
  const approvedPaths = prop.diff_items.filter(i => i.approved).map(i => i.parameter_path);
  try {
    await applyProposalDraft(prop.proposal_id, approvedPaths);
    alert('已成功依据批准修改项生成【新策略草稿版本】！原运行 Campaign 与已发布策略不受影响。');
  } catch (err) {
    console.error('Failed to apply draft:', err);
  }
};
</script>
