<template>
  <div class="risk-settings">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Setting /></el-icon>
        风控指标与限制阈值配置
      </h1>
      <p class="page-description">
        维护组合与单券风控阈值、交易制度与流动性约束
      </p>
    </div>

    <el-card class="settings-card" shadow="never" v-loading="saving">
      <el-form :model="config" label-width="200px" label-position="right">
        <!-- 持仓与回撤阈值 -->
        <div class="section-title">持仓与回撤阈值</div>
        <el-row :gutter="24">
          <el-col :xs="24" :sm="12">
            <el-form-item label="单股最大持仓上限 (%)">
              <el-input-number
                v-model="config.max_stock_weight"
                :min="0"
                :max="1"
                :step="0.01"
                :precision="4"
                controls-position="right"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="单行业最大持仓上限 (%)">
              <el-input-number
                v-model="config.max_sector_weight"
                :min="0"
                :max="1"
                :step="0.01"
                :precision="4"
                controls-position="right"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="组合最大回撤阀值 (%)">
              <el-input-number
                v-model="config.max_drawdown_limit"
                :min="0"
                :max="1"
                :step="0.01"
                :precision="4"
                controls-position="right"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="日度 VaR (95%) 限制 (%)">
              <el-input-number
                v-model="config.max_var_95_limit"
                :min="0"
                :max="1"
                :step="0.005"
                :precision="4"
                controls-position="right"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider />

        <!-- 交易制度与流动性约束 -->
        <div class="section-title">交易制度与流动性约束</div>
        <el-form-item label="强制执行 A 股 T+1">
          <el-switch v-model="config.enforce_t_plus_1" />
          <span class="form-tip">结算卖出数量限制</span>
        </el-form-item>
        <el-form-item label="涨停板买入拦截">
          <el-switch v-model="config.block_limit_up_buy" />
          <span class="form-tip">Block Limit-Up Buy</span>
        </el-form-item>
        <el-form-item label="跌停板卖出警告">
          <el-switch v-model="config.block_limit_down_sell" />
          <span class="form-tip">Block Limit-Down Sell</span>
        </el-form-item>

        <el-divider />

        <el-form-item>
          <el-button type="primary" :icon="Check" @click="onSave">保存风控配置</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Setting, Check } from '@element-plus/icons-vue'
import type { RiskConfig } from '../../types/risk'

const saving = ref(false)

const config = ref<RiskConfig>({
  portfolio_id: 'default_portfolio',
  max_stock_weight: 0.10,
  max_sector_weight: 0.30,
  max_drawdown_limit: 0.15,
  max_var_95_limit: 0.03,
  max_adv_participation_rate: 0.05,
  enforce_t_plus_1: true,
  block_limit_up_buy: true,
  block_limit_down_sell: true
})

const onSave = () => {
  saving.value = true
  try {
    localStorage.setItem('risk_config', JSON.stringify(config.value))
    ElMessage.success('风控设置已更新')
  } finally {
    saving.value = false
  }
}
</script>

<style lang="scss" scoped>
.risk-settings {
  max-width: 960px;
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

  .settings-card {
    .section-title {
      font-size: 16px;
      font-weight: 600;
      color: var(--el-text-color-primary);
      margin-bottom: 16px;
    }

    .form-tip {
      margin-left: 12px;
      font-size: 13px;
      color: var(--el-text-color-secondary);
    }
  }
}
</style>
