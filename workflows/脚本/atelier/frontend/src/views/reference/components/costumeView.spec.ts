/**
 * 服装库视图层纯逻辑单测。
 *
 * 覆盖 §7 服装相关 6 行 + 下载分流：
 * 双库合并后的分类 / 标签联动、安全模式与 ` · 18+` 后缀、搜索、
 * 三库共用分页切片（服装页转出姿势库实现）、图片地址（统一走 referenceImageUrl、
 * 无二次拼接）、外链标注与「外链不下载 / 现实可下载」。
 */

import { describe, expect, it } from 'vitest'

import type { CostumeItem } from '../../../api/reference'

import {
  COSTUME_ALL_TAGS,
  DEFAULT_PAGE_SIZE,
  PAGE_SIZES,
  REMOTE_COSTUME_NOTE,
  REMOTE_COSTUME_SOURCE,
  REAL_COSTUME_SOURCE,
  clampPage,
  costumeAuthorSiteUrl,
  costumeBaseItems,
  costumeCategorySummaries,
  costumeCounter,
  costumeDownloadName,
  costumeHiddenNsfwCount,
  costumeLightboxMeta,
  costumePreviewUrl,
  costumeSourceLabel,
  costumeTagOptions,
  costumeTagPreview,
  costumeThumbnailUrl,
  filterCostumes,
  isRemoteCostume,
  matchesCostumeKind,
  normalizePageSize,
  pageCount,
  pageSlice,
  resolveActiveCategory,
  resolveActiveTag,
  safeExternalUrl,
  stepCostumeIndex,
} from './costumeView'
import type { CostumeFilters } from './costumeView'

/** 构造现实条目。 */
function real(overrides: Partial<CostumeItem> & { id: string }): CostumeItem {
  return {
    分类: '春季穿搭',
    一级分类: '现实',
    服装名称: '测试服装',
    标签: [],
    关键词: '',
    缩略图: '',
    预览图: '',
    原图: '',
    检索: '',
    library: 'costume',
    remote: false,
    ...overrides,
  }
}

/** 构造外链二次元条目（图片端点按传入 id 生成，避免断言被固定 URL 掩盖）。 */
function anime(overrides: Partial<CostumeItem> & { id: string }): CostumeItem {
  const id = overrides.id
  return {
    分类: '制服与校园风',
    一级分类: '二次元',
    服装名称: '藏青水手服',
    标签: ['水手服', '蓝色'],
    关键词: 'serafuku, sailor collar',
    缩略图: `/api/reference/items/costume-anime/${id}/image?kind=thumb`,
    预览图: `/api/reference/items/costume-anime/${id}/image?kind=image`,
    原图: `/api/reference/items/costume-anime/${id}/image?kind=image`,
    检索: `${id} 藏青水手服 制服与校园风 serafuku`,
    来源: REMOTE_COSTUME_SOURCE,
    来源地址: 'https://charadb-2fi.pages.dev/',
    library: 'costume-anime',
    remote: true,
    ...overrides,
  }
}

const EMPTY_FILTERS: CostumeFilters = { category: '', tag: COSTUME_ALL_TAGS, query: '' }

describe('一级分类与安全模式', () => {
  const items = [
    real({ id: 'r1', 分类: '春季穿搭' }),
    real({ id: 'r2', 分类: '冬季穿搭' }),
    anime({ id: 'a1', 分类: '制服与校园风' }),
    real({ id: 'r3', 分类: '泳装・度假', nsfw: true }),
  ]

  it('「全部」不限，现实中二次元按 一级分类 收窄', () => {
    expect(costumeBaseItems(items, '全部', false)).toHaveLength(4)
    expect(costumeBaseItems(items, '现实', false).map((item) => item.id)).toEqual(['r1', 'r2', 'r3'])
    expect(costumeBaseItems(items, '二次元', false).map((item) => item.id)).toEqual(['a1'])
    expect(matchesCostumeKind(items[0], '现实')).toBe(true)
    expect(matchesCostumeKind(items[0], '二次元')).toBe(false)
  })

  it('安全模式隐藏 18+，hiddenNsfwCount 按一级分类统计', () => {
    expect(costumeBaseItems(items, '全部', true).map((item) => item.id)).toEqual(['r1', 'r2', 'a1'])
    expect(costumeBaseItems(items, '现实', true).map((item) => item.id)).toEqual(['r1', 'r2'])
    expect(costumeHiddenNsfwCount(items, '全部')).toBe(1)
    expect(costumeHiddenNsfwCount(items, '现实')).toBe(1)
    expect(costumeHiddenNsfwCount(items, '二次元')).toBe(0)
  })

  it('安全模式下选中含 18+ 的分类自动落回「全部」', () => {
    expect(resolveActiveCategory('泳装・度假', true, items)).toBe('')
    expect(resolveActiveCategory('春季穿搭', true, items)).toBe('春季穿搭')
    expect(resolveActiveCategory('泳装・度假', false, items)).toBe('泳装・度假')
    expect(resolveActiveCategory('', true, items)).toBe('')
  })
})

