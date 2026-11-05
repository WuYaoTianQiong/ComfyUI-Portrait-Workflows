/**
 * 人像库视图层纯逻辑单测（阶段 2.3a）。
 *
 * 覆盖 §7 人像 4 行的判定核心：
 * - 分区 / 发长药丸计数（全库统计）与「再次点击取消」；
 * - 发型细分下拉按分区 / 发长联动收窄、中文排序、失效选项回落；
 * - 搜索语义（检索串 + ID，AND 组合）；
 * - 加载更多（初始 60、每次 +60、非分页）；
 * - 灯箱翻页循环与原图尺寸文案；
 * - 图片地址（thumb / image、无图 null、无二次拼接）。
 */

import { describe, expect, it } from 'vitest'

import type { PortraitItem } from '../../../api/reference'

import {
  ALL_STYLES,
  INITIAL_PORTRAIT_COUNT,
  PORTRAIT_HAIRS,
  PORTRAIT_LOAD_MORE_STEP,
  PORTRAIT_SECTIONS,
  activePortraitStyle,
  filterPortraits,
  formatPortraitSize,
  matchesPortraitFilters,
  matchesPortraitQuery,
  nextPortraitShown,
  portraitHairCounts,
  portraitLoadMoreState,
  portraitPreviewUrl,
  portraitSectionCounts,
  portraitStyleOptions,
  portraitThumbnailUrl,
  stepPortraitIndex,
  togglePortraitHair,
  togglePortraitSection,
} from './portraitView'
import type { PortraitFilters } from './portraitView'

const EMPTY_FILTERS: PortraitFilters = { section: '', hair: '', styleName: ALL_STYLES, query: '' }

function portrait(overrides: Partial<PortraitItem> & { id: string }): PortraitItem {
  return {
    分区: '正脸参考',
    发长: '短发',
    发型名称: '波波头',
    标题: '短发・标准款',
    宽: 0,
    高: 0,
    字节数: 0,
    精选: false,
    热门: false,
    缩略图: '',
    原图: '',
    检索: '',
    library: 'portrait',
    nsfw: false,
    ...overrides,
  }
}

/** 覆盖两个分区、四种发长、多种发型的样本。 */
function sample(): PortraitItem[] {
  return [
    portrait({
      id: 'a1',
      分区: '正脸参考',
      发长: '短发',
      发型名称: '波波头',
      检索: 'a1 正脸参考 短发 波波头',
    }),
    portrait({
      id: 'a2',
      分区: '正脸参考',
      发长: '中发',
      发型名称: '狼尾',
      检索: 'a2 正脸参考 中发 狼尾',
    }),
    portrait({
      id: 'a3',
      分区: '正脸参考',
      发长: '中长发',
      发型名称: '空气刘海',
      检索: 'a3 正脸参考 中长发 空气刘海',
    }),
    portrait({
      id: 'b1',
      分区: '造型氛围',
      发长: '长发',
      发型名称: '大波浪',
      检索: 'b1 造型氛围 长发 大波浪',
    }),
    portrait({
      id: 'b2',
      分区: '造型氛围',
      发长: '短发',
      发型名称: '波波头',
      检索: 'b2 造型氛围 短发 波波头',
    }),
  ]
}

describe('枚举与常量（§7 冻结）', () => {
  it('分区固定 正脸参考 / 造型氛围', () => {
    expect([...PORTRAIT_SECTIONS]).toEqual(['正脸参考', '造型氛围'])
  })

  it('发长固定 短发 / 中发 / 中长发 / 长发', () => {
    expect([...PORTRAIT_HAIRS]).toEqual(['短发', '中发', '中长发', '长发'])
  })

  it('首屏 60 张、每次 +60（加载更多，不是分页）', () => {
    expect(INITIAL_PORTRAIT_COUNT).toBe(60)
    expect(PORTRAIT_LOAD_MORE_STEP).toBe(60)
  })
})

