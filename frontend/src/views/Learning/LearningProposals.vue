<template>
  <div class="learning-proposals">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><MagicStick /></el-icon>
        受控学习提议与策略优化草稿
      </h1>
      <p class="page-description">
        浏览 AI 提议的参数修改项，勾选批准项生成新策略草稿版本（不修改实盘）
      </p>
    </div>

    <div v-loading="loading" class="content-wrapper">
      <div v-if="proposals.length" class="proposals-list">
        <el-card v-for="prop in proposals" :key="prop.proposal_id" class="proposal-card" shadow="never">
          <!-- 提议头部 -->
          <div class="proposal-header">
            <div class="header-left">
              <span class="proposal-id">提议 ID: {{ prop.proposal_id }}</span>
              <el-divider direction="vertical" />
              <span class="strategy-info">绑定策略: {{ prop.strategy_id }}</span>
            </div>
            <el-tag type="warning" size="small" effect="plain">
              样本数: {{ prop.sample_count }} / 5
            </el-tag>
          </div>

          <el-divider />

          <!-- 参数修订对比表 -->
          <div class="section-title">白名单参数修订对比</div>
          <el-table :data="prop.diff_items" border style="width: 100%">
            <el-table-column label="批准" width="70" align="center">
              <template #default="{ row }">
                <el-checkbox v-model="row.approved" />
              </template>
            </el-table-column>
            <el-table-column label="参数路径" min-width="180">
              <template #default="{ row }">
                <span class="mono">{{ row.parameter_path }}</span>
              </template>
            </el-table-column>
            <el-table-column label="当前值" min-width="120">
              <template #default="{ row }">
                <span class="text-regular">{{ row.current_value }}</span>
              </template>
            </el-table-column>
            <el-table-column label="建议优化值" min-width="120">
              <template #default="{ row }">
                <span class="text-success">{{ row.proposed_value }}</span>
              </template>
            </el-table-column>
            <el-table-column label="优化说明" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="text-regular">{{ row.reasoning }}</span>
              </template>
            </el-table-column>
          </el-table>

          <!-- 操作按钮 -->
          <div class="proposal-footer">
            <el-button type="primary" size="small" @click="onApplyDraft(prop)">
              生成新策略草稿 (无自动发布/不修改实盘)
            </el-button>
          </div>
        </el-card>
      </div>
      <el-empty v-else description="暂无学习提议" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { MagicStick } from '@element-plus/icons-vue'
import { listLearningProposals, applyProposalDraft } from '../../api/learning'
import type { LearningProposal } from '../../types/learning'

const proposals = ref<LearningProposal[]>([])
const loading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    proposals.value = await listLearningProposals()
  } catch (err) {
    console.error('Failed to load learning proposals:', err)
    ElMessage.error('加载学习提议失败')
  } finally {
    loading.value = false
  }
})

const onApplyDraft = async (prop: LearningProposal) => {
  const approvedPaths = prop.diff_items.filter(i => i.approved).map(i => i.parameter_path)
  try {
    await applyProposalDraft(prop.proposal_id, approvedPaths)
    ElMessage.success('已成功依据批准修改项生成【新策略草稿版本】！原运行 Campaign 与已发布策略不受影响。')
  } catch (err) {
    console.error('Failed to apply draft:', err)
    ElMessage.error('生成策略草稿失败')
  }
}
</script>

<style lang="scss" scoped>
.learning-proposals {
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

  .proposal-card {
    .proposal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;

      .header-left {
        display: flex;
        align-items: center;

        .proposal-id {
          font-size: 16px;
          font-weight: 600;
          color: var(--el-text-color-primary);
        }

        .strategy-info {
          font-size: 13px;
          color: var(--el-text-color-regular);
        }
      }
    }

    .section-title {
      font-size: 14px;
      font-weight: 600;
      color: var(--el-text-color-primary);
      margin-bottom: 12px;
    }

    .proposal-footer {
      margin-top: 16px;
      display: flex;
      justify-content: flex-end;
    }
  }

  .mono {
    font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
    font-size: 13px;
    font-weight: 600;
    color: var(--el-text-color-primary);
  }

  .text-regular {
    color: var(--el-text-color-regular);
  }

  .text-success {
    color: var(--el-color-success);
    font-weight: 600;
  }
}
</style>
