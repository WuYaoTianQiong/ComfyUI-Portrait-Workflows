import { computed, ref, watch } from 'vue'

import { FRAGMENT_TYPES } from '../constants'

export interface CanvasSlot {
  content: string
  promptId: number | null
  source: 'prompt' | 'library' | 'custom'
}

const CANVAS_KEY = 'pb.composerCanvas'
const PIN_KEY = 'pb.composerPinned'

function readCanvas(): Record<string, CanvasSlot> {
  try {
    const raw = localStorage.getItem(CANVAS_KEY)
    const parsed = raw ? (JSON.parse(raw) as Record<string, CanvasSlot>) : {}
    if (!parsed || typeof parsed !== 'object') return {}
    const out: Record<string, CanvasSlot> = {}
    for (const [type, slot] of Object.entries(parsed)) {
      if ((FRAGMENT_TYPES as readonly string[]).includes(type) && slot?.content) out[type] = slot
    }
    return out
  } catch {
    return {}
  }
}

function readPinned(): string[] {
  try {
    const raw = localStorage.getItem(PIN_KEY)
    const parsed = raw ? (JSON.parse(raw) as string[]) : []
    return Array.isArray(parsed)
      ? parsed.filter((t) => (FRAGMENT_TYPES as readonly string[]).includes(t))
      : []
  } catch {
    return []
  }
}

/**
 * 组合器画布：每个类型一个槽位（同类型只能有一个碎片），并记住固定列。
 *
 * 持久化放在这里，视图只关心"选了哪个碎片 / 随机成什么"。
 */
export function useComposerCanvas() {
  const canvas = ref<Record<string, CanvasSlot>>(readCanvas())

  watch(
    canvas,
    (value) => {
      try {
        localStorage.setItem(CANVAS_KEY, JSON.stringify(value))
      } catch {
        /* 隐私模式下忽略 */
      }
    },
    { deep: true },
  )

  const pinned = ref<string[]>(readPinned())

  function togglePin(type: string) {
    pinned.value = pinned.value.includes(type)
      ? pinned.value.filter((t) => t !== type)
      : [...pinned.value, type]
    try {
      localStorage.setItem(PIN_KEY, JSON.stringify(pinned.value))
    } catch {
      /* 忽略 */
    }
  }

  const canvasTypes = computed(() => FRAGMENT_TYPES.filter((t) => canvas.value[t]))
  const canvasCount = computed(() => canvasTypes.value.length)

  /** 渲染成标准文本：与后端 `composition.render` 完全一致的格式。 */
  const composedPrompt = computed(() =>
    canvasTypes.value.map((t) => `【${t}】\n${canvas.value[t].content}`).join('\n\n'),
  )

  function setSlot(type: string, slot: CanvasSlot) {
    canvas.value = { ...canvas.value, [type]: slot }
  }

  function removeSlot(type: string) {
    const next = { ...canvas.value }
    delete next[type]
    canvas.value = next
  }

  function setCanvas(next: Record<string, CanvasSlot>) {
    canvas.value = next
  }

  function pick(item: {
    type: string
    content: string
    prompt_id: number | null
    source: CanvasSlot['source']
  }) {
    setSlot(item.type, {
      content: item.content,
      promptId: item.prompt_id,
      source: item.source,
    })
  }

  return {
    canvas,
    pinned,
    canvasTypes,
    canvasCount,
    composedPrompt,
    setSlot,
    removeSlot,
    setCanvas,
    pick,
    togglePin,
  }
}
