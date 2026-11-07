/**
 * 参考图库 composable 单测。
 *
 * 覆盖：分组键（体系|姿势编号，编号缺失回退 id）、体系排序、角度顺序、
 * 服装双库并行与「现实在前、二次元在后」的合并顺序，
 * 以及 items/loading/error/retry 状态机。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { PoseItem, ReferenceItemDto } from '@/api/reference'

import {
  ANGLES,
  PREFERRED_POSE_LINE_ORDER,
  buildPoseGroups,
  resetReferenceLibraryState,
  useReferenceCostumes,
  useReferencePortraits,
  useReferencePoses,
} from './useReferenceLibrary'

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
    nsfw: false,
    ...overrides,
  }
}

function dto(overrides: Partial<ReferenceItemDto> & { id: string }): ReferenceItemDto {
  return {
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
  }
}

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

function listBody(items: ReferenceItemDto[], total = items.length): unknown {
  return { items, total, page: 1, page_size: 200 }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

beforeEach(() => {
  resetReferenceLibraryState()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// ---------------------------------------------------------------------------
// 姿势分组
// ---------------------------------------------------------------------------

describe('buildPoseGroups', () => {
  it('分组键为「体系|姿势编号」，编号缺失回退 id', () => {
    const items = [
      pose({ id: 'p1', 体系: '全身单人・标准系', 姿势编号: 'P002', 角度: '正面' }),
      pose({ id: 'p2', 体系: '全身单人・标准系', 姿势编号: 'P002', 角度: '俯视' }),
      pose({ id: 'no-number', 体系: '未知体系', 姿势编号: '', 角度: '正面' }),
    ]

    const { groups } = buildPoseGroups(items)

    expect(groups).toHaveLength(2)
    const standard = groups.find((group) => group.system === '全身单人・标准系')
    expect(standard?.key).toBe('全身单人・标准系|P002')
    // 同编号的多个角度归入同一组，不按角度拆组
    expect(standard?.items.map((item) => item.id)).toEqual(['p1', 'p2'])

    const unknown = groups.find((group) => group.system === '未知体系')
    // 空编号不能把所有条目挤成一组，回退 id
    expect(unknown?.key).toBe('未知体系|no-number')
  })

  it('体系按全身单人・标准系 / 上半身单人 / 全身单人・性感系 / 双人缠绵 排序，其余排后', () => {
    const items = [
      pose({ id: 'd', 体系: '双人缠绵', 姿势编号: 'D001' }),
      pose({ id: 'u', 体系: '自定义体系', 姿势编号: 'X001' }),
      pose({ id: 's2', 体系: '全身单人・性感系', 姿势编号: 'S001' }),
      pose({ id: 's1', 体系: '全身单人・标准系', 姿势编号: 'P001' }),
      pose({ id: 'h', 体系: '上半身单人', 姿势编号: 'H001' }),
    ]

    const { lines, groups } = buildPoseGroups(items)

    expect(lines).toEqual([
      '全身单人・标准系',
      '上半身单人',
      '全身单人・性感系',
      '双人缠绵',
      '自定义体系',
    ])
    expect(groups.map((group) => group.system)).toEqual(lines)
  })

  it('组内角度顺序固定为 正面/俯视/仰视/侧面/斜侧，未列出的角度追加在后', () => {
    const order = ['斜侧', '侧面', '仰视', '俯视', '正面', '背面']
    const items = order.map((angle, index) =>
      pose({ id: `p${index}`, 体系: '全身单人・标准系', 姿势编号: 'P001', 角度: angle }),
    )

    const { groups } = buildPoseGroups(items)
    const angles = groups[0].order.map((item) => item.角度)

    expect(angles.slice(0, ANGLES.length)).toEqual([...ANGLES])
    expect(angles).toEqual(['正面', '俯视', '仰视', '侧面', '斜侧', '背面'])
  })

  it('同组同角度只保留首个条目，其余仍进入组内 items', () => {
    const first = pose({ id: 'a', 体系: '体系', 姿势编号: 'N1', 角度: '正面' })
    const duplicate = pose({ id: 'b', 体系: '体系', 姿势编号: 'N1', 角度: '正面' })

    const { groups } = buildPoseGroups([first, duplicate])

    expect(groups[0].items).toHaveLength(2)
    expect(groups[0].angles['正面'].id).toBe('a')
    expect(groups[0].order.map((item) => item.id)).toEqual(['a', 'b'])
  })
})

// ---------------------------------------------------------------------------
// 服装双库
// ---------------------------------------------------------------------------

describe('useReferenceCostumes', () => {
  it('两库并行拉取，合并顺序为现实在前、二次元在后', async () => {
    let active = 0
    let maxActive = 0
    const started: string[] = []

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(String(input), 'http://localhost')
        const library = url.searchParams.get('library') ?? ''
        started.push(library)
        active += 1
        maxActive = Math.max(maxActive, active)
        // 两个库都必须在对方完成前发起，串行实现会让 maxActive 恒为 1
        await delay(10)
        active -= 1
        const id = library === 'costume' ? 'real-1' : 'anime-1'
        return jsonResponse(
          listBody([
            dto({
              id,
              library,
              name: id,
              group: library === 'costume' ? '女装' : '二次元',
              source_url: library === 'costume-anime' ? 'https://example.com/a' : null,
            }),
          ]),
        )
      }),
    )

    const state = useReferenceCostumes()
    await state.load()

    expect(maxActive).toBe(2)
    expect(started).toEqual(['costume', 'costume-anime'])
    expect(state.items.value.map((item) => item.library)).toEqual(['costume', 'costume-anime'])
    expect(state.items.value.map((item) => item.id)).toEqual(['real-1', 'anime-1'])
  })

  it('任一库失败整体报错（不留半成品）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(String(input), 'http://localhost')
        if (url.searchParams.get('library') === 'costume-anime') {
          return jsonResponse({ detail: 'boom' }, 502)
        }
        return jsonResponse(listBody([dto({ id: 'real-1', library: 'costume' })]))
      }),
    )

    const state = useReferenceCostumes()
    await state.load()

    expect(state.error.value).toContain('加载参考库 costume-anime 第 1 页失败：HTTP 502')
    expect(state.items.value).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// 状态机
// ---------------------------------------------------------------------------

describe('composable 状态', () => {
  it('加载中 loading=true，成功后填充 items 并清空 error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        await delay(5)
        return jsonResponse(
          listBody([
            dto({ id: 'p1', library: 'pose', group: '全身单人・标准系', number: 'P001' }),
          ]),
        )
      }),
    )

    const state = useReferencePoses()
    expect(state.items.value).toEqual([])
    expect(state.loading.value).toBe(false)
    expect(state.error.value).toBeNull()

    const pending = state.load()
    expect(state.loading.value).toBe(true)
    await pending

    expect(state.loading.value).toBe(false)
    expect(state.items.value.map((item) => item.id)).toEqual(['p1'])
    expect(state.error.value).toBeNull()
    // 分组与体系列表由 items 派生
    expect(state.groups.value[0].key).toBe('全身单人・标准系|P001')
    expect(state.lines.value).toContain('全身单人・标准系')
  })

  it('失败后 error 可读，retry 成功后清空 error 并填充数据', async () => {
    let attempt = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        attempt += 1
        if (attempt === 1) return jsonResponse({ detail: 'boom' }, 500)
        return jsonResponse(
          listBody([dto({ id: 'portrait-1', library: 'portrait', group: '正脸参考' })]),
        )
      }),
    )

    const state = useReferencePortraits()
    await state.load()
    expect(state.error.value).toContain('加载参考库 portrait 第 1 页失败：HTTP 500')
    expect(state.items.value).toEqual([])

    await state.retry()
    expect(state.error.value).toBeNull()
    expect(state.items.value.map((item) => item.id)).toEqual(['portrait-1'])
  })

  it('多个页签共享同一份库状态，已加载后不再重复请求', async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(listBody([dto({ id: 'p1' })])),
    )
    vi.stubGlobal('fetch', fetchMock)

    const first = useReferencePoses()
    const second = useReferencePoses()
    expect(first.items).toBe(second.items)

    await first.load()
    await second.load()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(second.items.value.map((item) => item.id)).toEqual(['p1'])
  })

  it('并发调用 load 复用同一批请求，不重复打后端', async () => {
    const fetchMock = vi.fn(async () => {
      await delay(5)
      return jsonResponse(listBody([dto({ id: 'p1' })]))
    })
    vi.stubGlobal('fetch', fetchMock)

    const state = useReferencePoses()
    const first = state.load()
    const second = state.load()
    await Promise.all([first, second])

    expect(fetchMock).toHaveBeenCalledTimes(1)
    // PREFERRED_POSE_LINE_ORDER 常量参与排序，避免误删
    expect(PREFERRED_POSE_LINE_ORDER[0]).toBe('全身单人・标准系')
  })
})