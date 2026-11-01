import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'

import { apiGet, apiPost } from '../api/client'
import { customWorkflowContent } from './useWorkflows'
import { useJobStream } from './useJobStream'
import { useSettings } from './useSettings'
import type { JobSnapshot } from '../api/types'

const TERMINAL = new Set(['done', 'error', 'cancelled', 'stopped'])
const LAST_JOB_PREFIX = 'pb.lastJob'
/** 队列模式下最多记住多少个任务 id（刷新后按 id 补齐快照）。 */
const QUEUE_LIMIT = 12

/**
 * 提交出图并跟踪进度。
 *
 * 用后端已有的 SSE（`/api/jobs/events?ids=<id>`）而不是轮询：
 * 单任务订阅在终态时服务端会主动结束连接，前端不用自己判超时。
 * 旧前端是 1Hz 轮询 `GET /api/jobs/{id}`，双 tab 就会翻倍打后端。
 *
 * `sessionKey`（可选）把这"最近一次任务"记到 localStorage：任务快照本来就在
 * 后端 `gen_jobs` 里，前端只要记住 id，刷新后就能接回来 —— 否则结果中心一刷新
 * 就变成"还没有提交任务"。不传则保持纯内存（不持久化）。
 *
 * `options.queue`（可选）开启**队列模式**，这是给组合器用的：
 * - `busy` 只表示"提交请求在飞行中"，POST 返回即解除，不会一直占到整个任务跑完
 *   （旧行为下 `busy` 一直挂到终态，于是"试跑"按钮在整个批次跑完前都是 loading，
 *   无法接着提交下一组 —— 但 ComfyUI 本来就有队列，后端 `/api/jobs` 也能同时
 *   推进多个任务，卡住的只是前端）；
 * - 同时跟踪多个任务的快照（`queue` / `activeCount`），`job` 固定是最新提交的那个；
 * - 任务 id 列表落盘，刷新后队列与结果中心都还在。
 */
