<template>
  <div class="risk-settings p-6 max-w-4xl mx-auto">
    <h1 class="text-2xl font-bold mb-6">风控指标与限制阈值配置</h1>

    <div class="bg-white p-6 border rounded shadow space-y-4">
      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="block font-medium mb-1">单股最大持仓上限 (%)</label>
          <input v-model.number="config.max_stock_weight" type="number" step="0.01" class="w-full border rounded p-2" />
        </div>
        <div>
          <label class="block font-medium mb-1">单行业最大持仓上限 (%)</label>
          <input v-model.number="config.max_sector_weight" type="number" step="0.01" class="w-full border rounded p-2" />
        </div>
      </div>

      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="block font-medium mb-1">组合最大回撤阀值 (%)</label>
          <input v-model.number="config.max_drawdown_limit" type="number" step="0.01" class="w-full border rounded p-2" />
        </div>
        <div>
          <label class="block font-medium mb-1">日度 VaR (95%) 限制 (%)</label>
          <input v-model.number="config.max_var_95_limit" type="number" step="0.005" class="w-full border rounded p-2" />
        </div>
      </div>

      <div class="border-t pt-4 space-y-3">
        <h2 class="font-semibold text-lg">交易制度与流动性约束</h2>
        <div class="flex items-center gap-3">
          <input type="checkbox" v-model="config.enforce_t_plus_1" class="h-5 w-5" />
          <span class="text-sm font-medium">强制执行 A 股 T+1 结算卖出数量限制</span>
        </div>
        <div class="flex items-center gap-3">
          <input type="checkbox" v-model="config.block_limit_up_buy" class="h-5 w-5" />
          <span class="text-sm font-medium">涨停板买入拦截 (Block Limit-Up Buy)</span>
        </div>
        <div class="flex items-center gap-3">
          <input type="checkbox" v-model="config.block_limit_down_sell" class="h-5 w-5" />
          <span class="text-sm font-medium">跌停板卖出警告 (Block Limit-Down Sell)</span>
        </div>
      </div>

      <div class="pt-4">
        <button @click="onSave" class="w-full bg-blue-600 text-white font-medium py-2 rounded hover:bg-blue-700">
          保存风控配置
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';

const config = ref({
  portfolio_id: 'default_portfolio',
  max_stock_weight: 0.10,
  max_sector_weight: 0.30,
  max_drawdown_limit: 0.15,
  max_var_95_limit: 0.03,
  max_adv_participation_rate: 0.05,
  enforce_t_plus_1: true,
  block_limit_up_buy: true,
  block_limit_down_sell: true
});

const onSave = () => {
  localStorage.setItem('risk_config', JSON.stringify(config.value));
  alert('风控设置已更新！');
};
</script>
