import { defineComponent, onMounted } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useJobStream } from './useJobStream'
import type { JobSnapshot } from '../api/types'

class FakeEventSource {
  static instances: FakeEventSource[] = []
  url: string
  closed = false
  onerror: ((event: Event) => void) | null = null
  private listeners = new Map<string, Array<(event: Event) => void>>()

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, callback: (event: Event) => void) {
    const list = this.listeners.get(type) ?? []
    list.push(callback)
    this.listeners.set(type, list)
  }

  close() {
    this.closed = true
  }

  emit(type: string, data: unknown) {
    const event = { data: JSON.stringify(data) } as MessageEvent
    for (const callback of this.listeners.get(type) ?? []) callback(event)
  }
}

function snapshot(id: number): JobSnapshot {
  return {
    id,
    job_type: 'batch',
    status: 'running',
    title: '',
    total: 1,
    done_count: 0,
    error_count: 0,
    items: [],
    workflow_path: '',
    orientation: '',
    quality: '',
    extra: null,
    created_at: '',
    updated_at: '',
  }
}

afterEach(() => {
  FakeEventSource.instances = []
  vi.unstubAllGlobals()
})

describe('useJobStream', () => {
  it('订阅 snapshot/job 事件并在卸载时关闭连接', () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const received: JobSnapshot[] = []
    const Test = defineComponent({
      setup() {
        const stream = useJobStream((item) => received.push(item))
        onMounted(() => stream.open([1, 2]))
        return () => null
      },
    })

    const wrapper = mount(Test)
    const source = FakeEventSource.instances[0]
    // 单连接多路复用：底层始终订阅全部任务，由订阅者按 id 过滤。
    expect(source.url).toBe('/api/jobs/events')

    source.emit('snapshot', snapshot(1))
    source.emit('job', snapshot(2))
    source.emit('job', snapshot(3))
    expect(received.map((item) => item.id)).toEqual([1, 2])

    wrapper.unmount()
    expect(source.closed).toBe(true)
  })

  it('不传 ids 时订阅全部任务', () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const Test = defineComponent({
      setup() {
        const stream = useJobStream(() => {})
        onMounted(() => stream.open())
        return () => null
      },
    })
    const wrapper = mount(Test)
    expect(FakeEventSource.instances[0].url).toBe('/api/jobs/events')
    wrapper.unmount()
  })

  it('closeOnError 时错误后自动关闭', () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const errors: string[] = []
    const Test = defineComponent({
      setup() {
        const stream = useJobStream(() => {}, {
          closeOnError: true,
          onError: () => errors.push('error'),
        })
        onMounted(() => stream.open([1]))
        return () => null
      },
    })
    const wrapper = mount(Test)
    const source = FakeEventSource.instances[0]
    source.onerror?.(new Event('error'))
    expect(errors).toEqual(['error'])
    expect(source.closed).toBe(true)
    wrapper.unmount()
  })
})
