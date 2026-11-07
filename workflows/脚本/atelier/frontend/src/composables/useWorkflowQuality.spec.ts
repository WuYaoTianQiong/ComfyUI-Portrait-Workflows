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

  it('首次使用默认 1.0×，不从上一个工作流继承', () => {
    const path = ref('/wf/a.json')
    const quality = useWorkflowQuality(path)
    expect(quality.value).toBe('1.0x')
  })

  it('旧版本存的 2K/4K/8K 读取时归一成倍率键', () => {
    const store = stubStorage()
    store.set('pb.quality:/wf/legacy.json', '8K')
    const quality = useWorkflowQuality(ref('/wf/legacy.json'))
    expect(quality.value).toBe('1.5x')
  })

  it('两个工作流各存各的，切换后互不影响', async () => {
    const store = stubStorage()
    const path = ref('/wf/switch-a.json')
    const quality = useWorkflowQuality(path)

    quality.value = '0.75x'
    await nextTick()
    path.value = '/wf/switch-b.json'
    expect(quality.value).toBe('1.0x')

    quality.value = '1.5x'
    await nextTick()
    expect(store.get('pb.quality:/wf/switch-a.json')).toBe('0.75x')
    expect(store.get('pb.quality:/wf/switch-b.json')).toBe('1.5x')

    path.value = '/wf/switch-a.json'
    expect(quality.value).toBe('0.75x')
  })

  it('同一路径的多个组件共用同一个值', () => {
    const path = ref('/wf/shared-1.json')
    const first = useWorkflowQuality(path)
    const second = useWorkflowQuality(path)

    first.value = '1.25x'
    expect(second.value).toBe('1.25x')
  })
})