describe('分类药丸', () => {
  const base = [
    real({ id: 'r1', 分类: '春季穿搭' }),
    real({ id: 'r2', 分类: '春季穿搭' }),
    real({ id: 'r3', 分类: '冬季穿搭' }),
    anime({ id: 'a1', 分类: '制服与校园风' }),
  ]
  // 安全模式下泳装被隐藏，但药丸仍要标记 18+
  const all = [...base, real({ id: 'r4', 分类: '泳装・度假', nsfw: true })]

  it('计数只统计当前一级分类范围，顺序按首次出现', () => {
    const summaries = costumeCategorySummaries(base, all)
    expect(summaries.map((item) => item.name)).toEqual(['春季穿搭', '冬季穿搭', '制服与校园风'])
    expect(summaries[0]).toMatchObject({ count: 2, nsfw: false })
  })

  it('18+ 标记按全部已加载条目聚合，被安全模式隐藏的分类也在内', () => {
    const summaries = costumeCategorySummaries(base, all)
    expect(summaries.some((item) => item.name === '泳装・度假')).toBe(false)
    expect(summaries.find((item) => item.name === '春季穿搭')?.nsfw).toBe(false)
  })

  it('空分类不产出药丸', () => {
    const summaries = costumeCategorySummaries([real({ id: 'x', 分类: '' })], [])
    expect(summaries).toEqual([])
  })
})

describe('标签下拉', () => {
  const items = [
    real({ id: 'r1', 分类: '春季穿搭', 标签: ['象牙白', '针织'] }),
    real({ id: 'r2', 分类: '春季穿搭', 标签: ['针织', '牛仔'] }),
    real({ id: 'r3', 分类: '冬季穿搭', 标签: ['羊毛'] }),
    anime({ id: 'a1', 分类: '制服与校园风', 标签: ['水手服', '蓝色'] }),
  ]

  it('按当前分类收窄，去重保序', () => {
    expect(costumeTagOptions(items, '')).toEqual(['象牙白', '针织', '牛仔', '羊毛', '水手服', '蓝色'])
    expect(costumeTagOptions(items, '春季穿搭')).toEqual(['象牙白', '针织', '牛仔'])
    expect(costumeTagOptions(items, '制服与校园风')).toEqual(['水手服', '蓝色'])
  })

  it('选中标签在当前分类下不存在时落回「全部」', () => {
    expect(resolveActiveTag('羊毛', items, '')).toBe('羊毛')
    expect(resolveActiveTag('羊毛', items, '春季穿搭')).toBe(COSTUME_ALL_TAGS)
    expect(resolveActiveTag(COSTUME_ALL_TAGS, items, '任何分类')).toBe(COSTUME_ALL_TAGS)
  })
})

describe('搜索 + 最终筛选', () => {
  const items = [
    real({ id: 'r1', 分类: '春季穿搭', 标签: ['针织'], 检索: 'SPR-0001 针织 春季 season denim' }),
    real({ id: 'r2', 分类: '冬季穿搭', 标签: ['羊毛'], 检索: 'WIN-0001 羊毛 winter coat' }),
    anime({ id: 'a1', 分类: '制服与校园风', 标签: ['水手服'], 检索: 'charadb-O001 水手服セーラー服 serafuku' }),
  ]

  it('分类精确匹配', () => {
    expect(filterCostumes(items, { ...EMPTY_FILTERS, category: '冬季穿搭' })).toHaveLength(1)
  })

  it('标签包含匹配', () => {
    expect(filterCostumes(items, { ...EMPTY_FILTERS, tag: '水手服' }).map((item) => item.id)).toEqual([
      'a1',
    ])
  })

  it('搜索只匹配 检索 串，去首尾空白且大小写无关', () => {
    expect(filterCostumes(items, { ...EMPTY_FILTERS, query: '  denim ' })).toHaveLength(1)
    expect(filterCostumes(items, { ...EMPTY_FILTERS, query: 'SERAFUKU' })).toHaveLength(1)
    expect(filterCostumes(items, { ...EMPTY_FILTERS, query: '不存在的词' })).toHaveLength(0)
  })

  it('三类条件同时生效', () => {
    expect(
      filterCostumes(items, { category: '春季穿搭', tag: '针织', query: 'SPR' }),
    ).toHaveLength(1)
    expect(
      filterCostumes(items, { category: '春季穿搭', tag: '羊毛', query: '' }),
    ).toHaveLength(0)
  })
})

