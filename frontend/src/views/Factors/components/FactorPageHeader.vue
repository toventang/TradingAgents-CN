<template>
  <div class="factor-heading">
    <div>
      <div class="eyebrow">FACTOR LAB</div>
      <h1>{{ title }}</h1>
      <p>{{ description }}</p>
    </div>
    <el-segmented v-model="activePath" :options="options" @change="navigate" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

defineProps<{ title: string; description: string }>()

const route = useRoute()
const router = useRouter()
const options = [
  { label: '因子目录', value: '/factors/catalog' },
  { label: '发起计算', value: '/factors/compute' },
  { label: '数据快照', value: '/factors/snapshots' }
]
const activePath = computed({
  get: () => route.path,
  set: () => undefined
})

function navigate(value: string | number | boolean) {
  void router.push(String(value))
}
</script>

<style scoped lang="scss">
.factor-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 22px;
  padding: 4px 2px;

  .eyebrow {
    margin-bottom: 7px;
    color: var(--el-color-primary);
    font-size: 11px;
    font-weight: 750;
    letter-spacing: 0.18em;
  }

  h1 {
    margin: 0;
    color: var(--el-text-color-primary);
    font-size: clamp(25px, 3vw, 34px);
    line-height: 1.15;
  }

  p {
    max-width: 720px;
    margin: 9px 0 0;
    color: var(--el-text-color-secondary);
    line-height: 1.65;
  }
}

@media (max-width: 820px) {
  .factor-heading {
    align-items: stretch;
    flex-direction: column;
  }

  :deep(.el-segmented) {
    width: 100%;
  }
}
</style>
