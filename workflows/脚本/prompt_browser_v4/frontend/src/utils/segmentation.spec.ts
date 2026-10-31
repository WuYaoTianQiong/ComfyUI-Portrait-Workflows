import { describe, expect, it } from 'vitest'

import {
  parseMarkedSegments,
  renderAllSegments,
  renderSegmented,
  replaceMarkedSegment,
  smartSegmentText,
} from './segmentation'

describe('智能分段', () => {
  it('按关键词把一段话分到对应类型', () => {
    const text = '黑色长发，正脸看向镜头。身穿浅蓝色连衣裙，站在窗边。柔和的光线，赛璐璐画风。'
    const segments = smartSegmentText(text)
    expect(Object.keys(segments)).toContain('人物面部')
    expect(Object.keys(segments)).toContain('人物服饰')
    expect(Object.keys(segments)).toContain('画风技术')
  })

  it('渲染成【类型】格式，与组合器输出一致', () => {
    const segments = smartSegmentText('黑色长发，身穿连衣裙')
    const text = renderSegmented(segments)
    expect(text).toMatch(/【人物面部】\n/)
    expect(text).toMatch(/【人物服饰】\n/)
  })

  it('空文本返回空结果', () => {
    expect(smartSegmentText('')).toEqual({})
    expect(renderSegmented({})).toBe('')
  })

  it('没命中关键词的文本也能落到兜底类型，不丢内容', () => {
    const segments = smartSegmentText('qwerty zxcvb')
    const text = renderSegmented(segments)
    expect(text).toContain('qwerty')
  })
})

describe('已分段提示词的再次分段', () => {
  it('全部是【类型】块时，leftover 为空，不会被再次分段', () => {
    const text = '【人物面部】\n黑色长发\n\n【人物服饰】\n白色连衣裙'
    const { marked, leftover } = parseMarkedSegments(text)
    expect(leftover).toBe('')
    expect(marked['人物面部']).toBe('黑色长发')
    expect(marked['人物服饰']).toBe('白色连衣裙')
  })

  it('混合文本只把未标记部分交给智能分段', () => {
    const text = '【人物面部】\n黑色长发\n\n一个站在窗边的女孩'
    const { marked, leftover } = parseMarkedSegments(text)
    expect(marked['人物面部']).toBe('黑色长发')
    expect(leftover).toBe('一个站在窗边的女孩')
  })

  it('渲染时保留自定义碎片名，不按内置类型过滤', () => {
    const text = renderAllSegments({ 人物面部: '黑色长发', 自定义氛围: '雨后街道' })
    expect(text).toContain('【自定义氛围】')
    expect(text).toContain('雨后街道')
  })
})

describe('批量替换碎片', () => {
  it('只替换目标类型，其他块原样保留', () => {
    const text = '【人物面部】黑色长发\n\n【人物身材】旧身材\n\n【场景环境】街道'
    const replaced = replaceMarkedSegment(text, '人物身材', '统一身材')
    expect(replaced).toBe('【人物面部】黑色长发\n\n【人物身材】\n统一身材\n\n【场景环境】街道')
    expect(replaced).toContain('黑色长发')
    expect(replaced).toContain('街道')
    expect(replaced).not.toContain('旧身材')
  })

  it('没有目标类型时返回 null，交给调用方跳过', () => {
    expect(replaceMarkedSegment('【人物面部】黑色长发', '人物身材', '新身材')).toBeNull()
  })

  it('扁平文本（没有【类型】块）也返回 null，不会被凭空加上一段', () => {
    expect(replaceMarkedSegment('一整段没有分块的提示词', '人物身材', '新身材')).toBeNull()
  })
})