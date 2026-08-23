<template>
  <div class="risk-dashboard p-6">
    <h1 class="text-2xl font-bold mb-6">实时风控与合规监控面板</h1>

    <div class="grid grid-cols-3 gap-4 mb-6">
      <div class="bg-white p-4 border rounded shadow">
        <div class="text-gray-500 text-sm">风控状态决策</div>
        <div class="text-xl font-bold text-green-600">APPROVED</div>
      </div>
      <div class="bg-white p-4 border rounded shadow">
        <div class="text-gray-500 text-sm">活动违规记录</div>
        <div class="text-xl font-bold text-gray-800">0 条</div>
      </div>
      <div class="bg-white p-4 border rounded shadow">
        <div class="text-gray-500 text-sm">T+1 状态</div>
        <div class="text-xl font-bold text-blue-600">正常受控</div>
      </div>
    </div>

    <div class="bg-white p-6 border rounded shadow">
      <h2 class="text-lg font-semibold mb-4">风控拦截与告警明细</h2>
      <p class="text-gray-500 text-sm">目前暂无活动风控拦截告警。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
</script>
