/**
 * 文本补充 / 槽位模式纯数据层单测（P2 替代态，方案 §4.4 / §8 P2）。
 *
 * 覆盖：
 * - `deriveSlotMode` 的旧数据推导口径（有图 → image，无图有文本 → text，否则 empty）；
 * - 模式表容错归一与整份推导；
 * - 矩阵组键 / 组标签：text 槽必须带文本内容（不同文本不能碰撞成同一组）；
 * - 文本前 12 字预览。
 */

import { describe, expect, it } from 'vitest'

import {
  EMPTY_SLOT_TEXTS,
  buildRecipeSlotDisplays,
  cloneSlotModes,
  cloneSupplementFlags,
  compileActiveSlotTexts,
  compileSlotTexts,
  createEmptyRecipeTextFragments,
  createEmptySlotModes,
  createEmptySupplementFlags,
  deriveSlotMode,
  deriveSlotModes,
  slotDisplaysGroupKey,
  slotDisplaysGroupLabel,
  slotTextPreview,
} from './recipeTextFragments'

describe('deriveSlotMode（旧快照缺 mode 时的推导）', () => {
  it('有图 → image（即使也有碎片）', () => {
    expect(deriveSlotMode(1, [{ type: '人物面部', content: '圆脸' }])).toBe('image')
  })

  it('无图但有对应碎片 → text', () => {
    expect(deriveSlotMode(0, [{ type: '人物服饰', content: '白色衬衫' }])).toBe('text')
  })

  it('无图且无碎片 → empty', () => {
    expect(deriveSlotMode(0, [])).toBe('empty')
    expect(deriveSlotMode(0, undefined)).toBe('empty')
  })
})

describe('模式表容错与整份推导', () => {
  it('cloneSlotModes：非对象 / 非法值回退 empty，合法值保留', () => {
    expect(cloneSlotModes(undefined)).toEqual(createEmptySlotModes())
    expect(cloneSlotModes('bad')).toEqual(createEmptySlotModes())
    expect(
      cloneSlotModes({ portrait: 'text', costume: 'nope', pose: 'image' }),
    ).toEqual({ portrait: 'text', costume: 'empty', pose: 'image' })
  })

  it('deriveSlotModes：人像槽合并面部 + 身材两类', () => {
    const fragments = {
      ...createEmptyRecipeTextFragments(),
      人物身材: [{ type: '人物身材' as const, content: '身形纤细' }],
    }
    expect(
      deriveSlotModes({ portrait: 0, costume: 0, pose: 0 }, fragments),
    ).toEqual({ portrait: 'text', costume: 'empty', pose: 'empty' })

    expect(
      deriveSlotModes({ portrait: 2, costume: 1, pose: 0 }, fragments),
    ).toEqual({ portrait: 'image', costume: 'image', pose: 'empty' })
  })
})

describe('compileSlotTexts', () => {
  it('人像槽把面部与身材以「；」连接', () => {
    const texts = compileSlotTexts({
      ...createEmptyRecipeTextFragments(),
      人物面部: [{ type: '人物面部', content: '圆脸' }],
      人物身材: [{ type: '人物身材', content: '身形纤细' }],
      人物服饰: [{ type: '人物服饰', content: '白色衬衫' }],
      姿态动作: [{ type: '姿态动作', content: '自然站立' }],
    })
    expect(texts).toEqual({
      portrait: '圆脸；身形纤细',
      costume: '白色衬衫',
      pose: '自然站立',
    })
  })

  it('逐条去掉尾部句号，不产生「。；」', () => {
    const texts = compileSlotTexts({
      ...createEmptyRecipeTextFragments(),
      人物面部: [{ type: '人物面部', content: '圆脸。' }],
      人物身材: [{ type: '人物身材', content: '身形纤细。' }],
      人物服饰: [
        { type: '人物服饰', content: '白色衬衫。' },
        { type: '人物服饰', content: '黑色长裤。' },
      ],
    })
    expect(texts.portrait).toBe('圆脸；身形纤细')
    expect(texts.costume).toBe('白色衬衫；黑色长裤')
    expect(texts.portrait).not.toContain('。；')
  })
})

