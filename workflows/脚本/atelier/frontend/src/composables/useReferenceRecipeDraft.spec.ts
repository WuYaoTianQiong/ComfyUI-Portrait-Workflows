/**
 * 三槽位配方选择状态单测（多选版）。
 *
 * 覆盖：多选追加 / 去重 / 移除、非空槽数 n/3 与条目总数、已选判定
 * （姿势区分白模与深度图）、切换模式、清空；并显式断言「不做持久化」——
 * 操作后 localStorage / sessionStorage 不被写入。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { CostumeItem, PoseItem, PortraitItem } from '../api/reference'

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

import { RECIPE_SLOT_TOTAL, useReferenceRecipeDraft } from './useReferenceRecipeDraft'

function pose(id: string, name = '姿势'): PoseItem {
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

  it('setPose(null) / removePose 清空', () => {
    draft.setPose(pose('p1'), true)
    draft.setPose(null)
    expect(draft.pose.value).toEqual([])

    draft.setPose(pose('p2'))
    draft.removePose()
    expect(draft.pose.value).toEqual([])
  })
})

describe('清空与不持久化', () => {
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

  it('M3：不写 localStorage / sessionStorage', () => {
    draft.addPortrait(portrait('pt1'))
    draft.addCostume(costume('c1'))
    draft.addPose(pose('p1'), true)

    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })
})