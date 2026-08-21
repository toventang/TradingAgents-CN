<template>
  <div class="factor-compute-container">
    <el-card class="box-card">
      <template #header>
        <div class="card-header">
          <span>因子计算任务提交</span>
        </div>
      </template>

      <el-form :model="form" label-width="120px">
        <el-form-item label="股票代码">
          <el-input v-model="symbolsInput" placeholder="请输入股票代码，用逗号或换行分隔（例如 000001, 600000）" type="textarea" :rows="3" />
        </el-form-item>

        <el-form-item label="市场类型">
          <el-radio-group v-model="form.market">
            <el-radio value="CN">A 股 (CN)</el-radio>
            <el-radio value="HK">港 股 (HK)</el-radio>
            <el-radio value="US">美 股 (US)</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="选择因子">
          <el-checkbox-group v-model="form.factor_ids">
            <el-checkbox value="ret_1d">1日收益率 (ret_1d)</el-checkbox>
            <el-checkbox value="ret_5d">5日收益率 (ret_5d)</el-checkbox>
            <el-checkbox value="sma_5">5日均线 (sma_5)</el-checkbox>
            <el-checkbox value="sma_20">20日均线 (sma_20)</el-checkbox>
            <el-checkbox value="volatility_20d">20日波动率 (volatility_20d)</el-checkbox>
            <el-checkbox value="volume_sma_20">20日量均值 (volume_sma_20)</el-checkbox>
            <el-checkbox value="pe_ttm">市盈率 TTM (pe_ttm)</el-checkbox>
            <el-checkbox value="roe_ttm">ROE TTM (roe_ttm)</el-checkbox>
          </el-checkbox-group>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="submitting" @click="handleSubmit">提交计算任务</el-button>
        </el-form-item>
      </el-form>

      <!-- 任务进度跟进 -->
      <div v-if="activeTaskId" class="task-progress-box" style="margin-top: 30px; padding: 20px; border: 1px solid #ebeef5; border-radius: 4px;">
        <h3>任务状态 (Task ID: {{ activeTaskId }})</h3>
        <p>状态: <el-tag>{{ taskStatus }}</el-tag></p>
        <p>最新消息: {{ taskMessage }}</p>
        <el-progress :percentage="Math.round(taskProgress * 100)" />
        <div v-if="resultSnapshotId" style="margin-top: 15px;">
          <el-button type="success" @click="$router.push('/factors/snapshots/' + resultSnapshotId)">查看计算结果快照</el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from "vue"
import { ElMessage } from "element-plus"
import factorsApi from "@/api/factors"

const symbolsInput = ref("000001, 600000")
const submitting = ref(false)
const activeTaskId = ref("")
const taskStatus = ref("queued")
const taskMessage = ref("")
const taskProgress = ref(0)
const resultSnapshotId = ref("")

const form = reactive({
  market: "CN",
  factor_ids: ["ret_1d", "sma_5"]
})

const handleSubmit = async () => {
  const symbols = symbolsInput.value.split(/[\n,\s]+/).map(s => s.trim()).filter(Boolean)
  if (symbols.length === 0) {
    ElMessage.warning("请至少输入一个股票代码")
    return
  }
  if (form.factor_ids.length === 0) {
    ElMessage.warning("请至少选择一个因子")
    return
  }

  submitting.value = true
  try {
    const res = await factorsApi.submitFactorComputeJob({
      symbols,
      market: form.market,
      factor_ids: form.factor_ids
    })
    if (res && res.data && res.data.task_id) {
      activeTaskId.value = res.data.task_id
      taskStatus.value = res.data.status
      localStorage.setItem("last_factor_task_id", res.data.task_id)
      ElMessage.success("因子计算任务提交成功")
    }
  } catch (err: any) {
    ElMessage.error(err?.message || "提交任务失败")
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  const savedTaskId = localStorage.getItem("last_factor_task_id")
  if (savedTaskId) {
    activeTaskId.value = savedTaskId
  }
})
</script>

<style scoped>
.factor-compute-container {
  padding: 20px;
}
</style>
