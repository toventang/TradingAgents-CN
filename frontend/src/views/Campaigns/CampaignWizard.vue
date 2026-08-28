<template>
  <div class="campaign-wizard">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Plus /></el-icon>
        创建实盘/模拟 Campaign
      </h1>
      <p class="page-description">
        绑定策略与隔离组合，配置初始资金并提交校验
      </p>
    </div>

    <el-card class="form-card" shadow="never" v-loading="submitting">
      <el-form :model="form" label-width="180px" label-position="right">
        <el-form-item label="Campaign 名称" required>
          <el-input v-model="form.name" placeholder="如：动量双因子模拟 Campaign" />
        </el-form-item>

        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>

        <el-divider />

        <el-row :gutter="24">
          <el-col :xs="24" :sm="12">
            <el-form-item label="绑定策略 ID" required>
              <el-input v-model="form.strategy_id" placeholder="sys_tmpl_01_val_mom" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="策略版本号">
              <el-input-number
                v-model="form.strategy_version_num"
                :min="1"
                controls-position="right"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="24">
          <el-col :xs="24" :sm="12">
            <el-form-item label="隔离组合 Portfolio ID">
              <el-input v-model="form.portfolio_id" placeholder="p_sim_01" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="初始分配资金 (RMB)">
              <el-input-number
                v-model="form.initial_allocation_cash"
                :min="0"
                :step="10000"
                controls-position="right"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="开始日期">
          <el-date-picker
            v-model="form.start_date"
            type="date"
            placeholder="选择开始日期 (非追溯, >= 今天)"
            value-format="YYYY-MM-DD"
            style="width: 100%"
          />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :icon="Check" @click="onSubmit">保存 Draft 并前往校验</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, Check } from '@element-plus/icons-vue'
import { createCampaign } from '../../api/campaigns'

const router = useRouter()
const submitting = ref(false)

const form = ref({
  name: '',
  description: '',
  strategy_id: 'sys_tmpl_01_val_mom',
  strategy_version_num: 1,
  portfolio_id: 'p_sim_01',
  initial_allocation_cash: 100000,
  start_date: new Date().toISOString().substring(0, 10),
  rebalance_frequency: 'daily'
})

const onSubmit = async () => {
  if (!form.value.name || !form.value.strategy_id) {
    ElMessage.warning('请填写必要字段')
    return
  }
  submitting.value = true
  try {
    const res = await createCampaign(form.value)
    ElMessage.success('Campaign 已保存为 Draft')
    router.push(`/campaigns/${res.campaign.campaign_id}`)
  } catch (err) {
    console.error('Failed to create campaign:', err)
    ElMessage.error('创建 Campaign 失败')
  } finally {
    submitting.value = false
  }
}
</script>

<style lang="scss" scoped>
.campaign-wizard {
  max-width: 960px;
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
}
</style>
