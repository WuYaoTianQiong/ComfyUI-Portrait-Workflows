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
  NO_IMAGE_SLOT_HINT,
  POSE_TEXT_PAIR_CONFLICT_HINT,
  TEXT_MODE_FRAGMENT_REQUIRED_HINT,
  createEmptyPersonBVariant,
  createEmptyRecipeTextFragments,
  describeAlternateModeConflicts,
} from './recipeTextFragments'
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
  resolveExtraKindConflict,
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
  RecipeTextFragments,
  StudioWorkflowOption,
} from './useReferenceRecipe'
import { useReferenceRecipeDraft } from './useReferenceRecipeDraft'
import { useReferenceSafeMode } from './useReferenceSafeMode'

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

  it('V2-C 第 5 槽只带 1 个人物B服装来源，路径优先', () => {
    const fromLibrary = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      {
        style: 'realistic',
        promptSuffix: '',
        extraPath: '',
        extraCostumeId: 'char-costume-HAN-006',
        extraCostumeLibrary: 'costume',
      },
    )
    expect(fromLibrary.extra_costume_id).toBe('char-costume-HAN-006')
    expect(fromLibrary.extra_costume_library).toBe('costume')
    expect(fromLibrary.extra_costume_path).toBeUndefined()

    const both = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      {
        style: 'realistic',
        promptSuffix: '',
        extraPath: '',
        extraCostumePath: 'F:/lib/uploads/b-costume.png',
        extraCostumeId: 'char-costume-HAN-006',
        extraCostumeLibrary: 'costume',
      },
    )
    expect(both.extra_costume_path).toBe('F:/lib/uploads/b-costume.png')
    expect(both.extra_costume_id).toBeUndefined()
    expect(both.extra_costume_library).toBeUndefined()

    const blank = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      { style: 'realistic', promptSuffix: '', extraPath: '' },
    )
    expect('extra_costume_id' in blank).toBe(false)
    expect('extra_costume_path' in blank).toBe(false)
  })

  it('第 4 张可改走发型库条目（extra_id + extra_library），路径优先', () => {
    const fromLibrary = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      {
        style: 'realistic',
        promptSuffix: '',
        extraPath: '',
        extraId: 'char-hair-082',
        extraLibrary: 'hair',
      },
    )
    expect(fromLibrary.extra_id).toBe('char-hair-082')
    expect(fromLibrary.extra_library).toBe('hair')
    expect(fromLibrary.extra_path).toBeUndefined()

    const both = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      {
        style: 'realistic',
        promptSuffix: '',
        extraPath: 'F:/lib/uploads/abc.png',
        extraId: 'char-hair-082',
        extraLibrary: 'hair',
      },
    )
    expect(both.extra_path).toBe('F:/lib/uploads/abc.png')
    expect(both.extra_id).toBeUndefined()
    expect(both.extra_library).toBeUndefined()
  })

  it('第 4 槽文字补充只随图片发送，手动改写不发送', () => {
    const withImage = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      {
        style: 'realistic',
        promptSuffix: '',
        extraPath: 'F:/lib/uploads/hair.png',
        extraText: '  发尾浅金色挑染  ',
      },
    )
    expect(withImage.extra_text).toBe('发尾浅金色挑染')

    const noImage = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      { style: 'realistic', promptSuffix: '', extraPath: '', extraText: '发尾浅金色挑染' },
    )
    expect('extra_text' in noImage).toBe(false)

    const manual = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      {
        style: 'realistic',
        promptSuffix: '',
        extraPath: 'F:/lib/uploads/hair.png',
        extraText: '发尾浅金色挑染',
        promptOverride: '手动改写后的提示词',
      },
    )
    expect(manual.prompt_override).toBe('手动改写后的提示词')
    expect('extra_text' in manual).toBe(false)
  })

  it('双人姿势的 B 文字设定写入 person_b_text，空串不发送', () => {
    const withB = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      {
        style: 'realistic',
        promptSuffix: '',
        extraPath: '',
        personBText: '金色齐肩短发，酒红色西装外套',
      },
    )
    expect(withB.person_b_text).toBe('金色齐肩短发，酒红色西装外套')

    const blank = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      { style: 'realistic', promptSuffix: '', extraPath: '', personBText: '   ' },
    )
    expect('person_b_text' in blank).toBe(false)
  })

  it('v1.5：B 变体拆成面/身、服饰、自由文字三个字段发送', () => {
    const request = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      {
        style: 'realistic',
        promptSuffix: '',
        extraPath: '',
        personBVariant: {
          ...createEmptyPersonBVariant('b-1'),
          fragments: {
            ...createEmptyRecipeTextFragments(),
            人物面部: [{ type: '人物面部', content: '鹅蛋脸', person: 'B' }],
            人物身材: [{ type: '人物身材', content: '高挑', person: 'B' }],
            人物服饰: [{ type: '人物服饰', content: '酒红西装', person: 'B' }],
          },
          freeText: '年龄与人物 A 相近',
        },
      },
    )

    expect(request.person_b_portrait_text).toBe('鹅蛋脸；高挑')
    expect(request.person_b_costume_text).toBe('酒红西装')
    expect(request.person_b_text).toBe('年龄与人物 A 相近')
    // A 的三槽字段不能被 B 碎片污染
    expect(request.portrait_text).toBeUndefined()
    expect(request.costume_text).toBeUndefined()
  })

  it('八类碎片按归属映射到 4 个文本字段（同类以「；」连接）', () => {
    const fragments: RecipeTextFragments = {
      ...createEmptyRecipeTextFragments(),
      人物面部: [
        { type: '人物面部', content: '黑色短发' },
        { type: '人物面部', content: '圆脸' },
      ],
      人物身材: [{ type: '人物身材', content: '身形纤细' }],
      人物服饰: [{ type: '人物服饰', content: '白色衬衫' }],
      姿态动作: [{ type: '姿态动作', content: '自然站立' }],
      拍摄视角: [{ type: '拍摄视角', content: '低角度仰拍' }],
      场景环境: [{ type: '场景环境', content: '黄昏街道' }],
      光影色调: [{ type: '光影色调', content: '暖色侧光' }],
      画风技术: [{ type: '画风技术', content: '胶片质感' }],
    }

    const request = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      {
        style: 'realistic',
        promptSuffix: '',
        extraPath: '',
        textFragments: fragments,
        // P4：image 模式 + 文本默认不发；本用例验证完整映射，显式打开三槽补充。
        supplementFlags: { portrait: true, costume: true, pose: true },
        negativePrompt: '  低质量，多余手指  ',
      },
    )

    expect(request.portrait_text).toBe('黑色短发；圆脸；身形纤细')
    expect(request.costume_text).toBe('白色衬衫')
    expect(request.pose_text).toBe('自然站立')
    expect(request.portrait_supplement).toBe(true)
    expect(request.costume_supplement).toBe(true)
    expect(request.pose_supplement).toBe(true)
    expect(request.modifier_fragments).toBe(
      [
        '• 拍摄视角：低角度仰拍',
        '• 场景环境：黄昏街道',
        '• 光影色调：暖色侧光',
        '• 画风技术：胶片质感',
      ].join('\n'),
    )
    expect(request.negative_prompt).toBe('低质量，多余手指')
  })

  it('选「画风技术」碎片时 style 强制 none；未选时保留原画风', () => {
    const base: RecipeTextFragments = {
      ...createEmptyRecipeTextFragments(),
      人物服饰: [{ type: '人物服饰', content: '白色衬衫' }],
    }

    const locked = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      {
        style: 'realistic',
        promptSuffix: '',
        extraPath: '',
        textFragments: {
          ...base,
          画风技术: [{ type: '画风技术', content: '胶片质感' }],
        },
      },
    )
    expect(locked.style).toBe('none')

    const unlocked = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      { style: 'realistic', promptSuffix: '', extraPath: '', textFragments: base },
    )
    expect(unlocked.style).toBe('realistic')
  })

  it('文本 / 负向为空时不发送对应字段', () => {
    const blanks: RecipeTextFragments = {
      ...createEmptyRecipeTextFragments(),
      人物面部: [{ type: '人物面部', content: '   ' }],
      场景环境: [{ type: '场景环境', content: '' }],
    }

    const request = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      {
        style: 'realistic',
        promptSuffix: '',
        extraPath: '',
        textFragments: blanks,
        negativePrompt: '   ',
      },
    )

    expect('portrait_text' in request).toBe(false)
    expect('costume_text' in request).toBe(false)
    expect('pose_text' in request).toBe(false)
    expect('modifier_fragments' in request).toBe(false)
    expect('negative_prompt' in request).toBe(false)

    // 完全不传 textFragments 时同样不带这些字段（旧调用方行为不变）
    const legacy = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      { style: 'realistic', promptSuffix: '', extraPath: '' },
    )
    expect('portrait_text' in legacy).toBe(false)
    expect('negative_prompt' in legacy).toBe(false)
  })

  it('P2 text 模式：只发对应槽文本，不发该槽 id / path', () => {
    const fragments: RecipeTextFragments = {
      ...createEmptyRecipeTextFragments(),
      人物服饰: [{ type: '人物服饰', content: '白色衬衫' }],
      姿态动作: [{ type: '姿态动作', content: '自然站立' }],
    }

    const request = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      {
        style: 'realistic',
        promptSuffix: '',
        extraPath: '',
        textFragments: fragments,
        slotModes: { portrait: 'image', costume: 'text', pose: 'text' },
      },
    )

    expect(request.portrait_id).toBe('portrait-1')
    expect('costume_id' in request).toBe(false)
    expect('costume_path' in request).toBe(false)
    expect('pose_id' in request).toBe(false)
    expect('pose_path' in request).toBe(false)
    expect(request.costume_text).toBe('白色衬衫')
    expect(request.pose_text).toBe('自然站立')
  })

  it('P2 image 模式 + 碎片 = 补充：图文同时发送', () => {
    const fragments: RecipeTextFragments = {
      ...createEmptyRecipeTextFragments(),
      人物面部: [{ type: '人物面部', content: '圆脸' }],
    }

    const request = buildRecipeRequest(
      { portrait: portrait(), costume: null, pose: null },
      {
        style: 'realistic',
        promptSuffix: '',
        extraPath: '',
        textFragments: fragments,
        slotModes: { portrait: 'image', costume: 'empty', pose: 'empty' },
        // P4：image + 文本必须显式打开补充才发送，并带对应 *_supplement=true。
        supplementFlags: { portrait: true, costume: false, pose: false },
      },
    )

    expect(request.portrait_id).toBe('portrait-1')
    expect(request.portrait_text).toBe('圆脸')
    expect(request.portrait_supplement).toBe(true)
  })

  it('P4 image 模式 + 碎片 + 补充关闭：只发图片，不发文本', () => {
    const request = buildRecipeRequest(
      { portrait: portrait(), costume: null, pose: null },
      {
        style: 'realistic',
        promptSuffix: '',
        extraPath: '',
        textFragments: {
          ...createEmptyRecipeTextFragments(),
          人物面部: [{ type: '人物面部', content: '圆脸' }],
        },
        slotModes: { portrait: 'image', costume: 'empty', pose: 'empty' },
      },
    )

    expect(request.portrait_id).toBe('portrait-1')
    expect('portrait_text' in request).toBe(false)
    expect('portrait_supplement' in request).toBe(false)
  })

  it('P2 服装 text 模式：body_mode 仍为 costume（即使调用方传 bare）', () => {
    const request = buildRecipeRequest(
      { portrait: portrait(), costume: null, pose: null },
      {
        style: 'realistic',
        promptSuffix: '',
        extraPath: '',
        bodyMode: 'bare',
        textFragments: {
          ...createEmptyRecipeTextFragments(),
          人物服饰: [{ type: '人物服饰', content: '白色衬衫' }],
        },
        slotModes: { portrait: 'image', costume: 'text', pose: 'empty' },
      },
    )

    expect(request.body_mode).toBe('costume')
    expect(request.costume_text).toBe('白色衬衫')
    expect('costume_id' in request).toBe(false)
  })
})

