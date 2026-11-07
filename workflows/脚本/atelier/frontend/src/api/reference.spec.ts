/**
 * 参考图库数据层单测。
 *
 * 覆盖施工手册 §4「1.2 数据层」验收口径：
 * 6 并发上限、去重保序、total 补拉、任一页失败整体 reject、null/tags 归一、
 * `costume-anime` 一级分类收窄、图片 URL 无 `//` 且 depth 仅 pose。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  REFERENCE_MAX_CONCURRENT_PAGES,
  REFERENCE_MAX_PAGES,
  REFERENCE_PAGE_SIZE,
  costumeCategoryHasNsfw,
  fetchAllReferenceItems,
  isNsfwCostumeItem,
  isNsfwPoseItem,
  poseSystemHasNsfw,
  referenceImageEndpoint,
  referenceImageUrl,
  toCostumeItem,
  toPortraitItem,
  toPoseItem,
} from './reference'
import type { PoseGroup, ReferenceItemDto, ReferenceItemListDto } from './reference'

/** 构造完整 DTO；overrides 允许故意塞 null / undefined 验证归一化。 */
function dto(overrides: Record<string, unknown> = {}): ReferenceItemDto {
  return {
    id: 'item-1',
    library: 'pose',
    name: '',
    subtitle: '',
    group: '',
    facet: '',
    angle: '',
    tags: [],
    keywords: '',
    thumb_url: null,
    image_url: null,
    depth_url: null,
    depth_thumb_url: null,
    hot: false,
    featured: false,
    nsfw: false,
    remote: false,
    number: '',
    source_url: null,
    search_text: '',
    ...overrides,
  } as unknown as ReferenceItemDto
}

/** 与后端响应等价的极简 Response（不依赖全局 Response，happy-dom 下最稳）。 */
interface FakeResponse {
  ok: boolean
  status: number
  json: () => Promise<unknown>
  text: () => Promise<string>
}

function jsonResponse(body: unknown, status = 200): FakeResponse {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  }
}

function pageBody(
  items: ReferenceItemDto[],
  total: number,
  page = 1,
): ReferenceItemListDto {
  return { items, total, page, page_size: REFERENCE_PAGE_SIZE }
}

interface RecordedCall {
  library: string
  page: number
  url: URL
}

interface ConcurrencyProbe {
  inFlight: number
  maxInFlight: number
}

/**
 * 替换全局 fetch，记录每次请求的库/页号与并发峰值。
 *
 * 注意：inFlight 必须在 handler 返回（含 await）之后才递减，
 * 否则并发统计只会看到同步入队瞬间。
 */
function stubFetch(
  handler: (url: URL, callIndex: number) => FakeResponse | Promise<FakeResponse>,
) {
  const calls: RecordedCall[] = []
  const probe: ConcurrencyProbe = { inFlight: 0, maxInFlight: 0 }

  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost')
    calls.push({
      library: url.searchParams.get('library') ?? '',
      page: Number(url.searchParams.get('page') ?? '1'),
      url,
    })
    probe.inFlight += 1
    probe.maxInFlight = Math.max(probe.maxInFlight, probe.inFlight)
    try {
      return await handler(url, calls.length - 1)
    } finally {
      probe.inFlight -= 1
    }
  })
  vi.stubGlobal('fetch', mock)
  return { calls, probe, mock }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

// ---------------------------------------------------------------------------
// 分页：并发、页序、去重、补拉、上限、失败
// ---------------------------------------------------------------------------

