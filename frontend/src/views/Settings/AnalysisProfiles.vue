<template>
  <section class="profile-page">
    <header class="page-header">
      <div><h1>AnalysisProfile 设置</h1><p>以版本化配置管理分析师、模型引用、Skill、研究深度、风险偏好和关注因子。</p></div>
      <el-button type="primary" :icon="Plus" @click="beginCreate">新建配置</el-button>
    </header>

    <el-alert title="这里只保存模型配置 ID，不接受 API Key、令牌或其他凭据。发布版本不可修改。" type="info" :closable="false" show-icon />

    <div class="profile-layout">
      <aside class="profile-list" aria-label="AnalysisProfile 列表">
        <div class="list-heading"><strong>我的配置</strong><el-button link :icon="Refresh" :loading="loading" @click="loadProfiles">刷新</el-button></div>
        <el-skeleton v-if="loading" :rows="5" animated />
        <template v-else-if="profiles.length">
          <button v-for="profile in profiles" :key="profile.profile_id" type="button" class="profile-item" :class="{ active: profile.profile_id === selectedId }" @click="selectProfile(profile.profile_id)">
            <span><strong>{{ profile.name }}</strong><small>v{{ profile.version_sequence }} · {{ profile.latest_published_version_id ? '已发布' : '草稿' }}</small></span>
            <el-icon><ArrowRight /></el-icon>
          </button>
        </template>
        <div v-else class="teaching-empty"><strong>还没有分析配置</strong><p>新建一个配置，在策略或分析任务中复用并锁定版本。</p><el-button type="primary" link @click="beginCreate">创建第一项</el-button></div>
      </aside>

      <main class="editor-panel">
        <template v-if="creating || selectedDetail">
          <div class="editor-heading">
            <div><h2>{{ creating ? '新建 AnalysisProfile' : selectedDetail?.profile.name }}</h2><p v-if="currentVersion">当前编辑 v{{ currentVersion.version }} · {{ statusLabel(currentVersion.status) }}</p></div>
            <el-space v-if="selectedDetail" wrap>
              <el-button v-if="!draftVersion && publishedVersion" :loading="creatingVersion" @click="createNextVersion">从已发布版本创建草稿</el-button>
              <el-button type="danger" plain @click="archiveProfile">归档</el-button>
            </el-space>
          </div>

          <el-form label-position="top" class="profile-form">
            <section class="form-section">
              <h3>基础分析设置</h3>
              <div class="form-grid">
                <el-form-item label="配置名称" required><el-input v-model="form.name" :disabled="!creating" maxlength="200" /></el-form-item>
                <el-form-item label="研究深度"><el-select v-model="form.research_depth"><el-option v-for="depth in depths" :key="depth" :label="depth" :value="depth" /></el-select></el-form-item>
                <el-form-item label="风险偏好"><el-select v-model="form.risk_preference"><el-option label="稳健" value="conservative" /><el-option label="平衡" value="balanced" /><el-option label="进取" value="aggressive" /></el-select></el-form-item>
                <el-form-item label="投资期限"><el-select v-model="form.investment_horizon"><el-option label="短期" value="short" /><el-option label="中期" value="medium" /><el-option label="长期" value="long" /></el-select></el-form-item>
              </div>
              <el-form-item label="分析师" required><el-checkbox-group v-model="form.selected_analysts"><el-checkbox v-for="analyst in analysts" :key="analyst.value" :label="analyst.value">{{ analyst.label }}</el-checkbox></el-checkbox-group></el-form-item>
            </section>

            <section class="form-section">
              <h3>模型与推理轮次</h3>
              <div class="form-grid">
                <el-form-item label="快速模型配置 ID" required><el-input v-model="form.quick_model_ref.config_id" placeholder="model-config:quick" /></el-form-item>
                <el-form-item label="深度模型配置 ID" required><el-input v-model="form.deep_model_ref.config_id" placeholder="model-config:deep" /></el-form-item>
                <el-form-item label="快速模型名称"><el-input v-model="form.quick_model_ref.model_name" placeholder="可选，仅用于显示" /></el-form-item>
                <el-form-item label="深度模型名称"><el-input v-model="form.deep_model_ref.model_name" placeholder="可选，仅用于显示" /></el-form-item>
                <el-form-item label="研究辩论轮次"><el-input-number v-model="form.debate_rounds" :min="0" :max="5" /></el-form-item>
                <el-form-item label="风险辩论轮次"><el-input-number v-model="form.risk_debate_rounds" :min="0" :max="5" /></el-form-item>
              </div>
            </section>

            <section class="form-section">
              <h3>Skill 与因子上下文</h3>
              <div class="form-grid">
                <el-form-item label="Skill 版本"><el-select v-model="form.enabled_skill_versions" multiple allow-create filterable default-first-option placeholder="skill-id:v1" /></el-form-item>
                <el-form-item label="关注因子（最多 50 个）"><el-select v-model="form.factor_context.factor_ids" multiple allow-create filterable default-first-option :multiple-limit="50" /></el-form-item>
                <el-form-item label="每因子证据上限"><el-input-number v-model="form.factor_context.max_evidence_items_per_factor" :min="0" :max="10" /></el-form-item>
                <el-form-item label="摘要结构版本"><el-input v-model="form.factor_context.summary_schema_version" /></el-form-item>
                <el-form-item label="关联策略上下文"><el-input v-model="form.strategy_context" clearable placeholder="可选策略版本引用" /></el-form-item>
              </div>
            </section>

            <section class="form-section">
              <h3>输出与版本说明</h3>
              <div class="form-grid">
                <el-form-item label="输出结构版本"><el-input v-model="form.output_schema_version" /></el-form-item>
                <el-form-item label="免责声明版本"><el-input v-model="form.disclaimer_profile" /></el-form-item>
              </div>
              <el-form-item label="变更说明"><el-input v-model="form.change_summary" maxlength="2000" /></el-form-item>
            </section>

            <div class="form-actions">
              <el-button v-if="creating" @click="cancelCreate">取消</el-button>
              <el-button type="primary" :loading="saving" :disabled="!canSave || (!creating && !draftVersion)" @click="save">{{ creating ? '创建草稿' : '保存草稿' }}</el-button>
              <el-button v-if="draftVersion" type="warning" plain @click="openPublish">发布 v{{ draftVersion.version }}</el-button>
            </div>
          </el-form>

          <section v-if="selectedDetail" class="version-history">
            <h2>版本历史</h2>
            <el-table :data="selectedDetail.versions" row-key="profile_version_id" stripe>
              <el-table-column label="版本" width="80"><template #default="{ row }">v{{ row.version }}</template></el-table-column><el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="row.status === 'published' ? 'success' : 'warning'">{{ statusLabel(row.status) }}</el-tag></template></el-table-column><el-table-column prop="change_summary" label="说明" min-width="200" /><el-table-column label="创建时间" width="180"><template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template></el-table-column>
            </el-table>
          </section>
        </template>
        <div v-else class="editor-empty"><el-empty description="选择左侧配置，或新建 AnalysisProfile" /></div>
      </main>
    </div>

    <el-dialog v-model="publishDialog" title="发布不可变 AnalysisProfile 版本" width="min(560px, 94vw)">
      <el-alert title="发布后此版本不可编辑；模型和 Skill 仅冻结引用，不保存凭据。" type="warning" :closable="false" show-icon />
      <el-descriptions v-if="draftVersion" :column="1" border class="publish-summary">
        <el-descriptions-item label="版本">v{{ draftVersion.version }} · {{ draftVersion.profile_version_id }}</el-descriptions-item>
        <el-descriptions-item label="分析师">{{ draftVersion.selected_analysts.map(analystLabel).join('、') }}</el-descriptions-item>
        <el-descriptions-item label="模型引用">{{ draftVersion.quick_model_ref.config_id }} / {{ draftVersion.deep_model_ref.config_id }}</el-descriptions-item>
        <el-descriptions-item label="Skill / 因子">{{ draftVersion.enabled_skill_versions.length }} / {{ draftVersion.factor_context.factor_ids.length }}</el-descriptions-item>
      </el-descriptions>
      <el-checkbox v-model="publishConfirmed">我确认发布该不可变版本</el-checkbox>
      <template #footer><el-button @click="publishDialog = false">取消</el-button><el-button type="warning" :disabled="!publishConfirmed" :loading="publishing" @click="publish">确认发布</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowRight, Plus, Refresh } from '@element-plus/icons-vue'
