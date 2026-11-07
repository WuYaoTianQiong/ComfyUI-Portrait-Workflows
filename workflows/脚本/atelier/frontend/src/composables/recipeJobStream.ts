import { jobEventsUrl } from '../api/jobs'
import type { RecipeJobSnapshot } from './recipeModel'

const TERMINAL = new Set(['done', 'error', 'cancelled', 'stopped'])

export class RecipeStreamTimeoutError extends Error {
  constructor(timeoutMs: number) {
    super(`等待任务超时（${Math.max(1, Math.round(timeoutMs / 60000))} 分钟）`)
    this.name = 'RecipeStreamTimeoutError'
  }
}

export interface RecipeJobWaitResult {
  snapshots: Map<number, RecipeJobSnapshot>
  error: unknown | null
}

export interface RecipeJobWaitOptions {
  onUpdate?: (snapshot: RecipeJobSnapshot) => void
  /** SSE 不可用/断开时回退到逐任务轮询；不传则只依赖 SSE。 */
  pollJob?: (
    id: number,
    onUpdate: (snapshot: RecipeJobSnapshot) => void,
  ) => Promise<RecipeJobSnapshot>
  timeoutMs?: number
}

/**
 * 等待一批任务到终态。
 *
 * 首选一条 `/api/jobs/events?ids=...` SSE 连接推送所有组；连接失败或浏览器
 * 不支持 EventSource 时，退回现有的逐任务轮询。返回值始终是「已拿到的快照」+
 * 整体错误，调用方仍按每个 job 分别归类，避免一个组超时拖垮整批。
 */
export function awaitRecipeJobs(
  jobIds: number[],
  options: RecipeJobWaitOptions = {},
): Promise<RecipeJobWaitResult> {
  const ids = [...new Set(jobIds)]
  const snapshots = new Map<number, RecipeJobSnapshot>()
  const timeoutMs = options.timeoutMs ?? 30 * 60 * 1000
  if (!ids.length) return Promise.resolve({ snapshots, error: null })

  return new Promise((resolve) => {
    let settled = false
    let polling = false
    let source: EventSource | null = null
    let timer: ReturnType<typeof setTimeout> | undefined

    const isTerminal = (snapshot: RecipeJobSnapshot) => TERMINAL.has(String(snapshot.status))
    const allTerminal = () =>
      ids.every((id) => {
        const snapshot = snapshots.get(id)
        return !!snapshot && isTerminal(snapshot)
      })

    const cleanup = () => {
      if (timer !== undefined) clearTimeout(timer)
      source?.close()
      source = null
    }

    const finish = (error: unknown | null) => {
      if (settled) return
      settled = true
      cleanup()
      resolve({ snapshots, error })
    }

    const accept = (snapshot: RecipeJobSnapshot) => {
      if (settled || !snapshot || !ids.includes(snapshot.id)) return
      snapshots.set(snapshot.id, snapshot)
      options.onUpdate?.(snapshot)
      if (allTerminal()) finish(null)
    }

    const startPolling = async () => {
      if (settled || polling) return
      polling = true
      source?.close()
      source = null

      if (!options.pollJob) {
        finish(new Error('任务进度连接中断，且没有轮询回退'))
        return
      }

      const pending = ids.filter((id) => {
        const snapshot = snapshots.get(id)
        return !snapshot || !isTerminal(snapshot)
      })
      const outcomes = await Promise.allSettled(
        pending.map(async (id) => {
          const snapshot = await options.pollJob!(id, accept)
          accept(snapshot)
          return snapshot
        }),
      )
      if (allTerminal()) {
        finish(null)
        return
      }
      const failed = outcomes.find(
        (outcome): outcome is PromiseRejectedResult => outcome.status === 'rejected',
      )
      finish(failed?.reason ?? new Error('任务进度未完成'))
    }

    timer = setTimeout(() => finish(new RecipeStreamTimeoutError(timeoutMs)), timeoutMs)

    if (typeof EventSource === 'undefined') {
      void startPolling()
      return
    }

    try {
      source = new EventSource(jobEventsUrl(ids))
    } catch {
      void startPolling()
      return
    }

    const onEvent = (event: Event) => {
      try {
        accept(JSON.parse((event as MessageEvent).data) as RecipeJobSnapshot)
      } catch {
        /* 心跳/异常帧忽略 */
      }
    }
    source.addEventListener('snapshot', onEvent)
    source.addEventListener('job', onEvent)
    source.onerror = () => {
      if (!settled) void startPolling()
    }
  })
}
