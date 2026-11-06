/**
 * 姿势库视图层纯逻辑单测。
 *
 * 覆盖 §7 姿势相关 8 行的判定核心：
 * 分组键（体系|姿势编号，编号缺失回退 id）、角度顺序、体系药丸计数与 18+ 后缀、
 * 筛选语义（体系 / 分类 / 角度 / 搜索）、三库共用分页切片（每页 20/60/100/200）、
 * 灯箱角度与跨组翻页、图片地址（depth 仅 pose、无二次拼接）。
 */

import { describe, expect, it } from 'vitest'

import type { PoseItem } from '../../../api/reference'
import { buildPoseGroups } from '../../../composables/useReferenceLibrary'

import {
  ANGLES,
  DEFAULT_PAGE_SIZE,
  PAGE_SIZES,
  activeGroupItem,
  clampPage,
  filterPoseGroups,
  filterPoseSingles,
  firstNsfwLine,
  groupAngleItem,
  groupIndexOfItem,
  hiddenNsfwCount,
  matchesPoseFilters,
  normalizePageSize,
  pageCount,
  pageSlice,
  poseCategoryOptions,
  posePreviewUrl,
  poseSystemSummaries,
  poseThumbnailUrl,
  resolveActiveLine,
  stepGroupItem,
} from './poseView'
import type { PoseFilters } from './poseView'

const EMPTY_FILTERS: PoseFilters = { line: '', category: 'all', angle: '', query: '' }

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

/** 一组 5 角度的姿势，用于分组 / 角度顺序断言。 */
function fifthAngleGroup(): PoseItem[] {
  return ['斜侧', '侧面', '仰视', '俯视', '正面'].map((angle) =>
    pose({
      id: `P001_${angle}`,
      体系: '全身单人・标准系',
      姿势编号: 'P001',
      分类: '坐姿',
      姿势名称: '后仰坐',
      角度: angle,
      缩略图: `/api/reference/items/pose/P001_${angle}/image?kind=thumb`,
      depthThumbUrl: `/api/reference/items/pose/P001_${angle}/image?kind=depth_thumb`,
      depthUrl: `/api/reference/items/pose/P001_${angle}/image?kind=depth`,
    }),
  )
}

describe('角度顺序与分组键', () => {
  it('角度顺序固定为 正面/俯视/仰视/侧面/斜侧', () => {
    expect([...ANGLES]).toEqual(['正面', '俯视', '仰视', '侧面', '斜侧'])
  })

  it('组内角度按 ANGLES 排序，而不是按原始返回顺序', () => {
    const built = buildPoseGroups(fifthAngleGroup())
    expect(built.groups).toHaveLength(1)
    expect(built.groups[0].order.map((item) => item.角度)).toEqual([...ANGLES])
  })

  it('分组键为「体系|姿势编号」，编号缺失回退 id', () => {
    const built = buildPoseGroups([
      pose({ id: 'a', 体系: '上半身单人', 姿势编号: 'U001' }),
      pose({ id: 'b', 体系: '上半身单人', 姿势编号: 'U001' }),
      pose({ id: 'c', 体系: '上半身单人', 姿势编号: '' }),
    ])
    // 组顺序按姿势编号 localeCompare（与 buildPoseGroups 一致）：
    // 'c' 排在 'U001' 前，编号缺失的条目不会与其他编号混组
    expect(built.groups.map((group) => group.key)).toEqual([
      '上半身单人|c',
      '上半身单人|U001',
    ])
  })
})

describe('筛选语义', () => {
  const items = [
    pose({ id: 'p1', 体系: 'A', 姿势编号: 'P001', 分类: '坐姿', 姿势名称: '后仰坐', 角度: '正面' }),
    pose({ id: 'p2', 体系: 'A', 姿势编号: 'P001', 分类: '坐姿', 姿势名称: '后仰坐', 角度: '侧面' }),
    pose({ id: 'p3', 体系: 'B', 姿势编号: 'P002', 分类: '站姿', 姿势名称: '侧身站', 角度: '正面' }),
  ]
  const built = buildPoseGroups(items)

  it('体系 / 分类按组过滤', () => {
    expect(filterPoseGroups(built.groups, { ...EMPTY_FILTERS, line: 'B' })).toHaveLength(1)
    expect(filterPoseGroups(built.groups, { ...EMPTY_FILTERS, category: '坐姿' })).toHaveLength(1)
    expect(filterPoseGroups(built.groups, { ...EMPTY_FILTERS, category: 'all' })).toHaveLength(2)
  })

  it('角度命中组内任一角度即保留整组（角度条仍展示全部角度）', () => {
    const result = filterPoseGroups(built.groups, { ...EMPTY_FILTERS, angle: '侧面' })
    expect(result.map((group) => group.key)).toEqual(['A|P001'])
    expect(result[0].order).toHaveLength(2)
  })

  it('搜索匹配名称 / id / 分类 / 编号 / 体系，且大小写无关、去首尾空白', () => {
    expect(filterPoseGroups(built.groups, { ...EMPTY_FILTERS, query: '  p001 ' })).toHaveLength(1)
    expect(filterPoseGroups(built.groups, { ...EMPTY_FILTERS, query: '侧身' })).toHaveLength(1)
    expect(filterPoseGroups(built.groups, { ...EMPTY_FILTERS, query: 'P002' })).toHaveLength(1)
    expect(filterPoseGroups(built.groups, { ...EMPTY_FILTERS, query: '不存在的词' })).toHaveLength(0)
  })

  it('单张视图逐条过滤，角度条件作用于条目本身', () => {
    expect(filterPoseSingles(items, { ...EMPTY_FILTERS, angle: '正面' })).toHaveLength(2)
    expect(filterPoseSingles(items, { ...EMPTY_FILTERS, line: 'A', query: 'p2' })).toHaveLength(1)
    expect(matchesPoseFilters(items[2], EMPTY_FILTERS)).toBe(true)
  })

  it('动作分类下拉按当前体系收窄并按中文排序', () => {
    // localeCompare('zh-CN') 下「站」排在「坐」前（与 React 一致）
    expect(poseCategoryOptions(items, '')).toEqual(['站姿', '坐姿'])
    expect(poseCategoryOptions(items, 'A')).toEqual(['坐姿'])
    expect(poseCategoryOptions(items, 'B')).toEqual(['站姿'])
  })
})