describe('分页切片（复用姿势库实现）', () => {
  const items = Array.from({ length: 130 }, (_, index) => `c${index}`)

  it('服装页转出的分页常量与姿势库一致', () => {
    expect([...PAGE_SIZES]).toEqual([20, 60, 100, 200])
    expect(DEFAULT_PAGE_SIZE).toBe(60)
    expect(normalizePageSize(100)).toBe(100)
    // pageSize 非法（不在 20/60/100/200 内）回落 60
    expect(normalizePageSize(50)).toBe(60)
    expect(normalizePageSize(0)).toBe(60)
    expect(normalizePageSize('bad')).toBe(60)
  })

  it('第 1 页按 pageSize 切片', () => {
    expect(pageSlice(items, 1, 60)).toHaveLength(60)
    expect(pageSlice(items, 1, 60)[0]).toBe('c0')
  })

  it('最后一页不满时只返回剩余条目，越界页为空', () => {
    expect(pageSlice(items, 3, 60)).toEqual(['c120', 'c121', 'c122', 'c123', 'c124', 'c125', 'c126', 'c127', 'c128', 'c129'])
    expect(pageSlice(items, 4, 60)).toEqual([])
  })

  it('总页数向上取整，空列表至少 1 页', () => {
    expect(pageCount(1464, 60)).toBe(25)
    expect(pageCount(120, 60)).toBe(2)
    expect(pageCount(121, 60)).toBe(3)
    expect(pageCount(0, 60)).toBe(1)
  })

  it('页码越界夹到最后一页，非法页码夹到第 1 页', () => {
    expect(clampPage(2, 1464, 60)).toBe(2)
    expect(clampPage(99, 1464, 60)).toBe(25)
    expect(clampPage(0, 1464, 60)).toBe(1)
    expect(clampPage(Number.NaN, 1464, 60)).toBe(1)
    expect(clampPage(9, 10, 60)).toBe(1)
  })
})

describe('图片地址', () => {
  it('现实条目用后端下发的 thumb / image 端点', () => {
    const item = real({
      id: 'SPR-0001',
      缩略图: '/api/reference/items/costume/SPR-0001/image?kind=thumb',
      预览图: '/api/reference/items/costume/SPR-0001/image?kind=image',
      原图: '/api/reference/items/costume/SPR-0001/image?kind=image',
    })
    expect(costumeThumbnailUrl(item)).toBe('/api/reference/items/costume/SPR-0001/image?kind=thumb')
    expect(costumePreviewUrl(item)).toBe('/api/reference/items/costume/SPR-0001/image?kind=image')
  })

  it('外链条目保留 costume-anime 库名，不拼死库名', () => {
    const item = anime({ id: 'charadb-O001' })
    expect(costumeThumbnailUrl(item)).toBe(
      '/api/reference/items/costume-anime/charadb-O001/image?kind=thumb',
    )
  })

  it('无图返回 null，不产出空串或 //api 二次拼接', () => {
    const empty = real({ id: 'EMPTY-1' })
    expect(costumeThumbnailUrl(empty)).toBeNull()
    expect(costumePreviewUrl(empty)).toBeNull()

    // 只有原图、没有缩略图：按契约构造 thumb 端点，仍然只有单斜杠
    const noThumb = real({
      id: 'ONLY-IMAGE',
      原图: '/api/reference/items/costume/ONLY-IMAGE/image?kind=image',
    })
    const url = costumeThumbnailUrl(noThumb)
    expect(url).toBe('/api/reference/items/costume/ONLY-IMAGE/image?kind=thumb')
    expect(url?.startsWith('/api/reference/items/')).toBe(true)
    expect(url).not.toContain('//api')
  })
})

