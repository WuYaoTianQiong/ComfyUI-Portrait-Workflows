/**
 * 提示词分段解析 / 拼装单测（P3，方案 §14）。
 *
 * 核心契约：`compose(parse(prompt)) === prompt`，
 * 这样「手动改写按原文提交」才有意义。
 */

import { describe, expect, it } from 'vitest'

import {
  composePromptSegments,
  figureBadge,
  figureLegend,
  parsePromptSegments,
  segmentDisplayLabel,
  segmentFigureRole,
  segmentOwner,
  segmentSourceHint,
  segmentTone,
} from './promptSegments'

const PROMPT = `请根据提供的 3 张参考图，生成一张完整的真实人物照片：
• 人物：图1中的人物，保持其脸型、五官一致。
• 服装：让人物穿上图2中展示的整套服装。
• 姿势：严格复现图3中人体模型的身体姿态。
• 拍摄视角：低角度仰拍
• 补充要求：暖色灯光
画面中没有任何文字、标志或水印。`

describe('parsePromptSegments', () => {
  it('拆出开头 / 5 个 bullet / 结尾', () => {
    const segments = parsePromptSegments(PROMPT)

    expect(segments.map((segment) => segment.kind)).toEqual([
      'head',
      'bullet',
      'bullet',
      'bullet',
      'bullet',
      'bullet',
      'tail',
    ])
    expect(segments[1].label).toBe('人物')
    expect(segments[1].text).toBe('图1中的人物，保持其脸型、五官一致。')
    expect(segments[6].text).toBe('画面中没有任何文字、标志或水印。')
  })

  it('兼容半角冒号', () => {
    const [segment] = parsePromptSegments('• 场景环境: 温馨卧室')
    expect(segment.kind).toBe('bullet')
    expect(segment.label).toBe('场景环境')
    expect(segment.text).toBe('温馨卧室')
  })

  it('没有 bullet 时整段作为开头', () => {
    const segments = parsePromptSegments('只有一段普通文本')
    expect(segments).toHaveLength(1)
    expect(segments[0].kind).toBe('head')
    expect(segments[0].text).toBe('只有一段普通文本')
  })

  it('空串返回空数组', () => {
    expect(parsePromptSegments('')).toEqual([])
    expect(parsePromptSegments('   \n  ')).toEqual([])
  })
})

describe('composePromptSegments', () => {
  it('解析后拼装能逐字还原原文', () => {
    expect(composePromptSegments(parsePromptSegments(PROMPT))).toBe(PROMPT)
  })

  it('空的 head / tail 不产生空行', () => {
    const segments = [
      { id: 'head', label: '', text: '', kind: 'head' as const },
      { id: 'bullet-0', label: '人物', text: '短发', kind: 'bullet' as const },
      { id: 'tail', label: '', text: '  ', kind: 'tail' as const },
    ]
    expect(composePromptSegments(segments)).toBe('• 人物：短发')
  })
})

describe('段展示辅助', () => {
  it('色调用标签前缀判定', () => {
    expect(segmentTone('人物')).toBe('portrait')
    expect(segmentTone('服装')).toBe('costume')
    expect(segmentTone('姿势')).toBe('pose')
    expect(segmentTone('拍摄视角')).toBe('modifier')
    expect(segmentTone('补充要求')).toBe('modifier')
    expect(segmentTone('双人要求')).toBe('neutral')
  })

  it('来源提示区分图片槽 / 碎片 / 预设 / 自由文本', () => {
    expect(segmentSourceHint('人物')).toBe('图片 + 补充碎片')
    expect(segmentSourceHint('场景环境')).toBe('碎片')
    expect(segmentSourceHint('风格')).toBe('画风预设')
    expect(segmentSourceHint('补充要求')).toBe('自由文本')
    expect(segmentSourceHint('双人要求')).toBe('自动生成')
  })

  it('开头 / 结尾使用占位展示名', () => {
    expect(segmentDisplayLabel({ id: 'head', label: '', text: 'x', kind: 'head' })).toBe('开头')
    expect(segmentDisplayLabel({ id: 'tail', label: '', text: 'x', kind: 'tail' })).toBe('结尾')
    expect(segmentDisplayLabel({ id: 'b', label: '人物', text: 'x', kind: 'bullet' })).toBe('人物')
  })
})