describe('P2 替代态校验（至少 1 图 / 文本模式 / 素体 / 双人）', () => {
  const imageModes = {
    portrait: 'image',
    costume: 'image',
    pose: 'image',
  } as const

  it('P1 旧规则已移除：某槽无图但有文本不再阻止（image 模式 + 碎片 = 补充）', () => {
    const fragments: RecipeTextFragments = {
      ...createEmptyRecipeTextFragments(),
      人物面部: [{ type: '人物面部', content: '圆脸' }],
    }
    expect(
      describeAlternateModeConflicts({
        modes: imageModes,
        fragments,
        imageCounts: { portrait: 1, costume: 1, pose: 1 },
      }),
    ).toBe('')
  })

  it('三槽都没有图片槽 → 至少保留 1 张参考图（文本不计入）', () => {
    expect(
      describeAlternateModeConflicts({
        modes: { portrait: 'text', costume: 'text', pose: 'text' },
        fragments: {
          ...createEmptyRecipeTextFragments(),
          人物面部: [{ type: '人物面部', content: '圆脸' }],
        },
        imageCounts: { portrait: 0, costume: 0, pose: 0 },
      }),
    ).toBe(NO_IMAGE_SLOT_HINT)
  })

  it('text 模式但对应类碎片为空 → 逐槽返回「文本模式需要至少选择 1 条碎片」', () => {
    const empty = createEmptyRecipeTextFragments()

    expect(
      describeAlternateModeConflicts({
        modes: { portrait: 'text', costume: 'image', pose: 'image' },
        fragments: empty,
        imageCounts: { portrait: 0, costume: 1, pose: 1 },
      }),
    ).toBe(`人像槽：${TEXT_MODE_FRAGMENT_REQUIRED_HINT}`)

    expect(
      describeAlternateModeConflicts({
        modes: { portrait: 'image', costume: 'text', pose: 'image' },
        fragments: empty,
        imageCounts: { portrait: 1, costume: 0, pose: 1 },
      }),
    ).toBe(`服装槽：${TEXT_MODE_FRAGMENT_REQUIRED_HINT}`)

    expect(
      describeAlternateModeConflicts({
        modes: { portrait: 'image', costume: 'image', pose: 'text' },
        fragments: empty,
        imageCounts: { portrait: 1, costume: 1, pose: 0 },
      }),
    ).toBe(`姿势槽：${TEXT_MODE_FRAGMENT_REQUIRED_HINT}`)
  })

  it('text 模式有对应碎片时通过', () => {
    expect(
      describeAlternateModeConflicts({
        modes: { portrait: 'image', costume: 'text', pose: 'image' },
        fragments: {
          ...createEmptyRecipeTextFragments(),
          人物服饰: [{ type: '人物服饰', content: '白色衬衫' }],
        },
        imageCounts: { portrait: 1, costume: 0, pose: 1 },
      }),
    ).toBe('')
  })

  it('素体展示 + 服装文本 → 阻止', () => {
    expect(
      describeAlternateModeConflicts({
        modes: { portrait: 'image', costume: 'text', pose: 'image' },
        fragments: {
          ...createEmptyRecipeTextFragments(),
          人物服饰: [{ type: '人物服饰', content: '白色衬衫' }],
        },
        imageCounts: { portrait: 1, costume: 0, pose: 1 },
        bodyMode: 'bare',
      }),
    ).toContain('素体展示与服装文本冲突')

    // 即使服装槽不是 text 模式，只要残留碎片非空也会进入提交体（文本始终按映射发送）。
    expect(
      describeAlternateModeConflicts({
        modes: { portrait: 'image', costume: 'empty', pose: 'image' },
        fragments: {
          ...createEmptyRecipeTextFragments(),
          人物服饰: [{ type: '人物服饰', content: '白色衬衫' }],
        },
        imageCounts: { portrait: 1, costume: 0, pose: 1 },
        bodyMode: 'bare',
      }),
    ).toContain('素体展示与服装文本冲突')
  })

  it('姿势文本 + 当前 / 上次是 pair 双人姿势 → 阻止', () => {
    expect(
      describeAlternateModeConflicts({
        modes: { portrait: 'image', costume: 'image', pose: 'text' },
        fragments: {
          ...createEmptyRecipeTextFragments(),
          姿态动作: [{ type: '姿态动作', content: '自然站立' }],
        },
        imageCounts: { portrait: 1, costume: 1, pose: 0 },
        poseId: 'pair-01',
      }),
    ).toBe(POSE_TEXT_PAIR_CONFLICT_HINT)

    expect(
      describeAlternateModeConflicts({
        modes: { portrait: 'image', costume: 'image', pose: 'text' },
        fragments: {
          ...createEmptyRecipeTextFragments(),
          姿态动作: [{ type: '姿态动作', content: '自然站立' }],
        },
        imageCounts: { portrait: 1, costume: 1, pose: 0 },
        poseId: 'single-01',
      }),
    ).toBe('')
  })

  it('第 4 张上传图也算 1 张参考图', () => {
    expect(
      describeAlternateModeConflicts({
        modes: { portrait: 'text', costume: 'empty', pose: 'empty' },
        fragments: {
          ...createEmptyRecipeTextFragments(),
          人物面部: [{ type: '人物面部', content: '圆脸' }],
        },
        imageCounts: { portrait: 0, costume: 0, pose: 0 },
        extraFilled: true,
      }),
    ).toBe('')
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
    expect(urls[1]).toBe('/api/media/image?filename=b.png&type=temp')
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
// dry-run 预览的最终负向（方案 §11.3：预览必须显示最终正向 + 最终负向）
// ---------------------------------------------------------------------------

describe('dry-run 预览的最终负向', () => {
  /**
   * 在真实组件 setup 中运行 composable（内部注册 `onBeforeUnmount`，
   * 直接调用会触发 no active component instance 告警）。
   */
  async function runRecipeAsync<T>(
    fn: (recipe: ReturnType<typeof useReferenceRecipe>) => Promise<T>,
  ): Promise<T> {
    let pending!: Promise<T>
    const wrapper = mount(
      defineComponent({
        setup() {
          pending = fn(useReferenceRecipe())
          return () => h('div')
        },
      }),
    )
    try {
      return await pending
    } finally {
      wrapper.unmount()
    }
  }

  /** 一次 dry-run 请求的固定响应；`body` 用来控制返回字段。 */
  function stubPreviewResponse(body: Record<string, unknown>): void {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({ success: true, dry_run: true, ...body }),
      })),
    )
  }

  async function readPreviewState() {
    return runRecipeAsync(async (recipe) => {
      await recipe.refreshPreviewPrompt()
      return {
        prompt: recipe.previewPrompt.value,
        negative: recipe.previewNegativePrompt.value,
        effective: recipe.previewNegativeEffective.value,
      }
    })
  }

  it('响应带 negative_prompt / negative_effective 时写入预览 refs', async () => {
    stubPreviewResponse({
      prompt: '编译后的最终正向',
      negative_prompt: '低质量，文字水印',
      negative_effective: true,
      prompt_raw: '编译前的原始正向',
    })

    await expect(readPreviewState()).resolves.toEqual({
      prompt: '编译后的最终正向',
      negative: '低质量，文字水印',
      effective: true,
    })
  })

  it('响应缺 negative_* 字段时按空 / null（旧后端不臆测生效态）', async () => {
    stubPreviewResponse({ prompt: '只有正向' })

    await expect(readPreviewState()).resolves.toEqual({
      prompt: '只有正向',
      negative: '',
      effective: null,
    })
  })

  it('negative_effective=false 原样保留（不能被 || 吞成 null）', async () => {
    stubPreviewResponse({
      prompt: '正向',
      negative_prompt: '',
      negative_effective: false,
    })

    await expect(readPreviewState()).resolves.toEqual({
      prompt: '正向',
      negative: '',
      effective: false,
    })
  })

  it('预览失败时同时清空最终负向（不残留上一次结果）', async () => {
    stubPreviewResponse({ prompt: '上一次正向', negative_prompt: '上一次负向', negative_effective: true })
    await readPreviewState()

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 400,
        json: async () => ({ detail: '请至少选择一个参考图或上传一张参考图' }),
      })),
    )

    const state = await readPreviewState()
    expect(state.prompt).toBe('')
    expect(state.negative).toBe('')
    expect(state.effective).toBeNull()
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