import { analysisProfileApi } from '@/api/analysisProfiles'
import type { AnalysisAnalyst, AnalysisProfile, AnalysisProfileChanges, AnalysisProfileDetail, AnalysisProfileForm, AnalysisProfileVersion, AnalysisResearchDepth } from '@/types/analysisProfile'

const blankForm = (): AnalysisProfileForm => ({
  name: '', selected_analysts: ['market', 'fundamentals', 'news'], research_depth: '标准',
  quick_model_ref: { config_id: 'model-config:default-quick', model_name: null },
  deep_model_ref: { config_id: 'model-config:default-deep', model_name: null },
  risk_preference: 'balanced', investment_horizon: 'medium', enabled_skill_versions: [],
  factor_context: { factor_ids: [], summary_schema_version: 'factor-summary-v1', max_evidence_items_per_factor: 3 },
  strategy_context: null, debate_rounds: 2, risk_debate_rounds: 1,
  output_schema_version: 'analysis-report-v1', disclaimer_profile: 'standard-cn-v1',
  change_summary: 'Initial AnalysisProfile draft'
})
const analysts: Array<{ value: AnalysisAnalyst; label: string }> = [
  { value: 'market', label: '市场' }, { value: 'fundamentals', label: '基本面' },
  { value: 'news', label: '新闻' }, { value: 'social', label: '社交情绪' }
]
const depths: AnalysisResearchDepth[] = ['快速', '基础', '标准', '深度', '全面']
const loading = ref(true)
const saving = ref(false)
const creatingVersion = ref(false)
const publishing = ref(false)
const profiles = ref<AnalysisProfile[]>([])
const selectedId = ref('')
const selectedDetail = ref<AnalysisProfileDetail | null>(null)
const creating = ref(false)
const form = reactive<AnalysisProfileForm>(blankForm())
const publishDialog = ref(false)
const publishConfirmed = ref(false)

