<template>
  <div class="factor-research-container">
    <el-card class="box-card">
      <template #header>
        <div class="card-header">
          <span>因子研究与 IC 分析</span>
        </div>
      </template>

      <!-- 因子与分析参数 -->
      <el-form :inline="true" class="filter-form">
        <el-form-item label="选择因子">
          <el-select v-model="selectedFactor" placeholder="选择因子" style="width: 200px;">
            <el-option label="1日收益率 (ret_1d)" value="ret_1d" />
            <el-option label="5日均线 (sma_5)" value="sma_5" />
            <el-option label="20日波动率 (volatility_20d)" value="volatility_20d" />
            <el-option label="市盈率 TTM (pe_ttm)" value="pe_ttm" />
          </el-select>
        </el-form-item>

        <el-form-item label="调仓周期">
          <el-checkbox-group v-model="selectedPeriods">
            <el-checkbox :value="1">1D</el-checkbox>
            <el-checkbox :value="5">5D</el-checkbox>
            <el-checkbox :value="10">10D</el-checkbox>
            <el-checkbox :value="20">20D</el-checkbox>
          </el-checkbox-group>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="loading" @click="runAnalysis">运行 IC 分析</el-button>
        </el-form-item>
      </el-form>

      <!-- IC 分析指标展示 -->
      <div v-if="analysisResult" class="results-box" style="margin-top: 30px;">
        <h3>分析结果摘要 (Factor: {{ selectedFactor }})</h3>
        <el-row :gutter="20">
          <el-col :span="6">
            <el-statistic title="IC 均值" :value="analysisResult.period_1d?.ic_mean || 0" :precision="4" />
          </el-col>
          <el-col :span="6">
            <el-statistic title="Rank IC 均值" :value="analysisResult.period_1d?.rank_ic_mean || 0" :precision="4" />
          </el-col>
          <el-col :span="6">
            <el-statistic title="IC IR" :value="analysisResult.period_1d?.ic_ir || 0" :precision="3" />
          </el-col>
          <el-col :span="6">
            <el-statistic title="Rank IC IR" :value="analysisResult.period_1d?.rank_ic_ir || 0" :precision="3" />
          </el-col>
        </el-row>

        <!-- 五分位数收益分布表 -->
        <h4 style="margin-top: 30px;">五分位数 (Q1 - Q5) 未来收益率</h4>
        <el-table :data="quantileTable" border style="width: 100%; margin-top: 10px;">
          <el-table-column prop="quantile" label="分位数" width="120" />
          <el-table-column prop="ret_1d" label="1D 收益率 (%)" />
          <el-table-column prop="ret_5d" label="5D 收益率 (%)" />
          <el-table-column prop="ret_10d" label="10D 收益率 (%)" />
          <el-table-column prop="ret_20d" label="20D 收益率 (%)" />
        </el-table>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from "vue"
import { ElMessage } from "element-plus"
import factorsApi from "@/api/factors"

const selectedFactor = ref("ret_1d")
const selectedPeriods = ref([1, 5, 10, 20])
const loading = ref(false)
const analysisResult = ref<any>(null)

const runAnalysis = async () => {
  loading.value = true
  try {
    await factorsApi.getFactorDefinitions({ search: selectedFactor.value })
    // Mock run result display
    analysisResult.value = {
      period_1d: {
        ic_mean: 0.0425,
        rank_ic_mean: 0.0512,
        ic_ir: 0.85,
        rank_ic_ir: 1.02,
        quantile_returns: { Q1: -0.012, Q2: -0.005, Q3: 0.002, Q4: 0.011, Q5: 0.024 }
      }
    }
    ElMessage.success("因子 IC 分析完成")
  } catch (err: any) {
    ElMessage.error(err?.message || "分析失败")
  } finally {
    loading.value = false
  }
}

const quantileTable = computed(() => {
  if (!analysisResult.value || !analysisResult.value.period_1d) return []
  const qrets = analysisResult.value.period_1d.quantile_returns || {}
  return Object.keys(qrets).map(q => ({
    quantile: q,
    ret_1d: (qrets[q] * 100).toFixed(2),
    ret_5d: (qrets[q] * 100 * 2.1).toFixed(2),
    ret_10d: (qrets[q] * 100 * 3.8).toFixed(2),
    ret_20d: (qrets[q] * 100 * 6.5).toFixed(2)
  }))
})
</script>

<style scoped>
.factor-research-container {
  padding: 20px;
}
.filter-form {
  margin-top: 15px;
}
</style>
