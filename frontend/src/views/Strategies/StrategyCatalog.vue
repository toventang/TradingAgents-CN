<template>
  <div class="strategy-catalog">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-content">
        <div class="title-section">
          <h1 class="page-title">
            <el-icon class="title-icon"><DataAnalysis /></el-icon>
            策略中心与模版目录
          </h1>
          <p class="page-description">
            浏览系统模版与自定义策略，克隆并定制你的策略组合
          </p>
        </div>
        <div class="header-actions">
          <el-button type="primary" :icon="Refresh" :loading="loading" @click="loadData">刷新</el-button>
        </div>
      </div>
    </div>

    <!-- 策略卡片列表 -->
    <el-row :gutter="24" v-loading="loading">
      <el-col v-for="strat in strategies" :key="strat.strategy_id" :xs="24" :sm="12" :lg="8" class="card-col">
        <el-card class="strategy-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <span class="strategy-name">{{ strat.name }}</span>
              <el-tag v-if="strat.is_system_template" type="primary" size="small">系统模版</el-tag>
              <el-tag v-else type="success" size="small">自定义策略</el-tag>
            </div>
          </template>

          <p class="strategy-desc">{{ strat.description || '无策略描述' }}</p>

          <div class="strategy-meta">
            <span>状态: <el-tag :type="getStatusType(strat.status)" size="small" effect="plain">{{ strat.status }}</el-tag></span>
            <span>最新版本: <el-tag size="small" effect="plain">v{{ strat.latest_version_num }}</el-tag></span>
          </div>

          <div class="card-actions">
            <el-button type="primary" size="small" :icon="CopyDocument" @click="onClone(strat.strategy_id)">
              克隆此策略
            </el-button>
          </div>
        </el-card>
      </el-col>
      <el-col :span="24" v-if="!loading && strategies.length === 0">
        <el-empty description="暂无可用策略" />
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { DataAnalysis, Refresh, CopyDocument } from '@element-plus/icons-vue'
import { listStrategies, cloneStrategy } from '../../api/strategies'
import type { Strategy } from '../../types/strategy'

const strategies = ref<Strategy[]>([])
const loading = ref(false)

const loadData = async () => {
  loading.value = true
  try {
    strategies.value = await listStrategies(true)
  } catch (err) {
    console.error('Failed to load strategies:', err)
    ElMessage.error('加载策略列表失败')
  } finally {
    loading.value = false
  }
}

const onClone = async (stratId: string) => {
  try {
    await cloneStrategy(stratId, {})
    ElMessage.success('策略克隆成功')
    await loadData()
  } catch (err) {
    console.error('Failed to clone strategy:', err)
    ElMessage.error('策略克隆失败')
  }
}

const getStatusType = (status: string) => {
  switch (status) {
    case 'active': return 'success'
    case 'draft': return 'info'
    case 'deprecated': return 'warning'
    default: return 'info'
  }
}

onMounted(() => {
  loadData()
})
</script>

<style lang="scss" scoped>
.strategy-catalog {
  .page-header {
    margin-bottom: 24px;

    .header-content {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
    }

    .page-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 24px;
      font-weight: 600;
      color: var(--el-text-color-primary);
      margin: 0 0 8px 0;

      .title-icon {
        color: var(--el-color-primary);
      }
    }

    .page-description {
      color: var(--el-text-color-regular);
      margin: 0;
    }
  }

  .card-col {
    margin-bottom: 24px;
  }

  .strategy-card {
    height: 100%;

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;

      .strategy-name {
        font-size: 16px;
        font-weight: 600;
        color: var(--el-text-color-primary);
      }
    }

    .strategy-desc {
      color: var(--el-text-color-regular);
      font-size: 14px;
      line-height: 1.6;
      min-height: 44px;
      margin: 0 0 12px 0;
    }

    .strategy-meta {
      display: flex;
      flex-direction: column;
      gap: 6px;
      font-size: 13px;
      color: var(--el-text-color-secondary);
      margin-bottom: 16px;
    }

    .card-actions {
      display: flex;
      justify-content: flex-end;
    }
  }
}
</style>