describe('fetchAllReferenceItems 分页算法', () => {
  it('page_size=200，首屏先取 page=1', async () => {
    const { calls } = stubFetch((url) => {
      const page = Number(url.searchParams.get('page'))
      return jsonResponse(pageBody([dto({ id: `p${page}` })], 1, page))
    })

    await fetchAllReferenceItems('pose')

    expect(calls).toHaveLength(1)
    expect(calls[0].page).toBe(1)
    expect(calls[0].url.searchParams.get('page_size')).toBe('200')
    expect(calls[0].url.searchParams.get('library')).toBe('pose')
  })

  it('其余页并发数不超过 6，且确实达到 6（20 页）', async () => {
    const total = REFERENCE_PAGE_SIZE * 20
    const { calls, probe } = stubFetch(async (url) => {
      const page = Number(url.searchParams.get('page'))
      await delay(5)
      return jsonResponse(pageBody([dto({ id: `p${page}` })], total, page))
    })

    const items = await fetchAllReferenceItems('pose')

    // 1 首屏 + 19 其余页 = 20 次请求；每条 id 唯一，全部保留
    expect(calls).toHaveLength(20)
    expect(items).toHaveLength(20)
    expect(probe.maxInFlight).toBe(REFERENCE_MAX_CONCURRENT_PAGES)
    expect(probe.maxInFlight).toBeLessThanOrEqual(6)
  })

  it('按页序合并，同 id 去重且保留首次出现位置', async () => {
    const total = REFERENCE_PAGE_SIZE * 3
    const { calls } = stubFetch(async (url) => {
      const page = Number(url.searchParams.get('page'))
      // 让后面的页先返回，验证合并不依赖完成顺序
      if (page === 2) await delay(15)
      if (page === 3) await delay(1)
      const byPage: Record<number, ReferenceItemDto[]> = {
        1: [dto({ id: 'a' }), dto({ id: 'b' })],
        2: [dto({ id: 'a' }), dto({ id: 'c' }), dto({ id: 'd' })],
        3: [dto({ id: 'b' }), dto({ id: 'e' })],
      }
      return jsonResponse(pageBody(byPage[page], total, page))
    })

    const items = await fetchAllReferenceItems('pose')

    expect(calls.map((call) => call.page).sort((a, b) => a - b)).toEqual([1, 2, 3])
    expect(items.map((item) => item.id)).toEqual(['a', 'b', 'c', 'd', 'e'])
  })

  it('分页期间 total 变大时补拉一轮增量页', async () => {
    const { calls } = stubFetch((url) => {
      const page = Number(url.searchParams.get('page'))
      const totals: Record<number, number> = {
        1: REFERENCE_PAGE_SIZE * 2,
        2: REFERENCE_PAGE_SIZE * 3,
        3: REFERENCE_PAGE_SIZE * 3,
      }
      const byPage: Record<number, ReferenceItemDto[]> = {
        1: [dto({ id: 'a' })],
        2: [dto({ id: 'b' })],
        3: [dto({ id: 'c' })],
      }
      return jsonResponse(pageBody(byPage[page], totals[page], page))
    })

    const items = await fetchAllReferenceItems('pose')

    expect(calls.map((call) => call.page).sort((a, b) => a - b)).toEqual([1, 2, 3])
    expect(items.map((item) => item.id)).toEqual(['a', 'b', 'c'])
  })

  it('补拉只做一轮：增量页再次抬高 total 也不再翻页', async () => {
    const { calls } = stubFetch((url) => {
      const page = Number(url.searchParams.get('page'))
      // 首屏 total=600（3 页）；page=2 在分页期间把 total 抬到 800（4 页），
      // 因此补拉 page=4；page=4 再抬到 5 页，但补拉已结束，不得请求 page=5
      const total = page === 2 ? REFERENCE_PAGE_SIZE * 4 : page >= 4 ? REFERENCE_PAGE_SIZE * 5 : REFERENCE_PAGE_SIZE * 3
      return jsonResponse(pageBody([dto({ id: `p${page}` })], total, page))
    })

    await fetchAllReferenceItems('pose')

    expect(calls.map((call) => call.page).sort((a, b) => a - b)).toEqual([1, 2, 3, 4])
    expect(calls.some((call) => call.page === 5)).toBe(false)
  })

  it('总页数超过上限 200 时立即中止并给出明确错误', async () => {
    const { calls } = stubFetch(() =>
      jsonResponse(pageBody([dto({ id: 'a' })], REFERENCE_PAGE_SIZE * (REFERENCE_MAX_PAGES + 1))),
    )

    await expect(fetchAllReferenceItems('pose')).rejects.toThrow(
      `超过上限 ${REFERENCE_MAX_PAGES}`,
    )
    // 首屏算出超限后就不该继续翻页
    expect(calls).toHaveLength(1)
  })

  it('任一页失败整体 reject，错误文本带 library 与 page', async () => {
    stubFetch((url) => {
      const page = Number(url.searchParams.get('page'))
      if (page === 2) return jsonResponse({ detail: 'boom' }, 500)
      return jsonResponse(pageBody([dto({ id: `p${page}` })], REFERENCE_PAGE_SIZE * 2, page))
    })

    await expect(fetchAllReferenceItems('pose')).rejects.toThrow(
      '加载参考库 pose 第 2 页失败：HTTP 500',
    )
  })

  it('网络异常与非 JSON 响应都按页给出错误', async () => {
    stubFetch((url) => {
      const page = Number(url.searchParams.get('page'))
      if (page === 2) throw new TypeError('network down')
      return jsonResponse(pageBody([dto({ id: `p${page}` })], REFERENCE_PAGE_SIZE * 2, page))
    })
    await expect(fetchAllReferenceItems('costume')).rejects.toThrow(
      '加载参考库 costume 第 2 页失败：网络请求失败',
    )

    vi.unstubAllGlobals()
    stubFetch(() => ({
      ok: true,
      status: 200,
      json: async () => {
        throw new SyntaxError('Unexpected token <')
      },
      text: async () => '<!doctype html>',
    }))
    await expect(fetchAllReferenceItems('portrait')).rejects.toThrow(
      '加载参考库 portrait 第 1 页失败：响应不是 JSON',
    )
  })

  it('响应结构异常（items 不是数组）按页报错', async () => {
    stubFetch(() => jsonResponse({ items: null, total: 1, page: 1, page_size: 200 }))

    await expect(fetchAllReferenceItems('costume')).rejects.toThrow(
      '加载参考库 costume 第 1 页失败：响应结构异常',
    )
  })

  it('total=0 时只取首屏并返回空数组', async () => {
    const { calls } = stubFetch(() => jsonResponse(pageBody([], 0)))

    const items = await fetchAllReferenceItems('pose')

    expect(items).toEqual([])
    expect(calls).toHaveLength(1)
  })

  it('可选过滤 search/nsfw 透传为 query 参数', async () => {
    const { calls } = stubFetch(() =>
      jsonResponse(pageBody([dto({ id: 'a', library: 'costume-anime' })], 1)),
    )

    await fetchAllReferenceItems('costume-anime', { search: '猫娘 白裙', nsfw: false })

    const params = calls[0].url.searchParams
    expect(params.get('library')).toBe('costume-anime')
    expect(params.get('search')).toBe('猫娘 白裙')
    // false 是有效筛选值，必须保留（不能像空串一样被丢掉）
    expect(params.get('nsfw')).toBe('false')
  })
})

