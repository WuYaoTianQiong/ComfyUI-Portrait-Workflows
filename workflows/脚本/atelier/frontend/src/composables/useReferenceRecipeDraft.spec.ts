/**
 * 三槽位配方选择状态单测。
 *
 * 覆盖：加入 / 替换 / 移除、n/3 计数、已选判定（姿势区分白模与深度图）、清空；
 * 并显式断言「不做持久化」——操作后 localStorage / sessionStorage 不被写入。
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

describe('三槽位计数', () => {
  it('初始为空，n/3 为 0/3', () => {
    expect(draft.count.value).toBe(0)
    expect(draft.countLabel.value).toBe('0/3')
    expect(draft.isComplete.value).toBe(false)
    expect(RECIPE_SLOT_TOTAL).toBe(3)
  })

  it('三个槽位各加一条 → 3/3 且 isComplete', () => {
    draft.setPortrait(portrait('pt1'))
    draft.setCostume(costume('c1'))
    draft.setPose(pose('p1'))

    expect(draft.count.value).toBe(3)
    expect(draft.countLabel.value).toBe('3/3')
    expect(draft.isComplete.value).toBe(true)
  })

  it('同一槽位重复设置不会增加计数', () => {
    draft.setPortrait(portrait('pt1'))
    draft.setPortrait(portrait('pt2'))
    expect(draft.count.value).toBe(1)
    expect(draft.portrait.value?.id).toBe('pt2')
  })
})

describe('加入 / 移除', () => {
  it('人像槽点击同一条取消，点击别的替换', () => {
    expect(draft.togglePortrait(portrait('pt1'))).toBe(true)
    expect(draft.isPortraitSelected('pt1')).toBe(true)
    expect(draft.togglePortrait(portrait('pt2'))).toBe(true)
    expect(draft.portrait.value?.id).toBe('pt2')
    expect(draft.togglePortrait(portrait('pt2'))).toBe(false)
    expect(draft.isPortraitSelected()).toBe(false)
    expect(draft.count.value).toBe(0)
  })

  it('服装槽同理，removeCostume 直接清空', () => {
    draft.toggleCostume(costume('c1'))
    expect(draft.isCostumeSelected('c1')).toBe(true)
    expect(draft.isCostumeSelected('c2')).toBe(false)
    draft.removeCostume()
    expect(draft.costume.value).toBeNull()
    expect(draft.isCostumeSelected()).toBe(false)
  })

  it('姿势槽：同 id 同模式点击移除，同 id 换模式视为替换', () => {
    const item = pose('p1')
    expect(draft.togglePose(item, false)).toBe(true)
    expect(draft.pose.value).toMatchObject({ useDepth: false })

    // 卡片口径：只看 id，已选态不区分模式
    expect(draft.isPoseSelected('p1')).toBe(true)
    // 灯箱口径：必须 id + 模式都一致
    expect(draft.isPoseSelected('p1', false)).toBe(true)
    expect(draft.isPoseSelected('p1', true)).toBe(false)

    // 切到深度图再点：替换而不是取消
    expect(draft.togglePose(item, true)).toBe(true)
    expect(draft.pose.value).toMatchObject({ useDepth: true })
    expect(draft.count.value).toBe(1)

    // 同模式再点才移除
    expect(draft.togglePose(item, true)).toBe(false)
    expect(draft.pose.value).toBeNull()
  })

  it('setPose(null) 与 removePose 等价', () => {
    draft.setPose(pose('p1'), true)
    draft.setPose(null)
    expect(draft.pose.value).toBeNull()

    draft.setPose(pose('p2'))
    draft.removePose()
    expect(draft.pose.value).toBeNull()
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
    expect(draft.portrait.value).toBeNull()
    expect(draft.costume.value).toBeNull()
    expect(draft.pose.value).toBeNull()
  })

  it('M3：不写 localStorage / sessionStorage', () => {
    draft.setPortrait(portrait('pt1'))
    draft.setCostume(costume('c1'))
    draft.setPose(pose('p1'), true)

    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })
})