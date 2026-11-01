import { nextTick } from 'vue'
import { describe, expect, it, beforeEach } from 'vitest'

import { useComposerCanvas } from './useComposerCanvas'

const store = new Map<string, string>()
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
})

describe('useComposerCanvas', () => {
  it('填槽、生成标准文本、删除槽位并持久化', async () => {
    const composer = useComposerCanvas()

    composer.setSlot('人物面部', { content: '脸', promptId: 1, source: 'prompt' })
    composer.setSlot('场景环境', { content: '街', promptId: null, source: 'custom' })
    await nextTick()

    expect(composer.canvasCount.value).toBe(2)
    expect(composer.composedPrompt.value).toBe('【人物面部】\n脸\n\n【场景环境】\n街')
    expect(store.get('pb.composerCanvas')).toContain('人物面部')

    composer.removeSlot('人物面部')
    expect(composer.canvasCount.value).toBe(1)
  })

  it('pick 兼容碎片字段，固定列可切换并持久化', () => {
    const composer = useComposerCanvas()
    composer.pick({ type: '人物服饰', content: '裙', prompt_id: 3, source: 'prompt' })
    expect(composer.canvas.value['人物服饰']).toEqual({
      content: '裙',
      promptId: 3,
      source: 'prompt',
    })

    composer.togglePin('人物服饰')
    expect(composer.pinned.value).toEqual(['人物服饰'])
    expect(store.get('pb.composerPinned')).toContain('人物服饰')
    composer.togglePin('人物服饰')
    expect(composer.pinned.value).toEqual([])
  })
})
