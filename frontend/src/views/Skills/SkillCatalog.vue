<template>
  <div class="skill-catalog p-6">
    <div class="flex justify-between items-center mb-6">
      <h1 class="text-2xl font-bold">Skill 技能中心与能力库</h1>
      <router-link to="/skills/create" class="px-4 py-2 bg-blue-600 text-white font-medium rounded hover:bg-blue-700 text-sm">
        创建自定义 Skill
      </router-link>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div v-for="sk in skills" :key="sk.skill_id" class="border p-4 rounded shadow bg-white">
        <div class="flex justify-between items-center mb-2">
          <span class="font-semibold text-lg">{{ sk.name }}</span>
          <span v-if="sk.is_system_skill" class="px-2 py-0.5 text-xs bg-purple-100 text-purple-800 rounded">系统 Skill</span>
          <span v-else class="px-2 py-0.5 text-xs bg-green-100 text-green-800 rounded">自定义</span>
        </div>
        <p class="text-gray-600 text-sm mb-3">{{ sk.description || '无描述' }}</p>
        <div class="flex justify-between items-center text-xs text-gray-500 mb-4">
          <span>类型: <strong class="uppercase">{{ sk.skill_type }}</strong></span>
          <span>版本: v{{ sk.latest_version_num }}</span>
        </div>
        <div>
          <router-link :to="`/skills/${sk.skill_id}/test`" class="block text-center px-3 py-1.5 bg-indigo-600 text-white text-xs rounded hover:bg-indigo-700">
            进入沙箱测试
          </router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { listSkills } from '../../api/skills';
import { Skill } from '../../types/skill';

const skills = ref<Skill[]>([]);

onMounted(async () => {
  try {
    skills.value = await listSkills(true);
  } catch (err) {
    console.error('Failed to load skills:', err);
  }
});
</script>
