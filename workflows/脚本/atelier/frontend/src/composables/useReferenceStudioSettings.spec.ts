/**
 * 参考图库操作记忆持久化单测（2026-11-05）。
 *
 * 覆盖任务要求的最小用例集：
 * - 写入后读回（含字段结构）；
 * - 非法 JSON / 非对象 / 字段类型不对 → 整体丢弃回落默认；
 * - 隐私模式下 localStorage 读取抛错不崩、写入静默；
 * - 300ms 防抖只写一次盘；
 * - 最后页签的读 / 写（优先级由 ReferenceView.spec 覆盖 URL > 存储 > home）。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const localValues = new Map<string, string>()

const memoryStorage: Storage = {
  get length() {
    return localValues.size
  },
  getItem: (key: string) => localValues.get(key) ?? null,
  setItem: (key: string, value: string) => {
    localValues.set(key, value)
  },
  removeItem: (key: string) => {
    localValues.delete(key)
  },
  clear: () => {
    localValues.clear()
  },
  key: (index: number) => [...localValues.keys()][index] ?? null,
}

vi.stubGlobal('localStorage', memoryStorage)

import {
  DEFAULT_REFERENCE_STUDIO_BASE_SEED,
  REFERENCE_STUDIO_STORAGE_KEY,
  REFERENCE_STUDIO_WRITE_DEBOUNCE_MS,
  REFERENCE_TAB_STORAGE_KEY,
  createDefaultReferenceStudioSettings,
  flushReferenceStudioSettings,
  parseReferenceStudioSettings,
  readLastReferenceTab,
  readReferenceStudioSettings,
  writeLastReferenceTab,
  writeReferenceStudioSettings,
} from './useReferenceStudioSettings'
import type { ReferenceStudioSettings } from './useReferenceStudioSettings'
import { DEFAULT_RECIPE_SEED } from './useReferenceRecipe'

/** 一份字段齐全的合法快照。 */
function validSnapshot(): ReferenceStudioSettings {
  return {
    portrait: [
      { id: 'pt1', library: 'portrait', name: '发型 A', thumbnail: '/thumb/pt1' },
    ],
    costume: [
      { id: 'c1', library: 'costume', name: '服装 A', thumbnail: '/thumb/c1' },
      {
        id: 'c2',
        library: 'costume-anime',
        name: '服装 B',
        thumbnail: '/thumb/c2',
      },
    ],
    pose: [
      {
        id: 'p1',
        library: 'pose',
        name: '姿势 A',
        thumbnail: '/thumb/p1',
        useDepth: true,
      },
    ],
    style: 'none',
    workflow: 'Qwen21+VNCCS.json',
    baseSeed: 123456,
    qualities: ['4K'],
    ratios: ['3:4'],
    sizesConfigured: true,
  }
}

beforeEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.stubGlobal('localStorage', memoryStorage)
  memoryStorage.clear()
})

afterEach(() => {
  // 清掉可能遗留的防抖补丁，避免跨用例写盘。
  flushReferenceStudioSettings()
  memoryStorage.clear()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.stubGlobal('localStorage', memoryStorage)
})

describe('默认值', () => {
  it('无记录时 read 返回 null（调用方保留页面原有默认行为）', () => {
    expect(readReferenceStudioSettings()).toBeNull()
  })

  it('默认基础种子与 useReferenceRecipe 的默认值一致', () => {
    expect(DEFAULT_REFERENCE_STUDIO_BASE_SEED).toBe(DEFAULT_RECIPE_SEED)
  })

  it('默认快照结构完整且为「未配置尺寸」', () => {
    const defaults = createDefaultReferenceStudioSettings()
    expect(defaults).toEqual({
      portrait: [],
      costume: [],
      pose: [],
      style: 'realistic',
      workflow: '',
      baseSeed: DEFAULT_REFERENCE_STUDIO_BASE_SEED,
      qualities: [],
      ratios: [],
      sizesConfigured: false,
    })
  })
})

describe('写入后读回', () => {
  it('flush 后能把三槽 / 画风 / 工作流 / 种子 / 尺寸完整读回', () => {
    const snapshot = validSnapshot()
    writeReferenceStudioSettings(snapshot)
    flushReferenceStudioSettings()

    expect(readReferenceStudioSettings()).toEqual(snapshot)
  })

  it('多次写入合并成一份，不丢其它字段', () => {
    writeReferenceStudioSettings({ style: 'none' })
    writeReferenceStudioSettings({ baseSeed: 7 })
    writeReferenceStudioSettings({ workflow: 'a.json' })
    flushReferenceStudioSettings()

    const stored = readReferenceStudioSettings()
    expect(stored).toMatchObject({ style: 'none', baseSeed: 7, workflow: 'a.json' })
    expect(stored?.portrait).toEqual([])
    expect(stored?.sizesConfigured).toBe(false)
  })

  it('存储键名带版本后缀，且只写这一个键', () => {
    writeReferenceStudioSettings(validSnapshot())
    flushReferenceStudioSettings()

    expect(REFERENCE_STUDIO_STORAGE_KEY).toBe('pb.reference_studio_v1')
    expect([...localValues.keys()]).toEqual([REFERENCE_STUDIO_STORAGE_KEY])
  })
})

