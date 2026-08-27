<template>
  <div class="skill-test p-6 max-w-4xl mx-auto">
    <h1 class="text-2xl font-bold mb-6">Skill 沙箱运行测试</h1>

    <div v-if="skill" class="bg-white p-6 border rounded shadow space-y-4">
      <div class="border-b pb-3">
        <h2 class="text-xl font-bold">{{ skill.name }}</h2>
        <p class="text-gray-600 text-sm mt-1">{{ skill.description }}</p>
      </div>

      <div>
        <label class="block font-medium mb-1">输入参数 (JSON 格式):</label>
        <textarea v-model="inputsJson" class="w-full font-mono text-sm border rounded p-2" rows="4"></textarea>
      </div>

      <div>
        <button @click="onRun" class="px-6 py-2 bg-indigo-600 text-white font-medium rounded hover:bg-indigo-700">
          在沙箱中运行
        </button>
      </div>

      <div v-if="execResult" class="border-t pt-4">
        <h3 class="font-semibold text-lg mb-2">执行结果:</h3>
        <div class="p-3 rounded text-sm font-mono" :class="execResult.success ? 'bg-green-50 border-green-200 text-green-900 border' : 'bg-red-50 border-red-200 text-red-900 border'">
          <p><span class="font-bold">状态:</span> {{ execResult.success ? 'SUCCESS' : 'FAILED' }}</p>
          <p><span class="font-bold">耗时:</span> {{ execResult.execution_time_ms.toFixed(2) }} ms</p>
          <div v-if="execResult.success" class="mt-2">
            <span class="font-bold">输出数据:</span>
            <pre class="bg-white p-2 rounded border mt-1">{{ JSON.stringify(execResult.result, null, 2) }}</pre>
          </div>
          <div v-else class="mt-2 text-red-700 font-bold">
            错误日志: {{ execResult.error_message }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import { getSkill, executeSkill } from '../../api/skills';
import { Skill, SkillExecutionResult } from '../../types/skill';

const route = useRoute();
const skillId = route.params.id as string;
const skill = ref<Skill | null>(null);
const inputsJson = ref('{\n  "returns_20d": 0.08,\n  "volatility_20d": 0.15\n}');
const execResult = ref<SkillExecutionResult | null>(null);

onMounted(async () => {
  try {
    const res = await getSkill(skillId);
    skill.value = res.skill;
  } catch (err) {
    console.error('Failed to load skill:', err);
  }
});

const onRun = async () => {
  let parsed = {};
  try {
    parsed = JSON.parse(inputsJson.value);
  } catch (err) {
    alert('输入参数 JSON 格式非法');
    return;
  }

  try {
    execResult.value = await executeSkill(skillId, parsed);
  } catch (err) {
    console.error('Failed to execute skill:', err);
  }
};
</script>
