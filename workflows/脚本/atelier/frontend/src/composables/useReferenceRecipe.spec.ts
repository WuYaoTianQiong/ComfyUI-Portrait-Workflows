/**
 * 合成台提交 / 轮询单测（阶段 3）。
 *
 * 覆盖：
 * - 提交体构造（三槽 id、costume_library 归一、旧画风降级、prompt_suffix 去空白、
 *   extra_path 只带 1 张）；
 * - 工作流默认选中（default 优先，缺失回落首条）；
 * - 进度文案与终态集合（与 React `recipeClient` 一致）；
 * - 结果图地址（`/api/media/image?...`、去重、默认 type=output）；
 * - 三句式中文错误（含后端空槽 / 输入数 / 白名单原文）；
 * - 轮询 1500ms 语义：连续 3 次失败才抛错、超时抛 RecipeTimeoutError。
 *
 * 多选批量（笛卡尔积、上限、caps 过滤、seed 派生、切换工作流清空尺寸）
 * 的用例见 `useReferenceRecipeBatch.spec.ts`。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, reactive } from 'vue'

import type { CostumeItem, PoseItem, PortraitItem } from '@/api/reference'

import {
  DEFAULT_RECIPE_SEED,
  MAX_CONSECUTIVE_POLL_ERRORS,
  RecipeSubmitError,
  RecipeTimeoutError,
  WORKFLOW_SELECTION_SESSION_KEY,
  buildRecipeRequest,
  costumeDimensionForBodyMode,
  costumeLibraryOf,
  describeJobFailure,
  describeJobProgress,
  describeMissingResult,
  describePollFailure,
  describePreviewFailure,
  describeSubmitFailure,
  describeWorkflowSelectionRestoreNotice,
  groupResultKeyOf,
  hasWorkflowSelectionSession,
  isJobSucceeded,
  isJobTerminal,
  normalizeRecipeStyle,
  normalizeWorkflowSelectionPaths,
  parseWorkflowSelectionSession,
  pollRecipeJob,
  previewRecipePrompt,
  pruneInapplicableWorkflowSelection,
  readWorkflowSelectionSession,
  recipeJobResultUrls,
  resolveInitialWorkflowPath,
  submitRecipe,
  useReferenceRecipe,
  workflowDisplayName,
  writeWorkflowSelectionSession,
} from './useReferenceRecipe'
import type {
  RecipeBatchGroup,
  RecipeJobSnapshot,
  RecipeSubmitRequest,
  StudioWorkflowOption,
} from './useReferenceRecipe'

function portrait(overrides: Partial<PortraitItem> = {}): PortraitItem {
  return {
    id: 'portrait-1',
    分区: '正脸参考',
    发长: '短发',
    发型名称: '齐耳短发',
    标题: '人像 A',
    宽: 0,
    高: 0,
    字节数: 0,
    精选: false,
    热门: false,
    缩略图: '/api/reference/items/portrait/portrait-1/image?kind=thumb',
    原图: '/api/reference/items/portrait/portrait-1/image?kind=image',
    检索: '',
    ...overrides,
  }
}

function costume(overrides: Partial<CostumeItem> = {}): CostumeItem {
  return {
    id: 'costume-1',
    分类: '日常',
    服装名称: '白衬衫',
    标签: [],
    关键词: '',
    缩略图: '',
    预览图: '',
    原图: '',
    检索: '',
    library: 'costume',
    ...overrides,
  }
}

function pose(overrides: Partial<PoseItem> = {}): PoseItem {
  return {
    id: 'pose-1',
    体系: '全身单人・标准系',
    姿势编号: '001',
    分类: '站姿',
    姿势名称: '站立',
    角度: '正面',
    缩略图: '',
    原图: '',
    检索: '',
    nsfw: false,
    ...overrides,
  }
}

function snapshot(overrides: Partial<RecipeJobSnapshot> = {}): RecipeJobSnapshot {
  return {
    id: 42,
    status: 'running',
    total: 1,
    done_count: 0,
    error_count: 0,
    items: [],
    ...overrides,
  }
}

function workflow(path: string, overrides: Partial<StudioWorkflowOption> = {}): StudioWorkflowOption {
  return {
    path,
    name: `${path}.json`,
    source: '图库专用',
    relPath: path,
    imageSlots: 3,
    inputCount: 3,
    recommended: false,

    ...overrides,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('normalizeRecipeStyle / costumeLibraryOf', () => {
  it('只保留 none，其余旧画风降级 realistic', () => {
    expect(normalizeRecipeStyle('none')).toBe('none')
    expect(normalizeRecipeStyle('realistic')).toBe('realistic')
    expect(normalizeRecipeStyle('fashion')).toBe('realistic')
    expect(normalizeRecipeStyle(undefined)).toBe('realistic')
    expect(normalizeRecipeStyle('')).toBe('realistic')
  })

  it('服装库只允许 costume / costume-anime，缺省现实库', () => {
    expect(costumeLibraryOf(null)).toBe('costume')
    expect(costumeLibraryOf(costume())).toBe('costume')
    expect(costumeLibraryOf(costume({ library: 'costume-anime' }))).toBe('costume-anime')
    // 脏数据（未知库名）按现实库处理，避免提交被后端拒绝
    expect(costumeLibraryOf(costume({ library: undefined }))).toBe('costume')
  })
})

describe('buildRecipeRequest', () => {
  it('三槽齐全时发送 id、costume_library、style 与 prompt_suffix', () => {
    const request = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      { style: 'realistic', promptSuffix: '  暖色灯光，浅景深  ', extraPath: '' },
    )

    expect(request).toEqual<RecipeSubmitRequest>({
      portrait_id: 'portrait-1',
      costume_id: 'costume-1',
      pose_id: 'pose-1',
      costume_library: 'costume',
      body_mode: 'costume',
      style: 'realistic',
      prompt_suffix: '暖色灯光，浅景深',
      seed: DEFAULT_RECIPE_SEED,
      seed_mode: 'fixed',
    })
    expect('extra_path' in request).toBe(false)
  })

  it('素体模式：body_mode=bare 且绝不发送 costume_id（即使槽位残留服装）', () => {
    const bare = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      { style: 'realistic', promptSuffix: '', extraPath: '', bodyMode: 'bare' },
    )
    expect(bare.body_mode).toBe('bare')
    expect('costume_id' in bare).toBe(false)
    // 服装库字段保留默认值，不额外改变既有协议形状
    expect(bare.costume_library).toBe('costume')

    const normal = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      { style: 'realistic', promptSuffix: '', extraPath: '', bodyMode: 'costume' },
    )
    expect(normal.body_mode).toBe('costume')
    expect(normal.costume_id).toBe('costume-1')

    // 组合阶段同样裁掉服装维度：bare 时即使槽位里有服装也不进入分组
    expect(costumeDimensionForBodyMode([costume()], 'bare')).toEqual([])
    expect(costumeDimensionForBodyMode([costume()], 'costume')).toHaveLength(1)
  })

  it('二次元服装库原样进入提交体', () => {
    const request = buildRecipeRequest(
      { portrait: portrait(), costume: costume({ library: 'costume-anime', id: 'anime-9' }), pose: pose() },
      { style: 'none', promptSuffix: '', extraPath: '' },
    )
    expect(request.costume_library).toBe('costume-anime')
    expect(request.costume_id).toBe('anime-9')
    expect(request.style).toBe('none')
  })

  it('旧画风值降级为 realistic', () => {
    const request = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      // 故意传旧值，验证归一
      { style: 'film' as unknown as 'realistic', promptSuffix: '', extraPath: '' },
    )
    expect(request.style).toBe('realistic')
  })

  it('第 4 张只带 1 个路径，空串不发送该字段', () => {
    const withExtra = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      { style: 'realistic', promptSuffix: '', extraPath: 'F:/lib/uploads/abc.png' },
    )
    expect(withExtra.extra_path).toBe('F:/lib/uploads/abc.png')

    const blank = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      { style: 'realistic', promptSuffix: '', extraPath: '   ' },
    )
    expect('extra_path' in blank).toBe(false)
  })
})

describe('resolveInitialWorkflowPath / workflowDisplayName', () => {
  const list = [workflow('/a'), workflow('/b')]

  it('默认选中后端的 default（在列表内时）', () => {
    expect(resolveInitialWorkflowPath(list, '/b')).toBe('/b')
  })

  it('default 缺失或不在列表时回落首条', () => {
    expect(resolveInitialWorkflowPath(list, '')).toBe('/a')
    expect(resolveInitialWorkflowPath(list, '/missing')).toBe('/a')
  })

  it('空列表返回空串（页面据此禁用提交）', () => {
    expect(resolveInitialWorkflowPath([], '/b')).toBe('')
  })

  it('展示名去掉 .api.json / .json 后缀', () => {
    expect(workflowDisplayName('角色合成.api.json')).toBe('角色合成')
    expect(workflowDisplayName('角色合成.json')).toBe('角色合成')
    expect(workflowDisplayName('角色合成')).toBe('角色合成')
  })
})

describe('终态与进度', () => {
  it('成功 / 失败终态集合与 React 一致', () => {
    for (const status of ['success', 'done', 'completed', 'finished', 'DONE']) {
      expect(isJobSucceeded(snapshot({ status }))).toBe(true)
      expect(isJobTerminal(snapshot({ status }))).toBe(true)
    }
    for (const status of ['failed', 'error', 'cancelled', 'canceled', 'stopped']) {
      expect(isJobSucceeded(snapshot({ status }))).toBe(false)
      expect(isJobTerminal(snapshot({ status }))).toBe(true)
    }
    expect(isJobTerminal(snapshot({ status: 'running' }))).toBe(false)
    expect(isJobTerminal(snapshot({ status: 'pending' }))).toBe(false)
  })

  it('total > 0 才给百分比，排队与出图文案分开', () => {
    expect(describeJobProgress(snapshot({ status: 'pending', total: 2, done_count: 0 }))).toEqual({
      stage: 'queued',
      message: '任务已提交，正在排队…（已完成 0/2）',
      percent: 0,
    })
    expect(describeJobProgress(snapshot({ status: 'running', total: 2, done_count: 1 }))).toEqual({
      stage: 'running',
      message: '正在出图…（已完成 1/2）',
      percent: 50,
    })
    expect(describeJobProgress(snapshot({ status: 'done', total: 0, done_count: 0 }))).toEqual({
      stage: 'done',
      message: '任务已完成，正在获取生成结果…',
      percent: null,
    })
  })

  it('结果图走 /api/media/image 并去重，默认 type=output', () => {
    const urls = recipeJobResultUrls(
      snapshot({
        status: 'done',
        items: [
          { images: [{ filename: 'a.png', subfolder: '2026-11' }] },
          { images: [{ filename: 'a.png', subfolder: '2026-11' }] },
          { images: [{ filename: 'b.png', subfolder: '', type: 'temp' }] },
        ],
      }),
    )

    expect(urls).toHaveLength(2)
    expect(urls[0]).toBe(
      '/api/media/image?filename=a.png&subfolder=2026-11&type=output',
    )
    expect(urls[1]).toBe('/api/media/image?filename=b.png&subfolder=&type=temp')
    // 零直连：不出现 8188 / prompt / comfy
    for (const url of urls) {
      expect(url).not.toContain('8188')
      expect(url).not.toContain('/prompt')
      expect(url).not.toContain('/comfy')
    }
  })
})

describe('三句式中文错误', () => {
  it('提交错误包含现象、原因、下一步', () => {
    const network = describeSubmitFailure(new RecipeSubmitError('提交出图任务失败', 0, '网络请求失败'))
    expect(network).toContain('提交出图任务失败')
    expect(network).toContain('原因：')
    expect(network).toContain('下一步：')

    const upload = describeSubmitFailure(
      new RecipeSubmitError('提交出图任务失败', 400, '第 4 张参考必须是上传目录 uploads 内的文件'),
    )
    expect(upload).toContain('第 4 张参考图被后端拒绝')
    expect(upload).toContain('uploads')
    expect(upload).toContain('下一步：')

    const missing = describeSubmitFailure(new RecipeSubmitError('提交出图任务失败', 400, '缺少姿势'))
    expect(missing).toContain('缺少姿势')
    expect(missing).toContain('补齐对应槽位')
  })

  it('任务失败终态带上后端条目错误', () => {
    const message = describeJobFailure(
      snapshot({ status: 'error', items: [{ images: [], error: '模型缺失' }] }),
    )
    expect(message).toContain('生成失败')
    expect(message).toContain('模型缺失')
    expect(message).toContain('任务中心')
  })

  it('成功但无结果图有专门文案', () => {
    const message = describeMissingResult(snapshot({ id: 7, status: 'done' }))
    expect(message).toContain('未找到结果图')
    expect(message).toContain('任务 #7')
  })

  it('超时文案区分于普通轮询失败', () => {
    const timeout = describePollFailure(new RecipeTimeoutError(12, 30 * 60 * 1000), 12)
    expect(timeout).toContain('超过 30 分钟')
    expect(timeout).toContain('任务中心')

    const network = describePollFailure(new Error('查询任务状态失败：网络请求失败'), 12)
    expect(network).toContain('连续 3 次查询失败')
    expect(network).toContain('下一步：')
  })

  it('新增后端错误文案保留原文并给下一步', () => {
    const noReference = describeSubmitFailure(
      new RecipeSubmitError('提交出图任务失败', 400, '请至少选择一个参考图或上传一张参考图'),
    )
    expect(noReference).toContain('请至少选择一个参考图或上传一张参考图')
    expect(noReference).toContain('下一步：')

    const tooMany = describeSubmitFailure(
      new RecipeSubmitError('提交出图任务失败', 400, '该工作流只有 3 个输入，但提交了 4 张'),
    )
    expect(tooMany).toContain('该工作流只有 3 个输入，但提交了 4 张')

    const untrimmable = describeSubmitFailure(
      new RecipeSubmitError(
        '提交出图任务失败',
        400,
        '该工作流有 4 个输入且无法裁剪到 2 个；请至少提供 4 张参考图',
      ),
    )
    expect(untrimmable).toContain('无法裁剪')

    const outOfScope = describeSubmitFailure(
      new RecipeSubmitError('提交出图任务失败', 400, '该工作流不属于合成台可用范围'),
    )
    expect(outOfScope).toContain('不属于合成台可用范围')
  })
})

describe('submitRecipe / pollRecipeJob', () => {
  it('groupResultKeyOf 不受 reactive Proxy 包装影响（P2 结果图对配方回归）', () => {
    const group = { index: 7 } as RecipeBatchGroup
    const batch = reactive({ groups: [group] })

    // 引用被 Proxy 包装后不再相等，这正是不能用对象做 Map 键的原因。
    expect(batch.groups[0]).not.toBe(group)
    expect(groupResultKeyOf(batch.groups[0]!)).toBe(7)
    expect(groupResultKeyOf(group)).toBe(7)
  })

  it('非 2xx 抛 RecipeSubmitError 并保留后端 detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 400,
        json: async () => ({ detail: '不支持的服装库：xxx' }),
      })),
    )

    await expect(
      submitRecipe({
        style: 'realistic',
        prompt_suffix: '',
        seed: DEFAULT_RECIPE_SEED,
        seed_mode: 'fixed',
      }),
    ).rejects.toMatchObject({
      name: 'RecipeSubmitError',
      status: 400,
      detail: '不支持的服装库：xxx',
    })
  })

  it('轮询到成功终态后返回快照', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => snapshot({ status: 'running', done_count: 0 }),
    }))
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => snapshot({ status: 'running' }),
    } as never)
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => snapshot({ status: 'done', done_count: 1 }),
    } as never)
    vi.stubGlobal('fetch', fetchMock)

    const updates: string[] = []
    const result = await pollRecipeJob(9, {
      intervalMs: 1,
      onUpdate: (next) => updates.push(next.status),
    })

    expect(result.status).toBe('done')
    expect(updates).toEqual(['running', 'done'])
  })

  it('连续 3 次查询失败才抛错，2 次失败后恢复仍返回终态', async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error('boomed'))
      .mockRejectedValueOnce(new Error('boomed'))
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => snapshot({ status: 'done' }) })
    vi.stubGlobal('fetch', fetchMock)

    const result = await pollRecipeJob(9, { intervalMs: 1 })
    expect(result.status).toBe('done')
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it(`${MAX_CONSECUTIVE_POLL_ERRORS} 次连续失败后抛出`, async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('网络请求失败'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(pollRecipeJob(9, { intervalMs: 1 })).rejects.toThrow('网络请求失败')
    expect(fetchMock).toHaveBeenCalledTimes(MAX_CONSECUTIVE_POLL_ERRORS)
  })

  it('超过上限抛 RecipeTimeoutError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => snapshot({ status: 'running' }),
      })),
    )

    await expect(pollRecipeJob(9, { intervalMs: 5, timeoutMs: 12 })).rejects.toBeInstanceOf(
      RecipeTimeoutError,
    )
  })
})


describe('提示词 dry-run 预览', () => {
  const previewRequest = (): RecipeSubmitRequest =>
    buildRecipeRequest(
      { portrait: portrait(), costume: null, pose: null },
      { style: 'realistic', promptSuffix: '暖色灯光', extraPath: '', workflow: 'wf.json' },
    )

  it('POST 同一端点并带 dry_run=true，返回 prompt', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ success: true, dry_run: true, prompt: '组合后的提示词' }),
    }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await previewRecipePrompt(previewRequest())

    expect(result.prompt).toBe('组合后的提示词')
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/reference/recipes')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toMatchObject({
      dry_run: true,
      portrait_id: 'portrait-1',
      prompt_suffix: '暖色灯光',
    })
  })

  it('后端 400 时抛 RecipeSubmitError，预览文案为三句式', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 400,
        json: async () => ({ detail: '请至少选择一个参考图或上传一张参考图' }),
      })),
    )

    await expect(previewRecipePrompt(previewRequest())).rejects.toBeInstanceOf(RecipeSubmitError)

    const message = describePreviewFailure(
      new RecipeSubmitError('获取提示词预览失败', 400, '请至少选择一个参考图或上传一张参考图'),
    )
    expect(message).toContain('提示词预览失败')
    expect(message).toContain('原因：')
    expect(message).toContain('下一步：')
  })

  it('响应缺少 prompt 字段时按失败处理', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({ success: true, dry_run: true }),
      })),
    )

    await expect(previewRecipePrompt(previewRequest())).rejects.toBeInstanceOf(RecipeSubmitError)
    const message = describePreviewFailure(
      new RecipeSubmitError('获取提示词预览失败', 200, '响应不是有效的 JSON，或缺少 prompt 字段'),
    )
    expect(message).toContain('下一步：')
  })
})

// ---------------------------------------------------------------------------
// 工作流多选的会话级记忆（sessionStorage 键
// pb.reference_studio_workflows_session_v1；2026-11-06 用户拍板）
// ---------------------------------------------------------------------------

/** 内存版 Storage：用于断言只写会话记忆键、值与容错行为。 */
function memoryStorage(options: { throwOnWrite?: boolean; throwOnRead?: boolean } = {}): {
  storage: Storage
  values: Map<string, string>
  writes: string[]
} {
  const values = new Map<string, string>()
  const writes: string[] = []
  const storage: Storage = {
    get length(): number {
      return values.size
    },
    clear(): void {
      values.clear()
    },
    getItem(key: string): string | null {
      if (options.throwOnRead) throw new Error('SecurityError')
      return values.has(key) ? (values.get(key) as string) : null
    },
    key(index: number): string | null {
      return [...values.keys()][index] ?? null
    },
    removeItem(key: string): void {
      values.delete(key)
    },
    setItem(key: string, value: string): void {
      if (options.throwOnWrite) throw new Error('QuotaExceededError')
      writes.push(key)
      values.set(key, value)
    },
  }
  return { storage, values, writes }
}

