<template>
  <section class="strategy-page">
    <header class="page-header">
      <div>
        <h1>策略中心</h1>
        <p>从系统模板开始，或通过结构化向导管理自己的草稿与不可变发布版本。</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="router.push('/strategies/new')">新建策略</el-button>
    </header>

    <el-tabs v-model="activeTab" class="strategy-tabs">
      <el-tab-pane label="系统模板" name="templates">
        <div class="toolbar">
          <el-input v-model="search" clearable placeholder="搜索模板名称、说明或 ID" :prefix-icon="Search" />
          <span>{{ filteredTemplates.length }} 个模板</span>
        </div>
        <el-skeleton v-if="loading" :rows="7" animated />
        <el-table v-else :data="filteredTemplates" row-key="template_id" stripe>
          <el-table-column label="模板" min-width="260">
            <template #default="{ row }">
              <button class="name-link" type="button" @click="openTemplate(row)">
                <strong>{{ row.name }}</strong><code>{{ row.template_id }}</code>
              </button>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="用途" min-width="320" show-overflow-tooltip />
          <el-table-column label="类型 / 市场" width="150"><template #default="{ row }"><el-tag effect="plain">{{ kindLabel(row.kind) }}</el-tag> {{ row.market }}</template></el-table-column>
          <el-table-column label="参数" width="90" align="center"><template #default="{ row }">{{ row.parameter_ranges.length }}</template></el-table-column>
          <el-table-column label="操作" width="150" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openTemplate(row)">详情</el-button><el-button link type="success" @click="beginClone(row)">克隆</el-button></template></el-table-column>
          <template #empty><el-empty description="没有匹配的系统模板，请调整搜索条件" /></template>
        </el-table>
      </el-tab-pane>

      <el-tab-pane :label="`我的草稿 (${draftStrategies.length})`" name="drafts">
        <StrategyListTable :items="draftStrategies" empty="还没有草稿。使用结构化向导创建第一条策略。" @open="openStrategy" @archive="archiveStrategy" />
      </el-tab-pane>
      <el-tab-pane :label="`已发布 (${publishedStrategies.length})`" name="published">
        <StrategyListTable :items="publishedStrategies" empty="尚未发布策略。打开草稿、通过校验并确认发布。" @open="openStrategy" @archive="archiveStrategy" />
      </el-tab-pane>
      <el-tab-pane :label="`已归档 (${archivedStrategies.length})`" name="archived">
        <StrategyListTable :items="archivedStrategies" empty="没有归档策略。归档不会删除版本和审计数据。" archived @open="openStrategy" />
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="templateDrawer" title="系统模板详情" size="min(720px, 96vw)">
      <template v-if="selectedTemplate">
        <div class="drawer-title"><div><h2>{{ selectedTemplate.name }}</h2><code>{{ selectedTemplate.template_id }} · v{{ selectedTemplate.version }}</code></div><el-tag>{{ selectedTemplate.market }}</el-tag></div>
        <p>{{ selectedTemplate.description }}</p>
        <el-alert :title="selectedTemplate.risk_warning" type="warning" :closable="false" show-icon />
        <el-descriptions :column="1" border class="detail-block">
          <el-descriptions-item label="结构公式">{{ selectedTemplate.formula }}</el-descriptions-item>
          <el-descriptions-item label="适用市场">{{ selectedTemplate.suitable_markets.join('、') }}</el-descriptions-item>
          <el-descriptions-item label="不适用情形">{{ selectedTemplate.unsuitable_scenarios.join('、') }}</el-descriptions-item>
        </el-descriptions>
        <h3>可调参数</h3>
        <el-table :data="selectedTemplate.parameter_ranges" size="small" border>
          <el-table-column prop="name" label="参数" min-width="130" /><el-table-column prop="default" label="默认" width="90" /><el-table-column label="范围" width="150"><template #default="{ row }">{{ row.minimum }}–{{ row.maximum }} {{ row.unit }}</template></el-table-column><el-table-column prop="sensitivity" label="敏感性" min-width="180" />
        </el-table>
        <div class="drawer-footer"><el-button type="primary" @click="beginClone(selectedTemplate)">克隆为我的草稿</el-button></div>
      </template>
    </el-drawer>

    <el-dialog v-model="cloneDialog" title="克隆系统模板" width="min(520px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="新策略名称" required><el-input v-model="cloneName" maxlength="200" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="cloneDescription" type="textarea" :rows="3" maxlength="4000" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="cloneDialog = false">取消</el-button><el-button type="primary" :loading="cloning" :disabled="!cloneName.trim()" @click="cloneTemplate">确认克隆</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElButton, ElMessage, ElMessageBox, ElTable, ElTableColumn, ElTag } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import { strategyApi } from '@/api/strategies'
import type { Strategy, StrategyTemplate } from '@/types/strategy'

