<template>
  <div class="backtest-comparison">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><DataLine /></el-icon>
        多回测定量横向对比
      </h1>
      <p class="page-description">
        输入多个回测 ID，对比绩效指标与收益曲线
      </p>
    </div>

    <!-- 输入对比 ID -->
    <el-card class="filter-card" shadow="never">
      <el-form label-position="top">
        <el-form-item label="输入要对比的回测 ID (逗号分隔)">
          <el-input
            v-model="idsInput"
            placeholder="如：bt_001, bt_002"
            clearable
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" :loading="loading" @click="onCompare">
            开始对比
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 对比结果 -->
    <el-card v-if="comparisonData" class="result-card" shadow="never" v-loading="loading">
      <template #header>
        <div class="card-header">
          <h3>绩效指标横向对比</h3>
        </div>
      </template>

      <el-table :data="comparisonData.summary" border style="width: 100%">
        <el-table-column prop="backtest_id" label="回测 ID" min-width="160">
          <template #default="{ row }">
            <span class="mono">{{ row.backtest_id }}</span>
          </template>
        </el-table-column>
        <el-table-column label="累计收益率" min-width="140">
          <template #default="{ row }">
            <span class="text-success">{{ (row.total_return * 100).toFixed(2) }}%</span>
          </template>
        </el-table-column>
        <el-table-column label="年化收益率" min-width="140">
          <template #default="{ row }">
            <span class="text-success">{{ (row.annualized_return * 100).toFixed(2) }}%</span>
          </template>
        </el-table-column>
        <el-table-column label="最大回撤" min-width="140">
          <template #default="{ row }">
            <span class="text-danger">{{ (row.max_drawdown * 100).toFixed(2) }}%</span>
          </template>
        </el-table-column>
        <el-table-column label="夏普比率" min-width="120">
          <template #default="{ row }">
            <span class="text-primary">{{ row.sharpe_ratio.toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="换手率" min-width="120">
          <template #default="{ row }">
            {{ row.turnover_rate.toFixed(2) }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-empty v-else-if="!loading" description="请输入回测 ID 后点击「开始对比」" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { DataLine, Search } from '@element-plus/icons-vue'
import { compareBacktests } from '../../api/backtests'

const idsInput = ref('')
const comparisonData = ref<any>(null)
const loading = ref(false)

const onCompare = async () => {
  const ids = idsInput.value.split(',').map(s => s.trim()).filter(Boolean)
  if (!ids.length) {
    ElMessage.warning('请输入至少一个回测 ID')
    return
  }
  loading.value = true
  try {
    comparisonData.value = await compareBacktests(ids)
  } catch (err) {
    console.error('Failed to compare backtests:', err)
    ElMessage.error('回测对比失败')
  } finally {
    loading.value = false
  }
}
</script>

<style lang="scss" scoped>
.backtest-comparison {
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

  .filter-card {
    margin-bottom: 24px;
  }

  .result-card {
    .card-header h3 {
      margin: 0;
      font-size: 16px;
      font-weight: 600;
    }
  }

  .mono {
    font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
    font-size: 13px;
  }

  .text-success {
    color: var(--el-color-success);
    font-weight: 600;
  }

  .text-danger {
    color: var(--el-color-danger);
    font-weight: 600;
  }

  .text-primary {
    color: var(--el-color-primary);
    font-weight: 600;
  }
}
</style>
