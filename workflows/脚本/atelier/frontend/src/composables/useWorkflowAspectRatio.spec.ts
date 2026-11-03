import { nextTick, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useWorkflowAspectRatio } from './useWorkflowAspectRatio'

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

describe('useWorkflowAspectRatio 比例按工作流记忆', () => {
  beforeEach(() => {
    stubStorage()
  })

  it('首次为空，交给工作流默认比例兜底', () => {
    const path = ref('/wf/ratio-a.json')
    expect(useWorkflowAspectRatio(path).value).toBe('')
  })

  it('两个工作流各存各的，切换后互不影响', async () => {
    const store = stubStorage()
    const path = ref('/wf/ratio-b.json')
    const ratio = useWorkflowAspectRatio(path)

    ratio.value = '9:16'
    await nextTick()
    path.value = '/wf/ratio-c.json'
    expect(ratio.value).toBe('')

    ratio.value = '1:1'
    await nextTick()
    expect(store.get('pb.aspectRatio:/wf/ratio-b.json')).toBe('9:16')
    expect(store.get('pb.aspectRatio:/wf/ratio-c.json')).toBe('1:1')

    path.value = '/wf/ratio-b.json'
    expect(ratio.value).toBe('9:16')
  })
})
