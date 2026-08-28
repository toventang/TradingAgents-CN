<template>
  <div class="risk-dashboard">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Warning /></el-icon>
        实时风控与合规监控面板
      </h1>
      <p class="page-description">
        监控组合风控决策、违规记录与交易制度执行状态
      </p>
    </div>

    <!-- 状态指标卡片 -->
    <el-row :gutter="24" class="metric-row">
      <el-col :xs="24" :sm="8">
        <el-card class="metric-card" shadow="hover">
          <div class="metric-label">风控状态决策</div>
          <div class="metric-value text-success">APPROVED</div>
          <el-tag type="success" size="small" effect="plain">正常</el-tag>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="8">
        <el-card class="metric-card" shadow="hover">
          <div class="metric-label">活动违规记录</div>
          <div class="metric-value">0 条</div>
          <el-tag type="info" size="small" effect="plain">无违规</el-tag>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="8">
        <el-card class="metric-card" shadow="hover">
          <div class="metric-label">T+1 状态</div>
          <div class="metric-value text-primary">正常受控</div>
          <el-tag type="primary" size="small" effect="plain">已启用</el-tag>
        </el-card>
      </el-col>
    </el-row>

    <!-- 风控拦截与告警明细 -->
    <el-card class="alert-card" shadow="never">
      <template #header>
        <div class="card-header">
          <h3>风控拦截与告警明细</h3>
          <el-tag type="info" size="small">实时</el-tag>
        </div>
      </template>
      <el-empty description="目前暂无活动风控拦截告警。">
        <template #image>
          <el-icon :size="64" color="#909399"><CircleCheck /></el-icon>
        </template>
      </el-empty>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { Warning, CircleCheck } from '@element-plus/icons-vue'
</script>

<style lang="scss" scoped>
.risk-dashboard {
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

  .metric-row {
    margin-bottom: 24px;
  }

  .metric-card {
    text-align: center;

    .metric-label {
      font-size: 14px;
      color: var(--el-text-color-regular);
      margin-bottom: 8px;
    }

    .metric-value {
      font-size: 24px;
      font-weight: 700;
      color: var(--el-text-color-primary);
      margin-bottom: 12px;

      &.text-success {
        color: var(--el-color-success);
      }

      &.text-primary {
        color: var(--el-color-primary);
      }
    }
  }

  .alert-card {
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
}
</style>
