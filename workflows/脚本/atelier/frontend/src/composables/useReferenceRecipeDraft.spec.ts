/**
 * 三槽位配方选择状态单测（多选版）。
 *
 * 覆盖：多选追加 / 去重 / 移除、非空槽数 n/3 与条目总数、已选判定
 * （姿势区分白模与深度图）、切换模式、清空；
 * 以及 2026-11-05 新增的持久化（persist / hydrate）：三槽落盘、
 * 按 id + library 匹配恢复、匹配不到的条目被丢弃。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { CostumeItem, PoseItem, PortraitItem } from '../api/reference'
import { createEmptyRecipeTextFragments } from './recipeTextFragments'
import {
  flushReferenceStudioSettings,
  readReferenceStudioSettings,
  REFERENCE_STUDIO_STORAGE_KEY,
} from './useReferenceStudioSettings'

/**
 * happy-dom / Node 25 的全局 localStorage 在当前运行方式下不是完整 Storage，
 * 按仓库既有 spec 的做法补一份最小实现（需要 clear / length）。
 */
const localValues = new Map<string, string>()
vi.stubGlobal('localStorage', {
  get length() {
    return localValues.size
  },
  getItem: (key: string) => localValues.get(key) ?? null,
  setItem: (key: string, value: string) => void localValues.set(key, value),
  removeItem: (key: string) => void localValues.delete(key),
  clear: () => localValues.clear(),
})

const sessionValues = new Map<string, string>()
vi.stubGlobal('sessionStorage', {
  get length() {
    return sessionValues.size
  },
  getItem: (key: string) => sessionValues.get(key) ?? null,
  setItem: (key: string, value: string) => void sessionValues.set(key, value),
  removeItem: (key: string) => void sessionValues.delete(key),
  clear: () => sessionValues.clear(),
})

import {
  RECIPE_SLOT_TOTAL,
  uploadPathOf,
  useReferenceRecipeDraft,
} from './useReferenceRecipeDraft'

function pose(id: string, name = '姿势', withDepth = true): PoseItem {
  return {
    id,
    体系: '体系',
    姿势编号: id,
    分类: '分类',
    姿势名称: name,
    角度: '正面',
    缩略图: '',
    原图: '',
    检索: '',
    nsfw: false,
    hasDepth: withDepth,
    depthThumbUrl: withDepth
      ? `/api/reference/items/pose/${id}/image?kind=depth_thumb`
      : null,
    depthUrl: withDepth ? `/api/reference/items/pose/${id}/image?kind=depth` : null,
  }
}

function costume(id: string): CostumeItem {
  return {
    id,
    分类: '分类',
    服装名称: '服装',
    标签: [],
    关键词: '',
    缩略图: '',
    预览图: '',
    原图: '',
    检索: '',
  }
}

function portrait(id: string): PortraitItem {
  return {
    id,
    分区: '分区',
    发长: '',
    发型名称: '发型',
    标题: '人像',
    宽: 0,
    高: 0,
    字节数: 0,
    精选: false,
    热门: false,
    缩略图: '',
    原图: '',
    检索: '',
  }
}

const draft = useReferenceRecipeDraft()

beforeEach(() => {
  draft.clearDraft()
  // 自动持久化会调度防抖写；立即冲刷并清空，避免跨用例污染。
  flushReferenceStudioSettings()
  localStorage.clear()
  sessionStorage.clear()
})

