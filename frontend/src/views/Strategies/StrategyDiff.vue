<template>
  <div class="strategy-diff">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Switch /></el-icon>
        策略版本对比 (Diff)
      </h1>
      <p class="page-description">
        选择两个版本进行参数、规则与选股宇宙的差异对比
      </p>
    </div>

    <!-- 版本选择 -->
    <el-card class="filter-card" shadow="never">
      <el-form :inline="true" class="filter-form">
        <el-form-item label="基准版本 v1">
          <el-input-number v-model="v1" :min="1" controls-position="right" />
        </el-form-item>
        <el-form-item label="对比版本 v2">
          <el-input-number v-model="v2" :min="1" controls-position="right" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" :loading="loading" @click="onCompare">开始对比</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 差异结果 -->
    <div v-if="diffResult" v-loading="loading" class="diff-result">
      <el-card class="diff-section" shadow="never">
        <template #header>
          <div class="card-header">
            <h3>参数差异 (Parameters)</h3>
          </div>
        </template>
        <pre class="json-block">{{ JSON.stringify(diffResult.parameter_diffs, null, 2) }}</pre>
      </el-card>

      <el-card class="diff-section" shadow="never">
        <template #header>
          <div class="card-header">
            <h3>选购规则差异 (Rules)</h3>
          </div>
        </template>
        <pre class="json-block">{{ JSON.stringify(diffResult.rule_diffs, null, 2) }}</pre>
      </el-card>

      <el-card class="diff-section" shadow="never">
        <template #header>
          <div class="card-header">
            <h3>选股宇宙差异 (Universe)</h3>
          </div>
        </template>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="新增股票">
            <el-tag
              v-for="sym in diffResult.universe_diffs.added_symbols"
              :key="sym"
              type="success"
              size="small"
              class="symbol-tag"
            >
              {{ sym }}
            </el-tag>
            <span v-if="!diffResult.universe_diffs.added_symbols.length" class="empty-text">无</span>
          </el-descriptions-item>
          <el-descriptions-item label="移除股票">
            <el-tag
              v-for="sym in diffResult.universe_diffs.removed_symbols"
              :key="sym"
              type="danger"
              size="small"
              class="symbol-tag"
            >
              {{ sym }}
            </el-tag>
            <span v-if="!diffResult.universe_diffs.removed_symbols.length" class="empty-text">无</span>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>
    </div>
    <el-empty v-else-if="!loading" description="请选择版本后点击「开始对比」" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Switch, Search } from '@element-plus/icons-vue'
import { diffVersions } from '../../api/strategies'

const route = useRoute()
const strategyId = route.params.id as string
const v1 = ref(1)
const v2 = ref(2)
const diffResult = ref<any>(null)
const loading = ref(false)

const onCompare = async () => {
  loading.value = true
  try {
    diffResult.value = await diffVersions(strategyId, v1.value, v2.value)
  } catch (err) {
    console.error('Failed to diff versions:', err)
    ElMessage.error('策略版本对比失败')
  } finally {
    loading.value = false
  }
}
</script>

<style lang="scss" scoped>
.strategy-diff {
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

  .diff-result {
    display: flex;
    flex-direction: column;
    gap: 24px;
  }

  .diff-section {
    .card-header h3 {
      margin: 0;
      font-size: 16px;
      font-weight: 600;
    }
  }

  .json-block {
    margin: 0;
    padding: 16px;
    background: var(--el-fill-color-light);
    border-radius: 4px;
    font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
    font-size: 13px;
    color: var(--el-text-color-regular);
    overflow-x: auto;
  }

  .symbol-tag {
    margin: 0 6px 6px 0;
  }

  .empty-text {
    color: var(--el-text-color-placeholder);
    font-size: 13px;
  }
}
</style>
