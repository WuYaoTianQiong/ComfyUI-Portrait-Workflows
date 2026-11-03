import { beforeEach, describe, expect, it, vi } from 'vitest'

const { apiPost } = vi.hoisted(() => ({ apiPost: vi.fn() }))
vi.mock('../api/client', () => ({ apiPost }))

import { FRAGMENT_TYPES } from '../constants'
import {
  batchReplaceSegments,
  fragmentsInOrder,
  parseMarkedSegments,
  renderAllSegments,
  renderSegmented,
  renderSegments,
  smartSegmentText,
  toFragments,
} from './segmentation'

beforeEach(() => {
  apiPost.mockReset()
})

describe('关键词分段（纯前端启发式，后端没有对应实现）', () => {
  it('按关键词把一段话分到对应类型', () => {
    const text = '黑色长发，正脸看向镜头。身穿浅蓝色连衣裙，站在窗边。柔和的光线，赛璐璐画风。'
    const segments = smartSegmentText(text)
    expect(Object.keys(segments)).toContain('人物面部')
    expect(Object.keys(segments)).toContain('人物服饰')
    expect(Object.keys(segments)).toContain('画风技术')
  })

  it('空文本返回空结果', () => {
    expect(smartSegmentText('')).toEqual({})
  })

  it('没命中关键词的文本也能落到兜底类型，不丢内容', () => {
    const segments = smartSegmentText('qwerty zxcvb')
    expect(segments['画风技术']).toContain('qwerty')
  })
})

describe('碎片列表整形（纯前端，决定顺序与取舍）', () => {
  it('fragmentsInOrder 只保留内置类型并按内置顺序排列', () => {
    const fragments = fragmentsInOrder({ 画风技术: '赛璐璐', 人物面部: '黑发', 自定义氛围: '雨' })
    expect(fragments.map((f) => f.type)).toEqual(['人物面部', '画风技术'])
  })

  it('toFragments 保留自定义类型与对象键顺序', () => {
    const fragments = toFragments({ 人物面部: '黑发', 自定义氛围: '雨后街道', 空: '' })
    expect(fragments).toEqual([
      { type: '人物面部', content: '黑发' },
      { type: '自定义氛围', content: '雨后街道' },
    ])
  })
})

describe('【类型】语法全部走后端（POST /api/composition/*）', () => {
  it('parseMarkedSegments 把 fragments 折成 type→content 映射', async () => {
    apiPost.mockResolvedValue({
      fragments: [
        { type: '人物面部', content: '黑色长发' },
        { type: '人物服饰', content: '白色连衣裙' },
      ],
      leftover: '一个站在窗边的女孩',
    })

    const { marked, leftover } = await parseMarkedSegments('随便什么文本')

    expect(apiPost).toHaveBeenCalledWith('/api/composition/parse', { text: '随便什么文本' })
    expect(marked).toEqual({ 人物面部: '黑色长发', 人物服饰: '白色连衣裙' })
    expect(leftover).toBe('一个站在窗边的女孩')
  })

  it('renderSegmented 只提交内置 8 类，取返回的第 1 段', async () => {
    apiPost.mockResolvedValue({ texts: ['【人物面部】\n黑色长发'] })

    const text = await renderSegmented({ 人物面部: '黑色长发', 自定义氛围: '雨' })

    const [path, body] = apiPost.mock.calls[0]
    expect(path).toBe('/api/composition/render')
    const sent = (body as { items: Array<Array<{ type: string }>> }).items[0]
    expect(sent.map((f) => f.type)).toEqual(['人物面部'])
    expect(sent.every((f) => (FRAGMENT_TYPES as readonly string[]).includes(f.type))).toBe(true)
    expect(text).toBe('【人物面部】\n黑色长发')
  })

  it('renderAllSegments 保留自定义类型', async () => {
    apiPost.mockResolvedValue({ texts: ['【自定义氛围】\n雨后街道'] })

    const text = await renderAllSegments({ 自定义氛围: '雨后街道' })

    const sent = (apiPost.mock.calls[0][1] as { items: Array<Array<{ type: string }>> }).items[0]
    expect(sent).toEqual([{ type: '自定义氛围', content: '雨后街道' }])
    expect(text).toBe('【自定义氛围】\n雨后街道')
  })

  it('renderSegments 空输入不打后端', async () => {
    expect(await renderSegments([])).toEqual([])
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('batchReplaceSegments 按清单返回每个类型的结果，全部跳过时 replaced 为 null', async () => {
    apiPost.mockResolvedValue({
      items: [
        {
          id: 1,
          replaced: '【人物服饰】\n统一服饰\n\n【人物面部】\n银发',
          outcomes: [
            { type: '人物服饰', old_content: '白色连衣裙', action: 'replaced' },
            { type: '人物面部', old_content: '黑色长发', action: 'replaced' },
          ],
        },
        { id: 2, replaced: null, outcomes: [{ type: '人物服饰', old_content: '', action: 'skipped' }] },
      ],
    })

    const outcomes = await batchReplaceSegments(
      [{ id: 1, text: 'a' }, { id: 2, text: 'b' }],
      [
        { type: '人物服饰', content: '统一服饰' },
        { type: '人物面部', content: '银发' },
      ],
    )

    expect(apiPost).toHaveBeenCalledWith('/api/composition/batch_replace', {
      texts: [{ id: 1, text: 'a' }, { id: 2, text: 'b' }],
      replacements: [
        { type: '人物服饰', content: '统一服饰', missing: 'skip' },
        { type: '人物面部', content: '银发', missing: 'skip' },
      ],
    })
    expect(outcomes.get(1)).toEqual({
      replaced: '【人物服饰】\n统一服饰\n\n【人物面部】\n银发',
      outcomes: [
        { type: '人物服饰', oldContent: '白色连衣裙', action: 'replaced' },
        { type: '人物面部', oldContent: '黑色长发', action: 'replaced' },
      ],
    })
    expect(outcomes.get(2)?.replaced).toBeNull()
    expect(outcomes.get(2)?.outcomes[0].action).toBe('skipped')
  })

  it('batchReplaceSegments 把每个类型的缺失策略原样带给后端', async () => {
    apiPost.mockResolvedValue({
      items: [{ id: 2, replaced: '【人物服饰】\n统一服饰', outcomes: [] }],
    })

    await batchReplaceSegments(
      [{ id: 2, text: 'b' }],
      [{ type: '人物服饰', content: '统一服饰', missing: 'append' }],
    )

    expect(apiPost).toHaveBeenCalledWith('/api/composition/batch_replace', {
      texts: [{ id: 2, text: 'b' }],
      replacements: [{ type: '人物服饰', content: '统一服饰', missing: 'append' }],
    })
  })

  it('batchReplaceSegments 没有输入时不发请求', async () => {
    await batchReplaceSegments([], [{ type: '人物服饰', content: '统一服饰' }])
    await batchReplaceSegments([{ id: 1, text: 'a' }], [])
    expect(apiPost).not.toHaveBeenCalled()
  })
})
