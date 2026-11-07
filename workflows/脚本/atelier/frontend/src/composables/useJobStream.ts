import { onBeforeUnmount } from 'vue'

import { jobEventsUrl } from '../api/jobs'
import type { JobSnapshot } from '../api/types'

interface JobStreamOptions {
  /** 连接错误时回调；默认不关闭连接，交给浏览器重连。 */
  onError?: () => void
  /** 单任务模式：错误后不再等待重连。 */
  closeOnError?: boolean
}

/**
 * 任务 SSE 的唯一入口。
 *
 * 后端 `/api/jobs/events` 会先推 `snapshot`，之后推 `job`，两者结构一致。
 * 不传 ids = 订阅所有任务；传 ids = 只订阅指定任务（单任务/队列模式）。
 */
export function useJobStream(
  onSnapshot: (snapshot: JobSnapshot) => void,
  options: JobStreamOptions = {},
) {
  let source: EventSource | null = null

  function close() {
    if (source) {
      source.close()
      source = null
    }
  }

  function open(ids: number[] | null = null) {
    close()
    if (ids && !ids.length) return
    const es = new EventSource(jobEventsUrl(ids))
    source = es

    const parse = (event: Event) => {
      try {
        onSnapshot(JSON.parse((event as MessageEvent).data) as JobSnapshot)
      } catch {
        /* 心跳/异常帧忽略 */
      }
    }
    es.addEventListener('snapshot', parse)
    es.addEventListener('job', parse)
    es.onerror = () => {
      options.onError?.()
      if (options.closeOnError) close()
    }
  }

  onBeforeUnmount(close)

  return { open, close }
}
