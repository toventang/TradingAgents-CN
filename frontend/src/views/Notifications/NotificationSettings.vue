<template>
  <div class="notification-settings p-6 max-w-4xl mx-auto">
    <h1 class="text-2xl font-bold mb-6">通知渠道与 Webhook 告警设置</h1>

    <div v-if="pref" class="bg-white p-6 border rounded shadow space-y-6">
      <div v-for="(config, channel) in pref.channels" :key="channel" class="border-b pb-4">
        <div class="flex justify-between items-center mb-2">
          <span class="font-semibold uppercase text-lg">{{ channel }} 渠道</span>
          <input type="checkbox" v-model="config.enabled" class="h-5 w-5" />
        </div>

        <div class="grid grid-cols-2 gap-4 mt-2">
          <div>
            <label class="block text-sm text-gray-600 mb-1">最严格警报级别</label>
            <select v-model="config.min_severity" class="w-full border rounded p-2">
              <option value="info">INFO</option>
              <option value="warning">WARNING</option>
              <option value="critical">CRITICAL</option>
            </select>
          </div>
          <div>
            <label class="block text-sm text-gray-600 mb-1">推送目标地址 / URL</label>
            <input v-model="config.target_address" type="text" class="w-full border rounded p-2" placeholder="e.g. https://hooks.example.com/alerts" />
          </div>
        </div>
      </div>

      <div class="flex gap-4 pt-4">
        <button @click="onSave" class="px-6 py-2 bg-blue-600 text-white font-medium rounded hover:bg-blue-700">
          保存偏好设置
        </button>
        <button @click="onTestWebhook" class="px-6 py-2 bg-gray-600 text-white font-medium rounded hover:bg-gray-700">
          测试 Webhook 发送
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { getNotificationPreferences, updateNotificationPreferences, testWebhook } from '../../api/notifications';

const pref = ref<any>(null);

onMounted(async () => {
  try {
    pref.value = await getNotificationPreferences();
  } catch (err) {
    console.error('Failed to load preferences:', err);
  }
});

const onSave = async () => {
  try {
    await updateNotificationPreferences(pref.value);
    alert('通知偏好设置已保存！');
  } catch (err) {
    console.error('Failed to save preferences:', err);
  }
};

const onTestWebhook = async () => {
  const url = pref.value?.channels?.webhook?.target_address;
  if (!url) {
    alert('请先填写 Webhook 推送目标 URL');
    return;
  }
  try {
    await testWebhook(url);
    alert('测试 Webhook 消息发送成功！');
  } catch (err) {
    alert(`测试 Webhook 失败: ${err}`);
  }
};
</script>