describe('第 4 槽语义互斥（v2-A 收尾）', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  afterEach(() => {
    sessionStorage.clear()
  })

  it('同时选中 person_b 与 hair 时只保留最新一条，并复用 workflowSelectionNotice 提示', () => {
    const personB = workflow('/person-b', { extraKind: 'person_b' })
    const hair = workflow('/hair', { extraKind: 'hair' })
    const plain = workflow('/plain')

    // 纯函数：勾选总追加到末尾，末尾即最新。
    expect(
      resolveExtraKindConflict(['/plain', '/hair', '/person-b'], [personB, hair, plain]),
    ).toEqual({
      kind: 'person_b',
      kept: ['/plain', '/person-b'],
      removed: ['/hair'],
    })
    expect(resolveExtraKindConflict(['/person-b', '/hair'], [personB, hair])).toEqual({
      kind: 'hair',
      kept: ['/hair'],
      removed: ['/person-b'],
    })
    // 只有一种语义 / 目录未加载：不处理。
    expect(resolveExtraKindConflict(['/hair'], [hair])).toEqual({
      kind: null,
      kept: ['/hair'],
      removed: [],
    })
    expect(resolveExtraKindConflict(['/person-b', '/hair'], [])).toEqual({
      kind: null,
      kept: ['/person-b', '/hair'],
      removed: [],
    })

    // 组合入口：watch 必须真的收敛选择并写入既有提示通道。
    let result!: { selection: string[]; notice: string }
    const wrapper = mount(
      defineComponent({
        setup() {
          const recipe = useReferenceRecipe()
          recipe.workflows.value = [personB, hair]
          recipe.workflowSelection.value = ['/hair']
          recipe.workflowSelection.value = ['/hair', '/person-b']
          result = {
            selection: [...recipe.workflowSelection.value],
            notice: recipe.workflowSelectionNotice.value,
          }
          return () => h('div')
        },
      }),
    )
    wrapper.unmount()

    expect(result.selection).toEqual(['/person-b'])
    expect(result.notice).toContain('原因：第 4 槽不能同时用作')
    expect(result.notice).toContain('只保留最新选择的「人物B身份参考」')
    expect(result.notice).toContain('下一步：')
  })
})