// ---------------------------------------------------------------------------
// DTO → 页面模型
// ---------------------------------------------------------------------------

describe('DTO 归一化与映射', () => {
  it('null/undefined 字符串归一为 ""，depthUrl/depthThumbUrl 保持 null', () => {
    const item = toPoseItem(
      dto({
        id: 'pose-1',
        group: null,
        number: undefined,
        facet: null,
        name: undefined,
        angle: null,
        thumb_url: null,
        image_url: null,
        search_text: undefined,
      }),
    )

    expect(item.体系).toBe('')
    expect(item.姿势编号).toBe('')
    expect(item.分类).toBe('')
    expect(item.姿势名称).toBe('')
    expect(item.角度).toBe('')
    expect(item.缩略图).toBe('')
    expect(item.原图).toBe('')
    expect(item.检索).toBe('')
    expect(item.depthUrl).toBeNull()
    expect(item.depthThumbUrl).toBeNull()
    expect(item.library).toBe('pose')
  })

  it('原图 = image_url || thumb_url；深度图字段透传', () => {
    const item = toPoseItem(
      dto({
        id: 'pose-2',
        group: '全身单人・标准系',
        number: 'P001',
        facet: '坐姿',
        name: '后仰坐',
        angle: '正面',
        thumb_url: '/api/a?kind=thumb',
        image_url: '/api/a?kind=image',
        depth_url: '/api/a?kind=depth',
        depth_thumb_url: null,
        nsfw: false,
        search_text: 'P001',
      }),
    )

    expect(item.原图).toBe('/api/a?kind=image')

    expect(item.depthUrl).toBe('/api/a?kind=depth')
    expect(item.depthThumbUrl).toBeNull()

    const fallback = toPoseItem(dto({ id: 'pose-3', thumb_url: '/api/t?kind=thumb', image_url: null }))
    expect(fallback.原图).toBe('/api/t?kind=thumb')
  })

  it('tags 缺失归一为 []，并剔除空串', () => {
    const missing = toCostumeItem(dto({ id: 'c1', library: 'costume', tags: undefined }))
    expect(missing.标签).toEqual([])

    const dirty = toCostumeItem(
      dto({ id: 'c2', library: 'costume', tags: ['女仆', '', '   ', '白色 '] }),
    )
    expect(dirty.标签).toEqual(['女仆', '白色 '])
  })

  it('costume-anime 一级分类收窄：仅「现实」保留，其余归「二次元」', () => {
    const normal = toCostumeItem(
      dto({
        id: 'anime-1',
        library: 'costume-anime',
        group: '二次元',
        facet: '女仆装',
        name: 'メイド',
        subtitle: 'メイド服',
        source_url: 'https://example.com/item/1',
        tags: [' maid '],
        nsfw: true,
      }),
    )
    expect(normal.分类).toBe('女仆装')
    expect(normal.一级分类).toBe('二次元')
    expect(normal.来源).toBe('CharaDB')
    expect(normal.日文名称).toBe('メイド服')
    expect(normal.来源地址).toBe('https://example.com/item/1')
    expect(normal.sourceUrl).toBe('https://example.com/item/1')
    expect(normal.library).toBe('costume-anime')
    expect(normal.remote).toBe(true)
    expect(normal.nsfw).toBe(true)

    expect(toCostumeItem(dto({ id: 'a2', library: 'costume-anime', group: '现实' })).一级分类).toBe(
      '现实',
    )
    // 上游枚举异常值一律收窄为「二次元」，避免污染一级分类筛选
    expect(toCostumeItem(dto({ id: 'a3', library: 'costume-anime', group: '未知异常值' })).一级分类).toBe(
      '二次元',
    )
    expect(toCostumeItem(dto({ id: 'a4', library: 'costume-anime', group: '' })).一级分类).toBe(
      '二次元',
    )
  })

  it('本地服装库：分类取 group、一级分类固定「现实」、无外链字段', () => {
    const item = toCostumeItem(
      dto({ id: 'c3', library: 'costume', group: '女装', facet: '连衣裙', nsfw: false }),
    )

    expect(item.分类).toBe('女装')
    expect(item.一级分类).toBe('现实')
    expect(item.library).toBe('costume')
    expect(item.remote).toBe(false)
    expect(item.来源).toBeUndefined()
    expect(item.sourceUrl).toBeUndefined()
  })

  it('本地第二来源：source_label 写入来源，不覆盖本地原图下载', () => {
    const item = toCostumeItem(
      dto({
        id: 'char-1',
        library: 'costume',
        group: '汉服形制',
        name: '百迭秋金',
        source_label: '角色创作库 @62656456',
        source_url: 'https://62656456.github.io/character-reference-library/',
        tags: ['汉服', '角色创作库'],
      }),
    )

    expect(item.一级分类).toBe('现实')
    expect(item.来源).toBe('角色创作库 @62656456')
    expect(item.sourceUrl).toBeUndefined()
    expect(item.library).toBe('costume')
  })

  it('人像：分区=group、发长=facet、发型名称=subtitle、标题=name', () => {
    const item = toPortraitItem(
      dto({
        id: 'portrait-1',
        library: 'portrait',
        group: '正脸参考',
        facet: '长发',
        subtitle: '黑长直',
        name: '人像 A',
        featured: true,
        hot: false,
      }),
    )

    expect(item.分区).toBe('正脸参考')
    expect(item.发长).toBe('长发')
    expect(item.发型名称).toBe('黑长直')
    expect(item.标题).toBe('人像 A')
    expect(item.精选).toBe(true)
    expect(item.热门).toBe(false)
    expect(item.宽).toBe(0)
    expect(item.高).toBe(0)
    expect(item.字节数).toBe(0)
    expect(item.library).toBe('portrait')
  })
})

