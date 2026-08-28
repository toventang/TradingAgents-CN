<template>
  <div class="skill-test">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><VideoPlay /></el-icon>
        Skill 沙箱运行测试
      </h1>
      <p class="page-description">
        在隔离沙箱中执行 Skill，验证输入输出与执行耗时
      </p>
    </div>

    <div v-loading="loading" class="content-wrapper">
      <el-card v-if="skill" class="test-card" shadow="never">
        <!-- Skill 信息 -->
        <div class="skill-info">
          <h2 class="skill-name">{{ skill.name }}</h2>
          <p class="skill-description">{{ skill.description }}</p>
        </div>

        <el-divider />

        <!-- 输入参数 -->
        <div class="section-block">
          <h3 class="section-title">输入参数 (JSON 格式)</h3>
          <el-input
            v-model="inputsJson"
            type="textarea"
            :rows="6"
            class="code-input"
          />
        </div>

        <div class="action-bar">
          <el-button type="primary" :icon="VideoPlay" :loading="running" @click="onRun">
            在沙箱中运行
          </el-button>
        </div>

        <!-- 执行结果 -->
        <div v-if="execResult" class="result-block">
          <h3 class="section-title">执行结果</h3>
          <div class="result-box" :class="execResult.success ? 'success' : 'error'">
            <div class="result-row">
              <span class="result-label">状态:</span>
              <el-tag :type="execResult.success ? 'success' : 'danger'" size="small" effect="dark">
                {{ execResult.success ? 'SUCCESS' : 'FAILED' }}
              </el-tag>
            </div>
            <div class="result-row">
              <span class="result-label">耗时:</span>
              <span class="result-value">{{ execResult.execution_time_ms.toFixed(2) }} ms</span>
            </div>

            <div v-if="execResult.success" class="output-section">
              <span class="result-label">输出数据:</span>
              <pre class="output-pre">{{ JSON.stringify(execResult.result, null, 2) }}</pre>
            </div>
            <div v-else class="error-section">
              <span class="result-label">错误日志:</span>
              <pre class="output-pre error">{{ execResult.error_message }}</pre>
            </div>
          </div>
        </div>
      </el-card>
      <el-empty v-else-if="!loading" description="未找到 Skill" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { VideoPlay } from '@element-plus/icons-vue'
import { getSkill, executeSkill } from '../../api/skills'
import type { Skill, SkillExecutionResult } from '../../types/skill'

const route = useRoute()
const skillId = route.params.id as string
const skill = ref<Skill | null>(null)
const inputsJson = ref('{\n  "returns_20d": 0.08,\n  "volatility_20d": 0.15\n}')
const execResult = ref<SkillExecutionResult | null>(null)
const loading = ref(false)
const running = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    const res = await getSkill(skillId)
    skill.value = res.skill
  } catch (err) {
    console.error('Failed to load skill:', err)
    ElMessage.error('加载 Skill 失败')
  } finally {
    loading.value = false
  }
})

const onRun = async () => {
  let parsed = {}
  try {
    parsed = JSON.parse(inputsJson.value)
  } catch (err) {
    ElMessage.error('输入参数 JSON 格式非法')
    return
  }

  running.value = true
  try {
    execResult.value = await executeSkill(skillId, parsed)
  } catch (err) {
    console.error('Failed to execute skill:', err)
    ElMessage.error('Skill 执行失败')
  } finally {
    running.value = false
  }
}
</script>

<style lang="scss" scoped>
.skill-test {
  max-width: 1000px;
  margin: 0 auto;

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

  .test-card {
    .skill-info {
      .skill-name {
        margin: 0 0 8px 0;
        font-size: 20px;
        font-weight: 600;
        color: var(--el-text-color-primary);
      }

      .skill-description {
        margin: 0;
        font-size: 14px;
        color: var(--el-text-color-regular);
      }
    }

    .section-block {
      margin-bottom: 20px;

      .section-title {
        margin: 0 0 12px 0;
        font-size: 15px;
        font-weight: 600;
        color: var(--el-text-color-primary);
      }
    }

    .action-bar {
      margin-bottom: 24px;
    }

    .result-block {
      .section-title {
        margin: 0 0 12px 0;
        font-size: 15px;
        font-weight: 600;
        color: var(--el-text-color-primary);
      }

      .result-box {
        padding: 16px;
        border-radius: 6px;
        border: 1px solid var(--el-border-color);

        &.success {
          background: var(--el-color-success-light-9);
          border-color: var(--el-color-success-light-7);
        }

        &.error {
          background: var(--el-color-danger-light-9);
          border-color: var(--el-color-danger-light-7);
        }

        .result-row {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 12px;

          .result-label {
            font-size: 13px;
            font-weight: 600;
            color: var(--el-text-color-primary);
          }

          .result-value {
            font-size: 13px;
            color: var(--el-text-color-regular);
          }
        }

        .output-section,
        .error-section {
          margin-top: 12px;

          .result-label {
            display: block;
            margin-bottom: 8px;
            font-size: 13px;
            font-weight: 600;
            color: var(--el-text-color-primary);
          }

          .output-pre {
            margin: 0;
            padding: 12px;
            background: var(--el-bg-color);
            border: 1px solid var(--el-border-color-lighter);
            border-radius: 4px;
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
            font-size: 12px;
            line-height: 1.6;
            overflow-x: auto;

            &.error {
              color: var(--el-color-danger);
            }
          }
        }
      }
    }
  }

  :deep(.code-input) {
    textarea {
      font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
      font-size: 13px;
      line-height: 1.6;
    }
  }
}
</style>