export function useGenerate(sessionKey = '', options: { queue?: boolean } = {}) {
  const queueMode = options.queue === true
  const queryClient = useQueryClient()
  const { outputSubfolder } = useSettings()

  const storeKey = sessionKey ? `${LAST_JOB_PREFIX}.${sessionKey}` : ''
  const queueKey = storeKey ? `${storeKey}.ids` : ''
  const busy = ref(false)
  const job = ref<JobSnapshot | null>(null)
  /** 队列模式：本次会话提交过的任务（新→旧），含已结束的。 */
  const queue = ref<JobSnapshot[]>([])
  const activeCount = computed(() => queue.value.filter((j) => !TERMINAL.has(j.status)).length)
  const error = ref('')
  /** 队列模式下"结果中心展示哪个"：最近一次提交的 id。 */
  let latestId = 0
  /** 队列模式下要订阅的 id 集合（只增不减，同一会话内不重建连接以外的东西）。 */
  const tracked = new Set<number>()

  function rememberJob(jobId: number) {
    if (!storeKey) return
    try {
      localStorage.setItem(storeKey, String(jobId))
    } catch {
      /* 隐私模式下忽略 */
    }
  }

  function rememberQueue() {
    if (!queueKey) return
    try {
      localStorage.setItem(queueKey, JSON.stringify(Array.from(tracked).slice(0, QUEUE_LIMIT)))
    } catch {
      /* 忽略 */
    }
  }

  function forgetJob() {
    if (!storeKey) return
    try {
      localStorage.removeItem(storeKey)
      localStorage.removeItem(queueKey)
    } catch {
      /* 忽略 */
    }
  }

  /** 刷新后恢复：优先用 id 列表，旧版本只存了一个 id 时退化成单任务。 */
  function readStoredIds(): number[] {
    try {
      const raw = queueKey ? localStorage.getItem(queueKey) : null
      if (raw) {
        const parsed = JSON.parse(raw)
        if (Array.isArray(parsed)) {
          const ids = parsed
            .map((v) => Number(v))
            .filter((v) => Number.isFinite(v) && v > 0)
            .slice(0, QUEUE_LIMIT)
          if (ids.length) return ids
        }
      }
      const single = Number(localStorage.getItem(storeKey) ?? '')
      return Number.isFinite(single) && single > 0 ? [single] : []
    } catch {
      return []
    }
  }

  /**
   * 刷新后把上一次任务接回来：还在跑就继续订阅，已经结束也恢复快照
   * （结果中心要能看到上次出的图与状态）。任务已被删除就忘掉这条记录。
   */
  async function restoreLastJob() {
    if (!storeKey) return
    if (!queueMode) {
      let jobId = 0
      try {
        jobId = Number(localStorage.getItem(storeKey) ?? '')
      } catch {
        return
      }
      if (!jobId) return
      try {
        const snapshot = await apiGet<JobSnapshot>(`/api/jobs/${jobId}`)
        job.value = snapshot
        if (TERMINAL.has(snapshot.status)) return
        subscribe(jobId)
      } catch {
        forgetJob()
      }
      return
    }

    const ids = readStoredIds()
    if (!ids.length) return
    tracked.clear()
    for (const id of ids) tracked.add(id)
    latestId = ids[0]

    // 用 GET 补齐快照（SSE 首帧也能补，但要等连接建立；GET 让首屏立刻有内容）
    const snapshots = await Promise.all(
      ids.map((id) => apiGet<JobSnapshot>(`/api/jobs/${id}`).catch(() => null)),
    )
    const alive = snapshots.filter((s): s is JobSnapshot => Boolean(s))
    if (!alive.length) {
      forgetJob()
      return
    }
    queue.value = alive.slice().sort((a, b) => b.id - a.id)
    job.value = queue.value[0]
    if (queue.value.some((j) => !TERMINAL.has(j.status))) stream.open(Array.from(tracked))
  }

  onMounted(restoreLastJob)
  onBeforeUnmount(closeStream)

  const stream = useJobStream(applySnapshot, {
    closeOnError: !queueMode,
    onError: () => {
      // 服务端在终态后会主动关闭单任务订阅，这里只在仍在提交时标记失败
      if (busy.value) {
        error.value = '进度连接中断，可刷新页面查看结果'
        busy.value = false
      }
    },
  })

  function closeStream() {
    stream.close()
  }

  /** SSE 帧统一入口：首帧 `snapshot` 与后续 `job` 结构一致，都走这里。 */
  function applySnapshot(snapshot: JobSnapshot) {
    if (!queueMode) {
      job.value = snapshot
      if (TERMINAL.has(snapshot.status)) {
        busy.value = false
        closeStream()
        // 出图完成后画廊要立刻能看到新图
        queryClient.invalidateQueries({ queryKey: ['history'] })
      }
      return
    }

    // 队列模式：维持 id → 快照，结果中心固定展示"最近提交"的那个
    const rest = queue.value.filter((j) => j.id !== snapshot.id)
    queue.value = [snapshot, ...rest].sort((a, b) => b.id - a.id)
    if (snapshot.id === latestId || !job.value) job.value = snapshot
    if (TERMINAL.has(snapshot.status)) {
      queryClient.invalidateQueries({ queryKey: ['history'] })
      // 全部结束才断开：中途断开会让后面的任务失去进度
      if (activeCount.value === 0) closeStream()
    }
  }

  function subscribe(jobId: number) {
    rememberJob(jobId)
    // 等待首帧也算在飞行中：提交后到第一次进度之间不该出现"可再次点击"的空窗
    busy.value = true
    stream.open([jobId])
  }

  /** 队列模式：登记一个新提交的任务并订阅它的进度（不阻塞后续提交）。 */
  function trackQueued(jobId: number) {
    latestId = jobId
    tracked.add(jobId)
    rememberJob(jobId)
    rememberQueue()

    // 先放一条占位：结果中心在首帧到达前就能显示"正在提交"
    const placeholder = {
      id: jobId,
      job_type: 'batch',
      status: 'pending',
      title: '',
      total: 0,
      done_count: 0,
      error_count: 0,
      items: [],
      workflow_path: '',
      orientation: '',
      quality: '',
      extra: null,
      created_at: '',
      updated_at: '',
    } as unknown as JobSnapshot
    queue.value = [placeholder, ...queue.value.filter((j) => j.id !== jobId)].sort(
      (a, b) => b.id - a.id,
    )
    job.value = placeholder

    stream.open(Array.from(tracked))
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
        output_subfolder: outputSubfolder.value,
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
        output_subfolder: outputSubfolder.value,
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
        output_subfolder: outputSubfolder.value,
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
        output_subfolder: outputSubfolder.value,
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
      const payload =
        body && typeof body === 'object' && !Array.isArray(body)
          ? { ...(body as Record<string, unknown>), output_subfolder: outputSubfolder.value }
          : body
      const result = await apiPost<T>(path, payload)
      if (result.job_id) {
        if (queueMode) trackQueued(result.job_id)
        else subscribe(result.job_id)
      } else busy.value = false
      return result
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
      throw e
    } finally {
      // 队列模式：提交请求一结束就放行，让用户接着提交下一组（任务本身由 ComfyUI 排队）
      if (queueMode) busy.value = false
      else if (error.value) busy.value = false
    }
  }

  return {
    busy,
    job,
    queue,
    activeCount,
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
