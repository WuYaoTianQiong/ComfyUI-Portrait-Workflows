import { onBeforeUnmount } from 'vue'

import { jobEventsUrl } from '../api/jobs'
import type { JobSnapshot } from '../api/types'

interface JobStreamOptions {
  /** 连接错误时回调；默认不关闭连接，交给浏览器重连。 */
  onError?: () => void
  /** 单任务模式：错误后不再等待重连。 */
  closeOnError?: boolean
}

interface Subscriber {
  handler: (snapshot: JobSnapshot) => void
  ids: Set<number> | null
  active: boolean
  onError?: () => void
  closeOnError?: boolean
}

/**
 * 任务 SSE 的唯一连接。
 *
 * 多个页面/组合式同时订阅时只保留一个 EventSource（订阅全部任务），
 * 每个订阅者按自己的 id 集合过滤。断线重连由浏览器带 Last-Event-ID 完成，
 * 后端会补发缺口事件。
 */
const subscribers = new Set<Subscriber>()
let source: EventSource | null = null

function dispatch(snapshot: JobSnapshot) {
  for (const sub of Array.from(subscribers)) {
    if (!sub.active) continue
    if (sub.ids && !sub.ids.has(snapshot.id)) continue
    sub.handler(snapshot)
  }
}

function ensureSource() {
  if (source) return
  const es = new EventSource(jobEventsUrl())
  source = es
  const parse = (event: Event) => {
    try {
      dispatch(JSON.parse((event as MessageEvent).data) as JobSnapshot)
    } catch {
      /* 心跳/异常帧忽略 */
    }
  }
  es.addEventListener('snapshot', parse)
  es.addEventListener('job', parse)
  es.onerror = () => {
    for (const sub of Array.from(subscribers)) {
      if (!sub.active) continue
      sub.onError?.()
      if (sub.closeOnError) subscribers.delete(sub)
    }
    maybeClose()
  }
}

function maybeClose() {
  if (subscribers.size) return
  source?.close()
  source = null
}

export function useJobStream(
  onSnapshot: (snapshot: JobSnapshot) => void,
  options: JobStreamOptions = {},
) {
  const sub: Subscriber = {
    handler: onSnapshot,
    ids: null,
    active: false,
    onError: options.onError,
    closeOnError: options.closeOnError,
  }
  subscribers.add(sub)

  function open(ids: number[] | null = null) {
    if (ids && !ids.length) return
    sub.ids = ids ? new Set(ids) : null
    sub.active = true
    ensureSource()
  }

  function close() {
    subscribers.delete(sub)
    maybeClose()
  }

  onBeforeUnmount(close)

  return { open, close }
}
