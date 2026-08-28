<template>
  <div class="backtest-create">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><DataLine /></el-icon>
        发起策略定量回测
      </h1>
      <p class="page-description">
        配置策略、时间区间、资金与成本模型并提交回测任务
      </p>
    </div>

    <el-card class="form-card" shadow="never" v-loading="submitting">
      <el-form :model="config" label-width="160px" label-position="right">
        <div class="section-title">基础参数</div>
        <el-form-item label="策略 ID" required>
          <el-input v-model="config.strategy_id" placeholder="如：sys_tmpl_01_val_mom" />
        </el-form-item>

        <el-row :gutter="24">
          <el-col :xs="24" :sm="12">
            <el-form-item label="开始日期">
              <el-date-picker
                v-model="config.start_date"
                type="date"
                value-format="YYYY-MM-DD"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="结束日期">
              <el-date-picker
                v-model="config.end_date"
                type="date"
                value-format="YYYY-MM-DD"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="24">
          <el-col :xs="24" :sm="12">
            <el-form-item label="初始资金 (RMB)">
              <el-input-number
                v-model="config.initial_capital"
                :min="0"
                :step="100000"
                controls-position="right"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="对比基准">
              <el-input v-model="config.benchmark" placeholder="000300.SH" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider />

        <div class="section-title">券商/账户交易成本模型设置</div>
        <el-row :gutter="24">
          <el-col :xs="24" :sm="8">
            <el-form-item label="佣金比例">
              <el-input-number
                v-model="config.cost_model.commission_rate"
                :min="0"
                :step="0.0001"
                :precision="6"
                controls-position="right"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="8">
            <el-form-item label="最低佣金 (元)">
              <el-input-number
                v-model="config.cost_model.min_commission"
                :min="0"
                :step="0.5"
                :precision="2"
                controls-position="right"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="8">
            <el-form-item label="滑点比例">
              <el-input-number
                v-model="config.cost_model.slippage_rate"
                :min="0"
                :step="0.0005"
                :precision="6"
                controls-position="right"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item>
          <el-button type="primary" :icon="Check" @click="onSubmit">提交回测任务</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { DataLine, Check } from '@element-plus/icons-vue'
import { submitBacktest } from '../../api/backtests'

const router = useRouter()
const submitting = ref(false)

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
})

const onSubmit = async () => {
  submitting.value = true
  try {
    const res = await submitBacktest({ config: config.value })
    ElMessage.success('回测任务已提交')
    router.push(`/backtests/${res.backtest_id}`)
  } catch (err) {
    console.error('Failed to submit backtest:', err)
    ElMessage.error('提交回测任务失败')
  } finally {
    submitting.value = false
  }
}
</script>

<style lang="scss" scoped>
.backtest-create {
  max-width: 1000px;
  margin: 0 auto;

  .page-header {
    margin-bottom: 24px;

    .page-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 24px;
      font-weight: 600;
      color: var(--el-text-color-primary);
      margin: 0 0 8px 0;
    }

    .page-description {
      color: var(--el-text-color-regular);
      margin: 0;
    }
  }

  .form-card {
    .section-title {
      font-size: 16px;
      font-weight: 600;
      color: var(--el-text-color-primary);
      margin-bottom: 16px;
    }
  }
}
</style>