describe('工作流多选的会话级记忆（sessionStorage）', () => {
  it('键名带版本后缀，写入只碰这一个键（不混入 pb.reference_studio_v1）', () => {
    expect(WORKFLOW_SELECTION_SESSION_KEY).toBe(
      'pb.reference_studio_workflows_session_v1',
    )

    const { storage, values, writes } = memoryStorage()
    writeWorkflowSelectionSession(['/A.api.json', '/B.api.json'], storage)

    expect(writes).toEqual([WORKFLOW_SELECTION_SESSION_KEY])
    expect([...values.keys()]).toEqual([WORKFLOW_SELECTION_SESSION_KEY])
    expect([...values.keys()]).not.toContain('pb.reference_studio_v1')
    expect(JSON.parse(values.get(WORKFLOW_SELECTION_SESSION_KEY) as string)).toEqual({
      workflows: ['/A.api.json', '/B.api.json'],
    })
  })

  it('normalize 去首尾空白、丢弃空串与非字符串、保序去重', () => {
    expect(
      normalizeWorkflowSelectionPaths([
        '  /A.api.json  ',
        '',
        '   ',
        '/A.api.json',
        '/B.api.json',
        42,
        null,
        '/B.api.json',
      ]),
    ).toEqual(['/A.api.json', '/B.api.json'])
  })

  it('parse 容错：非法 JSON / 非对象 / workflows 非数组一律回落空数组', () => {
    expect(parseWorkflowSelectionSession(null)).toEqual([])
    expect(parseWorkflowSelectionSession('')).toEqual([])
    expect(parseWorkflowSelectionSession('   ')).toEqual([])
    expect(parseWorkflowSelectionSession('not-json')).toEqual([])
    expect(parseWorkflowSelectionSession('[]')).toEqual([])
    expect(parseWorkflowSelectionSession('"text"')).toEqual([])
    expect(parseWorkflowSelectionSession('null')).toEqual([])
    expect(parseWorkflowSelectionSession('{"workflows":"/A"}')).toEqual([])
    expect(parseWorkflowSelectionSession('{"workflows":null}')).toEqual([])
    // 结构正确时按同一口径归一（脏项忽略、重复项只留首次）
    expect(
      parseWorkflowSelectionSession(
        JSON.stringify({ workflows: [' /B.api.json ', '/A.api.json', '/B.api.json', 1] }),
      ),
    ).toEqual(['/B.api.json', '/A.api.json'])
  })

  it('write → read 往返；空选择写成 workflows: []（关闭标签页由浏览器清空）', () => {
    const { storage, values } = memoryStorage()

    writeWorkflowSelectionSession(['/B.api.json', '/A.api.json', '/B.api.json'], storage)
    expect(readWorkflowSelectionSession(storage)).toEqual(['/B.api.json', '/A.api.json'])

    writeWorkflowSelectionSession([], storage)
    expect(JSON.parse(values.get(WORKFLOW_SELECTION_SESSION_KEY) as string)).toEqual({
      workflows: [],
    })
    expect(readWorkflowSelectionSession(storage)).toEqual([])
  })

  it('存储不可用 / 读写抛错时静默降级，不阻塞页面', () => {
    expect(readWorkflowSelectionSession(null)).toEqual([])
    expect(() => writeWorkflowSelectionSession(['/A.api.json'], null)).not.toThrow()

    const broken = memoryStorage({ throwOnRead: true, throwOnWrite: true })
    expect(readWorkflowSelectionSession(broken.storage)).toEqual([])
    expect(() => writeWorkflowSelectionSession(['/A.api.json'], broken.storage)).not.toThrow()
    expect(broken.writes).toEqual([])
  })

  it('has：有效多选与「主动清空」都算存在；非法 JSON / 结构不符算不存在', () => {
    const { storage } = memoryStorage()
    expect(hasWorkflowSelectionSession(storage)).toBe(false)
    expect(hasWorkflowSelectionSession(null)).toBe(false)

    writeWorkflowSelectionSession(['/A.api.json'], storage)
    expect(hasWorkflowSelectionSession(storage)).toBe(true)

    // 用户本会话主动清空多选：也要算「存在」，否则刷新后会被 localStorage 单选回填。
    writeWorkflowSelectionSession([], storage)
    expect(hasWorkflowSelectionSession(storage)).toBe(true)

    storage.setItem(WORKFLOW_SELECTION_SESSION_KEY, 'not-json')
    expect(hasWorkflowSelectionSession(storage)).toBe(false)

    storage.setItem(WORKFLOW_SELECTION_SESSION_KEY, JSON.stringify({ workflows: '/A' }))
    expect(hasWorkflowSelectionSession(storage)).toBe(false)
  })

  it('恢复提示文案明确是「恢复 / 已跳过」，不写成用户刚取消', () => {
    const message = describeWorkflowSelectionRestoreNotice([
      '工作流「四输入」缺少服装输入，不适用于当前已选服装',
    ])

    expect(message).toContain('本次会话恢复')
    expect(message).toContain('已跳过')
    expect(message).toContain('原因：')
    expect(message).toContain('下一步：')
    expect(message).not.toContain('取消')
  })
})

