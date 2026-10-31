import { ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'

import { apiPost } from '../api/client'
import { customWorkflowContent } from './useWorkflows'
import type { JobSnapshot } from '../api/types'

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

  /** SSE 帧统一入口：首帧 `snapshot` 与后续 `job` 结构一致，都走这里。 */
  function applySnapshot(snapshot: JobSnapshot) {
    job.value = snapshot
    if (TERMINAL.has(snapshot.status)) {
      busy.value = false
      closeStream()
      // 出图完成后画廊要立刻能看到新图
      queryClient.invalidateQueries({ queryKey: ['history'] })
    }
  }

  function parseFrame(event: Event) {
    try {
      applySnapshot(JSON.parse((event as MessageEvent).data) as JobSnapshot)
    } catch {
      /* 心跳/异常帧忽略 */
    }
  }

  function subscribe(jobId: number) {
    closeStream()
    // 等待首帧也算在飞行中：提交后到第一次进度之间不该出现"可再次点击"的空窗
    busy.value = true
    const es = new EventSource(`/api/jobs/events?ids=${jobId}`)
    source = es

    // 后端连上会先推一帧当前状态（旧前端只监听 job，白白等了一个写者周期）
    es.addEventListener('snapshot', parseFrame)
    es.addEventListener('job', parseFrame)

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
      const result = await apiPost<{ success: boolean; job_id: number }>('/api/runs', {
        id: promptId,
        workflow_path: options.workflowPath,
        // 自定义工作流不在后端磁盘上，内容必须一起带过去
        workflow_content: customWorkflowContent(options.workflowPath),
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
   * 后端 `/api/runs/batch` 是同步提交（逐个入队），条数多时请求本身会持续几秒。
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
      const result = await apiPost<{ success: boolean; job_id: number }>('/api/runs/batch', {
        items: promptIds.map((id) => ({ prompt_id: id, seed: 0 })),
        workflow_path: options.workflowPath,
        // 自定义工作流不在后端磁盘上，内容必须一起带过去
        workflow_content: customWorkflowContent(options.workflowPath),
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


  /**
   * 批量替换碎片后出图：保留每条提示词原有参数，只用替换后的文本注入。
   *
   * 不写回提示词库 —— 这是"看效果"的操作，原件必须保持不变。
   */
  async function runBatchReplace(
    items: Array<{ promptId: number; seed: number; promptOverride: string }>,
    options: { workflowPath: string; quality: string; orientation: string; title?: string },
  ) {
    error.value = ''
    if (!options.workflowPath) {
      error.value = '请先选择工作流'
      return
    }
    if (!items.length) return
    try {
      busy.value = true
      const result = await apiPost<{ success: boolean; job_id: number }>('/api/runs/batch', {
        items: items.map((it) => ({
          prompt_id: it.promptId,
          seed: it.seed,
          prompt_override: it.promptOverride,
        })),
        workflow_path: options.workflowPath,
        workflow_content: customWorkflowContent(options.workflowPath),
        quality: options.quality,
        orientation: options.orientation,
        title: options.title ?? `批量替换碎片 ${items.length} 条`,
      })
      subscribe(result.job_id)
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
      busy.value = false
    }
  }

  /**
   * 用一段文本直接出图（不绑定提示词记录）。
   *
   * 用途：从**已有图片**重新出一张 —— 图片记录里存了当次的提示词文本与参数
   * （`prompt_params`），拿它重跑即可，不必先有提示词记录。
   */
  async function runText(
    options: {
      prompt: string
      negative_prompt?: string
      seed?: number
      workflowPath: string
      quality: string
      orientation: string
    },
  ) {
    error.value = ''
    if (!options.workflowPath) {
      error.value = '请先选择工作流'
      return
    }
    try {
      busy.value = true
      const result = await apiPost<{ success: boolean; job_id: number }>('/api/runs/text', {
        prompt: options.prompt,
        negative_prompt: options.negative_prompt ?? '',
        workflow_path: options.workflowPath,
        // 自定义工作流不在后端磁盘上，内容必须一起带过去
        workflow_content: customWorkflowContent(options.workflowPath),
        orientation: options.orientation,
        quality: options.quality,
        seed: options.seed ?? 0,
      })
      subscribe(result.job_id)
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
      busy.value = false
    }
  }
  /**
   * 提交出图请求并跟踪进度 —— 给"自己拼接口"的页面用。
   *
   * 旧写法是页面里直接 apiPost 再调 track：POST 期间 busy 一直是 false，
   * 按钮既不禁用也不变文案，用户看到的就是"点了没反应"。这里把提交阶段
   * 也纳入 busy，失败时复位并抛出，让调用方继续用自己的 toast。
   */
  async function submitAndTrack<T extends { success: boolean; job_id?: number | null }>(
    path: string,
    body?: unknown,
  ): Promise<T> {
    error.value = ''
    try {
      busy.value = true
      const result = await apiPost<T>(path, body)
      if (result.job_id) subscribe(result.job_id)
      else busy.value = false
      return result
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
      busy.value = false
      throw e
    }
  }
  return {
    busy,
    job,
    error,
    run,
    runBatch,
    runBatchReplace,
    runText,
    submitAndTrack,
    track: subscribe,
    closeStream,
  }
}