describe('多选计数', () => {
  it('初始为空：n/3 为 0/3，条目总数 0', () => {
    expect(draft.count.value).toBe(0)
    expect(draft.countLabel.value).toBe('0/3')
    expect(draft.totalSelected.value).toBe(0)
    expect(draft.portraitCount.value).toBe(0)
    expect(draft.isComplete.value).toBe(false)
    expect(RECIPE_SLOT_TOTAL).toBe(3)
  })

  it('同一槽位多张：非空槽数不增加，条目总数增加', () => {
    draft.togglePortrait(portrait('pt1'))
    draft.togglePortrait(portrait('pt2'))
    draft.togglePortrait(portrait('pt3'))

    expect(draft.portraitCount.value).toBe(3)
    expect(draft.totalSelected.value).toBe(3)
    expect(draft.count.value).toBe(1)
    expect(draft.countLabel.value).toBe('1/3')
    expect(draft.isComplete.value).toBe(false)
  })

  it('三个槽位各加一条 → 3/3 且 isComplete', () => {
    draft.setPortrait(portrait('pt1'))
    draft.setCostume(costume('c1'))
    draft.setPose(pose('p1'))

    expect(draft.count.value).toBe(3)
    expect(draft.countLabel.value).toBe('3/3')
    expect(draft.totalSelected.value).toBe(3)
    expect(draft.isComplete.value).toBe(true)
  })

  it('同一 id 重复加入不会产生重复条目', () => {
    draft.addPortrait(portrait('pt1'))
    draft.addPortrait(portrait('pt1'))
    expect(draft.portraitCount.value).toBe(1)
  })
})

describe('加入 / 移除 / 去重', () => {
  it('人像槽：多选 toggle，点已选只移除该条，其余保留', () => {
    expect(draft.togglePortrait(portrait('pt1'))).toBe(true)
    expect(draft.togglePortrait(portrait('pt2'))).toBe(true)
    expect(draft.isPortraitSelected('pt1')).toBe(true)
    expect(draft.isPortraitSelected('pt2')).toBe(true)

    expect(draft.togglePortrait(portrait('pt1'))).toBe(false)
    expect(draft.isPortraitSelected('pt1')).toBe(false)
    expect(draft.isPortraitSelected('pt2')).toBe(true)
    expect(draft.portraitCount.value).toBe(1)
  })

  it('人像槽：removePortrait(id) 只删一条，不传 id 清空', () => {
    draft.togglePortrait(portrait('pt1'))
    draft.togglePortrait(portrait('pt2'))
    draft.removePortrait('pt1')
    expect(draft.portrait.value.map((item) => item.id)).toEqual(['pt2'])

    draft.removePortrait()
    expect(draft.portrait.value).toEqual([])
    expect(draft.isPortraitSelected()).toBe(false)
  })

  it('服装槽同理：多选 toggle 与清空', () => {
    draft.toggleCostume(costume('c1'))
    draft.toggleCostume(costume('c2'))
    expect(draft.costumeCount.value).toBe(2)
    expect(draft.isCostumeSelected('c1')).toBe(true)

    draft.removeCostume('c1')
    expect(draft.costume.value.map((item) => item.id)).toEqual(['c2'])

    draft.removeCostume()
    expect(draft.costume.value).toEqual([])
    expect(draft.isCostumeSelected()).toBe(false)
  })

  it('setX(null) 清空整个槽位（随机捏人 / 旧语义）', () => {
    draft.toggleCostume(costume('c1'))
    draft.toggleCostume(costume('c2'))
    draft.setCostume(null)
    expect(draft.costume.value).toEqual([])
  })

  it('姿势槽：同 id 同模式点击移除，同 id 换模式更新该条目', () => {
    const item = pose('p1')
    expect(draft.togglePose(item, false)).toBe(true)
    expect(draft.pose.value[0]).toMatchObject({ useDepth: false })

    expect(draft.isPoseSelected('p1')).toBe(true)
    expect(draft.isPoseSelected('p1', false)).toBe(true)
    expect(draft.isPoseSelected('p1', true)).toBe(false)

    // 切到深度图再点：更新模式而不是新增第二条
    expect(draft.togglePose(item, true)).toBe(true)
    expect(draft.pose.value).toHaveLength(1)
    expect(draft.pose.value[0]).toMatchObject({ useDepth: true })

    // 同模式再点才移除
    expect(draft.togglePose(item, true)).toBe(false)
    expect(draft.pose.value).toEqual([])
  })

  it('姿势槽：多选不同 id；setPoseMode 统一改模式', () => {
    draft.togglePose(pose('p1'), false)
    draft.togglePose(pose('p2'), false)
    expect(draft.poseCount.value).toBe(2)

    draft.setPoseMode(true)
    expect(draft.pose.value.every((entry) => entry.useDepth)).toBe(true)
    expect(draft.isPoseSelected('p1', true)).toBe(true)
  })

  it('无深度条目即使切到深度模式也强制白模', () => {
    const item = pose('p9', '无深度姿势', false)

    expect(draft.togglePose(item, true)).toBe(true)
    expect(draft.pose.value[0]).toMatchObject({ useDepth: false })

    draft.setPoseMode(true)
    expect(draft.pose.value.every((entry) => entry.useDepth === false)).toBe(true)

    // 同 id 同（归一后的）模式再点才移除
    expect(draft.togglePose(item, true)).toBe(false)
    expect(draft.pose.value).toEqual([])
  })

  it('setPose(null) / removePose 清空', () => {
    draft.setPose(pose('p1'), true)
    draft.setPose(null)
    expect(draft.pose.value).toEqual([])

    draft.setPose(pose('p2'))
    draft.removePose()
    expect(draft.pose.value).toEqual([])
  })
})

