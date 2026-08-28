<template>
  <div class="campaign-list">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-content">
        <div class="title-section">
          <h1 class="page-title">
            <el-icon class="title-icon"><Promotion /></el-icon>
            实盘/模拟 Campaign 运行面板
          </h1>
          <p class="page-description">
            管理模拟与实盘 Campaign，跟踪运行状态与执行进度
          </p>
        </div>
        <div class="header-actions">
          <el-button type="primary" :icon="Plus" @click="$router.push('/campaigns/create')">
            创建新 Campaign
          </el-button>
        </div>
      </div>
    </div>

    <!-- Campaign 卡片列表 -->
    <el-row :gutter="24" v-loading="loading">
      <el-col v-for="c in campaigns" :key="c.campaign_id" :xs="24" :sm="12" :lg="8" class="card-col">
        <el-card class="campaign-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <span class="campaign-name">{{ c.name }}</span>
              <el-tag :type="getStatusType(c.status)" size="small" effect="dark">
                {{ c.status?.toUpperCase() }}
              </el-tag>
            </div>
          </template>

          <p class="campaign-desc">{{ c.description || '无描述' }}</p>

          <el-descriptions :column="1" size="small" class="campaign-meta">
            <el-descriptions-item label="策略 ID">
              <span class="mono">{{ c.strategy_id }} (v{{ c.strategy_version_num }})</span>
            </el-descriptions-item>
            <el-descriptions-item label="分配资金">
              ¥{{ c.initial_allocation_cash.toLocaleString() }}
            </el-descriptions-item>
            <el-descriptions-item label="开始日期">
              {{ c.start_date }}
            </el-descriptions-item>
          </el-descriptions>

          <div class="card-actions">
            <el-button type="primary" size="small" :icon="View" @click="$router.push(`/campaigns/${c.campaign_id}`)">
              查看详情与运行控制
            </el-button>
          </div>
        </el-card>
      </el-col>
      <el-col :span="24" v-if="!loading && campaigns.length === 0">
        <el-empty description="暂无 Campaign">
          <el-button type="primary" :icon="Plus" @click="$router.push('/campaigns/create')">创建新 Campaign</el-button>
        </el-empty>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Promotion, Plus, View } from '@element-plus/icons-vue'
import { listCampaigns } from '../../api/campaigns'
import type { Campaign } from '../../types/campaign'

const campaigns = ref<Campaign[]>([])
const loading = ref(false)

const loadData = async () => {
  loading.value = true
  try {
    campaigns.value = await listCampaigns()
  } catch (err) {
    console.error('Failed to load campaigns:', err)
    ElMessage.error('加载 Campaign 列表失败')
  } finally {
    loading.value = false
  }
}

const getStatusType = (status: string) => {
  switch (status) {
    case 'activated': return 'success'
    case 'paused': return 'warning'
    case 'stopped': return 'danger'
    case 'draft': return 'info'
    default: return 'info'
  }
}

onMounted(() => {
  loadData()
})
</script>

<style lang="scss" scoped>
.campaign-list {
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

  .campaign-card {
    height: 100%;

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;

      .campaign-name {
        font-size: 16px;
        font-weight: 600;
        color: var(--el-text-color-primary);
      }
    }

    .campaign-desc {
      color: var(--el-text-color-regular);
      font-size: 14px;
      line-height: 1.6;
      min-height: 44px;
      margin: 0 0 12px 0;
    }

    .card-actions {
      display: flex;
      justify-content: flex-end;
    }

    .mono {
      font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
      font-size: 13px;
    }
  }
}
</style>
