/**
 * 人像库视图层纯逻辑单测（阶段 2.3a）。
 *
 * 覆盖 §7 人像 4 行的判定核心：
 * - 分区 / 发长药丸计数（全库统计）与「再次点击取消」；
 * - 发型细分下拉按分区 / 发长联动收窄、中文排序、失效选项回落；
 * - 搜索语义（检索串 + ID，AND 组合）；
 * - 三库共用分页切片（人像页转出姿势库实现，每页 20/60/100/200）；
 * - 灯箱翻页循环与原图尺寸文案；
 * - 图片地址（thumb / image、无图 null、无二次拼接）。
 */

import { describe, expect, it } from 'vitest'

import type { PortraitItem } from '../../../api/reference'

import {
  ALL_STYLES,
  DEFAULT_PAGE_SIZE,
  PAGE_SIZES,
  PORTRAIT_HAIRS,
  PORTRAIT_SECTIONS,
  activePortraitStyle,
  clampPage,
  filterPortraits,
  formatPortraitSize,
  matchesPortraitFilters,
  matchesPortraitQuery,
  normalizePageSize,
  pageCount,
  pageSlice,
  portraitHairCounts,
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

  it('分页默认每页 60 张，下拉可选 20 / 60 / 100 / 200', () => {
    expect(DEFAULT_PAGE_SIZE).toBe(60)
    expect([...PAGE_SIZES]).toEqual([20, 60, 100, 200])
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

describe('分页切片（复用姿势库实现）', () => {
  const items = Array.from({ length: 1499 }, (_, index) => `p${index}`)

  it('第 1 页按 pageSize 切片，页码从 1 开始', () => {
    expect(pageSlice(items, 1, 60)).toHaveLength(60)
    expect(pageSlice(items, 1, 60)[0]).toBe('p0')
    expect(pageSlice(items, 1, 100)[99]).toBe('p99')
  })

  it('最后一页不满时只返回剩余条目，越界页为空', () => {
    // 1499 = 24 * 60 + 59，最后一页 59 张
    expect(pageSlice(items, 25, 60)).toHaveLength(59)
    expect(pageSlice(items, 25, 60)[58]).toBe('p1498')
    expect(pageSlice(items, 26, 60)).toEqual([])
  })

  it('pageSize 非法回落 60，页码非法回第 1 页', () => {
    expect(normalizePageSize(50)).toBe(60)
    expect(normalizePageSize(0)).toBe(60)
    expect(normalizePageSize(undefined)).toBe(60)
    expect(pageSlice(items, 0, 60)).toHaveLength(60)
    expect(pageSlice(items, Number.NaN, 60)).toHaveLength(60)
  })

  it('总页数向上取整，空列表至少 1 页', () => {
    expect(pageCount(1499, 60)).toBe(25)
    expect(pageCount(1499, 100)).toBe(15)
    expect(pageCount(0, 60)).toBe(1)
    expect(pageCount(60, 60)).toBe(1)
    expect(pageCount(61, 60)).toBe(2)
  })

  it('页码越界夹到最后一页，非法页码夹到第 1 页', () => {
    expect(clampPage(2, 1499, 60)).toBe(2)
    expect(clampPage(99, 1499, 60)).toBe(25)
    expect(clampPage(0, 1499, 60)).toBe(1)
    expect(clampPage(Number.NaN, 1499, 60)).toBe(1)
    expect(clampPage(99, 10, 60)).toBe(1)
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