const StrategyListTable = defineComponent({
  props: { items: { type: Array as () => Strategy[], required: true }, empty: { type: String, required: true }, archived: Boolean },
  emits: ['open', 'archive'],
  setup(props, { emit }) {
    return () => h(ElTable, { data: props.items, rowKey: 'strategy_id', stripe: true }, {
      default: () => [
        h(ElTableColumn, { label: '策略', minWidth: 260 }, { default: ({ row }: { row: Strategy }) => h('button', { class: 'name-link', type: 'button', onClick: () => emit('open', row) }, [h('strong', row.name), h('code', row.strategy_id)]) }),
        h(ElTableColumn, { prop: 'description', label: '说明', minWidth: 260, showOverflowTooltip: true }),
        h(ElTableColumn, { label: '类型', width: 110 }, { default: ({ row }: { row: Strategy }) => h(ElTag, { effect: 'plain' }, () => kindLabel(row.kind)) }),
        h(ElTableColumn, { label: '版本', width: 90, align: 'center' }, { default: ({ row }: { row: Strategy }) => `v${row.version_sequence}` }),
        h(ElTableColumn, { label: '更新时间', width: 175 }, { default: ({ row }: { row: Strategy }) => new Date(row.updated_at).toLocaleString() }),
        h(ElTableColumn, { label: '操作', width: props.archived ? 90 : 150, fixed: 'right' }, { default: ({ row }: { row: Strategy }) => [h(ElButton, { link: true, type: 'primary', onClick: () => emit('open', row) }, () => '详情'), !props.archived ? h(ElButton, { link: true, type: 'danger', onClick: () => emit('archive', row) }, () => '归档') : null] })
      ],
      empty: () => h('div', { class: 'teaching-empty' }, [h('strong', props.empty), !props.archived ? h(ElButton, { type: 'primary', link: true, onClick: () => emit('open', null) }, () => '打开向导') : null])
    })
  }
})

const router = useRouter()
const loading = ref(true)
const activeTab = ref('templates')
const search = ref('')
const templates = ref<StrategyTemplate[]>([])
const strategies = ref<Strategy[]>([])
const templateDrawer = ref(false)
const selectedTemplate = ref<StrategyTemplate | null>(null)
const cloneDialog = ref(false)
const cloneName = ref('')
const cloneDescription = ref('')
const cloning = ref(false)

const ownStrategies = computed(() => strategies.value.filter(item => item.visibility !== 'system'))
const draftStrategies = computed(() => ownStrategies.value.filter(item => !item.archived_at && item.current_draft_version_id))
const publishedStrategies = computed(() => ownStrategies.value.filter(item => !item.archived_at && item.latest_published_version_id))
const archivedStrategies = computed(() => ownStrategies.value.filter(item => item.archived_at))
const filteredTemplates = computed(() => {
  const query = search.value.trim().toLowerCase()
  if (!query) return templates.value
  return templates.value.filter(item => [item.name, item.description, item.template_id].some(value => value.toLowerCase().includes(query)))
})

onMounted(load)

async function load(): Promise<void> {
  loading.value = true
  try { [templates.value, strategies.value] = await Promise.all([strategyApi.listTemplates(), strategyApi.list(true)]) }
  finally { loading.value = false }
}
function kindLabel(kind: string): string { return ({ screening: '筛选', ranking: '排序', portfolio: '组合' } as Record<string, string>)[kind] || kind }
function openTemplate(template: StrategyTemplate): void { selectedTemplate.value = template; templateDrawer.value = true }
function beginClone(template: StrategyTemplate): void { selectedTemplate.value = template; cloneName.value = `${template.name}（副本）`; cloneDescription.value = template.description; cloneDialog.value = true }
async function cloneTemplate(): Promise<void> {
  if (!selectedTemplate.value) return
  cloning.value = true
  try {
    const result = await strategyApi.clone(selectedTemplate.value.strategy_id, selectedTemplate.value.strategy_version_id, cloneName.value.trim(), cloneDescription.value.trim())
    ElMessage.success('模板已克隆为草稿')
    await router.push(`/strategies/${result.strategy.strategy_id}`)
  } finally { cloning.value = false }
}
function openStrategy(strategy: Strategy | null): void { router.push(strategy ? `/strategies/${strategy.strategy_id}` : '/strategies/new') }
async function archiveStrategy(strategy: Strategy): Promise<void> {
  await ElMessageBox.confirm(`归档“${strategy.name}”？所有版本与审计数据将保留。`, '确认归档', { type: 'warning', confirmButtonText: '归档', cancelButtonText: '取消' })
  await strategyApi.archive(strategy.strategy_id)
  ElMessage.success('策略已归档')
  await load()
  activeTab.value = 'archived'
}
</script>

<style scoped lang="scss">
.strategy-page { padding: 24px; }
.page-header { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; margin-bottom: 20px; }
.page-header h1 { margin: 0 0 8px; font-size: 28px; }
.page-header p { margin: 0; color: var(--el-text-color-secondary); max-width: 68ch; }
.strategy-tabs { background: var(--el-bg-color); border-radius: 12px; padding: 6px 20px 20px; }
.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: 14px 0; color: var(--el-text-color-secondary); }
.toolbar .el-input { max-width: 440px; }
:deep(.name-link) { display: flex; flex-direction: column; gap: 4px; border: 0; background: none; color: var(--el-text-color-primary); text-align: left; cursor: pointer; padding: 5px 0; }
:deep(.name-link:hover strong), :deep(.name-link:focus-visible strong) { color: var(--el-color-primary); }
:deep(.name-link:focus-visible) { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
:deep(.name-link code) { color: var(--el-text-color-secondary); font-size: 12px; }
.drawer-title { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.drawer-title h2 { margin: 0 0 5px; }
.detail-block { margin: 18px 0; }
.drawer-footer { display: flex; justify-content: flex-end; margin-top: 22px; }
:deep(.teaching-empty) { padding: 32px; display: grid; place-items: center; gap: 8px; color: var(--el-text-color-secondary); }
@media (max-width: 720px) { .strategy-page { padding: 16px; } .page-header { align-items: stretch; flex-direction: column; } .toolbar { align-items: stretch; flex-direction: column; } .toolbar .el-input { max-width: none; } }
</style>