describe('体系药丸与 18+ 后缀', () => {
  const items = [
    pose({ id: 'safe', 体系: '上半身单人', 姿势编号: 'U1' }),
    pose({ id: 'risky1', 体系: '全身单人・性感系', 姿势编号: 'S1', nsfw: true }),
    pose({ id: 'risky2', 体系: '全身单人・性感系', 姿势编号: 'S2', nsfw: true }),
  ]
  const lines = buildPoseGroups(items).lines

  it('数量按全部已加载条目统计，与筛选无关', () => {
    const summaries = poseSystemSummaries(lines, items, true)
    expect(summaries.find((s) => s.line === '全身单人・性感系')).toMatchObject({
      count: 2,
      nsfw: true,
      visible: false,
    })
    expect(summaries.find((s) => s.line === '上半身单人')).toMatchObject({
      count: 1,
      nsfw: false,
      visible: true,
    })
  })

  it('安全模式隐藏含 18+ 的体系；完整模式全部可见', () => {
    expect(poseSystemSummaries(lines, items, true).filter((s) => s.visible)).toHaveLength(1)
    expect(poseSystemSummaries(lines, items, false).filter((s) => s.visible)).toHaveLength(2)
  })

  it('切回安全模式时，选中含 18+ 的体系自动落回「全部」', () => {
    expect(resolveActiveLine('全身单人・性感系', true, items)).toBe('')
    expect(resolveActiveLine('上半身单人', true, items)).toBe('上半身单人')
    expect(resolveActiveLine('全身单人・性感系', false, items)).toBe('全身单人・性感系')
  })

  it('解锁药丸数量与首个 18+ 体系', () => {
    expect(hiddenNsfwCount(items)).toBe(2)
    expect(firstNsfwLine(lines, items)).toBe('全身单人・性感系')
    expect(firstNsfwLine(buildPoseGroups([items[0]]).lines, [items[0]])).toBe('')
  })
})

describe('分页切片（三库共用）', () => {
  const items = Array.from({ length: 25 }, (_, index) => `i${index}`)

  it('每页条数只允许 20 / 60 / 100 / 200，默认 60，脏值回落 60', () => {
    expect([...PAGE_SIZES]).toEqual([20, 60, 100, 200])
    expect(DEFAULT_PAGE_SIZE).toBe(60)
    expect(normalizePageSize(20)).toBe(20)
    expect(normalizePageSize(200)).toBe(200)
    expect(normalizePageSize('100')).toBe(100)
    // 非法值（不在下拉选项内 / 0 / undefined / NaN）一律回落 60
    expect(normalizePageSize(50)).toBe(60)
    expect(normalizePageSize(0)).toBe(60)
    expect(normalizePageSize(undefined)).toBe(60)
    expect(normalizePageSize(Number.NaN)).toBe(60)
  })

  it('第 1 页从第 1 条开始，按 pageSize 切片', () => {
    expect(pageSlice(items, 1, 20)).toEqual(items.slice(0, 20))
    expect(pageSlice(items, 1, 60)).toEqual(items)
  })

  it('最后一页不满时只返回剩余条目，越界页返回空数组', () => {
    expect(pageSlice(items, 2, 20)).toEqual(['i20', 'i21', 'i22', 'i23', 'i24'])
    expect(pageSlice(items, 3, 20)).toEqual([])
    expect(pageSlice([], 1, 60)).toEqual([])
  })

  it('页码非法回第 1 页，pageSize 非法回落 60', () => {
    expect(pageSlice(items, 0, 20)).toEqual(items.slice(0, 20))
    expect(pageSlice(items, -2, 20)).toEqual(items.slice(0, 20))
    expect(pageSlice(items, Number.NaN, 20)).toEqual(items.slice(0, 20))
    // pageSize 50 / 0 → 60，25 条全部落在第 1 页
    expect(pageSlice(items, 1, 50)).toEqual(items)
    expect(pageSlice(items, 1, 0)).toEqual(items)
  })

  it('总页数向上取整，空列表也至少 1 页', () => {
    expect(pageCount(0, 60)).toBe(1)
    expect(pageCount(1, 60)).toBe(1)
    expect(pageCount(60, 60)).toBe(1)
    expect(pageCount(61, 60)).toBe(2)
    expect(pageCount(287, 60)).toBe(5)
    expect(pageCount(10, 0)).toBe(1)
    expect(pageCount(Number.NaN, 60)).toBe(1)
  })

  it('页码越界时夹到最后一页，非法页码夹到第 1 页', () => {
    expect(clampPage(1, 100, 60)).toBe(1)
    expect(clampPage(2, 100, 60)).toBe(2)
    expect(clampPage(9, 100, 60)).toBe(2)
    expect(clampPage(0, 100, 60)).toBe(1)
    expect(clampPage(-3, 100, 60)).toBe(1)
    expect(clampPage(Number.NaN, 61, 60)).toBe(1)
    expect(clampPage(5, 0, 60)).toBe(1)
    expect(clampPage(9, 100, 20)).toBe(5)
  })
})