// ---------------------------------------------------------------------------
// 18+ 判定
// ---------------------------------------------------------------------------

describe('18+ 判定只读 nsfw', () => {
  it('姿势条目与分组：分组内任一子项含 18+ 即为真', () => {
    const safe = toPoseItem(dto({ id: 'p1', group: '体系', nsfw: false }))
    const risky = toPoseItem(dto({ id: 'p2', group: '体系', nsfw: true }))
    const group: PoseGroup = {
      key: '体系|P001',
      system: '体系',
      number: 'P001',
      name: '',
      category: '',
      items: [safe, risky],
      angles: { 正面: safe },
      order: [safe, risky],
    }

    expect(isNsfwPoseItem(safe)).toBe(false)
    expect(isNsfwPoseItem(risky)).toBe(true)
    expect(isNsfwPoseItem(group)).toBe(true)
    expect(poseSystemHasNsfw([safe, risky], '体系')).toBe(true)
    expect(poseSystemHasNsfw([safe], '体系')).toBe(false)
  })

  it('服装条目与分类聚合', () => {
    const safe = toCostumeItem(dto({ id: 'c1', library: 'costume', group: '女装', nsfw: false }))
    const risky = toCostumeItem(dto({ id: 'c2', library: 'costume', group: '女装', nsfw: true }))

    expect(isNsfwCostumeItem(safe)).toBe(false)
    expect(isNsfwCostumeItem(risky)).toBe(true)
    expect(costumeCategoryHasNsfw([safe, risky], '女装')).toBe(true)
    expect(costumeCategoryHasNsfw([safe], '女装')).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// 图片地址
// ---------------------------------------------------------------------------

describe('referenceImageUrl', () => {
  it('后端已下发对应 URL 时原样使用', () => {
    const item = dto({
      id: 'pose-1',
      thumb_url: '/api/reference/items/pose/pose-1/image?kind=thumb',
      image_url: '/api/reference/items/pose/pose-1/image?kind=image',
    })

    expect(referenceImageUrl(item, 'thumb')).toBe(item.thumb_url)
    expect(referenceImageUrl(item, 'image')).toBe(item.image_url)
  })

  it('缩略图缺失但原图存在时按契约构造 thumb 端点', () => {
    const item = dto({
      id: 'costume-1',
      library: 'costume',
      thumb_url: null,
      image_url: '/api/reference/items/costume/costume-1/image?kind=image',
    })

    expect(referenceImageUrl(item, 'thumb')).toBe(
      '/api/reference/items/costume/costume-1/image?kind=thumb',
    )
  })

  it('原图缺失回退缩略图；完全无图返回 null（不产出空 src）', () => {
    const noImage = dto({
      id: 'anime-1',
      library: 'costume-anime',
      thumb_url: '/api/reference/items/costume-anime/anime-1/image?kind=thumb',
      image_url: null,
    })
    expect(referenceImageUrl(noImage, 'image')).toBe(noImage.thumb_url)

    const empty = dto({ id: 'anime-2', library: 'costume-anime' })
    expect(referenceImageUrl(empty, 'thumb')).toBeNull()
    expect(referenceImageUrl(empty, 'image')).toBeNull()
  })

  it('depth 仅 pose：非 pose 请求 depth/depth_thumb 一律 null', () => {
    const costume = dto({
      id: 'c1',
      library: 'costume',
      depth_url: '/api/should-not-be-used',
      depth_thumb_url: '/api/should-not-be-used',
    })
    const portrait = dto({ id: 'p1', library: 'portrait' })

    expect(referenceImageUrl(costume, 'depth')).toBeNull()
    expect(referenceImageUrl(costume, 'depth_thumb')).toBeNull()
    expect(referenceImageUrl(portrait, 'depth')).toBeNull()
    expect(referenceImageUrl(portrait, 'depth_thumb')).toBeNull()
  })

  it('pose 的 depth 按端点构造，depth_thumb 缺失保持 null（派生文件可能不存在）', () => {
    const item = dto({ id: 'pose-2', library: 'pose' })

    expect(referenceImageUrl(item, 'depth')).toBe(
      '/api/reference/items/pose/pose-2/image?kind=depth',
    )
    expect(referenceImageUrl(item, 'depth_thumb')).toBeNull()

    const withThumb = dto({
      id: 'pose-3',
      library: 'pose',
      depth_thumb_url: '/api/reference/items/pose/pose-3/image?kind=depth_thumb',
    })
    expect(referenceImageUrl(withThumb, 'depth_thumb')).toBe(withThumb.depth_thumb_url)
  })

  it('library/id 做 URL 编码，任何生成地址都不含 //', () => {
    const item = dto({
      id: 'role/a?b',
      library: 'costume-anime',
      // 无缩略图但有原图时，thumb 走端点构造，正好用来验证 id 编码
      image_url: '/api/reference/items/costume-anime/role%2Fa%3Fb/image?kind=image',
    })

    const url = referenceImageUrl(item, 'thumb')
    expect(url).toBe(
      '/api/reference/items/costume-anime/role%2Fa%3Fb/image?kind=thumb',
    )
    expect(url).not.toBeNull()
    expect(url as string).not.toContain('//')
    expect(url as string).toContain('/api/reference/items/')
  })

  it('空 id/library 返回 null，不拼出 //image', () => {
    expect(referenceImageUrl(dto({ id: '', library: 'pose' }), 'thumb')).toBeNull()
    expect(referenceImageUrl(dto({ id: 'x', library: '' }), 'thumb')).toBeNull()
  })

  it('referenceImageEndpoint 从常量前缀起拼，不产生协议相对地址', () => {
    for (const kind of ['thumb', 'image', 'depth', 'depth_thumb'] as const) {
      const url = referenceImageEndpoint('pose', 'a b', kind)
      expect(url.startsWith('/api/reference/items/pose/a%20b/image?kind=')).toBe(true)
      expect(url).not.toContain('//')
    }
  })
})