const sortedVersions = computed(() => [...(selectedDetail.value?.versions || [])].sort((a, b) => b.version - a.version))
const draftVersion = computed(() => sortedVersions.value.find(item => item.status === 'draft') || null)
const publishedVersion = computed(() => sortedVersions.value.find(item => item.status === 'published') || null)
const currentVersion = computed(() => draftVersion.value || publishedVersion.value || sortedVersions.value[0] || null)
const canSave = computed(() => Boolean(form.name.trim() && form.selected_analysts.length && form.quick_model_ref.config_id.trim() && form.deep_model_ref.config_id.trim() && form.factor_context.factor_ids.length <= 50))

onMounted(loadProfiles)

async function loadProfiles(): Promise<void> {
  loading.value = true
  try {
    const page = await analysisProfileApi.list()
    profiles.value = page.items
    if (selectedId.value && profiles.value.some(item => item.profile_id === selectedId.value)) await selectProfile(selectedId.value)
    else if (profiles.value[0] && !creating.value) await selectProfile(profiles.value[0].profile_id)
  } finally { loading.value = false }
}
function beginCreate(): void { creating.value = true; selectedId.value = ''; selectedDetail.value = null; Object.assign(form, blankForm()) }
function cancelCreate(): void { creating.value = false; if (profiles.value[0]) selectProfile(profiles.value[0].profile_id) }
async function selectProfile(profileId: string): Promise<void> {
  creating.value = false
  selectedId.value = profileId
  selectedDetail.value = await analysisProfileApi.get(profileId)
  if (currentVersion.value) fillForm(selectedDetail.value.profile, currentVersion.value)
}
function fillForm(profile: AnalysisProfile, version: AnalysisProfileVersion): void {
  Object.assign(form, {
    name: profile.name,
    selected_analysts: [...version.selected_analysts], research_depth: version.research_depth,
    quick_model_ref: { ...version.quick_model_ref }, deep_model_ref: { ...version.deep_model_ref },
    risk_preference: version.risk_preference, investment_horizon: version.investment_horizon,
    enabled_skill_versions: [...version.enabled_skill_versions], factor_context: { ...version.factor_context, factor_ids: [...version.factor_context.factor_ids] },
    strategy_context: version.strategy_context, debate_rounds: version.debate_rounds, risk_debate_rounds: version.risk_debate_rounds,
    output_schema_version: version.output_schema_version, disclaimer_profile: version.disclaimer_profile,
    change_summary: version.change_summary
  })
}
function changes(): AnalysisProfileChanges {
  return {
    selected_analysts: form.selected_analysts, research_depth: form.research_depth,
    quick_model_ref: form.quick_model_ref, deep_model_ref: form.deep_model_ref,
    risk_preference: form.risk_preference, investment_horizon: form.investment_horizon,
    enabled_skill_versions: form.enabled_skill_versions, factor_context: form.factor_context,
    strategy_context: form.strategy_context || null, debate_rounds: form.debate_rounds,
    risk_debate_rounds: form.risk_debate_rounds, output_schema_version: form.output_schema_version,
    disclaimer_profile: form.disclaimer_profile
  }
}
async function save(): Promise<void> {
  if (!canSave.value) return
  saving.value = true
  try {
    if (creating.value) {
      const created = await analysisProfileApi.create({ ...form })
      creating.value = false; selectedId.value = created.profile.profile_id; ElMessage.success('AnalysisProfile 草稿已创建')
    } else if (selectedDetail.value && draftVersion.value?.checksum) {
      await analysisProfileApi.updateVersion(selectedDetail.value.profile.profile_id, draftVersion.value.profile_version_id, draftVersion.value.checksum, changes(), form.change_summary)
      ElMessage.success('AnalysisProfile 草稿已保存')
    }
    await loadProfiles()
  } finally { saving.value = false }
}
async function createNextVersion(): Promise<void> {
  if (!selectedDetail.value) return
  creatingVersion.value = true
  try { await analysisProfileApi.createVersion(selectedDetail.value.profile.profile_id, `Create v${selectedDetail.value.profile.version_sequence + 1} draft`); ElMessage.success('新草稿版本已创建'); await selectProfile(selectedDetail.value.profile.profile_id) }
  finally { creatingVersion.value = false }
}
function openPublish(): void { publishConfirmed.value = false; publishDialog.value = true }
async function publish(): Promise<void> {
  if (!selectedDetail.value || !draftVersion.value || !publishConfirmed.value) return
  publishing.value = true
  try { await analysisProfileApi.publish(selectedDetail.value.profile.profile_id, draftVersion.value.profile_version_id); ElMessage.success(`AnalysisProfile v${draftVersion.value.version} 已发布`); publishDialog.value = false; await loadProfiles() }
  finally { publishing.value = false }
}
async function archiveProfile(): Promise<void> {
  if (!selectedDetail.value) return
  await ElMessageBox.confirm(`归档“${selectedDetail.value.profile.name}”？所有版本仍会保留。`, '确认归档', { type: 'warning', confirmButtonText: '归档', cancelButtonText: '取消' })
  await analysisProfileApi.archive(selectedDetail.value.profile.profile_id)
  ElMessage.success('AnalysisProfile 已归档'); selectedId.value = ''; selectedDetail.value = null; await loadProfiles()
}
function statusLabel(status: string): string { return ({ draft: '草稿', published: '已发布', deprecated: '已弃用' } as Record<string, string>)[status] || status }
function analystLabel(value: AnalysisAnalyst): string { return analysts.find(item => item.value === value)?.label || value }
</script>

