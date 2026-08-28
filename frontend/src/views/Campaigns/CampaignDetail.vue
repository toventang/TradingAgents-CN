<template>
  <div class="campaign-detail">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Promotion /></el-icon>
        Campaign 运行详情
      </h1>
      <p class="page-description">
        查看 Campaign 基本信息、运行控制与定量绩效
      </p>
    </div>

    <div v-loading="loading" class="content-wrapper">
      <!-- 基本信息 -->
      <el-card v-if="campaign" class="info-card" shadow="never">
        <template #header>
          <div class="card-header">
            <div class="title-block">
              <h3>{{ campaign.name }}</h3>
              <span class="campaign-id">ID: {{ campaign.campaign_id }}</span>
            </div>
            <div class="header-actions">
              <el-tag :type="getStatusType(campaign.status)" size="default" effect="dark">
                {{ campaign.status?.toUpperCase() }}
              </el-tag>
              <el-button
                v-if="campaign.status === 'draft'"
                type="success"
                size="small"
                :icon="Check"
                @click="onActivate"
              >
                校验并激活
              </el-button>
              <el-button
                v-if="campaign.status === 'activated'"
                type="warning"
                size="small"
                :icon="VideoPause"
                @click="onPause"
              >
                暂停
              </el-button>
              <el-button
                v-if="campaign.status === 'paused'"
                type="success"
                size="small"
                :icon="VideoPlay"
                @click="onResume"
              >
                确认恢复
              </el-button>
              <el-button
                v-if="campaign.status !== 'stopped'"
                type="danger"
                size="small"
                :icon="CircleClose"
                @click="onStop"
              >
                终止
              </el-button>
            </div>
          </div>
        </template>

        <el-descriptions :column="3" border>
          <el-descriptions-item label="绑定策略">
            <span class="mono">{{ campaign.strategy_id }} (v{{ campaign.strategy_version_num }})</span>
          </el-descriptions-item>
          <el-descriptions-item label="初始资金">
            ¥{{ campaign.initial_allocation_cash.toLocaleString() }}
          </el-descriptions-item>
          <el-descriptions-item label="开始日期">
            {{ campaign.start_date }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 绩效卡片 -->
      <el-card v-if="perf" class="perf-card" shadow="never">
        <template #header>
          <div class="card-header">
            <h3>定量绩效与机会成本分析</h3>
          </div>
        </template>

        <el-row :gutter="24">
          <el-col :xs="24" :sm="12" :lg="6">
            <div class="metric-item">
              <div class="metric-label">累计收益率</div>
              <div class="metric-value text-success">
                {{ (perf.metrics.total_return * 100).toFixed(2) }}%
              </div>
            </div>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="6">
            <div class="metric-item">
              <div class="metric-label">最大回撤</div>
              <div class="metric-value text-danger">
                {{ (perf.metrics.max_drawdown * 100).toFixed(2) }}%
              </div>
            </div>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="6">
            <div class="metric-item">
              <div class="metric-label">超越基准超额</div>
              <div class="metric-value text-primary">
                {{ (perf.opportunity_cost.benchmark_excess * 100).toFixed(2) }}%
              </div>
            </div>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="6">
            <div class="metric-item">
              <div class="metric-label">超越纯现金超额</div>
              <div class="metric-value text-info">
                {{ (perf.opportunity_cost.cash_baseline_excess * 100).toFixed(2) }}%
              </div>
            </div>
          </el-col>
        </el-row>
      </el-card>

      <el-empty v-if="!campaign && !loading" description="未找到 Campaign" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Promotion,
  Check,
  VideoPause,
  VideoPlay,
  CircleClose
} from '@element-plus/icons-vue'
import {
  getCampaign,
  activateCampaign,
  pauseCampaign,
  resumeCampaign,
  stopCampaign,
  getCampaignPerformance
} from '../../api/campaigns'
import type { Campaign } from '../../types/campaign'

const route = useRoute()
const campaignId = route.params.id as string
const campaign = ref<Campaign | null>(null)
const perf = ref<any>(null)
const loading = ref(false)

const loadData = async () => {
  loading.value = true
  try {
    campaign.value = await getCampaign(campaignId)
    perf.value = await getCampaignPerformance(campaignId)
  } catch (err) {
    console.error('Failed to load campaign detail:', err)
    ElMessage.error('加载 Campaign 详情失败')
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

const onActivate = async () => {
  try {
    await activateCampaign(campaignId)
    ElMessage.success('Campaign 校验通过，已成功激活运行')
    await loadData()
  } catch (err: any) {
    ElMessage.error(`激活失败: ${err.response?.data?.detail || err.message}`)
  }
}

const onPause = async () => {
  try {
    await pauseCampaign(campaignId)
    ElMessage.success('Campaign 已暂停')
    await loadData()
  } catch (err) {
    console.error('Failed to pause campaign:', err)
    ElMessage.error('暂停失败')
  }
}

const onResume = async () => {
  try {
    const { value: note } = await ElMessageBox.prompt('请输入恢复确认备注', '确认恢复', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      inputPlaceholder: 'Owner confirmed'
    })
    await resumeCampaign(campaignId, note || 'Owner confirmed')
    ElMessage.success('Campaign 已恢复运行')
    await loadData()
  } catch (err) {
    if (err === 'cancel') return
    console.error('Failed to resume campaign:', err)
    ElMessage.error('恢复失败')
  }
}

const onStop = async () => {
  try {
    await ElMessageBox.confirm('确定要终止当前 Campaign 吗？', '终止确认', {
      confirmButtonText: '确认终止',
      cancelButtonText: '取消',
      type: 'warning'
    })
  } catch {
    return
  }
  try {
    await stopCampaign(campaignId)
    ElMessage.success('Campaign 已终止')
    await loadData()
  } catch (err) {
    console.error('Failed to stop campaign:', err)
    ElMessage.error('终止失败')
  }
}

onMounted(() => {
  loadData()
})
</script>

<style lang="scss" scoped>
.campaign-detail {
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

  .info-card,
  .perf-card {
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;

      .title-block {
        display: flex;
        flex-direction: column;
        gap: 4px;

        h3 {
          margin: 0;
          font-size: 18px;
          font-weight: 600;
        }

        .campaign-id {
          font-size: 13px;
          color: var(--el-text-color-secondary);
        }
      }

      .header-actions {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }

      h3 {
        margin: 0;
        font-size: 16px;
        font-weight: 600;
      }
    }
  }

  .metric-item {
    text-align: center;
    padding: 16px;
    background: var(--el-fill-color-light);
    border-radius: 6px;
    border: 1px solid var(--el-border-color-lighter);
    margin-bottom: 16px;

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

      &.text-info {
        color: var(--el-color-info);
      }
    }
  }

  .mono {
    font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
    font-size: 13px;
  }
}
</style>
