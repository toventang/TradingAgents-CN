import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { factorApi } from '@/api/factors'
import { useAuthStore } from '@/stores/auth'
import type {
  DomainTask,
  FactorComputeAccepted,
  FactorJob,
  PersistedFactorTask
} from '@/types/factor'

const POLL_INTERVAL_MS = 2000
const TERMINAL_STATUSES = new Set(['succeeded', 'failed', 'cancelled'])

export const useFactorStore = defineStore('factors', () => {
  const task = ref<DomainTask | null>(null)
  const job = ref<FactorJob | null>(null)
  const tracking = ref<PersistedFactorTask | null>(null)
  const loading = ref(false)
  const refreshError = ref('')
  let pollTimer: ReturnType<typeof setTimeout> | null = null

  const authStore = useAuthStore()
  const storageKey = computed(() => `factor-compute-task:${authStore.user?.id || 'anonymous'}`)
  const isActive = computed(() => Boolean(task.value && !TERMINAL_STATUSES.has(task.value.status)))
  const progressPercent = computed(() => Math.round((task.value?.progress || 0) * 100))

  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
  }

  function schedulePoll() {
    stopPolling()
    if (!isActive.value) return
    pollTimer = setTimeout(() => void refresh(), POLL_INTERVAL_MS)
  }

  function save(value: PersistedFactorTask) {
    tracking.value = value
    localStorage.setItem(storageKey.value, JSON.stringify(value))
  }

  function clear() {
    stopPolling()
    task.value = null
    job.value = null
    tracking.value = null
    refreshError.value = ''
    localStorage.removeItem(storageKey.value)
  }

  async function refresh() {
    if (!tracking.value) return
    try {
      loading.value = true
      refreshError.value = ''
      const [taskResult, jobResult] = await Promise.all([
        factorApi.getTask(tracking.value.taskId),
        factorApi.getJob(tracking.value.jobId)
      ])
      task.value = taskResult
      job.value = jobResult
    } catch (error) {
      refreshError.value = error instanceof Error ? error.message : '任务状态刷新失败'
      stopPolling()
      return
    } finally {
      loading.value = false
    }
    schedulePoll()
  }

  async function track(accepted: FactorComputeAccepted) {
    save({
      jobId: accepted.job_id,
      taskId: accepted.task_id,
      requestChecksum: accepted.request_checksum,
      savedAt: new Date().toISOString()
    })
    await refresh()
  }

  async function restore() {
    if (tracking.value) {
      await refresh()
      return
    }
    const raw = localStorage.getItem(storageKey.value)
    if (!raw) return
    try {
      const saved = JSON.parse(raw) as Partial<PersistedFactorTask>
      if (!saved.jobId || !saved.taskId || !saved.requestChecksum || !saved.savedAt) {
        clear()
        return
      }
      tracking.value = saved as PersistedFactorTask
      await refresh()
    } catch {
      clear()
    }
  }

  return {
    task,
    job,
    tracking,
    loading,
    refreshError,
    isActive,
    progressPercent,
    track,
    restore,
    refresh,
    stopPolling,
    clear
  }
})
