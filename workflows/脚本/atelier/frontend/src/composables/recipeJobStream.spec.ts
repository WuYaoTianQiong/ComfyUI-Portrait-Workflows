import { afterEach, describe, expect, it, vi } from 'vitest'

import { awaitRecipeJobs } from './recipeJobStream'
import type { RecipeJobSnapshot } from './useReferenceRecipe'

function snapshot(id: number, status: string): RecipeJobSnapshot {
  return {
    id,
    status,
    total: 1,
    done_count: status === 'running' ? 0 : 1,
    error_count: 0,
    items: [],
  }
}

class FakeEventSource {
  static instances: FakeEventSource[] = []
  listeners: Record<string, (event: Event) => void> = {}
  onerror: (() => void) | null = null
  closed = false

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: (event: Event) => void) {
    this.listeners[type] = listener
  }

  close() {
    this.closed = true
  }

  emit(type: string, data: RecipeJobSnapshot) {
    this.listeners[type]?.({ data: JSON.stringify(data) } as MessageEvent)
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  FakeEventSource.instances = []
})

describe('awaitRecipeJobs', () => {
  it('一条 SSE 连接收集所有任务，全部终态后关闭', async () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const seen: number[] = []
    const pending = awaitRecipeJobs([7, 8], {
      onUpdate: (item) => seen.push(item.id),
    })

    const source = FakeEventSource.instances[0]
    expect(source.url).toBe('/api/jobs/events?ids=7,8')
    source.emit('snapshot', snapshot(7, 'running'))
    source.emit('job', snapshot(7, 'done'))
    source.emit('snapshot', snapshot(8, 'done'))

    const result = await pending
    expect(result.error).toBeNull()
    expect([...result.snapshots.keys()].sort()).toEqual([7, 8])
    expect(seen).toContain(7)
    expect(source.closed).toBe(true)
  })

  it('没有 EventSource 时退回逐任务轮询', async () => {
    vi.stubGlobal('EventSource', undefined)
    const polled: number[] = []
    const result = await awaitRecipeJobs([9], {
      pollJob: async (id, onUpdate) => {
        polled.push(id)
        const done = snapshot(id, 'done')
        onUpdate(done)
        return done
      },
    })

    expect(polled).toEqual([9])
    expect(result.snapshots.get(9)?.status).toBe('done')
    expect(result.error).toBeNull()
  })
})