describe('防抖', () => {
  it('连续写入在 300ms 内只落一次盘，且写的是最后一次合并结果', () => {
    vi.useFakeTimers()
    const setItemSpy = vi.spyOn(memoryStorage, 'setItem')

    writeReferenceStudioSettings({ style: 'none' })
    writeReferenceStudioSettings({ workflow: 'w1.json' })
    writeReferenceStudioSettings({ baseSeed: 42 })

    expect(setItemSpy).not.toHaveBeenCalled()
    expect(REFERENCE_STUDIO_WRITE_DEBOUNCE_MS).toBe(300)

    vi.advanceTimersByTime(REFERENCE_STUDIO_WRITE_DEBOUNCE_MS)

    expect(setItemSpy).toHaveBeenCalledTimes(1)
    const stored = readReferenceStudioSettings()
    expect(stored).toMatchObject({ style: 'none', workflow: 'w1.json', baseSeed: 42 })
  })

  it('值没有变化时不重复写盘', () => {
    vi.useFakeTimers()
    writeReferenceStudioSettings({ style: 'none' })
    vi.advanceTimersByTime(REFERENCE_STUDIO_WRITE_DEBOUNCE_MS)

    const setItemSpy = vi.spyOn(memoryStorage, 'setItem')
    writeReferenceStudioSettings({ style: 'none' })
    vi.advanceTimersByTime(REFERENCE_STUDIO_WRITE_DEBOUNCE_MS)

    expect(setItemSpy).not.toHaveBeenCalled()
  })
})

describe('数据校验：脏数据整体丢弃', () => {
  function storeRaw(raw: string): void {
    memoryStorage.setItem(REFERENCE_STUDIO_STORAGE_KEY, raw)
  }

  it('非法 JSON 回落 null', () => {
    storeRaw('{not json')
    expect(readReferenceStudioSettings()).toBeNull()
  })

  it('非对象（数组 / 字符串 / null）回落 null', () => {
    storeRaw('[]')
    expect(readReferenceStudioSettings()).toBeNull()
    storeRaw('"hello"')
    expect(readReferenceStudioSettings()).toBeNull()
    storeRaw('null')
    expect(readReferenceStudioSettings()).toBeNull()
  })

  it('字段缺失或类型不对整体丢弃', () => {
    const broken: Array<Record<string, unknown>> = [
      { ...validSnapshot(), style: 'anime' },
      { ...validSnapshot(), baseSeed: '-1' },
      { ...validSnapshot(), workflow: 42 },
      { ...validSnapshot(), qualities: '4K' },
      { ...validSnapshot(), ratios: [1, 2] },
      { ...validSnapshot(), portrait: [{ id: 'pt1', library: 'portrait' }] },
      { ...validSnapshot(), pose: [{ id: 'p1', library: 'pose', name: 'a', thumbnail: '', useDepth: 'yes' }] },
      { ...validSnapshot(), costume: [{ id: 'c1', library: 'unknown', name: 'a', thumbnail: '' }] },
      (() => {
        const missing: Record<string, unknown> = { ...validSnapshot() }
        delete missing.ratios
        return missing
      })(),
    ]

    for (const value of broken) {
      storeRaw(JSON.stringify(value))
      expect(readReferenceStudioSettings(), JSON.stringify(value)).toBeNull()
      // 纯函数口径同样返回 null。
      expect(parseReferenceStudioSettings(value)).toBeNull()
    }
  })

  it('sizesConfigured 缺省视为 false（兼容早期写入）', () => {
    const { sizesConfigured: _ignored, ...withoutFlag } = validSnapshot()
    storeRaw(JSON.stringify(withoutFlag))
    expect(readReferenceStudioSettings()?.sizesConfigured).toBe(false)
  })
})

describe('隐私模式 / 存储不可用', () => {
  it('访问 localStorage 属性本身抛 SecurityError 时 read 返回 null、write 不崩', () => {
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      get() {
        throw new Error('SecurityError')
      },
    })

    try {
      expect(readReferenceStudioSettings()).toBeNull()
      expect(readLastReferenceTab()).toBeNull()
      expect(() => writeReferenceStudioSettings({ style: 'none' })).not.toThrow()
      expect(() => flushReferenceStudioSettings()).not.toThrow()
      expect(() => writeLastReferenceTab('pose')).not.toThrow()
    } finally {
      if (descriptor) Object.defineProperty(globalThis, 'localStorage', descriptor)
      else vi.stubGlobal('localStorage', memoryStorage)
    }
  })

  it('getItem / setItem 抛错时静默降级，不阻断交互', () => {
    vi.stubGlobal('localStorage', {
      get length() {
        return 0
      },
      getItem() {
        throw new Error('SecurityError')
      },
      setItem() {
        throw new Error('QuotaExceededError')
      },
      removeItem() {
        throw new Error('SecurityError')
      },
      clear() {
        throw new Error('SecurityError')
      },
      key() {
        return null
      },
    } satisfies Storage)

    expect(readReferenceStudioSettings()).toBeNull()
    expect(() => {
      writeReferenceStudioSettings({ style: 'realistic' })
      flushReferenceStudioSettings()
    }).not.toThrow()
    expect(() => writeLastReferenceTab('studio')).not.toThrow()
  })
})

describe('最后访问页签', () => {
  it('无记录返回 null；写入后可读回', () => {
    expect(readLastReferenceTab()).toBeNull()

    writeLastReferenceTab('portrait')
    expect(readLastReferenceTab()).toBe('portrait')
    expect(REFERENCE_TAB_STORAGE_KEY).toBe('pb.reference_tab_v1')
    expect(memoryStorage.getItem(REFERENCE_TAB_STORAGE_KEY)).toBe('portrait')
  })

  it('空串视为无记录', () => {
    memoryStorage.setItem(REFERENCE_TAB_STORAGE_KEY, '')
    expect(readLastReferenceTab()).toBeNull()
  })
})