import { computed, ref, watch, type Ref } from 'vue'

import type { PromptDetail } from '../api/types'
import { confirmDialog } from '../utils/naive'

const DRAFT_KEY = (id: number) => `pb.draft.${id}`

/** 只有这些字段算"用户编辑"；收藏/置顶/评级等元数据变化不应触发脏状态。 */
const EDITABLE_KEYS: Array<keyof PromptDetail> = [
  'name',
  'tags',
  'prompt',
  'negative_prompt',
  'note',
  'steps',
  'cfg_scale',
  'sampler',
  'seed',
]

function editableSnapshot(value: PromptDetail): Partial<PromptDetail> {
  return {
    name: value.name,
    tags: value.tags,
    prompt: value.prompt,
    negative_prompt: value.negative_prompt,
    note: value.note,
    steps: value.steps,
    cfg_scale: value.cfg_scale,
    sampler: value.sampler,
    seed: value.seed,
  }
}

function sameEditable(a: Partial<PromptDetail>, b: Partial<PromptDetail>): boolean {
  return EDITABLE_KEYS.every((key) => a[key] === b[key])
}

function readSavedDraft(id: number): Partial<PromptDetail> | null {
  try {
    const raw = localStorage.getItem(DRAFT_KEY(id))
    return raw ? (JSON.parse(raw) as Partial<PromptDetail>) : null
  } catch {
    return null
  }
}

/** 标签文本拆分：与后端 `services/taxonomy.split_tags` 一致，不拆空格。 */
export function splitTagText(text: string): string[] {
  return text
    .split(/[,，;；]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

/**
 * 提示词详情的本地草稿：脏态、自动保存、刷新后恢复。
 *
 * 详情查询、保存 mutation、删除等仍留在视图；这里只拥有"编辑中的那份副本"。
 */
export function usePromptDraft(
  detail: Ref<PromptDetail | undefined>,
  selectedId: Ref<number | null>,
) {
  const draft = ref<PromptDetail | null>(null)
  /** 草稿恢复只针对"刚打开这条提示词"；详情因收藏/置顶等 refetch 时不再弹窗。 */
  const restoredFor = ref<number | null>(null)

  const dirty = computed(() => {
    if (!draft.value || !detail.value) return false
    // 跨条目的比较没有意义：切换瞬间 draft 还是上一条，会误判成"有未保存修改"
    if (draft.value.id !== detail.value.id) return false
    return !sameEditable(editableSnapshot(draft.value), editableSnapshot(detail.value))
  })

  let draftTimer: number | undefined

  watch(selectedId, () => {
    restoredFor.value = null
  })

  /**
   * 详情到达后初始化草稿；只有"首次打开这条提示词"才检查本地草稿。
   */
  watch(
    detail,
    async (value) => {
      if (!value) {
        draft.value = null
        return
      }
      const id = selectedId.value
      if (id === null) {
        draft.value = { ...value }
        return
      }

      // 已有未保存编辑：只同步服务端元数据，绝不能用服务端正文覆盖本地正文。
      if (draft.value && draft.value.id === value.id && dirty.value) {
        draft.value = {
          ...draft.value,
          is_favorite: value.is_favorite,
          is_pinned: value.is_pinned,
          rating: value.rating,
          usage_count: value.usage_count,
          updated_at: value.updated_at,
        }
        return
      }

      draft.value = { ...value }
      if (restoredFor.value === id) return
      restoredFor.value = id

      const saved = readSavedDraft(id)
      if (!saved) return
      if (sameEditable(saved, editableSnapshot(value))) {
        localStorage.removeItem(DRAFT_KEY(id))
        return
      }
      const restore = await confirmDialog({
        title: '发现本地草稿',
        content: '这条提示词有未保存的草稿，要恢复吗？',
        positiveText: '恢复草稿',
        negativeText: '丢弃',
        type: 'info',
      })
      if (restore) draft.value = { ...value, ...saved }
      else localStorage.removeItem(DRAFT_KEY(id))
    },
    { immediate: true },
  )

  const draftTagList = computed<string[]>({
    get: () => splitTagText(draft.value?.tags ?? ''),
    set: (list: string[]) => {
      if (draft.value) draft.value.tags = list.join(',')
    },
  })

  /** 800ms 合并写草稿；定时器触发时锁定当时的条目 id。 */
  watch(
    draft,
    (value) => {
      if (!value || selectedId.value === null) return
      const id = selectedId.value
      window.clearTimeout(draftTimer)
      draftTimer = window.setTimeout(() => {
        const snapshot = editableSnapshot(value)
        const server = detail.value ? editableSnapshot(detail.value) : null
        try {
          if (server && sameEditable(snapshot, server)) {
            localStorage.removeItem(DRAFT_KEY(id))
            return
          }
          localStorage.setItem(DRAFT_KEY(id), JSON.stringify(snapshot))
        } catch {
          /* 隐私模式下不可用，忽略 */
        }
      }, 800)
    },
    { deep: true },
  )

  function clearSavedDraft(id: number | null = selectedId.value) {
    window.clearTimeout(draftTimer)
    if (id !== null) localStorage.removeItem(DRAFT_KEY(id))
  }

  function markSaved() {
    clearSavedDraft(selectedId.value)
  }

  function revert() {
    draft.value = detail.value ? { ...detail.value } : null
  }

  function clearDraft() {
    draft.value = null
  }

  return {
    draft,
    dirty,
    draftTagList,
    revert,
    markSaved,
    clearDraft,
  }
}
