<template>
  <div class="skill-editor p-6 max-w-4xl mx-auto">
    <h1 class="text-2xl font-bold mb-6">创建自定义 Python Skill</h1>

    <div class="bg-white p-6 border rounded shadow space-y-4">
      <div>
        <label class="block font-medium mb-1">Skill 名称</label>
        <input v-model="form.name" type="text" class="w-full border rounded p-2" placeholder="e.g. 自定义动量评分器" />
      </div>

      <div>
        <label class="block font-medium mb-1">描述</label>
        <textarea v-model="form.description" class="w-full border rounded p-2" rows="2" placeholder="简要说明此 Skill 的功能..."></textarea>
      </div>

      <div>
        <label class="block font-medium mb-1">Skill 类别</label>
        <select v-model="form.skill_type" class="w-full border rounded p-2">
          <option value="market">Market (行情分析)</option>
          <option value="fundamentals">Fundamentals (基本面分析)</option>
          <option value="technical">Technical (技术面分析)</option>
          <option value="sentiment">Sentiment (舆情分析)</option>
          <option value="risk">Risk (风控分析)</option>
          <option value="composite">Composite (综合打分)</option>
        </select>
      </div>

      <div>
        <label class="block font-medium mb-1">Python 代码 (需定义 `run(inputs)` 函数)</label>
        <textarea v-model="form.code" class="w-full font-mono text-sm border rounded p-3 bg-gray-900 text-green-400" rows="10"></textarea>
      </div>

      <div class="pt-2">
        <button @click="onSubmit" class="w-full bg-blue-600 text-white font-medium py-2 rounded hover:bg-blue-700">
          提交保存 Skill
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { createSkill } from '../../api/skills';

const router = useRouter();

const form = ref({
  name: '',
  description: '',
  skill_type: 'market',
  code: `def run(inputs):\n    # 沙箱白名单库: math, np, pd, json, datetime\n    val = inputs.get('val', 0)\n    return {'score': val * 1.5}`
});

const onSubmit = async () => {
  if (!form.value.name || !form.value.code) {
    alert('请填写 Skill 名称和 Python 代码');
    return;
  }
  try {
    const res = await createSkill(form.value);
    router.push(`/skills/${res.skill.skill_id}/test`);
  } catch (err) {
    console.error('Failed to create skill:', err);
  }
};
</script>
