<template>
  <div class="skill-editor">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><EditPen /></el-icon>
        创建自定义 Python Skill
      </h1>
      <p class="page-description">
        编辑 Skill 名称、类别与 Python 代码 (需定义 run(inputs) 函数)
      </p>
    </div>

    <el-card class="editor-card" shadow="never" v-loading="submitting">
      <el-form :model="form" label-width="120px" label-position="right">
        <el-form-item label="Skill 名称" required>
          <el-input v-model="form.name" placeholder="如：自定义动量评分器" />
        </el-form-item>

        <el-form-item label="描述">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="2"
            placeholder="简要说明此 Skill 的功能"
          />
        </el-form-item>

        <el-form-item label="Skill 类别">
          <el-select v-model="form.skill_type" placeholder="选择类别" style="width: 100%">
            <el-option label="Market (行情分析)" value="market" />
            <el-option label="Fundamentals (基本面分析)" value="fundamentals" />
            <el-option label="Technical (技术面分析)" value="technical" />
            <el-option label="Sentiment (舆情分析)" value="sentiment" />
            <el-option label="Risk (风控分析)" value="risk" />
            <el-option label="Composite (综合打分)" value="composite" />
          </el-select>
        </el-form-item>

        <el-form-item label="Python 代码" required>
          <el-input
            v-model="form.code"
            type="textarea"
            :rows="14"
            class="code-input"
            placeholder="def run(inputs): ..."
          />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :icon="Check" @click="onSubmit">提交保存 Skill</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { EditPen, Check } from '@element-plus/icons-vue'
import { createSkill } from '../../api/skills'

const router = useRouter()
const submitting = ref(false)

const form = ref({
  name: '',
  description: '',
  skill_type: 'market',
  code: `def run(inputs):
    # 沙箱白名单库: math, np, pd, json, datetime
    val = inputs.get('val', 0)
    return {'score': val * 1.5}`
})

const onSubmit = async () => {
  if (!form.value.name || !form.value.code) {
    ElMessage.warning('请填写 Skill 名称和 Python 代码')
    return
  }
  submitting.value = true
  try {
    const res = await createSkill(form.value)
    ElMessage.success('Skill 创建成功')
    router.push(`/skills/${res.skill.skill_id}/test`)
  } catch (err) {
    console.error('Failed to create skill:', err)
    ElMessage.error('创建 Skill 失败')
  } finally {
    submitting.value = false
  }
}
</script>

<style lang="scss" scoped>
.skill-editor {
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

  .editor-card {
    :deep(.code-input) {
      textarea {
        font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
        font-size: 13px;
        line-height: 1.6;
        background: var(--el-fill-color-darker);
        color: var(--el-color-success);
      }
    }
  }
}
</style>
