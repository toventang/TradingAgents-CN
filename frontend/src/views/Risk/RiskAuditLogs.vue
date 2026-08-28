<template>
  <div class="risk-audit-logs">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Document /></el-icon>
        风控评估与审计日志
      </h1>
      <p class="page-description">
        查询所有风控评估决策的审计轨迹与违规明细
      </p>
    </div>

    <!-- 审计日志表格 -->
    <el-card class="logs-card" shadow="never">
      <template #header>
        <div class="card-header">
          <h3>评估日志</h3>
          <el-button type="primary" size="small" :icon="Refresh" @click="loadData" :loading="loading">
            刷新
          </el-button>
        </div>
      </template>

      <el-table :data="logs" v-loading="loading" style="width: 100%" empty-text="暂无评估日志">
        <el-table-column prop="evaluation_id" label="评估 ID" min-width="180">
          <template #default="{ row }">
            <span class="mono">{{ row.evaluation_id }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="evaluated_at" label="评估时间" min-width="160" />
        <el-table-column prop="decision" label="决策" width="120">
          <template #default="{ row }">
            <el-tag :type="row.decision === 'rejected' ? 'danger' : 'success'" size="small">
              {{ row.decision?.toUpperCase() }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="违规项数量" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="(row.violations?.length || 0) > 0 ? 'warning' : 'info'" size="small" effect="plain">
              {{ row.violations?.length || 0 }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, Refresh } from '@element-plus/icons-vue'
import { listRiskAuditLogs } from '../../api/risk'
import type { RiskAuditLog } from '../../types/risk'

const logs = ref<RiskAuditLog[]>([])
const loading = ref(false)

const loadData = async () => {
  loading.value = true
  try {
    logs.value = await listRiskAuditLogs()
  } catch (err) {
    console.error('Failed to load risk audit logs:', err)
    ElMessage.error('加载风控审计日志失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadData()
})
</script>

<style lang="scss" scoped>
.risk-audit-logs {
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

  .logs-card {
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
