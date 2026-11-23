import { ref, watch } from 'vue'

import { FRAGMENT_TYPES } from '../constants'

/**
 * 「批量替换」与「替换碎片」共用同一个弹窗组件，但这是两件不同的事：
 * 前者的清单是"这一批要换的 8 类碎片"，后者是"这一条要换的一段"。
 * 旧实现两处共用一把 localStorage 键，于是批量配好的清单会突然出现在
 * 单条入口里，用户以为自己在改一条，其实动的是另一套设置。
 *
 * 这里按入口分键存储：`pb.batchReplace.rows.batch` / `.single`。
 * 旧版共享键只在批量入口认领一次（那是它的主要用途），认领后即删除，
 * 避免继续漏进单条入口。
 */
export type ReplaceMode = 'batch' | 'single'

export interface ReplaceRow {
  key: number
  type: string
  content: string
  missing: 'skip' | 'append'
}

const STORAGE_PREFIX = 'pb.batchReplace.rows'
const LEGACY_KEY = 'pb.batchReplace'

export function useReplaceRows(mode: () => ReplaceMode) {
  let rowSeq = 0
  const rows = ref<ReplaceRow[]>([])
  let saveTimer: number | undefined

  function storageKey(): string {
    return `${STORAGE_PREFIX}.${mode()}`
  }

  function makeRow(type = '', content = '', missing: 'skip' | 'append' = 'skip'): ReplaceRow {
    return { key: ++rowSeq, type, content, missing }
  }

  /** 只认 8 类里的类型、同类只留一条；坏数据直接丢，不让弹窗带着脏清单启动。 */
  function parse(raw: string | null): ReplaceRow[] {
    if (!raw) return []
    try {
      const parsed = JSON.parse(raw) as { rows?: unknown }
      if (!Array.isArray(parsed.rows)) return []
      const seen = new Set<string>()
      const out: ReplaceRow[] = []
      for (const item of parsed.rows) {
        if (!item || typeof item !== 'object') continue
        const row = item as Partial<ReplaceRow>
        if (typeof row.type !== 'string') continue
        if (!(FRAGMENT_TYPES as readonly string[]).includes(row.type)) continue
        if (seen.has(row.type)) continue
        seen.add(row.type)
        out.push(makeRow(
          row.type,
          typeof row.content === 'string' ? row.content : '',
          row.missing === 'append' ? 'append' : 'skip',
        ))
      }
      return out
    } catch {
      return []
    }
  }

  function read(): ReplaceRow[] {
    try {
      const own = localStorage.getItem(storageKey())
      if (own) return parse(own)
      if (mode() !== 'batch') return []
      const legacy = localStorage.getItem(LEGACY_KEY)
      if (!legacy) return []
      localStorage.removeItem(LEGACY_KEY)
      return parse(legacy)
    } catch {
      /* localStorage 不可用时按空清单处理 */
      return []
    }
  }

  function load(): ReplaceRow[] {
    rows.value = read()
    return rows.value
  }

  function reset() {
    rows.value = []
    try {
      localStorage.removeItem(storageKey())
    } catch {
      /* 忽略 */
    }
  }

  function scheduleSave() {
    if (typeof window === 'undefined') return
    window.clearTimeout(saveTimer)
    saveTimer = window.setTimeout(() => {
      try {
        localStorage.setItem(storageKey(), JSON.stringify({
          rows: rows.value.map((r) => ({ type: r.type, content: r.content, missing: r.missing })),
        }))
      } catch {
        /* localStorage 不可用时忽略 */
      }
    }, 300)
  }

  watch(rows, scheduleSave, { deep: true })

  return { rows, makeRow, load, reset }
}