describe('卡片角度与灯箱翻页', () => {
  const built = buildPoseGroups(fifthAngleGroup())
  const group = built.groups[0]

  it('当前角度优先级：悬停 > 筛选视角 > 组内首张', () => {
    expect(activeGroupItem(group, {}, '')?.角度).toBe('正面')
    expect(activeGroupItem(group, {}, '侧面')?.角度).toBe('侧面')
    expect(activeGroupItem(group, { [group.key]: '斜侧' }, '侧面')?.角度).toBe('斜侧')
  })

  it('角度条按角度取条目，没有的角度返回 undefined', () => {
    expect(groupAngleItem(group, '俯视')?.角度).toBe('俯视')
    const onlyFront = buildPoseGroups([fifthAngleGroup()[0]]).groups[0]
    expect(groupAngleItem(onlyFront, '侧面')).toBeUndefined()
  })

  it('组内翻页循环', () => {
    expect(stepGroupItem(group, group.order[0].id, -1)?.角度).toBe('斜侧')
    expect(stepGroupItem(group, group.order[4].id, 1)?.角度).toBe('正面')
    // 未知 id 视为「第一张」，向后翻一格
    expect(stepGroupItem(group, 'unknown-id', 1)?.角度).toBe('俯视')
  })

  it('单张点开时定位所属分组，找不到回落 0', () => {
    const other = buildPoseGroups([
      pose({ id: 'x', 体系: 'B', 姿势编号: 'X1' }),
      pose({ id: 'y', 体系: 'A', 姿势编号: 'A1' }),
    ]).groups
    expect(groupIndexOfItem(other, 'y')).toBe(1)
    expect(groupIndexOfItem(other, 'not-found')).toBe(0)
  })
})

describe('图片地址', () => {
  const item = pose({
    id: 'p1',
    缩略图: '/api/reference/items/pose/p1/image?kind=thumb',
    原图: '/api/reference/items/pose/p1/image?kind=image',
    depthThumbUrl: '/api/reference/items/pose/p1/image?kind=depth_thumb',
    depthUrl: '/api/reference/items/pose/p1/image?kind=depth',
  })

  it('白模用 thumb / image，深度图用 depth_thumb / depth', () => {
    expect(poseThumbnailUrl(item, false)).toBe('/api/reference/items/pose/p1/image?kind=thumb')
    expect(poseThumbnailUrl(item, true)).toBe('/api/reference/items/pose/p1/image?kind=depth_thumb')
    expect(posePreviewUrl(item, false)).toBe('/api/reference/items/pose/p1/image?kind=image')
    expect(posePreviewUrl(item, true)).toBe('/api/reference/items/pose/p1/image?kind=depth')
  })

  it('深度缩略图缺失时回退 depth 端点（与 React 一致）', () => {
    const withoutThumb = pose({
      id: 'p2',
      缩略图: '/api/reference/items/pose/p2/image?kind=thumb',
      depthUrl: '/api/reference/items/pose/p2/image?kind=depth',
    })
    expect(poseThumbnailUrl(withoutThumb, true)).toBe('/api/reference/items/pose/p2/image?kind=depth')
  })

  it('无图返回 null，不产出空串或二次拼接的 //api', () => {
    const empty = pose({ id: 'p3' })
    expect(poseThumbnailUrl(empty, false)).toBeNull()
    expect(posePreviewUrl(empty, false)).toBeNull()
    for (const url of [poseThumbnailUrl(item, true), posePreviewUrl(item, true)]) {
      expect(url).not.toContain('//api')
    }
  })
})