import { describe, expect, it } from 'vitest'

import {
  desiredPoseFacets,
  pickMatchedPose,
  pickPoseForFacet,
  poseFacetToken,
} from './studioPoseMatch'

const POOL = [
  { id: 'stand', 分类: '站姿' },
  { id: 'sit', 分类: '坐姿' },
  { id: 'kneel', 分类: '跪立' },
  { id: 'lie', 分类: '趴卧' },
  { id: 'lean', 分类: '前倾' },
  { id: 'pair-sit', 分类: '坐姿' },
]

const first = () => 0

describe('desiredPoseFacets', () => {
  it('识别站 / 坐 / 跪 / 卧 / 前倾 / 蹲', () => {
    expect(desiredPoseFacets('她站在窗边')).toEqual(['站'])
    expect(desiredPoseFacets('她坐在床边')).toEqual(['坐'])
    expect(desiredPoseFacets('跪坐在地毯上')).toEqual(['跪', '坐'])
    expect(desiredPoseFacets('侧卧在沙发上')).toEqual(['卧'])
    expect(desiredPoseFacets('身体前倾俯身')).toEqual(['前倾'])
    expect(desiredPoseFacets('蹲在墙边')).toEqual(['特殊'])
    expect(desiredPoseFacets('她向前迈步行走')).toEqual(['站'])
  })

  it('空文本 / 无姿势词返回空数组', () => {
    expect(desiredPoseFacets('')).toEqual([])
    expect(desiredPoseFacets('她看向镜头')).toEqual([])
  })
})

describe('pickMatchedPose', () => {
  it('按文字匹配 facet，并排除 pair*', () => {
    expect(pickMatchedPose(POOL, '她坐在床边', first)?.id).toBe('sit')
    expect(pickMatchedPose(POOL, '她跪坐在地上', first)?.id).toBe('kneel')
    expect(pickMatchedPose(POOL, '她侧卧着', first)?.id).toBe('lie')
    expect(pickMatchedPose(POOL, '她迈步行走', first)?.id).toBe('stand')
  })

  it('匹配不到时回退到全部安全单人姿势', () => {
    expect(pickMatchedPose(POOL, '她看向镜头', first)?.id).toBe('stand')
  })

  it('只有双人姿势时返回 undefined', () => {
    expect(pickMatchedPose([{ id: 'pair-sit', 分类: '坐姿' }], '坐')).toBeUndefined()
  })
})

describe('pickPoseForFacet（原子库 pose_facet 优先）', () => {
  it('poseFacetToken 映射站/走/坐/前倾/跪', () => {
    expect(poseFacetToken('stand')).toBe('站')
    expect(poseFacetToken('walk')).toBe('站')
    expect(poseFacetToken('sit')).toBe('坐')
    expect(poseFacetToken('lean')).toBe('前倾')
    expect(poseFacetToken('kneel')).toBe('跪')
  })

  it('按 facet 选姿势并排除 pair', () => {
    expect(pickPoseForFacet(POOL, 'walk', first)?.id).toBe('stand')
    expect(pickPoseForFacet(POOL, 'sit', first)?.id).toBe('sit')
    expect(pickPoseForFacet(POOL, 'lean', first)?.id).toBe('lean')
    expect(pickPoseForFacet(POOL, 'kneel', first)?.id).toBe('kneel')
  })

  it('未知 facet 回退到安全单人池', () => {
    expect(pickPoseForFacet(POOL, 'nope', first)?.id).toBe('stand')
  })
})
