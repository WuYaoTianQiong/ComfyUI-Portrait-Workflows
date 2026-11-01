import { nextTick, ref } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { usePromptDraft } from './usePromptDraft'
import type { PromptDetail } from '../api/types'

vi.mock('../utils/naive', () => ({
  confirmDialog: vi.fn(),
}))

import { confirmDialog } from '../utils/naive'

const store = new Map<string, string>()

function detail(overrides: Partial<PromptDetail> = {}): PromptDetail {
  return {
    id: 1,
    name: '名称',
    prompt: '正文',
    negative_prompt: '',
    tags: 'a,b',
    note: '',
    steps: 20,
    cfg_scale: 7,
    sampler: 'euler',
    seed: 42,
    is_favorite: false,
    is_pinned: false,
    rating: null,
    usage_count: 0,
    created_at: '',
    updated_at: '',
    ...overrides,
  } as unknown as PromptDetail
}

beforeEach(() => {
  store.clear()
  Object.defineProperty(globalThis, 'localStorage', {
    value: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value)
      },
      removeItem: (key: string) => {
        store.delete(key)
      },
    },
    configurable: true,
  })
  vi.mocked(confirmDialog).mockReset()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('usePromptDraft', () => {
  it('详情变化后计算脏态，revert 恢复服务端内容', async () => {
    const current = ref<PromptDetail | undefined>(undefined)
    const selectedId = ref<number | null>(1)
    const promptDraft = usePromptDraft(current, selectedId)

    current.value = detail()
    await nextTick()
    expect(promptDraft.draft.value?.prompt).toBe('正文')
    expect(promptDraft.dirty.value).toBe(false)

    promptDraft.draft.value!.prompt = '改了'
    expect(promptDraft.dirty.value).toBe(true)

    promptDraft.revert()
    expect(promptDraft.draft.value?.prompt).toBe('正文')
    expect(promptDraft.dirty.value).toBe(false)
  })

  it('发现本地草稿且用户确认后恢复', async () => {
    store.set('pb.draft.1', JSON.stringify({ prompt: '本地草稿' }))
    vi.mocked(confirmDialog).mockResolvedValue(true)

    const current = ref<PromptDetail | undefined>(undefined)
    const selectedId = ref<number | null>(1)
    const promptDraft = usePromptDraft(current, selectedId)

    current.value = detail()
    await nextTick()
    await flushPromises()

    expect(confirmDialog).toHaveBeenCalled()
    expect(promptDraft.draft.value?.prompt).toBe('本地草稿')
    expect(promptDraft.dirty.value).toBe(true)
  })

  it('800ms 后自动保存可编辑字段，markSaved 清掉本地草稿', async () => {
    vi.useFakeTimers()
    const current = ref<PromptDetail | undefined>(detail())
    const selectedId = ref<number | null>(1)
    const promptDraft = usePromptDraft(current, selectedId)
    await nextTick()

    promptDraft.draft.value!.prompt = '自动保存'
    await nextTick()
    vi.advanceTimersByTime(800)
    expect(store.get('pb.draft.1')).toContain('自动保存')

    promptDraft.markSaved()
    expect(store.get('pb.draft.1')).toBeUndefined()
  })
})
