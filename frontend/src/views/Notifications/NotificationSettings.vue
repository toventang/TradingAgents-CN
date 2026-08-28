<template>
  <div class="notification-settings">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Bell /></el-icon>
        通知渠道与 Webhook 告警设置
      </h1>
      <p class="page-description">
        配置各通知渠道的启用状态、警报级别与推送地址
      </p>
    </div>

    <el-card class="settings-card" shadow="never" v-loading="loading">
      <div v-if="pref" class="channels-wrapper">
        <div v-for="(config, channel) in pref.channels" :key="channel" class="channel-block">
          <div class="channel-header">
            <span class="channel-name">{{ channel?.toString().toUpperCase() }} 渠道</span>
            <el-switch v-model="config.enabled" active-text="启用" inactive-text="停用" />
          </div>

          <el-row :gutter="24" class="config-row">
            <el-col :xs="24" :sm="12">
              <el-form-item label="最严格警报级别" label-width="140px">
                <el-select v-model="config.min_severity" placeholder="选择级别" style="width: 100%">
                  <el-option label="INFO" value="info" />
                  <el-option label="WARNING" value="warning" />
                  <el-option label="CRITICAL" value="critical" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="推送目标地址 / URL" label-width="160px">
                <el-input
                  v-model="config.target_address"
                  placeholder="如：https://hooks.example.com/alerts"
                />
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <el-divider />

        <div class="action-bar">
          <el-button type="primary" :icon="Check" :loading="saving" @click="onSave">
            保存偏好设置
          </el-button>
          <el-button :icon="Promotion" :loading="testing" @click="onTestWebhook">
            测试 Webhook 发送
          </el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Bell, Check, Promotion } from '@element-plus/icons-vue'
import {
  getNotificationPreferences,
  updateNotificationPreferences,
  testWebhook
} from '../../api/notifications'

const pref = ref<any>(null)
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    pref.value = await getNotificationPreferences()
  } catch (err) {
    console.error('Failed to load preferences:', err)
    ElMessage.error('加载通知偏好设置失败')
  } finally {
    loading.value = false
  }
})

const onSave = async () => {
  saving.value = true
  try {
    await updateNotificationPreferences(pref.value)
    ElMessage.success('通知偏好设置已保存')
  } catch (err) {
    console.error('Failed to save preferences:', err)
    ElMessage.error('保存通知偏好设置失败')
  } finally {
    saving.value = false
  }
}

const onTestWebhook = async () => {
  const url = pref.value?.channels?.webhook?.target_address
  if (!url) {
    ElMessage.warning('请先填写 Webhook 推送目标 URL')
    return
  }
  testing.value = true
  try {
    await testWebhook(url)
    ElMessage.success('测试 Webhook 消息发送成功')
  } catch (err: any) {
    ElMessage.error(`测试 Webhook 失败: ${err?.message || err}`)
  } finally {
    testing.value = false
  }
}
</script>

<style lang="scss" scoped>
.notification-settings {
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

  .settings-card {
    .channels-wrapper {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .channel-block {
      padding: 20px;
      border: 1px solid var(--el-border-color-lighter);
      border-radius: 6px;
      margin-bottom: 16px;

      .channel-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 16px;

        .channel-name {
          font-size: 16px;
          font-weight: 600;
          color: var(--el-text-color-primary);
        }
      }

      .config-row {
        margin-bottom: 0;
      }
    }

    .action-bar {
      display: flex;
      gap: 12px;
      justify-content: flex-end;
    }
  }
}
</style>