describe('会话恢复的两级校验（目录存在性 + slots 三态）', () => {
  it('目录缺失静默丢弃；不适用项带原因；undefined 保留；结果保序', () => {
    const unknownSlots = workflow('/unknown-slots') // slots === undefined：不判定
    const uiFormat = workflow('/ui-format', { slots: [] }) // []：角色不可识别
    const portraitOnly = workflow('/portrait-only', { slots: ['portrait'] })
    const portraitAndCostume = workflow('/portrait-costume', {
      slots: ['portrait', 'costume'],
    })

    // 会话恢复出来的顺序：先是一条目录里已删除的路径，再是各类三态样本。
    const restored = [
      '/deleted',
      '/unknown-slots',
      '/ui-format',
      '/portrait-only',
      '/portrait-costume',
    ]
    const result = pruneInapplicableWorkflowSelection(
      restored,
      [unknownSlots, uiFormat, portraitOnly, portraitAndCostume],
      ['portrait', 'costume'],
    )

    // 目录缺失项只有空原因（调用方静默，不 toast）；其余保留或给出原因。
    expect(result.removed.filter((item) => !item.reason)).toEqual([
      { path: '/deleted', reason: '' },
    ])
    expect(result.kept).toEqual(['/unknown-slots', '/portrait-costume'])
    expect(result.removed.filter((item) => item.reason)).toEqual([
      expect.objectContaining({
        path: '/ui-format',
        reason: expect.stringContaining('无法识别角色'),
      }),
      expect.objectContaining({
        path: '/portrait-only',
        reason: expect.stringContaining('缺少服装输入'),
      }),
    ])
  })

  it('槽位全空时恢复的多选不因适用性被丢弃（三态判定只在有非空槽位时生效）', () => {
    const uiFormat = workflow('/ui-format', { slots: [] })
    const restored = ['/deleted', '/ui-format']
    const result = pruneInapplicableWorkflowSelection(restored, [uiFormat], [])

    expect(result.kept).toEqual(['/ui-format'])
    // 目录缺失仍然剔除（静默），但「不可识别」在无槽位时不做判定。
    expect(result.removed).toEqual([{ path: '/deleted', reason: '' }])
  })
})

