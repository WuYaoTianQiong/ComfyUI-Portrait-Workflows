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
import {
  createEmptyRecipeTextFragments,
} from './recipeTextFragments'

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
    extra: {
      source: 'library',
      library: 'hair',
      id: 'hair-1',
      path: '',
      name: '发型参考 A',
      text: '发尾浅金色挑染',
    },
    style: 'none',
    workflow: 'Qwen21+VNCCS.json',
    baseSeed: 123456,
    qualities: ['4K'],
    ratios: ['3:4'],
    sizesConfigured: true,
    textFragments: {
      ...createEmptyRecipeTextFragments(),
      人物面部: [{ type: '人物面部', content: '黑色短发，齐刘海' }],
      场景环境: [{ type: '场景环境', content: '黄昏街道' }],
    },
    negativePrompt: '低质量，多余手指',
    personBText: '金色齐肩短发，酒红色西装外套',
    personBVariants: [],
    portraitMode: 'image',
    costumeMode: 'image',
    poseMode: 'image',
    portraitSupplement: true,
    costumeSupplement: false,
    poseSupplement: false,
    recipeSourceId: 622,
    recipeSourceName: '粉色卧室·抹胸长裙·韩系',
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
      extra: { source: 'empty', library: '', id: '', path: '', name: '', text: '' },
      style: 'realistic',
      workflow: '',
      baseSeed: DEFAULT_REFERENCE_STUDIO_BASE_SEED,
      qualities: [],
      ratios: [],
      sizesConfigured: false,
      textFragments: createEmptyRecipeTextFragments(),
      negativePrompt: '',
      personBText: '',
      personBVariants: [],
      portraitMode: null,
      costumeMode: null,
      poseMode: null,
      portraitSupplement: false,
      costumeSupplement: false,
      poseSupplement: false,
      recipeSourceId: null,
      recipeSourceName: '',
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

  it('P4 补充开关 / 来源字段缺失或脏数据时按默认值读回', () => {
    const raw = validSnapshot() as unknown as Record<string, unknown>
    delete raw.portraitSupplement
    delete raw.costumeSupplement
    delete raw.poseSupplement
    delete raw.recipeSourceId
    delete raw.recipeSourceName

    const parsed = parseReferenceStudioSettings(raw)
    expect(parsed?.portraitSupplement).toBe(false)
    expect(parsed?.costumeSupplement).toBe(false)
    expect(parsed?.poseSupplement).toBe(false)
    expect(parsed?.recipeSourceId).toBeNull()
    expect(parsed?.recipeSourceName).toBe('')

    raw.portraitSupplement = 'yes'
    raw.recipeSourceId = 'not-a-number'
    const dirty = parseReferenceStudioSettings(raw)
    expect(dirty?.portraitSupplement).toBe(false)
    expect(dirty?.recipeSourceId).toBeNull()
  })

  it('第 4 槽：缺字段按空槽读回，脏数据不整体丢弃', () => {
    const raw = validSnapshot() as unknown as Record<string, unknown>
    delete raw.extra
    expect(parseReferenceStudioSettings(raw)?.extra).toEqual({
      source: 'empty',
      library: '',
      id: '',
      path: '',
      name: '',
      text: '',
    })

    // 无 id 的 library 来源 → 视为未选；上传来源必须有 path
    raw.extra = { source: 'library', library: 'hair', id: '', path: '', name: 'x', text: 'y' }
    expect(parseReferenceStudioSettings(raw)?.extra.source).toBe('empty')
    raw.extra = { source: 'upload', library: '', id: '', path: '', name: 'x', text: 'y' }
    expect(parseReferenceStudioSettings(raw)?.extra.source).toBe('empty')
    raw.extra = { source: 'upload', library: '', id: '', path: '/up/a.png', name: 'x', text: 'y' }
    expect(parseReferenceStudioSettings(raw)?.extra).toMatchObject({
      source: 'upload',
      path: '/up/a.png',
      text: 'y',
    })
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

  it('文本补充字段缺失时按空读回（旧快照不整体丢弃）', () => {
    const { textFragments: _t, negativePrompt: _n, ...legacy } = validSnapshot()
    storeRaw(JSON.stringify(legacy))

    const stored = readReferenceStudioSettings()
    expect(stored).not.toBeNull()
    expect(stored?.portrait).toHaveLength(1)
    expect(stored?.textFragments).toEqual(createEmptyRecipeTextFragments())
    expect(stored?.negativePrompt).toBe('')
  })

  it('文本补充脏数据逐条丢弃 / 逐类回落空，不影响其余设置', () => {
    storeRaw(
      JSON.stringify({
        ...validSnapshot(),
        textFragments: {
          人物面部: [{ content: '保留' }, { content: 42 }, null],
          人物身材: 'not-array',
          人物服饰: [{ content: '   ' }],
          姿态动作: [
            { content: 'a' },
            { content: 'b' },
            { content: 'c' },
          ],
        },
        negativePrompt: 42,
      }),
    )

    const stored = readReferenceStudioSettings()
    expect(stored?.textFragments.人物面部).toEqual([
      { type: '人物面部', content: '保留' },
    ])
    expect(stored?.textFragments.人物身材).toEqual([])
    expect(stored?.textFragments.人物服饰).toEqual([])
    // 单类裁剪到软上限 2 条
    expect(stored?.textFragments.姿态动作).toHaveLength(2)
    expect(stored?.negativePrompt).toBe('')
    expect(stored?.workflow).toBe('Qwen21+VNCCS.json')
  })

  it('P2 槽位模式缺字段时读回 null（由草稿按内容推导，不整体丢弃）', () => {
    const {
      portraitMode: _pm,
      costumeMode: _cm,
      poseMode: _sm,
      ...legacy
    } = validSnapshot()
    storeRaw(JSON.stringify(legacy))

    const stored = readReferenceStudioSettings()
    expect(stored).not.toBeNull()
    expect(stored?.portraitMode).toBeNull()
    expect(stored?.costumeMode).toBeNull()
    expect(stored?.poseMode).toBeNull()
    // 其余字段照常恢复
    expect(stored?.portrait).toHaveLength(1)
    expect(stored?.textFragments.人物面部).toHaveLength(1)
  })

  it('P2 槽位模式：合法值保留，非法值按 null 容错', () => {
    storeRaw(
      JSON.stringify({
        ...validSnapshot(),
        portraitMode: 'text',
        costumeMode: 'bogus',
        poseMode: 'empty',
      }),
    )

    const stored = readReferenceStudioSettings()
    expect(stored?.portraitMode).toBe('text')
    expect(stored?.costumeMode).toBeNull()
    expect(stored?.poseMode).toBe('empty')
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