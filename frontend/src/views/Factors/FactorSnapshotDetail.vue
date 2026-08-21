<template>
  <div class="snapshot-detail-container">
    <el-card class="box-card" v-loading="loading">
      <template #header>
        <div class="card-header">
          <span>因子快照详情 ({{ snapshotId }})</span>
          <el-button @click="$router.push('/factors')">返回因子目录</el-button>
        </div>
      </template>

      <div v-if="snapshot" class="snapshot-info">
        <el-descriptions border :column="2">
          <el-descriptions-item label="快照 ID">{{ snapshot.snapshot_id }}</el-descriptions-item>
          <el-descriptions-item label="用户 ID">{{ snapshot.user_id }}</el-descriptions-item>
          <el-descriptions-item label="市场">{{ snapshot.market }}</el-descriptions-item>
          <el-descriptions-item label="状态"><el-tag type="success">{{ snapshot.status }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="校验码 (Checksum)">{{ snapshot.checksum }}</el-descriptions-item>
          <el-descriptions-item label="生成时间">{{ snapshot.created_at }}</el-descriptions-item>
        </el-descriptions>

        <h3 style="margin-top: 30px;">因子数值列表</h3>
        <el-table :data="tableData" stripe style="width: 100%; margin-top: 15px;">
          <el-table-column prop="symbol" label="股票代码" width="180" />
          <el-table-column v-for="fid in snapshot.factor_ids" :key="fid" :label="fid">
            <template #default="scope">
              {{ scope.row.values[fid] !== undefined ? scope.row.values[fid] : 'N/A' }}
            </template>
          </el-table-column>
        </el-table>

        <div style="margin-top: 20px; display: flex; justify-content: flex-end;">
          <el-pagination
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
            :total="totalSymbols"
            layout="total, sizes, prev, pager, next"
            @size-change="fetchValues"
            @current-change="fetchValues"
          />
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue"
import { useRoute } from "vue-router"
import factorsApi from "@/api/factors"
import type { FactorSnapshot } from "@/types/factor"

const route = useRoute()
const snapshotId = ref(route.params.id as string)
const loading = ref(false)
const snapshot = ref<FactorSnapshot | null>(null)
const tableData = ref<{ symbol: string; values: Record<string, any> }[]>([])
const currentPage = ref(1)
const pageSize = ref(10)
const totalSymbols = ref(0)

const fetchSnapshotDetail = async () => {
  loading.value = true
  try {
    const res = await factorsApi.getFactorSnapshot(snapshotId.value)
    if (res && res.data) {
      snapshot.value = res.data
      await fetchValues()
    }
  } catch (err) {
    console.error("Failed to fetch snapshot detail:", err)
  } finally {
    loading.value = false
  }
}

const fetchValues = async () => {
  try {
    const res = await factorsApi.getFactorSnapshotValues(snapshotId.value, currentPage.value, pageSize.value)
    if (res && res.data) {
      const items = res.data.items || {}
      totalSymbols.value = res.data.total || 0
      tableData.value = Object.keys(items).map(sym => ({
        symbol: sym,
        values: items[sym]
      }))
    }
  } catch (err) {
    console.error("Failed to fetch snapshot values:", err)
  }
}

onMounted(() => {
  fetchSnapshotDetail()
})
</script>

<style scoped>
.snapshot-detail-container {
  padding: 20px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
