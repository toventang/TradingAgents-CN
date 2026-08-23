<template>
  <div class="risk-audit-logs p-6 max-w-5xl mx-auto">
    <h1 class="text-2xl font-bold mb-6">风控评估与审计日志</h1>

    <div class="bg-white p-6 border rounded shadow">
      <table class="w-full text-left border-collapse text-sm">
        <thead>
          <tr class="border-b bg-gray-50">
            <th class="p-2">评估 ID</th>
            <th class="p-2">时间</th>
            <th class="p-2">决策</th>
            <th class="p-2">违规项数量</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="log in logs" :key="log.evaluation_id" class="border-b">
            <td class="p-2 font-mono">{{ log.evaluation_id }}</td>
            <td class="p-2">{{ log.evaluated_at }}</td>
            <td class="p-2 uppercase font-semibold" :class="log.decision === 'rejected' ? 'text-red-600' : 'text-green-600'">{{ log.decision }}</td>
            <td class="p-2">{{ log.violations?.length || 0 }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { listRiskAuditLogs } from '../../api/risk';
import { RiskAuditLog } from '../../types/risk';

const logs = ref<RiskAuditLog[]>([]);

onMounted(async () => {
  try {
    logs.value = await listRiskAuditLogs();
  } catch (err) {
    console.error('Failed to load risk audit logs:', err);
  }
});
</script>