describe('素体展示保留服装选择（2026-11-08）', () => {
  it('bare 不再清空服装槽，但服装不计入提交（计数 / 槽位名归零）', () => {
    const draft = useReferenceRecipeDraft()
    draft.clearDraft()
    draft.setCostume(costume())
    draft.setPersonBEnabled(true)
    draft.addPersonBCostume(costume({ id: 'b-costume' }))
    draft.setExtraCostumeLibrary('costume', 'legacy-costume', '旧 B 服装')

    let recipe!: ReturnType<typeof useReferenceRecipe>
    const wrapper = mount(
      defineComponent({
        setup() {
          recipe = useReferenceRecipe()
          return () => h('div')
        },
      }),
    )

    recipe.setBodyMode('bare')
    expect(recipe.bodyMode.value).toBe('bare')
    // 选择保留：关闭素体后无需重新挑一遍
    expect(draft.costume.value).toHaveLength(1)
    expect(draft.personBCostume.value).toHaveLength(1)
    expect(draft.extraCostume.value.source).not.toBe('empty')
    // 提交层裁掉：服装槽按 0 计，不进入「非空槽位」
    expect(recipe.slotCounts.value.costume).toBe(0)
    expect(recipe.filledSlotNames.value).not.toContain('服装')
    expect(recipe.filledSlotNames.value).not.toContain('人物B服装')

    // 关闭素体后自动恢复提交
    recipe.setBodyMode('costume')
    expect(recipe.slotCounts.value.costume).toBe(1)
    expect(recipe.filledSlotNames.value).toContain('服装')

    wrapper.unmount()
    draft.clearDraft()
  })

  it('素体模式保留的服装选择不进入提交体（costume_id / extra_costume_id 都不发）', () => {
    const bare = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      {
        style: 'realistic',
        promptSuffix: '',
        extraPath: '',
        bodyMode: 'bare',
        extraCostumeId: 'b-costume',
        extraCostumeLibrary: 'costume',
      },
    )
    expect('costume_id' in bare).toBe(false)
    expect('extra_costume_id' in bare).toBe(false)
    expect('extra_costume_path' in bare).toBe(false)

    const normal = buildRecipeRequest(
      { portrait: portrait(), costume: costume(), pose: pose() },
      {
        style: 'realistic',
        promptSuffix: '',
        extraPath: '',
        bodyMode: 'costume',
        extraCostumeId: 'b-costume',
        extraCostumeLibrary: 'costume',
      },
    )
    expect(normal.costume_id).toBe('costume-1')
    expect(normal.extra_costume_id).toBe('b-costume')
  })
})