describe('清空与持久化（2026-11-05 取代 M3 不持久化）', () => {
  /** 直接写一份合法的存储快照（用于构造「库中已删除条目」等场景）。 */
  function storeSnapshot(overrides: Record<string, unknown>): void {
    localStorage.setItem(
      REFERENCE_STUDIO_STORAGE_KEY,
      JSON.stringify({
        portrait: [],
        costume: [],
        pose: [],
        style: 'realistic',
        workflow: '',
        baseSeed: 100000,
        qualities: [],
        ratios: [],
        sizesConfigured: false,
        ...overrides,
      }),
    )
  }

  it('clearDraft 三槽同时清空', () => {
    draft.setPortrait(portrait('pt1'))
    draft.setCostume(costume('c1'))
    draft.setPose(pose('p1'), true)
    expect(draft.count.value).toBe(3)

    draft.clearDraft()
    expect(draft.count.value).toBe(0)
    expect(draft.totalSelected.value).toBe(0)
    expect(draft.portrait.value).toEqual([])
    expect(draft.costume.value).toEqual([])
    expect(draft.pose.value).toEqual([])
  })

  it('三槽变化自动写入最小记录（id + library + name + thumbnail）', () => {
    draft.setPortrait(portrait('pt1'))
    draft.addCostume({ ...costume('c1'), library: 'costume-anime' })
    draft.setPose(pose('p1'), true)

    flushReferenceStudioSettings()
    const stored = readReferenceStudioSettings()

    expect(stored?.portrait).toEqual([
      { id: 'pt1', library: 'portrait', name: '发型', thumbnail: '' },
    ])
    expect(stored?.costume).toEqual([
      { id: 'c1', library: 'costume-anime', name: '服装', thumbnail: '' },
    ])
    expect(stored?.pose).toEqual([
      { id: 'p1', library: 'pose', name: '姿势', thumbnail: '', useDepth: true },
    ])
  })

  it('hydrate：按 id 匹配库数据恢复三槽，顺序与姿势模式保持', () => {
    draft.addPortrait(portrait('pt2'))
    draft.addPortrait(portrait('pt1'))
    draft.setCostume(costume('c1'))
    draft.setPose(pose('p1'), true)
    flushReferenceStudioSettings()
    draft.clearDraft()

    const restored = draft.hydrate({
      portrait: [portrait('pt1'), portrait('pt2'), portrait('pt3')],
      costume: [costume('c1'), costume('c2')],
      pose: [pose('p1'), pose('p2')],
    })

    expect(restored).toBe(true)
    expect(draft.portrait.value.map((item) => item.id)).toEqual(['pt2', 'pt1'])
    expect(draft.costume.value.map((item) => item.id)).toEqual(['c1'])
    expect(draft.pose.value.map((entry) => entry.item.id)).toEqual(['p1'])
    expect(draft.pose.value[0].useDepth).toBe(true)
  })

  it('hydrate：匹配不到的 id 直接丢弃，不凭空造卡片', () => {
    storeSnapshot({
      portrait: [
        { id: 'pt1', library: 'portrait', name: '发型', thumbnail: '' },
        { id: 'deleted', library: 'portrait', name: '已删除', thumbnail: '' },
      ],
      costume: [{ id: 'gone', library: 'costume', name: '已删除', thumbnail: '' }],
    })

    const restored = draft.hydrate({
      portrait: [portrait('pt1')],
      costume: [],
      pose: [],
    })

    expect(restored).toBe(true)
    expect(draft.portrait.value.map((item) => item.id)).toEqual(['pt1'])
    expect(draft.costume.value).toEqual([])
    expect(draft.pose.value).toEqual([])
  })

  it('hydrate：library 不匹配的条目丢弃（同 id 不同库不互相串）', () => {
    storeSnapshot({
      costume: [
        { id: 'same-id', library: 'costume-anime', name: '二次元', thumbnail: '' },
        { id: 'real-id', library: 'costume', name: '现实', thumbnail: '' },
      ],
    })

    draft.hydrate({
      portrait: [],
      // 库里只有现实库的 same-id，不应被「二次元库」的记录命中。
      costume: [
        { ...costume('same-id'), library: 'costume' },
        { ...costume('real-id'), library: 'costume' },
      ],
      pose: [],
    })

    expect(draft.costume.value.map((item) => item.id)).toEqual(['real-id'])
  })

  it('无存储时 hydrate 返回 false，且不改变现有选择', () => {
    draft.setPortrait(portrait('pt1'))

    const restored = draft.hydrate({
      portrait: [portrait('pt2')],
      costume: [],
      pose: [],
    })

    expect(restored).toBe(false)
    expect(draft.portrait.value.map((item) => item.id)).toEqual(['pt1'])
  })

  it('P2 槽位模式：setSlotMode 立即落盘，read 可读回', () => {
    draft.setSlotMode('portrait', 'text')
    draft.setSlotMode('costume', 'image')

    flushReferenceStudioSettings()
    const stored = readReferenceStudioSettings()

    expect(stored?.portraitMode).toBe('text')
    expect(stored?.costumeMode).toBe('image')
    expect(stored?.poseMode).toBe('empty')
  })

  it('P2 槽位模式：clearDraft 重置为全空并清掉上次姿势', () => {
    draft.setSlotMode('pose', 'text')
    draft.setPose(pose('pair-01'))

    draft.clearDraft()

    expect(draft.slotModes.value).toEqual({
      portrait: 'empty',
      costume: 'empty',
      pose: 'empty',
    })
    expect(draft.lastPoseId.value).toBe('')
  })

  it('P4 补充开关：只在 image 模式打开，切 text 自动归零并落盘', () => {
    draft.setSlotMode('portrait', 'image')
    draft.setSlotSupplement('portrait', true)
    expect(draft.supplementFlags.value.portrait).toBe(true)

    draft.setSlotMode('portrait', 'text')
    expect(draft.supplementFlags.value.portrait).toBe(false)

    flushReferenceStudioSettings()
    const stored = readReferenceStudioSettings()
    expect(stored?.portraitSupplement).toBe(false)
  })

  it('P4 补充开关：empty 模式下打开会被忽略', () => {
    draft.setSlotMode('costume', 'empty')
    draft.setSlotSupplement('costume', true)
    expect(draft.supplementFlags.value.costume).toBe(false)
  })

  it('P4 clearDraft 同时清空补充开关', () => {
    draft.setSlotMode('pose', 'image')
    draft.setSlotSupplement('pose', true)
    draft.clearDraft()
    expect(draft.supplementFlags.value).toEqual({
      portrait: false,
      costume: false,
      pose: false,
    })
  })

  it('P2 旧快照缺 mode：按「有图 → image；无图 + 碎片 → text；否则 empty」推导', () => {
    storeSnapshot({
      portrait: [{ id: 'pt1', library: 'portrait', name: '发型', thumbnail: '' }],
      textFragments: {
        ...createEmptyRecipeTextFragments(),
        人物服饰: [{ type: '人物服饰', content: '白色衬衫' }],
      },
    })

    draft.hydrate({
      portrait: [portrait('pt1')],
      costume: [],
      pose: [],
    })

    expect(draft.slotModes.value).toEqual({
      portrait: 'image',
      costume: 'text',
      pose: 'empty',
    })
  })

  it('P2 快照有显式 mode 时优先于内容推导', () => {
    storeSnapshot({
      textFragments: {
        ...createEmptyRecipeTextFragments(),
        人物服饰: [{ type: '人物服饰', content: '白色衬衫' }],
      },
      costumeMode: 'image',
      portraitMode: 'text',
      poseMode: 'empty',
    })

    draft.hydrate({ portrait: [], costume: [], pose: [] })

    // costume 有碎片但用户显式选择 image：保留用户选择（可能是残留图被删）
    expect(draft.slotModes.value).toEqual({
      portrait: 'text',
      costume: 'image',
      pose: 'empty',
    })
  })

  it('P2 旧快照三槽全空且无碎片 → 全 empty', () => {
    storeSnapshot({})

    draft.hydrate({ portrait: [], costume: [], pose: [] })

    expect(draft.slotModes.value).toEqual({
      portrait: 'empty',
      costume: 'empty',
      pose: 'empty',
    })
  })
})

