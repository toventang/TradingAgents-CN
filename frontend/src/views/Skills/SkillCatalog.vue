<template>
  <div class="skill-catalog">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-content">
        <div class="title-section">
          <h1 class="page-title">
            <el-icon class="title-icon"><Cpu /></el-icon>
            Skill 技能中心与能力库
          </h1>
          <p class="page-description">
            浏览系统与自定义 Skill，进入沙箱测试与版本管理
          </p>
        </div>
        <div class="header-actions">
          <el-button type="primary" :icon="Plus" @click="$router.push('/skills/create')">
            创建自定义 Skill
          </el-button>
        </div>
      </div>
    </div>

    <el-row :gutter="24" v-loading="loading">
      <el-col v-for="sk in skills" :key="sk.skill_id" :xs="24" :sm="12" :lg="8" class="card-col">
        <el-card class="skill-card" shadow="hover">
          <div class="card-header">
            <span class="skill-name">{{ sk.name }}</span>
            <el-tag v-if="sk.is_system_skill" type="warning" size="small" effect="plain">系统 Skill</el-tag>
            <el-tag v-else type="success" size="small" effect="plain">自定义</el-tag>
          </div>

          <p class="skill-description">{{ sk.description || '无描述' }}</p>

          <div class="skill-meta">
            <span class="meta-item">
              类型: <strong class="mono uppercase">{{ sk.skill_type }}</strong>
            </span>
            <span class="meta-item">版本: v{{ sk.latest_version_num }}</span>
          </div>

          <div class="card-footer">
            <el-button type="primary" size="small" :icon="VideoPlay" @click="$router.push(`/skills/${sk.skill_id}/test`)">
              进入沙箱测试
            </el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
    <el-empty v-if="!loading && !skills.length" description="暂无 Skill" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Cpu, Plus, VideoPlay } from '@element-plus/icons-vue'
import { listSkills } from '../../api/skills'
import type { Skill } from '../../types/skill'

const skills = ref<Skill[]>([])
const loading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    skills.value = await listSkills(true)
  } catch (err) {
    console.error('Failed to load skills:', err)
    ElMessage.error('加载 Skill 列表失败')
  } finally {
    loading.value = false
  }
})
</script>

<style lang="scss" scoped>
.skill-catalog {
  .page-header {
    margin-bottom: 24px;

    .header-content {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      flex-wrap: wrap;
    }

    .title-section {
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
  }

  .card-col {
    margin-bottom: 24px;
  }

  .skill-card {
    height: 100%;

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;

      .skill-name {
        font-size: 16px;
        font-weight: 600;
        color: var(--el-text-color-primary);
      }
    }

    .skill-description {
      color: var(--el-text-color-regular);
      font-size: 13px;
      line-height: 1.6;
      margin: 0 0 16px 0;
      min-height: 40px;
    }

    .skill-meta {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
      padding: 8px 12px;
      background: var(--el-fill-color-light);
      border-radius: 4px;

      .meta-item {
        font-size: 12px;
        color: var(--el-text-color-secondary);
      }
    }

    .card-footer {
      display: flex;
      justify-content: flex-end;
    }
  }

  .mono {
    font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
    font-size: 12px;
  }

  .uppercase {
    text-transform: uppercase;
  }
}
</style>
