import { describe, expect, it } from 'vitest'

import { renderSegmented, smartSegmentText } from './segmentation'

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