// ---------------------------------------------------------------------------
// 本地上传图（2026-11-06）：三槽都支持，与库条目同数组、一起参与笛卡尔积
// ---------------------------------------------------------------------------

describe('本地上传图', () => {
  const upload = (name: string) => ({
    path: `F:/ComfyUI_Migration/ComfyUI-Portrait-Workflows/workflows/脚本/atelier/data/uploads/${name}`,
    name,
  })

  it('人像槽：加入、同路径去重、缩略图走 /uploads', () => {
    draft.addPortraitUpload(upload('a.png'))
    draft.addPortraitUpload(upload('a.png'))
    draft.addPortraitUpload(upload('b.png'))

    expect(draft.portraitCount.value).toBe(2)
    expect(draft.count.value).toBe(1)
    const first = draft.portrait.value[0]
    expect(first.id.startsWith('upload:')).toBe(true)
    expect(first.缩略图).toBe('/uploads/a.png')
    expect(uploadPathOf(first)).toContain('a.png')
  })

  it('服装 / 姿势槽：上传图同样进入数组并带 uploadPath', () => {
    draft.addCostumeUpload(upload('c.png'))
    draft.addPoseUpload(upload('p.png'))

    expect(draft.costumeCount.value).toBe(1)
    expect(draft.poseCount.value).toBe(1)
    expect(uploadPathOf(draft.costume.value[0])).toContain('c.png')
    expect(uploadPathOf(draft.pose.value[0]?.item)).toContain('p.png')
    // 上传图没有深度图变体
    expect(draft.pose.value[0]?.useDepth).toBe(false)
  })

  it('持久化后 hydrate：按 path 重建上传图（不需要库里有这条）', () => {
    draft.addPortraitUpload(upload('keep.png'))
    flushReferenceStudioSettings()
    draft.clearDraft()

    const restored = draft.hydrate({ portrait: [], costume: [], pose: [] })

    expect(restored).toBe(true)
    expect(draft.portraitCount.value).toBe(1)
    expect(uploadPathOf(draft.portrait.value[0])).toContain('keep.png')
    expect(draft.portrait.value[0].缩略图).toBe('/uploads/keep.png')
  })
})