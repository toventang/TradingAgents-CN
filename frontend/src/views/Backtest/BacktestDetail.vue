<template>
  <div class="backtest-detail">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><DataLine /></el-icon>
        回测定量分析与收益曲线
      </h1>
      <p class="page-description">
        查看回测绩效指标与成交撮合明细
      </p>
    </div>

    <div v-loading="loading" class="content-wrapper">
      <div v-if="result">
        <!-- 绩效指标卡片 -->
        <el-row v-if="result.metrics" :gutter="24" class="metric-row">
          <el-col :xs="24" :sm="12" :lg="6">
            <el-card class="metric-card" shadow="hover">
              <div class="metric-label">累计收益率</div>
              <div class="metric-value text-success">
                {{ (result.metrics.total_return * 100).toFixed(2) }}%
              </div>
            </el-card>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="6">
            <el-card class="metric-card" shadow="hover">
              <div class="metric-label">年化收益率</div>
              <div class="metric-value text-success">
                {{ (result.metrics.annualized_return * 100).toFixed(2) }}%
              </div>
            </el-card>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="6">
            <el-card class="metric-card" shadow="hover">
              <div class="metric-label">最大回撤</div>
              <div class="metric-value text-danger">
                {{ (result.metrics.max_drawdown * 100).toFixed(2) }}%
              </div>
            </el-card>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="6">
            <el-card class="metric-card" shadow="hover">
              <div class="metric-label">夏普比率</div>
              <div class="metric-value text-primary">
                {{ result.metrics.sharpe_ratio.toFixed(2) }}
              </div>
            </el-card>
          </el-col>
        </el-row>

        <!-- 成交记录明细表格 -->
        <el-card class="fills-card" shadow="never">
          <template #header>
            <div class="card-header">
              <h3>成交撮合明细</h3>
              <el-tag type="info" size="small">{{ result.fills?.length || 0 }} 笔</el-tag>
            </div>
          </template>

          <el-table :data="result.fills" border style="width: 100%" empty-text="暂无成交记录">
            <el-table-column prop="trade_date" label="交易日期" min-width="120" />
            <el-table-column prop="symbol" label="代码" min-width="120">
              <template #default="{ row }">
                <span class="mono">{{ row.symbol }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="side" label="方向" width="100">
              <template #default="{ row }">
                <el-tag :type="row.side === 'buy' ? 'danger' : 'success'" size="small" effect="plain">
                  {{ row.side?.toUpperCase() }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="quantity" label="数量" min-width="120" />
            <el-table-column label="成交价" min-width="120">
              <template #default="{ row }">
                ¥{{ row.execution_price.toFixed(2) }}
              </template>
            </el-table-column>
            <el-table-column label="手续费/规费" min-width="140">
              <template #default="{ row }">
                ¥{{ row.total_cost.toFixed(2) }}
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </div>
      <el-empty v-if="!result && !loading" description="未找到回测结果" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { DataLine } from '@element-plus/icons-vue'
import { getBacktestResult } from '../../api/backtests'

const route = useRoute()
const result = ref<any>(null)
const loading = ref(false)

onMounted(async () => {
  const btId = route.params.id as string
  loading.value = true
  try {
    result.value = await getBacktestResult(btId)
  } catch (err) {
    console.error('Failed to load backtest result:', err)
    ElMessage.error('加载回测结果失败')
  } finally {
    loading.value = false
  }
})
</script>

<style lang="scss" scoped>
.backtest-detail {
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

  .content-wrapper {
    display: flex;
    flex-direction: column;
    gap: 24px;
  }

  .metric-row {
    margin-bottom: 0;
  }

  .metric-card {
    text-align: center;
    margin-bottom: 24px;

    .metric-label {
      font-size: 14px;
      color: var(--el-text-color-regular);
      margin-bottom: 8px;
    }

    .metric-value {
      font-size: 24px;
      font-weight: 700;
      color: var(--el-text-color-primary);

      &.text-success {
        color: var(--el-color-success);
      }

      &.text-danger {
        color: var(--el-color-danger);
      }

      &.text-primary {
        color: var(--el-color-primary);
      }
    }
  }

  .fills-card {
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;

      h3 {
        margin: 0;
        font-size: 16px;
        font-weight: 600;
      }
    }
  }

  .mono {
    font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
    font-size: 13px;
  }
}
</style>