describe('成人向 adult_mode（2026-11-08）', () => {
  it('buildRecipeRequest 只在 adultMode=true 时发送 adult_mode', () => {
    const base = { style: 'realistic' as const, promptSuffix: '', extraPath: '' }
    const safe = buildRecipeRequest(
      { portrait: portrait(), costume: null, pose: null },
      base,
    )
    expect('adult_mode' in safe).toBe(false)

    const adult = buildRecipeRequest(
      { portrait: portrait(), costume: null, pose: null },
      { ...base, adultMode: true },
    )
    expect(adult.adult_mode).toBe(true)
  })

  it('预览按 18+ 安全模式下发 adult_mode（预览与提交同口径）', async () => {
    const { safeMode } = useReferenceSafeMode()
    const bodies: Array<Record<string, unknown>> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: unknown, init?: { body?: unknown }) => {
        bodies.push(JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>)
        return {
          ok: true,
          status: 200,
          json: async () => ({ success: true, dry_run: true, prompt: '正向' }),
        }
      }),
    )

    const runPreview = async (): Promise<void> => {
      let pending!: Promise<void>
      const wrapper = mount(
        defineComponent({
          setup() {
            const recipe = useReferenceRecipe()
            pending = recipe.refreshPreviewPrompt()
            return () => h('div')
          },
        }),
      )
      try {
        await pending
      } finally {
        wrapper.unmount()
      }
    }

    const previous = safeMode.value
    try {
      safeMode.value = true
      await runPreview()
      expect(bodies[0]?.adult_mode).toBeUndefined()

      safeMode.value = false
      await runPreview()
      expect(bodies[1]?.adult_mode).toBe(true)
    } finally {
      safeMode.value = previous
    }
  })
})
