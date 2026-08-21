<template>
  <div class="factor-catalog-container">
    <el-card class="box-card">
      <template #header>
        <div class="card-header">
          <span>因子元数据目录 (171 因子)</span>
          <el-button type="primary" @click="$router.push('/factors/compute')">去计算因子</el-button>
        </div>
      </template>

      <!-- 搜索与筛选 -->
      <div class="filter-bar">
        <el-input
          v-model="searchQuery"
          placeholder="搜索因子 ID / 名称 / 描述"
          clearable
          style="width: 300px; margin-right: 15px;"
          @input="fetchCatalog"
        />
        <el-select v-model="selectedCategory" placeholder="因子类别" clearable style="width: 180px; margin-right: 15px;" @change="fetchCatalog">
          <el-option label="全部" value="" />
          <el-option label="价格与收益 (price)" value="price" />
          <el-option label="趋势 (trend)" value="trend" />
          <el-option label="动量 (momentum)" value="momentum" />
          <el-option label="波动与风险 (volatility)" value="volatility" />
          <el-option label="流动性 (liquidity)" value="liquidity" />
          <el-option label="估值 (valuation)" value="valuation" />
          <el-option label="质量 (quality)" value="quality" />
          <el-option label="成长 (growth)" value="growth" />
          <el-option label="情绪 (sentiment)" value="sentiment" />
          <el-option label="横截面 (cross_sectional)" value="cross_sectional" />
        </el-select>
        <el-select v-model="selectedMarket" placeholder="适用市场" clearable style="width: 120px;" @change="fetchCatalog">
          <el-option label="全部" value="" />
          <el-option label="A股 (CN)" value="CN" />
          <el-option label="港股 (HK)" value="HK" />
          <el-option label="美股 (US)" value="US" />
        </el-select>
      </div>

      <!-- 因子表格 -->
      <el-table :data="factorList" v-loading="loading" stripe style="width: 100%; margin-top: 20px;">
        <el-table-column prop="factor_id" label="因子 ID" width="180" sortable />
        <el-table-column prop="name" label="名称" width="180" />
        <el-table-column prop="category" label="分类" width="150">
          <template #default="scope">
            <el-tag>{{ scope.row.category }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="250" />
        <el-table-column prop="version" label="版本" width="100" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue"
import factorsApi from "@/api/factors"
import type { FactorDefinition } from "@/types/factor"

const loading = ref(false)
const searchQuery = ref("")
const selectedCategory = ref("")
const selectedMarket = ref("")
const factorList = ref<FactorDefinition[]>([])

const fetchCatalog = async () => {
  loading.value = true
  try {
    const res = await factorsApi.getFactorDefinitions({
      category: selectedCategory.value || undefined,
      market: selectedMarket.value || undefined,
      search: searchQuery.value || undefined
    })
    if (res && res.data) {
      factorList.value = res.data.items || []
    }
  } catch (err) {
    console.error("Failed to fetch factor catalog:", err)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchCatalog()
})
</script>

<style scoped>
.factor-catalog-container {
  padding: 20px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.filter-bar {
  display: flex;
  align-items: center;
}
</style>