<style scoped lang="scss">
.profile-page { padding: 24px; display: grid; gap: 18px; }.page-header { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; }.page-header h1 { margin: 0 0 8px; font-size: 28px; }.page-header p { margin: 0; max-width: 68ch; color: var(--el-text-color-secondary); }
.profile-layout { display: grid; grid-template-columns: minmax(230px, 300px) minmax(0, 1fr); gap: 18px; align-items: start; }.profile-list, .editor-panel { background: var(--el-bg-color); border-radius: 12px; }.profile-list { padding: 12px; position: sticky; top: 16px; }.list-heading { display: flex; justify-content: space-between; align-items: center; padding: 4px 8px 10px; }
.profile-item { width: 100%; display: flex; justify-content: space-between; align-items: center; gap: 10px; border: 0; border-radius: 8px; padding: 12px; background: transparent; color: var(--el-text-color-primary); text-align: left; cursor: pointer; transition: background-color 180ms ease-out; }.profile-item:hover { background: var(--el-fill-color-light); }.profile-item:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }.profile-item.active { background: var(--el-color-primary-light-9); color: var(--el-color-primary); }.profile-item span { display: grid; gap: 4px; }.profile-item small { color: var(--el-text-color-secondary); }
.teaching-empty, .editor-empty { padding: 34px 14px; text-align: center; color: var(--el-text-color-secondary); }.teaching-empty p { line-height: 1.6; }.editor-panel { padding: 24px; }.editor-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 18px; }.editor-heading h2 { margin: 0 0 5px; }.editor-heading p { margin: 0; color: var(--el-text-color-secondary); }
.profile-form { margin-top: 24px; }.form-section { padding: 20px 0; border-top: 1px solid var(--el-border-color-lighter); }.form-section h3 { margin: 0 0 16px; font-size: 17px; }.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 22px; }.form-grid :deep(.el-select), .form-grid :deep(.el-input-number) { width: 100%; }.form-actions { display: flex; justify-content: flex-end; gap: 10px; padding-top: 18px; border-top: 1px solid var(--el-border-color-lighter); }.version-history { margin-top: 32px; }.version-history h2 { font-size: 19px; }.publish-summary { margin: 18px 0; }
@media (max-width: 900px) { .profile-layout { grid-template-columns: 1fr; }.profile-list { position: static; }.form-grid { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .profile-item { transition: none; } }
</style>