describe('useReferenceRecipe 的会话恢复入口', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  afterEach(() => {
    sessionStorage.clear()
  })

  /**
   * 在真实组件 setup 中运行 composable。
   *
   * composable 内部注册了 `onBeforeUnmount`，直接在测试体调用会触发
   * 「no active component instance」告警；这里挂载 / 卸载一个空组件，
   * 让生命周期与页面一致。
   */
  function runWithRecipe<T>(fn: (recipe: ReturnType<typeof useReferenceRecipe>) => T): T {
    let result!: T
    const wrapper = mount(
      defineComponent({
        setup() {
          result = fn(useReferenceRecipe())
          return () => h('div')
        },
      }),
    )
    wrapper.unmount()
    return result
  }

  it('workflowSelection 初始化从 sessionStorage 读取（去重保序）', () => {
    sessionStorage.setItem(
      WORKFLOW_SELECTION_SESSION_KEY,
      JSON.stringify({ workflows: ['/B.api.json', ' /A.api.json ', '/B.api.json'] }),
    )

    const selection = runWithRecipe((recipe) => recipe.workflowSelection.value)
    expect(selection).toEqual(['/B.api.json', '/A.api.json'])
  })

  it('恢复期间 localStorage 的单选回填（workflowPath）不覆盖多选', () => {
    sessionStorage.setItem(
      WORKFLOW_SELECTION_SESSION_KEY,
      JSON.stringify({ workflows: ['/A.api.json', '/B.api.json'] }),
    )

    const selection = runWithRecipe((recipe) => {
      // 页面 setup 会用 pb.reference_studio_v1.workflow（首条）回填 workflowPath。
      recipe.workflowPath.value = '/A.api.json'
      return recipe.workflowSelection.value
    })

    expect(selection).toEqual(['/A.api.json', '/B.api.json'])
  })

  it('本会话主动清空多选后刷新：保持空选择，不被单选回填成一条', () => {
    sessionStorage.setItem(
      WORKFLOW_SELECTION_SESSION_KEY,
      JSON.stringify({ workflows: [] }),
    )

    const selection = runWithRecipe((recipe) => {
      recipe.workflowPath.value = '/A.api.json'
      return recipe.workflowSelection.value
    })

    expect(selection).toEqual([])
  })
})
