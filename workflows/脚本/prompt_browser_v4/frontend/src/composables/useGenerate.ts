import { ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'

import { apiPost } from '../api/client'

export interface JobSnapshot {
  id: number
  status: string
  title?: string
  total?: number
  done_count?: number
  error_count?: number
  items?: Array<{ status?: string; error?: string }>
}

const TERMINAL = new Set(['done', 'error', 'cancelled', 'stopped'])

/**
 * 提交出图并跟踪进度。
 *
 * 用后端已有的 SSE（`/api/jobs/events?ids=<id>`）而不是轮询：
 * 单任务订阅在终态时服务端会主动结束连接，前端不用自己判超时。
 * 旧前端是 1Hz 轮询 `GET /api/jobs/{id}`，双 tab 就会翻倍打后端。
 */
export function useGenerate() {
  const queryClient = useQueryClient()

  const busy = ref(false)
  const job = ref<JobSnapshot | null>(null)
  const error = ref('')
  let source: EventSource | null = null

  function closeStream() {
    if (source) {
      source.close()
      source = null
    }
  }

  function subscribe(jobId: number) {
    closeStream()
    const es = new EventSource(`/api/jobs/events?ids=${jobId}`)
    source = es

    es.addEventListener('job', (event) => {
      try {
        const snapshot = JSON.parse((event as MessageEvent).data) as JobSnapshot
        job.value = snapshot
        if (TERMINAL.has(snapshot.status)) {
          busy.value = false
          closeStream()
          // 出图完成后画廊要立刻能看到新图
          queryClient.invalidateQueries({ queryKey: ['history'] })
        }
      } catch {
        /* 心跳/异常帧忽略 */
      }
    })

    es.onerror = () => {
      // 服务端在终态后会主动关闭，这里只在仍在跑时标记失败
      if (busy.value) {
        error.value = '进度连接中断，可刷新页面查看结果'
        busy.value = false
      }
      closeStream()
    }
  }

  async function run(
    promptId: number,
    options: { workflowPath: string; quality: string; orientation: string },
  ) {
    error.value = ''
    if (!options.workflowPath) {
      error.value = '请先选择工作流'
      return
    }
    try {
      busy.value = true
      const result = await apiPost<{ success: boolean; job_id: number }>('/api/run', {
        id: promptId,
        workflow_path: options.workflowPath,
        quality: options.quality,
        orientation: options.orientation,
      })
      if (!result.success) {
        error.value = '提交失败'
        busy.value = false
        return
      }
      subscribe(result.job_id)
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
      busy.value = false
    }
  }

  /**
   * 批量出图：一次提交多条提示词，共用同一个 job 跟踪进度。
   * 后端 `/api/batch_generate` 是同步提交（逐个入队），条数多时请求本身会持续几秒。
   */
  async function runBatch(
    promptIds: number[],
    options: { workflowPath: string; quality: string; orientation: string; title?: string },
  ) {
    error.value = ''
    if (!options.workflowPath) {
      error.value = '请先选择工作流'
      return
    }
    if (!promptIds.length) return
    try {
      busy.value = true
      const result = await apiPost<{ success: boolean; job_id: number }>('/api/batch_generate', {
        items: promptIds.map((id) => ({ prompt_id: id, seed: 0 })),
        workflow_path: options.workflowPath,
        quality: options.quality,
        orientation: options.orientation,
        title: options.title ?? `批量生成 ${promptIds.length} 条`,
      })
      subscribe(result.job_id)
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
      busy.value = false
    }
  }

  return { busy, job, error, run, runBatch, closeStream }
}