describe('药丸：计数与二次点击取消', () => {
  const items = sample()

  it('分区 / 发长数量按全库统计，与当前筛选无关', () => {
    expect(portraitSectionCounts(items)).toEqual([
      { value: '正脸参考', count: 3 },
      { value: '造型氛围', count: 2 },
    ])
    expect(portraitHairCounts(items)).toEqual([
      { value: '短发', count: 2 },
      { value: '中发', count: 1 },
      { value: '中长发', count: 1 },
      { value: '长发', count: 1 },
    ])
  })

  it('再次点击同一分区 / 发长会取消（回到全部）', () => {
    expect(togglePortraitSection('', '正脸参考')).toBe('正脸参考')
    expect(togglePortraitSection('正脸参考', '正脸参考')).toBe('')
    expect(togglePortraitSection('正脸参考', '造型氛围')).toBe('造型氛围')

    expect(togglePortraitHair('', '短发')).toBe('短发')
    expect(togglePortraitHair('短发', '短发')).toBe('')
    expect(togglePortraitHair('短发', '长发')).toBe('长发')
  })
})

describe('筛选语义', () => {
  const items = sample()

  it('分区与发长可叠加（AND）', () => {
    expect(filterPortraits(items, { ...EMPTY_FILTERS, section: '正脸参考' })).toHaveLength(3)
    expect(filterPortraits(items, { ...EMPTY_FILTERS, hair: '短发' })).toHaveLength(2)
    expect(
      filterPortraits(items, { ...EMPTY_FILTERS, section: '造型氛围', hair: '短发' }).map(
        (item) => item.id,
      ),
    ).toEqual(['b2'])
  })

  it('发型细分精确匹配，ALL_STYLES 表示不限制', () => {
    expect(
      filterPortraits(items, { ...EMPTY_FILTERS, styleName: '波波头' }).map((item) => item.id),
    ).toEqual(['a1', 'b2'])
    expect(filterPortraits(items, { ...EMPTY_FILTERS, styleName: ALL_STYLES })).toHaveLength(5)
  })

  it('搜索大小写无关、去首尾空白，且支持按 ID 搜', () => {
    expect(matchesPortraitQuery(items[0], '  波波头 ')).toBe(true)
    expect(matchesPortraitQuery(items[0], 'A1')).toBe(true)
    expect(matchesPortraitQuery(items[0], '不存在的词')).toBe(false)
    expect(filterPortraits(items, { ...EMPTY_FILTERS, query: 'b2' }).map((item) => item.id)).toEqual([
      'b2',
    ])
  })

  it('四类条件同时生效', () => {
    const filters: PortraitFilters = {
      section: '造型氛围',
      hair: '短发',
      styleName: '波波头',
      query: 'b2',
    }
    expect(matchesPortraitFilters(items[1], filters)).toBe(false)
    expect(filterPortraits(items, filters).map((item) => item.id)).toEqual(['b2'])
  })
})

describe('发型细分下拉联动收窄', () => {
  const items = sample()

  it('无分区 / 发长时展示全部发型，去重并按中文排序', () => {
    // localeCompare('zh-CN') 按拼音：bo(波) < da(大) < kong(空) < lang(狼)
    expect(portraitStyleOptions(items, '', '')).toEqual(['波波头', '大波浪', '空气刘海', '狼尾'])
  })

  it('选分区后只剩该分区的发型', () => {
    expect(portraitStyleOptions(items, '造型氛围', '')).toEqual(['波波头', '大波浪'])
    expect(portraitStyleOptions(items, '正脸参考', '')).toEqual(['波波头', '空气刘海', '狼尾'])
  })

  it('选发长后继续收窄；分区 + 发长取交集', () => {
    expect(portraitStyleOptions(items, '', '短发')).toEqual(['波波头'])
    expect(portraitStyleOptions(items, '正脸参考', '中发')).toEqual(['狼尾'])
    expect(portraitStyleOptions(items, '', '长发')).toEqual(['大波浪'])
  })

  it('联动后当前选项失效时自动回落「全部」', () => {
    const narrowed = portraitStyleOptions(items, '造型氛围', '长发')
    expect(activePortraitStyle('狼尾', narrowed)).toBe(ALL_STYLES)
    expect(activePortraitStyle('大波浪', narrowed)).toBe('大波浪')
    expect(activePortraitStyle(ALL_STYLES, narrowed)).toBe(ALL_STYLES)
  })
})

