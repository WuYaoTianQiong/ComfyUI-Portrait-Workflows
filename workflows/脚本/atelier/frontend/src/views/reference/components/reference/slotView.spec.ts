/**
 * 合成台槽位视图层单测。
 *
 * 覆盖：
 * - 多选顺序保持「加入顺序」，不被排序 / 去重打乱；
 * - `thumb` 与新增 `image` 字段各自取值（人像 / 服装 / 姿势）；
 * - 姿势槽按每条自身加入时的白模 / 深度图模式取图，同一数组内可混合；
 * - 无图条目返回 null（调用方渲染占位，不产出空 src）。
 */

import { describe, expect, it } from 'vitest'

import type { CostumeItem, PortraitItem, PoseItem } from '../../../../api/reference'

import { costumeSlotItems, poseSlotItems, portraitSlotItems } from './slotView'

function portrait(overrides: Partial<PortraitItem> & { id: string }): PortraitItem {
  return {
    分区: '',
    发长: '',
    发型名称: '',
    标题: '',
    宽: 0,
    高: 0,
    字节数: 0,
    精选: false,
    热门: false,
    缩略图: '',
    原图: '',
    检索: '',
    ...overrides,
  }
}

function costume(overrides: Partial<CostumeItem> & { id: string }): CostumeItem {
  return {
    分类: '',
    服装名称: '',
    标签: [],
    关键词: '',
    缩略图: '',
    预览图: '',
    原图: '',
    检索: '',
    ...overrides,
  }
}

function pose(overrides: Partial<PoseItem> & { id: string }): PoseItem {
  return {
    体系: '',
    姿势编号: '',
    分类: '',
    姿势名称: '',
    角度: '',
    缩略图: '',
    原图: '',
    检索: '',
    ...overrides,
  }
}

describe('portraitSlotItems', () => {
  it('保持多选加入顺序，并同时填充 thumb / image', () => {
    const items = portraitSlotItems([
      portrait({
        id: 'P_B',
        分区: '女性',
        发型名称: '长直发',
        标题: '长发女生',
        缩略图: '/t/p-b.webp',
        原图: '/i/p-b.webp',
      }),
      portrait({
        id: 'P_A',
        分区: '女性',
        发型名称: '短发',
        标题: '短发女生',
        缩略图: '/t/p-a.webp',
        原图: '/i/p-a.webp',
      }),
    ])

    expect(items.map((item) => item.key)).toEqual(['P_B', 'P_A'])
    expect(items[0]).toEqual({
      key: 'P_B',
      name: '长直发',
      thumb: '/t/p-b.webp',
      image: '/i/p-b.webp',
    })
  })

  it('发型名缺失时名称回退标题', () => {
    const [item] = portraitSlotItems([portrait({ id: 'P1', 标题: '只填了标题' })])

    expect(item?.name).toBe('只填了标题')
  })

  it('无原图时 image 回退缩略图；完全无图时两者都是 null', () => {
    const [withThumbOnly] = portraitSlotItems([
      portrait({ id: 'P1', 缩略图: '/t/p1.webp' }),
    ])
    const [noImage] = portraitSlotItems([portrait({ id: 'P2' })])

    expect(withThumbOnly?.thumb).toBe('/t/p1.webp')
    expect(withThumbOnly?.image).toBe('/t/p1.webp')
    expect(noImage?.thumb).toBeNull()
    expect(noImage?.image).toBeNull()
  })
})

describe('costumeSlotItems', () => {
  it('填充服装名称 / 缩略图 / 原图，且不改变加入顺序', () => {
    const items = costumeSlotItems([
      costume({
        id: 'C2',
        一级分类: '二次元',
        library: 'costume-anime',
        服装名称: '水手服',
        缩略图: '/t/c2.webp',
        原图: '/i/c2.webp',
      }),
      costume({
        id: 'C1',
        一级分类: '现实',
        library: 'costume',
        服装名称: '白衬衫',
        缩略图: '/t/c1.webp',
        原图: '/i/c1.webp',
      }),
    ])

    expect(items.map((item) => item.key)).toEqual(['C2', 'C1'])
    expect(items[0]).toEqual({
      key: 'C2',
      name: '水手服',
      thumb: '/t/c2.webp',
      image: '/i/c2.webp',
    })
  })
})

describe('poseSlotItems', () => {
  const basePose = pose({
    id: 'P001_正面',
    体系: '全身单人・标准系',
    姿势编号: 'P001',
    姿势名称: '站姿',
    角度: '正面',
    缩略图: '/t/pose.webp',
    原图: '/i/pose.webp',
    depthThumbUrl: '/t/pose-depth.webp',
    depthUrl: '/i/pose-depth.webp',
  })

  it('白模模式取缩略图 / 原图', () => {
    const [item] = poseSlotItems([{ item: basePose, useDepth: false }])

    expect(item).toEqual({
      key: 'P001_正面',
      name: '站姿 · 正面',
      thumb: '/t/pose.webp',
      image: '/i/pose.webp',
    })
  })

  it('深度模式取深度缩略图 / 深度大图', () => {
    const [item] = poseSlotItems([{ item: basePose, useDepth: true }])

    expect(item?.thumb).toBe('/t/pose-depth.webp')
    expect(item?.image).toBe('/i/pose-depth.webp')
  })

  it('同一数组内可按各自加入时的模式混排', () => {
    const items = poseSlotItems([
      { item: basePose, useDepth: false },
      { item: { ...basePose, id: 'P002_侧面', 姿势名称: '坐姿', 角度: '侧面' }, useDepth: true },
    ])

    expect(items[0]?.image).toBe('/i/pose.webp')
    expect(items[1]?.image).toBe('/i/pose-depth.webp')
    expect(items[1]?.key).toBe('P002_侧面')
  })

  it('深度图字段缺失时按契约端点取图，不返回空串', () => {
    const [item] = poseSlotItems([
      { item: { ...basePose, depthThumbUrl: null, depthUrl: null }, useDepth: true },
    ])

    expect(item?.thumb).toBe('/api/reference/items/pose/P001_%E6%AD%A3%E9%9D%A2/image?kind=depth')
    expect(item?.image).toBe('/api/reference/items/pose/P001_%E6%AD%A3%E9%9D%A2/image?kind=depth')
  })
})