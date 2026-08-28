<template>
  <div class="strategy-version-history">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Timer /></el-icon>
        策略版本历史与回退
      </h1>
      <p class="page-description">
        查看策略所有版本并安全回退至任意历史版本
      </p>
    </div>

    <el-card class="history-card" shadow="never" v-loading="loading">
      <template #header>
        <div class="card-header">
          <h3>版本时间线</h3>
          <el-button type="primary" size="small" :icon="Refresh" @click="loadData">刷新</el-button>
        </div>
      </template>

      <el-empty v-if="!loading && versions.length === 0" description="暂无版本历史" />

      <div v-else class="version-list">
        <div v-for="ver in versions" :key="ver.version_id" class="version-item">
          <div class="version-info">
            <div class="version-head">
              <span class="version-num">v{{ ver.version_num }}</span>
              <el-tag v-if="ver.is_published" type="success" size="small">已发布</el-tag>
              <el-tag v-else type="warning" size="small" effect="plain">草稿</el-tag>
            </div>
            <p class="version-message">{{ ver.commit_message || '无提交日志' }}</p>
            <p class="version-time">创建时间: {{ ver.created_at }}</p>
          </div>
          <div class="version-actions">
            <el-button
              type="warning"
              size="small"
              :icon="RefreshLeft"
              @click="onRollback(ver.version_num)"
            >
              回退至此版本
            </el-button>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Timer, Refresh, RefreshLeft } from '@element-plus/icons-vue'
import { getStrategy, rollbackVersion } from '../../api/strategies'
import type { StrategyVersion } from '../../types/strategy'

const route = useRoute()
const versions = ref<StrategyVersion[]>([])
const loading = ref(false)
const strategyId = route.params.id as string

const loadData = async () => {
  loading.value = true
  try {
    const res = await getStrategy(strategyId)
    versions.value = res.versions
  } catch (err) {
    console.error('Failed to load version history:', err)
    ElMessage.error('加载版本历史失败')
  } finally {
    loading.value = false
  }
}

const onRollback = async (verNum: number) => {
  try {
    await ElMessageBox.confirm(
      `确定要安全回退至版本 v${verNum} 吗？`,
      '版本回退确认',
      {
        confirmButtonText: '确认回退',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch {
    return
  }

  try {
    await rollbackVersion(strategyId, verNum, `Rollback to v${verNum}`)
    ElMessage.success(`成功回退至版本 v${verNum}`)
    await loadData()
  } catch (err) {
    console.error('Failed to rollback version:', err)
    ElMessage.error('版本回退失败')
  }
}

onMounted(() => {
  loadData()
})
</script>

<style lang="scss" scoped>
.strategy-version-history {
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

  .history-card {
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

    .version-list {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    .version-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      padding: 16px;
      background: var(--el-fill-color-light);
      border-radius: 6px;
      border: 1px solid var(--el-border-color-lighter);

      .version-info {
        flex: 1;
      }

      .version-head {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 6px;

        .version-num {
          font-size: 16px;
          font-weight: 700;
          color: var(--el-text-color-primary);
        }
      }

      .version-message {
        margin: 0 0 4px 0;
        font-size: 14px;
        color: var(--el-text-color-regular);
      }

      .version-time {
        margin: 0;
        font-size: 12px;
        color: var(--el-text-color-placeholder);
      }

      .version-actions {
        flex-shrink: 0;
      }
    }
  }
}
</style>