describe('加载更多（不是分页）', () => {
  it('剩余数量与按钮文案', () => {
    expect(portraitLoadMoreState(60, 1499)).toEqual({
      hasMore: true,
      remaining: 1439,
      label: '加载更多（剩余 1439 张）',
    })
  })

  it('到末尾后不再显示按钮', () => {
    expect(portraitLoadMoreState(1499, 1499)).toEqual({
      hasMore: false,
      remaining: 0,
      label: '加载更多（剩余 0 张）',
    })
  })

  it('步进 +60 并收敛到总数，不越界', () => {
    expect(nextPortraitShown(60, 1499)).toBe(120)
    expect(nextPortraitShown(120, 130)).toBe(130)
    expect(nextPortraitShown(130, 130)).toBe(130)
    expect(nextPortraitShown(0, 0)).toBe(0)
  })
})

describe('灯箱翻页与尺寸文案', () => {
  it('前后翻页在结果集内循环', () => {
    expect(stepPortraitIndex(0, 1, 3)).toBe(1)
    expect(stepPortraitIndex(2, 1, 3)).toBe(0)
    expect(stepPortraitIndex(0, -1, 3)).toBe(2)
    expect(stepPortraitIndex(1, 5, 3)).toBe(0)
    expect(stepPortraitIndex(4, 1, 3)).toBe(2)
  })

  it('空结果集返回 0，不产生 NaN', () => {
    expect(stepPortraitIndex(3, 1, 0)).toBe(0)
  })

  it('尺寸缺失显示「—」而不是 0 × 0', () => {
    expect(formatPortraitSize(0, 0)).toBe('—')
    expect(formatPortraitSize(-1, 800)).toBe('—')
    expect(formatPortraitSize(Number.NaN, 800)).toBe('—')
    expect(formatPortraitSize(1200, 1500)).toBe('1200 × 1500')
  })
})

describe('图片地址', () => {
  it('有缩略图 / 原图时原样使用后端下发地址', () => {
    const item = portrait({
      id: 'p1',
      缩略图: '/api/reference/items/portrait/p1/image?kind=thumb',
      原图: '/api/reference/items/portrait/p1/image?kind=image',
    })
    expect(portraitThumbnailUrl(item)).toBe('/api/reference/items/portrait/p1/image?kind=thumb')
    expect(portraitPreviewUrl(item)).toBe('/api/reference/items/portrait/p1/image?kind=image')
  })

  it('缩略图缺失但有原图时按契约构造 thumb 端点', () => {
    const item = portrait({
      id: 'p2',
      缩略图: '',
      原图: '/api/reference/items/portrait/p2/image?kind=image',
    })
    expect(portraitThumbnailUrl(item)).toBe('/api/reference/items/portrait/p2/image?kind=thumb')
  })

  it('完全无图返回 null（渲染占位），不产出空串或 //api 二次拼接', () => {
    const empty = portrait({ id: 'p3' })
    expect(portraitThumbnailUrl(empty)).toBeNull()
    expect(portraitPreviewUrl(empty)).toBeNull()

    const item = portrait({
      id: 'p4',
      缩略图: '/api/reference/items/portrait/p4/image?kind=thumb',
    })
    for (const url of [portraitThumbnailUrl(item), portraitPreviewUrl(item)]) {
      expect(url).not.toBe('')
      expect(url).not.toContain('//api')
      expect(url?.startsWith('/api/reference/items/portrait/')).toBe(true)
    }
  })

  it('人像没有深度图：深度 kind 不参与本页，且不构造 depth 地址', () => {
    const item = portrait({
      id: 'p5',
      缩略图: '/api/reference/items/portrait/p5/image?kind=thumb',
    })
    expect(portraitThumbnailUrl(item)).not.toContain('kind=depth')
    expect(portraitPreviewUrl(item)).not.toContain('kind=depth')
  })
})