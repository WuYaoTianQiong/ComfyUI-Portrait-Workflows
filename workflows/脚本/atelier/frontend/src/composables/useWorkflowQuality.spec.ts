import { nextTick, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useWorkflowQuality } from './useWorkflowQuality'

function stubStorage() {
  const store = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
  })
  return store
}

describe('useWorkflowQuality 画质按工作流记忆', () => {
  beforeEach(() => {
    stubStorage()
  })

  it('首次使用默认 1.0×（4K），不从上一个工作流继承', () => {
    const path = ref('/wf/a.json')
    const quality = useWorkflowQuality(path)
    expect(quality.value).toBe('4K')
  })

  it('两个工作流各存各的，切换后互不影响', async () => {
    const store = stubStorage()
    const path = ref('/wf/switch-a.json')
    const quality = useWorkflowQuality(path)

    quality.value = '2K'
    await nextTick()
    path.value = '/wf/switch-b.json'
    expect(quality.value).toBe('4K')

    quality.value = '8K'
    await nextTick()
    expect(store.get('pb.quality:/wf/switch-a.json')).toBe('2K')
    expect(store.get('pb.quality:/wf/switch-b.json')).toBe('8K')

    path.value = '/wf/switch-a.json'
    expect(quality.value).toBe('2K')
  })

  it('同一路径的多个组件共用同一个值', () => {
    const path = ref('/wf/shared-1.json')
    const first = useWorkflowQuality(path)
    const second = useWorkflowQuality(path)

    first.value = '6K'
    expect(second.value).toBe('6K')
  })
})
