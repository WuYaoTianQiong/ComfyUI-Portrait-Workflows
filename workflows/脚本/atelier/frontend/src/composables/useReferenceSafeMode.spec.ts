/**
 * 18+ 安全模式单测。
 *
 * 覆盖 §7 / §8 G6 的语义：
 * - 缺省安全模式（true）、显式 `'false'` 才解锁；
 * - 首次解锁弹一次确认，确认后写 `pose_atlas_nsfw_confirmed_v1`，二次解锁不弹；
 * - 切回安全模式**不重置**确认标记；
 * - 后端总闸 `allow_nsfw=false` 时解锁被拒、入口置灰（canUnlock=false）；
 * - 总闸探测失败按「未知」处理，不误伤既有功能。
 *
 * 模块内是单例状态，每个用例用 `vi.resetModules()` + 动态 import 取一份干净实例。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * happy-dom / Node 25 的全局 localStorage 在当前运行方式下不是完整 Storage，
 * 补一份最小实现；每个用例的重装由 installStorageStub 负责。
 */
function installStorageStub() {
  const values = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    get length() {
      return values.size
    },
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value),
    removeItem: (key: string) => void values.delete(key),
    clear: () => values.clear(),
  })
}

async function loadModule() {
  vi.resetModules()
  return import('./useReferenceSafeMode')
}

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response
}

beforeEach(() => {
  installStorageStub()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('记忆键与缺省值', () => {
  it('没有任何键时默认为安全模式', async () => {
    const mod = await loadModule()
    expect(mod.SAFE_MODE_STORAGE_KEY).toBe('pose_atlas_safe_mode_v1')
    expect(mod.NSFW_CONFIRMED_STORAGE_KEY).toBe('pose_atlas_nsfw_confirmed_v1')
    expect(mod.readSafeMode()).toBe(true)
    expect(mod.readNsfwConfirmed()).toBe(false)
  })

  it('只有显式 false 才视为解锁；其它值回落安全模式', async () => {
    localStorage.setItem('pose_atlas_safe_mode_v1', 'false')
    expect((await loadModule()).readSafeMode()).toBe(false)

    localStorage.setItem('pose_atlas_safe_mode_v1', 'garbage')
    expect((await loadModule()).readSafeMode()).toBe(true)
  })

  it('切回安全模式只写开关，不重置确认标记', async () => {
    // 确认标记必须在模块初始化前就存在（模块级状态在 import 时读取一次）
    localStorage.setItem('pose_atlas_nsfw_confirmed_v1', 'true')
    const mod = await loadModule()
    const state = mod.useReferenceSafeMode()
    expect(state.nsfwConfirmed.value).toBe(true)

    // 完整模式 → 安全模式
    state.safeMode.value = false
    state.toggleSafeMode()

    expect(state.safeMode.value).toBe(true)
    expect(localStorage.getItem('pose_atlas_safe_mode_v1')).toBe('true')
    expect(localStorage.getItem('pose_atlas_nsfw_confirmed_v1')).toBe('true')
    expect(state.nsfwConfirmed.value).toBe(true)
  })
})

describe('首次解锁只弹一次', () => {
  it('首次请求打开确认框，确认后才解锁并写标记', async () => {
    const mod = await loadModule()
    const state = mod.useReferenceSafeMode()
    const calls: string[] = []

    expect(state.requestUnlock(() => calls.push('unlocked'))).toBe(true)
    expect(state.ageGateOpen.value).toBe(true)
    expect(state.safeMode.value).toBe(true)
    expect(calls).toEqual([])
    expect(localStorage.getItem('pose_atlas_nsfw_confirmed_v1')).toBeNull()

    state.confirmUnlock()

    expect(state.ageGateOpen.value).toBe(false)
    expect(state.safeMode.value).toBe(false)
    expect(state.nsfwConfirmed.value).toBe(true)
    expect(calls).toEqual(['unlocked'])
    expect(localStorage.getItem('pose_atlas_safe_mode_v1')).toBe('false')
    expect(localStorage.getItem('pose_atlas_nsfw_confirmed_v1')).toBe('true')
  })

  it('第二次解锁不再弹窗，直接放行并执行回调', async () => {
    const mod = await loadModule()
    const state = mod.useReferenceSafeMode()

    state.requestUnlock()
    state.confirmUnlock()
    expect(state.safeMode.value).toBe(false)

    // 切回安全模式（不重置确认标记）
    state.toggleSafeMode()
    expect(state.safeMode.value).toBe(true)

    let unlocked = 0
    expect(state.requestUnlock(() => (unlocked += 1))).toBe(true)
    expect(state.ageGateOpen.value).toBe(false)
    expect(state.safeMode.value).toBe(false)
    expect(unlocked).toBe(1)
  })

  it('取消确认：保持安全模式、丢弃回调、不写标记', async () => {
    const mod = await loadModule()
    const state = mod.useReferenceSafeMode()
    let unlocked = 0

    state.requestUnlock(() => (unlocked += 1))
    state.cancelUnlock()

    expect(state.ageGateOpen.value).toBe(false)
    expect(state.safeMode.value).toBe(true)
    expect(unlocked).toBe(0)
    expect(localStorage.getItem('pose_atlas_nsfw_confirmed_v1')).toBeNull()
  })

  it('已是完整模式时请求解锁只执行回调，不弹窗', async () => {
    const mod = await loadModule()
    const state = mod.useReferenceSafeMode()
    state.safeMode.value = false
    let unlocked = 0

    state.requestUnlock(() => (unlocked += 1))
    expect(state.ageGateOpen.value).toBe(false)
    expect(unlocked).toBe(1)
  })
})

describe('后端总闸', () => {
  it('allow_nsfw=false：入口置灰、解锁被拒', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ allow_nsfw: false })))
    const mod = await loadModule()
    const state = mod.useReferenceSafeMode()

    expect(state.backendAllowNsfw.value).toBeNull()
    await state.loadBackendGate()

    expect(state.backendAllowNsfw.value).toBe(false)
    expect(state.nsfwAvailable.value).toBe(false)
    expect(state.canUnlock.value).toBe(false)
    expect(state.requestUnlock()).toBe(false)
    expect(state.ageGateOpen.value).toBe(false)
    expect(state.safeMode.value).toBe(true)
  })

  it('allow_nsfw=true：可解锁', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ allow_nsfw: true })))
    const mod = await loadModule()
    const state = mod.useReferenceSafeMode()
    await state.loadBackendGate()

    expect(state.nsfwAvailable.value).toBe(true)
    expect(state.canUnlock.value).toBe(true)
    expect(state.requestUnlock()).toBe(true)
    expect(state.ageGateOpen.value).toBe(true)
  })

  it('探测失败按未知处理，不阻塞解锁，并保留错误信息', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('网络不可用')
      }),
    )
    const mod = await loadModule()
    const state = mod.useReferenceSafeMode()
    await state.loadBackendGate()

    expect(state.backendAllowNsfw.value).toBeNull()
    expect(state.nsfwAvailable.value).toBe(true)
    expect(state.gateError.value).toBe('网络不可用')
    expect(state.requestUnlock()).toBe(true)
  })

  it('并发探测复用同一个请求', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ allow_nsfw: true }))
    vi.stubGlobal('fetch', fetchMock)
    const mod = await loadModule()
    const state = mod.useReferenceSafeMode()

    await Promise.all([state.loadBackendGate(), state.loadBackendGate()])
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})