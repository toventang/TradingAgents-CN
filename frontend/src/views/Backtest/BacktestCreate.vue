<template>
  <div class="backtest-create p-6 max-w-4xl mx-auto">
    <h1 class="text-2xl font-bold mb-6">发起策略定量回测</h1>

    <div class="bg-white p-6 rounded shadow border space-y-4">
      <div>
        <label class="block font-medium mb-1">策略 ID</label>
        <input v-model="config.strategy_id" type="text" class="w-full border rounded p-2" placeholder="e.g. sys_tmpl_01_val_mom" />
      </div>

      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="block font-medium mb-1">开始日期</label>
          <input v-model="config.start_date" type="date" class="w-full border rounded p-2" />
        </div>
        <div>
          <label class="block font-medium mb-1">结束日期</label>
          <input v-model="config.end_date" type="date" class="w-full border rounded p-2" />
        </div>
      </div>

      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="block font-medium mb-1">初始资金 (RMB)</label>
          <input v-model.number="config.initial_capital" type="number" class="w-full border rounded p-2" />
        </div>
        <div>
          <label class="block font-medium mb-1">对比基准</label>
          <input v-model="config.benchmark" type="text" class="w-full border rounded p-2" placeholder="000300.SH" />
        </div>
      </div>

      <div class="border-t pt-4">
        <h2 class="font-semibold text-lg mb-3">券商/账户交易成本模型设置</h2>
        <div class="grid grid-cols-3 gap-4">
          <div>
            <label class="block text-sm mb-1">佣金比例</label>
            <input v-model.number="config.cost_model.commission_rate" type="number" step="0.0001" class="w-full border rounded p-2" />
          </div>
          <div>
            <label class="block text-sm mb-1">最低佣金 (元)</label>
            <input v-model.number="config.cost_model.min_commission" type="number" class="w-full border rounded p-2" />
          </div>
          <div>
            <label class="block text-sm mb-1">滑点比例</label>
            <input v-model.number="config.cost_model.slippage_rate" type="number" step="0.0005" class="w-full border rounded p-2" />
          </div>
        </div>
      </div>

      <div class="pt-4">
        <button @click="onSubmit" class="w-full bg-blue-600 text-white font-medium py-2 rounded hover:bg-blue-700">
          提交回测任务
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { submitBacktest } from '../../api/backtests';

const router = useRouter();

const config = ref({
  strategy_id: 'sys_tmpl_01_val_mom',
  version_num: 1,
  start_date: '2026-01-01',
  end_date: '2026-06-30',
  initial_capital: 1000000,
  benchmark: '000300.SH',
  rebalance_frequency: 'daily',
  cost_model: {
    broker_id: 'default_broker',
    account_id: 'default_account',
    commission_rate: 0.0003,
    min_commission: 5.0,
    stamp_duty_rate: 0.0005,
    transfer_fee_rate: 0.00001,
    slippage_rate: 0.0010
  }
});

const onSubmit = async () => {
  try {
    const res = await submitBacktest({ config: config.value });
    router.push(`/backtests/${res.backtest_id}`);
  } catch (err) {
    console.error('Failed to submit backtest:', err);
  }
};
</script>
