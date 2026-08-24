<template>
  <div class="campaign-wizard p-6 max-w-4xl mx-auto">
    <h1 class="text-2xl font-bold mb-6">创建实盘/模拟 Campaign</h1>

    <div class="bg-white p-6 border rounded shadow space-y-4">
      <div>
        <label class="block font-medium mb-1">Campaign 名称</label>
        <input v-model="form.name" type="text" class="w-full border rounded p-2" placeholder="e.g. 动量双因子模拟 Campaign" />
      </div>

      <div>
        <label class="block font-medium mb-1">描述</label>
        <input v-model="form.description" type="text" class="w-full border rounded p-2" />
      </div>

      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="block font-medium mb-1">绑定策略 ID</label>
          <input v-model="form.strategy_id" type="text" class="w-full border rounded p-2" placeholder="sys_tmpl_01_val_mom" />
        </div>
        <div>
          <label class="block font-medium mb-1">策略版本号</label>
          <input v-model.number="form.strategy_version_num" type="number" class="w-full border rounded p-2" />
        </div>
      </div>

      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="block font-medium mb-1">隔离组合 Portfolio ID</label>
          <input v-model="form.portfolio_id" type="text" class="w-full border rounded p-2" placeholder="p_sim_01" />
        </div>
        <div>
          <label class="block font-medium mb-1">初始分配资金 (RMB)</label>
          <input v-model.number="form.initial_allocation_cash" type="number" class="w-full border rounded p-2" />
        </div>
      </div>

      <div>
        <label class="block font-medium mb-1">开始日期 (非追溯, >= 今天)</label>
        <input v-model="form.start_date" type="date" class="w-full border rounded p-2" />
      </div>

      <div class="pt-4">
        <button @click="onSubmit" class="w-full bg-blue-600 text-white font-medium py-2 rounded hover:bg-blue-700">
          保存 Draft 并前往校验
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { createCampaign } from '../../api/campaigns';

const router = useRouter();

const form = ref({
  name: '',
  description: '',
  strategy_id: 'sys_tmpl_01_val_mom',
  strategy_version_num: 1,
  portfolio_id: 'p_sim_01',
  initial_allocation_cash: 100000,
  start_date: new Date().toISOString().substring(0, 10),
  rebalance_frequency: 'daily'
});

const onSubmit = async () => {
  if (!form.value.name || !form.value.strategy_id) {
    alert('请填写必要字段');
    return;
  }
  try {
    const res = await createCampaign(form.value);
    router.push(`/campaigns/${res.campaign.campaign_id}`);
  } catch (err) {
    console.error('Failed to create campaign:', err);
  }
};
</script>