describe('人物A / 人物B 区分（2026-11-08）', () => {
  it('人物B 有独立色调，不再与人物A 同色', () => {
    expect(segmentTone('人物B（文字设定）')).toBe('person-b')
    expect(segmentTone('人物B（图像参考）')).toBe('person-b')
    expect(segmentTone('人物B（附加修饰）')).toBe('person-b')
    // 回归：A 的段色不变
    expect(segmentTone('人物')).toBe('portrait')
    expect(segmentTone('人物A')).toBe('portrait')
  })

  it('人物B 的来源提示不再误写成「图片」', () => {
    expect(segmentSourceHint('人物B（图像参考）')).toBe('图像')
    expect(segmentSourceHint('人物B（服装图像参考）')).toBe('图像')
    expect(segmentSourceHint('人物B（文字设定）')).toBe('文字碎片')
    expect(segmentSourceHint('人物B（姿态文字）')).toBe('文字碎片')
    expect(segmentSourceHint('人物B（附加修饰）')).toBe('文字碎片')
    expect(segmentSourceHint('人物B')).toBe('自动生成')
  })

  it('按标签前缀归组：B 优先，其次 A 专属前缀，其余为共用', () => {
    expect(segmentOwner('人物B（文字设定）')).toBe('B')
    expect(segmentOwner('人物B')).toBe('B')
    expect(segmentOwner('人物')).toBe('A')
    expect(segmentOwner('人物A')).toBe('A')
    expect(segmentOwner('服装')).toBe('A')
    expect(segmentOwner('姿势')).toBe('A')
    expect(segmentOwner('发型')).toBe('A')
    expect(segmentOwner('附加参考')).toBe('A')
    expect(segmentOwner('此外需体现')).toBe('A')
    expect(segmentOwner('双人要求')).toBe('shared')
    expect(segmentOwner('素体展示')).toBe('shared')
    expect(segmentOwner('拍摄视角')).toBe('shared')
    expect(segmentOwner('')).toBe('shared')
  })
})

describe('图号徽标（2026-11-08）', () => {
  const NUMBERS = { pose: 1, portrait: 2, costume: 3, extra: 4, extra_costume: 5 }

  it('段标签 → 图位角色：与后端 build_recipe_prompt 的图号来源一致', () => {
    expect(segmentFigureRole('人物')).toBe('portrait')
    expect(segmentFigureRole('人物A')).toBe('portrait')
    expect(segmentFigureRole('服装')).toBe('costume')
    expect(segmentFigureRole('姿势')).toBe('pose')
    expect(segmentFigureRole('人物B（图像参考）')).toBe('extra')
    expect(segmentFigureRole('人物B（服装图像参考）')).toBe('extra_costume')
    expect(segmentFigureRole('发型')).toBe('extra')
    expect(segmentFigureRole('附加参考')).toBe('extra')
    // 纯文字 / 共用条款不引用具体图位
    expect(segmentFigureRole('人物B')).toBeNull()
    expect(segmentFigureRole('人物B（文字设定）')).toBeNull()
    expect(segmentFigureRole('人物B（姿态文字）')).toBeNull()
    expect(segmentFigureRole('双人要求')).toBeNull()
    expect(segmentFigureRole('素体展示')).toBeNull()
    expect(segmentFigureRole('')).toBeNull()
  })

  it('figureBadge：有映射才显示图号，绝不显示错的图号', () => {
    expect(figureBadge('portrait', NUMBERS)).toBe('图2')
    expect(figureBadge('extra', NUMBERS)).toBe('图4')
    expect(figureBadge(null, NUMBERS)).toBe('')
    expect(figureBadge('pose', undefined)).toBe('')
    expect(figureBadge('pose', {})).toBe('')
    expect(figureBadge('pose', { pose: 0 })).toBe('')
  })

  it('figureLegend：固定顺序输出，缺失图位跳过', () => {
    expect(figureLegend(NUMBERS)).toBe('姿势=图1 · 人像=图2 · 服装=图3 · 第 4 张=图4 · 第 5 张=图5')
    // 服装空槽：图例仍显示服装=图3（空槽保留图号，用户才能看懂为何跳号）
    expect(figureLegend({ pose: 1, portrait: 2, costume: 3, extra: 4 })).toBe(
      '姿势=图1 · 人像=图2 · 服装=图3 · 第 4 张=图4',
    )
    expect(figureLegend({})).toBe('')
    expect(figureLegend(undefined)).toBe('')
  })
})