describe('外链标注与下载分流', () => {
  it('外链条目：来源 CharaDB、素材说明、标签全量', () => {
    const item = anime({ id: 'charadb-O001', 标签: ['制服与校园风', '水手服', '蓝色', '红色', '百褶', '半身裙'] })
    expect(isRemoteCostume(item)).toBe(true)
    expect(costumeSourceLabel(item)).toBe(REMOTE_COSTUME_SOURCE)

    const meta = costumeLightboxMeta(item)
    expect(meta).toEqual([
      { label: '分类', value: '制服与校园风' },
      { label: '来源', value: REMOTE_COSTUME_SOURCE },
      { label: '素材说明', value: REMOTE_COSTUME_NOTE },
      { label: '标签', value: '制服与校园风、水手服、蓝色、红色、百褶、半身裙' },
    ])
  })

  it('现实条目：来源回落作者署名，没有素材说明', () => {
    const item = real({ id: 'SPR-0001', 标签: ['针织', '象牙白'] })
    expect(isRemoteCostume(item)).toBe(false)
    expect(costumeSourceLabel(item)).toBe(REAL_COSTUME_SOURCE)
    expect(costumeLightboxMeta(item)).toEqual([
      { label: '分类', value: '春季穿搭' },
      { label: '来源', value: REAL_COSTUME_SOURCE },
      { label: '标签', value: '针织、象牙白' },
    ])
  })

  it('卡片只展示前 5 个标签，灯箱展示全量', () => {
    const item = anime({ id: 'x', 标签: ['a', 'b', 'c', 'd', 'e', 'f'] })
    expect(costumeTagPreview(item)).toEqual(['a', 'b', 'c', 'd', 'e'])
    expect(costumeTagPreview(item).length).toBeLessThan(item.标签.length)
    const meta = costumeLightboxMeta(item)
    expect(meta.find((row) => row.label === '标签')?.value).toBe('a、b、c、d、e、f')
  })

  it('*.pages.dev 外链被拦截，原作者站点回落到后端原图端点', () => {
    const item = anime({
      id: 'charadb-O001',
      来源地址: 'https://charadb-2fi.pages.dev/',
      原图: '/api/reference/items/costume-anime/charadb-O001/image?kind=image',
    })
    const preview = costumePreviewUrl(item)
    expect(safeExternalUrl('https://charadb-2fi.pages.dev/')).toBeNull()
    const author = costumeAuthorSiteUrl(item, preview)
    expect(author).toBe(preview)
    expect(author).not.toContain('pages.dev')
    expect(author?.startsWith('/api/reference/items/')).toBe(true)
  })

  it('非静态托管的上游地址原样保留', () => {
    const item = anime({ id: 'x', 来源地址: 'https://example.invalid/source/O001' })
    expect(costumeAuthorSiteUrl(item, '/api/fallback')).toBe(
      'https://example.invalid/source/O001',
    )
  })

  it('非法地址（javascript: / 空串）一律丢弃', () => {
    expect(safeExternalUrl('javascript:alert(1)')).toBeNull()
    expect(safeExternalUrl('')).toBeNull()
    expect(safeExternalUrl(null)).toBeNull()
    expect(costumeAuthorSiteUrl(anime({ id: 'x', 来源地址: undefined }), null)).toBeNull()
  })

  it('下载文件名固定 {id}.webp（仅现实条目使用）', () => {
    expect(costumeDownloadName(real({ id: 'SPR-0001' }))).toBe('SPR-0001.webp')
  })
})

describe('灯箱翻页', () => {
  it('计数文案从 1 开始', () => {
    expect(costumeCounter(0, 1068)).toBe('1 / 1068')
    expect(costumeCounter(11, 1068)).toBe('12 / 1068')
    expect(costumeCounter(0, 0)).toBe('')
  })

  it('左右翻页循环，不越界', () => {
    expect(stepCostumeIndex(0, 5, -1)).toBe(4)
    expect(stepCostumeIndex(4, 5, 1)).toBe(0)
    expect(stepCostumeIndex(2, 5, 1)).toBe(3)
    expect(stepCostumeIndex(2, 0, 1)).toBe(0)
  })
})