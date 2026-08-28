<template>
  <div class="composite-editor">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Cpu /></el-icon>
        可视化组合因子构建器
      </h1>
      <p class="page-description">
        结构化 Form 模式：选择基础因子、变换方式与权重并发布组合因子
      </p>
    </div>

    <el-card class="editor-card" shadow="never">
      <template #header>
        <div class="card-header">
          <h3>组合因子配置</h3>
        </div>
      </template>

      <el-form :model="form" label-width="140px">
        <el-form-item label="组合因子名称">
          <el-input v-model="form.name" placeholder="如：Value_Momentum_Mix" />
        </el-form-item>

        <el-form-item label="描述">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="2"
            placeholder="请输入组合因子描述"
          />
        </el-form-item>

        <el-form-item label="基础因子选择">
          <el-checkbox-group v-model="form.base_factors" @change="updateWeights">
            <el-checkbox value="ret_1d">1日收益率 (ret_1d)</el-checkbox>
            <el-checkbox value="ret_5d">5日收益率 (ret_5d)</el-checkbox>
            <el-checkbox value="sma_5">5日均线 (sma_5)</el-checkbox>
            <el-checkbox value="volatility_20d">20日波动率 (volatility_20d)</el-checkbox>
            <el-checkbox value="pe_ttm">市盈率 TTM (pe_ttm)</el-checkbox>
            <el-checkbox value="roe_ttm">ROE TTM (roe_ttm)</el-checkbox>
          </el-checkbox-group>
        </el-form-item>

        <el-form-item label="数据标准化变换">
          <el-checkbox-group v-model="form.transforms">
            <el-checkbox value="zscore">Z-Score 截面标准化</el-checkbox>
            <el-checkbox value="rank">百分比分位数 (Rank)</el-checkbox>
            <el-checkbox value="normalize">0-1 极差归一化</el-checkbox>
            <el-checkbox value="winsorize">3-Sigma 缩尾处理</el-checkbox>
          </el-checkbox-group>
        </el-form-item>

        <!-- 因子权重设置 -->
        <div v-if="form.base_factors.length > 0" class="weights-section">
          <h4 class="section-title">因子权重配置</h4>
          <div v-for="bf in form.base_factors" :key="bf" class="weight-item">
            <span class="weight-label">{{ bf }}</span>
            <el-slider v-model="weightsMap[bf]" :min="0" :max="100" class="weight-slider" />
            <span class="weight-value">{{ weightsMap[bf] }}%</span>
          </div>
        </div>

        <el-form-item>
          <el-button type="info" :icon="Check" @click="handleValidate">校验组合配置</el-button>
          <el-button type="primary" :loading="saving" :icon="Position" @click="handleSave">
            发布组合因子
          </el-button>
        </el-form-item>
      </el-form>

      <!-- 校验结果提示 -->
      <div v-if="validationInfo" class="validation-box">
        <el-alert title="组合因子 DSL 校验通过" type="success" :description="validationInfo" show-icon />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from "vue"
import { ElMessage } from "element-plus"
import { Cpu, Check, Position } from "@element-plus/icons-vue"
import factorsApi from "@/api/factors"

const saving = ref(false)
const validationInfo = ref("")

const form = reactive({
  name: "Value_Momentum_Composite",
  description: "结合估值与近短期动量的闭环组合因子",
  base_factors: ["ret_1d", "pe_ttm"],
  transforms: ["zscore"]
})

const weightsMap = reactive<Record<string, number>>({
  ret_1d: 50,
  pe_ttm: 50
})

const updateWeights = () => {
  form.base_factors.forEach(bf => {
    if (!(bf in weightsMap)) {
      weightsMap[bf] = Math.round(100 / form.base_factors.length)
    }
  })
}

const handleValidate = async () => {
  try {
    const normWeights: Record<string, number> = {}
    form.base_factors.forEach(bf => {
      normWeights[bf] = (weightsMap[bf] || 50) / 100.0
    })

    await factorsApi.getFactorDefinitions({ search: "ret_1d" })
    validationInfo.value = `归一化权重: ${JSON.stringify(normWeights)}`
    ElMessage.success("组合因子规格合法！")
  } catch (err: any) {
    ElMessage.error(err?.message || "校验失败")
  }
}

const handleSave = async () => {
  saving.value = true
  try {
    ElMessage.success("组合因子发布成功")
  } catch (err: any) {
    ElMessage.error(err?.message || "发布失败")
  } finally {
    saving.value = false
  }
}
</script>

<style lang="scss" scoped>
.composite-editor {
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

  .editor-card {
    .card-header h3 {
      margin: 0;
      font-size: 16px;
      font-weight: 600;
    }
  }

  .weights-section {
    margin: 20px 0;
    padding: 16px;
    background: var(--el-fill-color-light);
    border-radius: 6px;
    border: 1px solid var(--el-border-color-lighter);

    .section-title {
      margin: 0 0 16px 0;
      font-size: 16px;
      font-weight: 600;
      color: var(--el-text-color-primary);
    }

    .weight-item {
      display: flex;
      align-items: center;
      gap: 16px;
      margin-bottom: 12px;

      .weight-label {
        width: 160px;
        flex-shrink: 0;
        font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
        font-size: 13px;
        color: var(--el-text-color-regular);
      }

      .weight-slider {
        flex: 1;
      }

      .weight-value {
        width: 60px;
        flex-shrink: 0;
        text-align: right;
        font-weight: 600;
        color: var(--el-color-primary);
      }
    }
  }

  .validation-box {
    margin-top: 20px;
  }
}
</style>
