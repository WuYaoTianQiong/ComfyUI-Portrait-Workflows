import { nextTick } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { useSettings } from './useSettings'

describe('useSettings 工作流按页独立', () => {
  it('提示词页 / 组合器 / 换脸各写各的 localStorage 键', async () => {
    // happy-dom 的 localStorage 在测试里不一定可用，这里补一份
    const store = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
      clear: () => store.clear(),
    })

    const { workflowPath, composerWorkflowPath, faceswapWorkflowPath } = useSettings()

    workflowPath.value = 'prompt.json'
    composerWorkflowPath.value = 'composer.json'
    faceswapWorkflowPath.value = 'faceswap.json'
    await nextTick()

    expect(localStorage.getItem('pb.workflowPath')).toBe('prompt.json')
    expect(localStorage.getItem('pb.composerWorkflowPath')).toBe('composer.json')
    expect(localStorage.getItem('pb.faceswapWorkflowPath')).toBe('faceswap.json')
  })
})