describe('compileActiveSlotTexts（P4 只统计真正生效的文本）', () => {
  const fragments = {
    ...createEmptyRecipeTextFragments(),
    人物面部: [{ type: '人物面部' as const, content: '圆脸' }],
    人物服饰: [{ type: '人物服饰' as const, content: '白色衬衫' }],
    姿态动作: [{ type: '姿态动作' as const, content: '自然站立' }],
  }

  it('text 模式恒生效；image 模式只有开关打开才生效；empty 恒空', () => {
    const modes = { portrait: 'image', costume: 'text', pose: 'empty' } as const
    expect(
      compileActiveSlotTexts(fragments, modes, {
        portrait: false,
        costume: false,
        pose: false,
      }),
    ).toEqual({ portrait: '', costume: '白色衬衫', pose: '' })

    expect(
      compileActiveSlotTexts(fragments, modes, {
        portrait: true,
        costume: false,
        pose: true,
      }),
    ).toEqual({ portrait: '圆脸', costume: '白色衬衫', pose: '' })
  })
})

describe('cloneSupplementFlags（容错）', () => {
  it('非对象 / 脏值一律按 false，显式 true 保留', () => {
    expect(cloneSupplementFlags(undefined)).toEqual(createEmptySupplementFlags())
    expect(cloneSupplementFlags('bad')).toEqual(createEmptySupplementFlags())
    expect(
      cloneSupplementFlags({ portrait: true, costume: 'yes', pose: 1 }),
    ).toEqual({ portrait: true, costume: false, pose: false })
  })
})

describe('slotTextPreview', () => {
  it('不超过 12 字原样返回，超过加省略号', () => {
    expect(slotTextPreview('短文本')).toBe('短文本')
    expect(slotTextPreview('一二三四五六七八九十十一')).toBe('一二三四五六七八九十十一')
    expect(slotTextPreview('这是一段明显超过十二个字的碎片内容')).toBe(
      '这是一段明显超过十二个字…',
    )
    expect(slotTextPreview('  前后空白  ')).toBe('前后空白')
  })
})

describe('矩阵组键 / 组标签（文本槽）', () => {
  const slots = {
    portrait: { id: 'pt1', name: '人像A' },
    costume: { id: 'c1', name: '服装B' },
    pose: null,
  }

  it('text 槽组键包含完整文本、组标签用前 12 字，不显示空图占位', () => {
    const displays = buildRecipeSlotDisplays({
      slots,
      modes: { portrait: 'image', costume: 'text', pose: 'empty' },
      texts: {
        ...EMPTY_SLOT_TEXTS,
        costume: '白色衬衫配黑色西裤和黑色皮鞋',
      },
    })

    expect(displays[0].key).toBe('pt1')
    expect(displays[0].label).toBe('人像A')
    expect(displays[1].mode).toBe('text')
    expect(displays[1].key).toBe('text:白色衬衫配黑色西裤和黑色皮鞋')
    expect(displays[1].label).toBe('白色衬衫配黑色西裤和黑色…')
    expect(displays[1].textLabel).toBe('文本 · 人物服饰')
    expect(displays[2].key).toBe('')
    expect(displays[2].label).toBe('')
  })

  it('不同文本 → 不同组键（矩阵里不会碰撞成同一组）', () => {
    const base = {
      slots,
      modes: { portrait: 'image', costume: 'text', pose: 'empty' } as const,
    }
    const first = buildRecipeSlotDisplays({
      ...base,
      texts: { ...EMPTY_SLOT_TEXTS, costume: '白色衬衫' },
    })
    const second = buildRecipeSlotDisplays({
      ...base,
      texts: { ...EMPTY_SLOT_TEXTS, costume: '黑色外套' },
    })

    expect(slotDisplaysGroupKey(first)).not.toBe(slotDisplaysGroupKey(second))
  })

  it('P4 image + 补充：组键带补充文本，缩略图展示补充小标', () => {
    const displays = buildRecipeSlotDisplays({
      slots,
      modes: { portrait: 'image', costume: 'image', pose: 'empty' },
      texts: { ...EMPTY_SLOT_TEXTS, portrait: '圆脸' },
      supplements: { portrait: true, costume: false, pose: false },
    })

    expect(displays[0].key).toBe('pt1|supp:圆脸')
    expect(displays[0].label).toBe('人像A（+文本补充）')
    expect(displays[0].supplementLabel).toBe('补充 · 人物面部')
    expect(displays[0].supplementPreview).toBe('圆脸')

    // 开关关闭的 image 槽不带补充文本
    expect(displays[1].key).toBe('c1')
    expect(displays[1].supplementLabel).toBe('')
  })

  it('组名只拼接非空片段；全空时给「未选参考图」', () => {
    const displays = buildRecipeSlotDisplays({
      slots: { portrait: null, costume: null, pose: null },
      modes: { portrait: 'empty', costume: 'empty', pose: 'empty' },
      texts: { ...EMPTY_SLOT_TEXTS },
    })
    expect(slotDisplaysGroupLabel(displays)).toBe('未选参考图')
  })
})