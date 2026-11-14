import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useLoadTimeout } from './useLoadTimeout'

function setup(onTimeout: () => void, ms?: number) {
  let api!: ReturnType<typeof useLoadTimeout>
  const wrapper = mount({
    setup() {
      api = useLoadTimeout(onTimeout, ms)
      return () => null
    },
  })
  return { api, wrapper }
}

describe('useLoadTimeout', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('到达时限才触发回调', () => {
    const cb = vi.fn()
    const { api } = setup(cb)
    api.start()
    vi.advanceTimersByTime(29_999)
    expect(cb).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(cb).toHaveBeenCalledTimes(1)
  })

  it('stop 之后不再触发', () => {
    const cb = vi.fn()
    const { api } = setup(cb)
    api.start()
    vi.advanceTimersByTime(10_000)
    api.stop()
    vi.advanceTimersByTime(60_000)
    expect(cb).not.toHaveBeenCalled()
  })

  it('重复 start 只保留最后一次计时', () => {
    const cb = vi.fn()
    const { api } = setup(cb)
    api.start()
    vi.advanceTimersByTime(20_000)
    api.start()
    vi.advanceTimersByTime(20_000)
    expect(cb).not.toHaveBeenCalled()
    vi.advanceTimersByTime(10_000)
    expect(cb).toHaveBeenCalledTimes(1)
  })

  it('自定义时限生效', () => {
    const cb = vi.fn()
    const { api } = setup(cb, 1_000)
    api.start()
    vi.advanceTimersByTime(1_000)
    expect(cb).toHaveBeenCalledTimes(1)
  })

  it('组件卸载时清理计时器', () => {
    const cb = vi.fn()
    const { api, wrapper } = setup(cb)
    api.start()
    wrapper.unmount()
    vi.advanceTimersByTime(60_000)
    expect(cb).not.toHaveBeenCalled()
  })
})