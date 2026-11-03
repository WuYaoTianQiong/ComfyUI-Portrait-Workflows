import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  confirmDialog,
  isConfirmSkipped,
  resetConfirmSkip,
  skipConfirm,
} from './naive'
import {
  CONFIRM_PROMPTS,
  listSkippedPrompts,
  resetAllConfirmSkips,
} from './confirmKeys'

/** happy-dom 的 localStorage 在部分运行方式下只是空壳，补一份最小实现。 */
const store = new Map<string, string>()
vi.stubGlobal('localStorage', {
  getItem: (key: string) => store.get(key) ?? null,
  setItem: (key: string, value: string) => void store.set(key, value),
  removeItem: (key: string) => void store.delete(key),
  clear: () => store.clear(),
})

describe('确认框「下次不再提示」', () => {
  beforeEach(() => store.clear())

  it('勾过之后同 key 的确认框直接放行', async () => {
    const key = CONFIRM_PROMPTS.batchReplace.key
    expect(isConfirmSkipped(key)).toBe(false)

    skipConfirm(key)
    expect(isConfirmSkipped(key)).toBe(true)
    await expect(confirmDialog({ content: '替换碎片出图？', rememberKey: key })).resolves.toBe(
      true,
    )
  })

  it('恢复单条后重新询问', () => {
    skipConfirm(CONFIRM_PROMPTS.batchReplace.key)
    skipConfirm(CONFIRM_PROMPTS.editorSubmit.key)
    expect(listSkippedPrompts().map((p) => p.key)).toEqual([
      CONFIRM_PROMPTS.batchReplace.key,
      CONFIRM_PROMPTS.editorSubmit.key,
    ])

    resetConfirmSkip(CONFIRM_PROMPTS.batchReplace.key)
    expect(listSkippedPrompts().map((p) => p.key)).toEqual([
      CONFIRM_PROMPTS.editorSubmit.key,
    ])
  })

  it('全部恢复清空登记表里的所有记忆', () => {
    for (const prompt of Object.values(CONFIRM_PROMPTS)) skipConfirm(prompt.key)
    resetAllConfirmSkips()
    expect(listSkippedPrompts()).toEqual([])
  })
})
