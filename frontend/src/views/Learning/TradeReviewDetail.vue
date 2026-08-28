<template>
  <div class="trade-review-detail">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><View /></el-icon>
        交易归因复盘与证据绑定
      </h1>
      <p class="page-description">
        AI 复盘交易归因、可控性评估与证据链
      </p>
    </div>

    <div v-loading="loading" class="content-wrapper">
      <el-card v-if="review" class="review-card" shadow="never">
        <!-- 头部信息 -->
        <div class="review-header">
          <div class="header-left">
            <span class="symbol">{{ review.symbol }}</span>
            <el-divider direction="vertical" />
            <span class="trade-id">Trade ID: {{ review.trade_id }}</span>
          </div>
          <el-tag :type="getConfidenceType(review.confidence)" size="small" effect="plain">
            {{ review.confidence?.toUpperCase() }}
          </el-tag>
        </div>

        <el-divider />

        <!-- AI 复盘摘要 -->
        <div class="section-block">
          <h3 class="section-title">AI 复盘摘要</h3>
          <div class="section-content">{{ review.summary }}</div>
        </div>

        <!-- 归因诊断 -->
        <div class="section-block">
          <h3 class="section-title">
            归因诊断与可控性评估
            <span class="score-tag">Score: {{ (review.controllability_score * 100).toFixed(0) }}%</span>
          </h3>
          <div class="section-content">{{ review.diagnosis }}</div>
        </div>

        <!-- 证据展示 -->
        <el-row :gutter="24" class="evidence-row">
          <el-col :xs="24" :sm="12">
            <div class="evidence-block supporting">
              <h4 class="evidence-title">支持证据 (Supporting Evidence)</h4>
              <ul class="evidence-list">
                <li v-for="(ev, idx) in review.grounding.supporting_evidence" :key="`s-${idx}`">{{ ev }}</li>
                <li v-if="!review.grounding.supporting_evidence?.length" class="empty-item">无支持证据</li>
              </ul>
            </div>
          </el-col>
          <el-col :xs="24" :sm="12">
            <div class="evidence-block counter">
              <h4 class="evidence-title">反例基准 (Counter Evidence)</h4>
              <ul class="evidence-list">
                <li v-for="(ev, idx) in review.grounding.counter_evidence" :key="`c-${idx}`">{{ ev }}</li>
                <li v-if="!review.grounding.counter_evidence?.length" class="empty-item">无反例基准</li>
              </ul>
            </div>
          </el-col>
        </el-row>
      </el-card>
      <el-empty v-else-if="!loading" description="未找到交易复盘" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { View } from '@element-plus/icons-vue'
import { getAITradeReview } from '../../api/learning'
import type { AITradeReview } from '../../types/learning'

const route = useRoute()
const tradeId = route.params.id as string
const review = ref<AITradeReview | null>(null)
const loading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    review.value = await getAITradeReview(tradeId)
  } catch (err) {
    console.error('Failed to load trade review:', err)
    ElMessage.error('加载交易复盘失败')
  } finally {
    loading.value = false
  }
})

const getConfidenceType = (conf: string) => {
  switch (conf) {
    case 'high': return 'success'
    case 'medium': return 'primary'
    case 'low': return 'warning'
    default: return 'danger'
  }
}
</script>

<style lang="scss" scoped>
.trade-review-detail {
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

  .review-card {
    .review-header {
      display: flex;
      justify-content: space-between;
      align-items: center;

      .header-left {
        display: flex;
        align-items: center;

        .symbol {
          font-size: 18px;
          font-weight: 700;
          color: var(--el-text-color-primary);
        }

        .trade-id {
          font-size: 13px;
          color: var(--el-text-color-regular);
        }
      }
    }

    .section-block {
      margin-bottom: 20px;

      .section-title {
        display: flex;
        align-items: center;
        gap: 12px;
        margin: 0 0 8px 0;
        font-size: 15px;
        font-weight: 600;
        color: var(--el-text-color-primary);

        .score-tag {
          padding: 2px 8px;
          background: var(--el-color-primary-light-9);
          color: var(--el-color-primary);
          border-radius: 4px;
          font-size: 12px;
        }
      }

      .section-content {
        padding: 12px 16px;
        background: var(--el-fill-color-light);
        border-radius: 6px;
        color: var(--el-text-color-primary);
        font-size: 14px;
        line-height: 1.6;
      }
    }

    .evidence-row {
      margin-top: 8px;

      .evidence-block {
        padding: 16px;
        border-radius: 6px;
        border: 1px solid var(--el-border-color-lighter);

        &.supporting {
          background: var(--el-color-success-light-9);
          border-color: var(--el-color-success-light-7);
        }

        &.counter {
          background: var(--el-color-danger-light-9);
          border-color: var(--el-color-danger-light-7);
        }

        .evidence-title {
          margin: 0 0 12px 0;
          font-size: 14px;
          font-weight: 600;

          .supporting & {
            color: var(--el-color-success);
          }

          .counter & {
            color: var(--el-color-danger);
          }
        }

        .evidence-list {
          margin: 0;
          padding-left: 20px;
          font-size: 13px;
          color: var(--el-text-color-regular);
          line-height: 1.8;

          .empty-item {
            list-style: none;
            margin-left: -20px;
            color: var(--el-text-color-placeholder);
            font-style: italic;
          }
        }
      }
    }
  }
}
</style>
