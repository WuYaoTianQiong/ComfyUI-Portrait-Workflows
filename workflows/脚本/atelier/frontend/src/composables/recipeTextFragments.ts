/**
 * 合成台「文本补充」八类碎片的纯数据层（方案 §4.1 / §4.2 / §5.2 / §5.3 / §5.5）。
 *
 * 为什么单独成模块：
 * - `useReferenceRecipe`（提交体编译）、`useReferenceStudioSettings`（持久化校验）、
 *   `useReferenceRecipeDraft`（草稿单例）都要用同一份类型与空值口径；
 * - 若类型直接放在 `useReferenceRecipe`，settings / draft 运行时导入会形成
 *   `useReferenceRecipe → useReferenceRecipeDraft → useReferenceStudioSettings → useReferenceRecipe`
 *   的循环依赖。这里只依赖无副作用的 `constants`，谁都可以安全引用。
 *
 * 本模块**只做纯函数**：不读写 localStorage、不发请求、不持有响应式状态。
 */

import { FRAGMENT_TYPES } from '../constants'
import type { FragmentType } from '../constants'

/**
 * 碎片的人物归属（v1.5）。
 *
 * 只有三类人物碎片（人物面部 / 人物身材 / 人物服饰）区分 A / B；
 * 其余五类（姿态动作及画面修饰）恒为共享，不写 `person`。
 * 旧数据没有该字段 → 一律视为 A（向后兼容）。
 */
export type FragmentPerson = 'A' | 'B'

/** 一条已选碎片；`content` 存全文（最长 783 字）。 */
export interface SelectedFragment {
  type: FragmentType
  content: string
  /** 仅人物类碎片：A / B；缺省 = A（旧数据）。 */
  person?: FragmentPerson
}

/** 可区分 A/B 的三类人物碎片。 */
export const PERSON_FRAGMENT_TYPES: readonly FragmentType[] = [
  '人物面部',
  '人物身材',
  '人物服饰',
]

/** 该类型是否支持人物归属（其余类型共享）。 */
export function isPersonFragmentType(type: FragmentType): boolean {
  return PERSON_FRAGMENT_TYPES.includes(type)
}

/** 八类碎片表：所有类可空，同类多碎片在槽内拼接，不参与笛卡尔积。 */
export type RecipeTextFragments = Record<FragmentType, SelectedFragment[]>

/** 碎片归属：前四类对应参考槽，后四类只做画面修饰。 */
export type FragmentHome = 'portrait' | 'costume' | 'pose' | 'modifier'

/** 三个参考槽的键（与草稿 / 提交体一致）。 */
export type RecipeSlotKey = 'portrait' | 'costume' | 'pose'

/** 槽位选择顺序（UI / 组键 / 校验共用）。 */
export const RECIPE_SLOT_KEYS: readonly RecipeSlotKey[] = ['portrait', 'costume', 'pose']

/**
 * 槽位模式（方案 §4.4）：
 * - `image`：提交该槽的参考图（若同时有碎片，文本作为「补充」）；
 * - `text`：不提交图片，只提交该槽对应类碎片作为「替代」；
 * - `empty`：该槽不提交任何内容（对应类碎片为空且无图）。
 */
export type RecipeSlotMode = 'image' | 'text' | 'empty'

/** 三槽模式表。 */
export type RecipeSlotModes = Record<RecipeSlotKey, RecipeSlotMode>

/** 全空模式：新建草稿 / 清空草稿的默认值。 */
export const EMPTY_SLOT_MODES: Readonly<RecipeSlotModes> = {
  portrait: 'empty',
  costume: 'empty',
  pose: 'empty',
}

/** 全图片模式：旧数据 / 缺省参数的回退口径（与 P1 行为一致）。 */
export const IMAGE_SLOT_MODES: Readonly<RecipeSlotModes> = {
  portrait: 'image',
  costume: 'image',
  pose: 'image',
}

/**
 * 跨源补充开关（P4）：image 模式下是否把对应槽的文本追加为「此外需体现」。
 * 默认全关；随机整套默认关闭，手动模式按槽显式开启。
 */
export type RecipeSupplementFlags = Record<RecipeSlotKey, boolean>

export const EMPTY_SUPPLEMENT_FLAGS: Readonly<RecipeSupplementFlags> = {
  portrait: false,
  costume: false,
  pose: false,
}

/** 复制一份可写的补充开关表。 */
export function createEmptySupplementFlags(): RecipeSupplementFlags {
  return { ...EMPTY_SUPPLEMENT_FLAGS }
}

/** 容错归一：只认显式 true，其余一律 false。 */
export function cloneSupplementFlags(source: unknown): RecipeSupplementFlags {
  const result = createEmptySupplementFlags()
  if (!source || typeof source !== 'object' || Array.isArray(source)) return result
  const record = source as Record<string, unknown>
  for (const slot of RECIPE_SLOT_KEYS) {
    if (record[slot] === true) result[slot] = true
  }
  return result
}

/** 缺省 = 全关；旧调用方无需传该字段。 */
export function resolveSupplementFlags(
  flags: RecipeSupplementFlags | undefined,
): RecipeSupplementFlags {
  return flags ? cloneSupplementFlags(flags) : createEmptySupplementFlags()
}

/** 某槽文本本次是否真正生效：text 模式恒生效；image 模式只在开关打开时生效。 */
export function isSlotTextActive(
  slot: RecipeSlotKey,
  mode: RecipeSlotMode,
  supplements: RecipeSupplementFlags | undefined,
): boolean {
  if (mode === 'text') return true
  if (mode === 'image') return supplements?.[slot] === true
  return false
}

/** 每个槽对应的碎片类（人像槽由面部 + 身材两类组成）。 */
export const SLOT_TEXT_TYPES: Readonly<Record<RecipeSlotKey, readonly FragmentType[]>> = {
  portrait: ['人物面部', '人物身材'],
  costume: ['人物服饰'],
  pose: ['姿态动作'],
}

/** 文本槽 chip 的类型名（取该槽主类，与方案 §8 P2 的「文本 · 类型」一致）。 */
export const SLOT_TEXT_TYPE_LABELS: Readonly<Record<RecipeSlotKey, string>> = {
  portrait: '人物面部',
  costume: '人物服饰',
  pose: '姿态动作',
}

/** 槽位文本模式说明里的「X 类」文案。 */
export const SLOT_TEXT_TYPE_HINTS: Readonly<Record<RecipeSlotKey, string>> = {
  portrait: '人物面部 / 人物身材',
  costume: '人物服饰',
  pose: '姿态动作',
}

/** 文本模式但对应类碎片为空时的统一提示（需求 §8 P2 校验）。 */
export const TEXT_MODE_FRAGMENT_REQUIRED_HINT = '文本模式需要至少选择 1 条碎片'

/** 姿势文本与双人姿势冲突的提示原文（页面 / 提交两侧共用）。 */
export const POSE_TEXT_PAIR_CONFLICT_HINT = '姿势文本暂不支持双人，请先换单人姿势或保留姿势图'

/** 素体展示与服装文本冲突的提示原文。 */
export const BARE_COSTUME_TEXT_CONFLICT_HINT =
  '素体展示与服装文本冲突，请先切回服装模式或保留服装参考图'

/** 三槽都无图时的提示原文（文本不计入参考图）。 */
export const NO_IMAGE_SLOT_HINT =
  '至少保留 1 张参考图：文本不能替代全部参考图（三槽都无图时无法提交）'

/** 复制一份可写的空模式表（避免共享同一对象引用）。 */
export function createEmptySlotModes(): RecipeSlotModes {
  return { ...EMPTY_SLOT_MODES }
}

/** 复制一份全图片模式表。 */
export function createImageSlotModes(): RecipeSlotModes {
  return { ...IMAGE_SLOT_MODES }
}

/**
 * 槽位模式推导（方案 §4.4 的旧数据兼容口径）：
 * `items.length ? 'image' : (对应碎片非空 ? 'text' : 'empty')`。
 */
export function deriveSlotMode(
  itemsCount: number,
  fragments: readonly SelectedFragment[] | undefined,
): RecipeSlotMode {
  if (itemsCount > 0) return 'image'
  return (fragments?.length ?? 0) > 0 ? 'text' : 'empty'
}

/** 容器是否是合法模式值（持久化 / 快照校验用）。 */
export function isRecipeSlotMode(value: unknown): value is RecipeSlotMode {
  return value === 'image' || value === 'text' || value === 'empty'
}

/**
 * 模式表容错归一：非对象 / 非法值一律回退为 `empty`。
 *
 * 与碎片表同口径：坏字段不抛错、不把整份旧快照带崩。
 */
export function cloneSlotModes(source: unknown): RecipeSlotModes {
  const modes = createEmptySlotModes()
  if (!source || typeof source !== 'object' || Array.isArray(source)) return modes
  const record = source as Record<string, unknown>
  for (const slot of RECIPE_SLOT_KEYS) {
    const value = record[slot]
    if (isRecipeSlotMode(value)) modes[slot] = value
  }
  return modes
}

/** 缺省模式表回退为全图片（P1 / 旧调用方行为不变）。 */
export function resolveSlotModes(modes: RecipeSlotModes | undefined): RecipeSlotModes {
  return modes ? cloneSlotModes(modes) : createImageSlotModes()
}

/** 取某类中属于指定人物的碎片；旧数据缺 `person` 时按 A 处理。 */
export function fragmentsOfPerson(
  fragments: RecipeTextFragments | undefined,
  type: FragmentType,
  person: FragmentPerson,
): SelectedFragment[] {
  return fragmentsOf(fragments, type).filter(
    (item) => (item.person ?? 'A') === person,
  )
}

/**
 * 取某槽对应的全部碎片（人像槽 = 面部 + 身材）。
 *
 * 只统计 **A**：B 是独立文字设定，不占图片槽，也不参与槽位模式推导（v1.5）。
 */
export function slotFragmentItems(
  fragments: RecipeTextFragments | undefined,
  slot: RecipeSlotKey,
): SelectedFragment[] {
  return SLOT_TEXT_TYPES[slot].flatMap((type) =>
    fragmentsOfPerson(fragments, type, 'A'),
  )
}

/** 按「三槽条目数 + 八类碎片」推导整份模式表（旧快照缺 mode 时使用）。 */
export function deriveSlotModes(
  counts: Record<RecipeSlotKey, number>,
  fragments: RecipeTextFragments | undefined,
): RecipeSlotModes {
  const modes = createEmptySlotModes()
  for (const slot of RECIPE_SLOT_KEYS) {
    modes[slot] = deriveSlotMode(counts[slot], slotFragmentItems(fragments, slot))
  }
  return modes
}

/** 归属中文名；彩色标签文案（放在类型名之前）。 */
export const FRAGMENT_HOME_LABELS: Readonly<Record<FragmentHome, string>> = {
  portrait: '人像',
  costume: '服装',
  pose: '姿势',
  modifier: '修饰',
}

/** 每类碎片归属（与文档 §0.2 表格逐条一致）。 */
export const FRAGMENT_HOMES: Readonly<Record<FragmentType, FragmentHome>> = {
  人物面部: 'portrait',
  人物身材: 'portrait',
  人物服饰: 'costume',
  姿态动作: 'pose',
  拍摄视角: 'modifier',
  场景环境: 'modifier',
  光影色调: 'modifier',
  画风技术: 'modifier',
}

/** 左列「与参考槽对应」：人像槽两类、服装槽一类、姿势槽一类。 */
export const SLOT_FRAGMENT_TYPES: readonly FragmentType[] = [
  '人物面部',
  '人物身材',
  '人物服饰',
  '姿态动作',
]

/** 右列「画面修饰」：始终追加到提示词修饰层。 */
export const MODIFIER_FRAGMENT_TYPES: readonly FragmentType[] = [
  '拍摄视角',
  '场景环境',
  '光影色调',
  '画风技术',
]

/** 单类软上限（方案 §9：碎片最长 783 字，避免一条提示词被撑爆）。 */
export const MAX_FRAGMENTS_PER_TYPE = 2

/** 与后端 `modifier_fragments` 的行格式一致；`strip_headers` 前仅做人读标记。 */
const MODIFIER_LINE_PREFIX = '•'

/** 槽位中文名（校验 / UI 文案用）。 */
const SLOT_LABELS: Readonly<Record<RecipeSlotKey, string>> = {
  portrait: '人像',
  costume: '服装',
  pose: '姿势',
}

/** 结构化空表：八类各一个空数组，永不共享同一个数组引用。 */
export function createEmptyRecipeTextFragments(): RecipeTextFragments {
  return FRAGMENT_TYPES.reduce((acc, type) => {
    acc[type] = []
    return acc
  }, {} as RecipeTextFragments)
}

/**
 * 深拷贝 + 容错归一。
 *
 * - `undefined` / 非对象 → 空表（旧版本持久化没有该字段）；
 * - 单类不是数组 → 该类按空；
 * - 单条缺 `content` / 内容非字符串 → 丢弃；
 * - `type` 一律以所在键为准（不信任存储里的旧值）；
 * - 单类裁剪到上限，避免脏数据撑爆 UI。
 */
export function cloneRecipeTextFragments(
  source: unknown,
): RecipeTextFragments {
  const result = createEmptyRecipeTextFragments()
  if (!source || typeof source !== 'object' || Array.isArray(source)) return result

  const record = source as Record<string, unknown>
  for (const type of FRAGMENT_TYPES) {
    const raw = record[type]
    if (!Array.isArray(raw)) continue
    const entries: SelectedFragment[] = []
    for (const item of raw) {
      if (!item || typeof item !== 'object') continue
      const content = (item as { content?: unknown }).content
      if (typeof content !== 'string') continue
      const text = content.trim()
      if (!text) continue
      const entry: SelectedFragment = { type, content: text }
      // 只有人物类碎片保留 A/B 归属；旧数据缺字段按 A（不写入，保持体积不变）。
      if (isPersonFragmentType(type)) {
        const person = (item as { person?: unknown }).person
        if (person === 'A' || person === 'B') entry.person = person
      }
      entries.push(entry)
      if (entries.length >= MAX_FRAGMENTS_PER_TYPE) break
    }
    result[type] = entries
  }
  return result
}

/** 取某一类的已选列表；表缺字段时返回空数组（不抛错）。 */
export function fragmentsOf(
  fragments: RecipeTextFragments | undefined,
  type: FragmentType,
): SelectedFragment[] {
  const list = fragments?.[type]
  return Array.isArray(list) ? list : []
}

/** 八类已选碎片总条数（卡头徽标用）。 */
export function countTextFragments(fragments: RecipeTextFragments | undefined): number {
  return FRAGMENT_TYPES.reduce((total, type) => total + fragmentsOf(fragments, type).length, 0)
}

/** 某一类已选碎片的字数合计（每行 `n/2 条 · x 字`）。 */
export function countFragmentChars(fragments: readonly SelectedFragment[]): number {
  return fragments.reduce((total, item) => total + item.content.length, 0)
}

/** 同类多碎片以「；」连接；空项与纯空白项跳过；逐条去掉尾部句号避免「。；」。 */
function joinFragmentContents(fragments: readonly SelectedFragment[]): string {
  return fragments
    .map((item) => item.content.trim().replace(/。+$/, ''))
    .filter((content) => content.length > 0)
    .join('；')
}

/** 编译结果；空串表示该字段不发送（后端缺省走旧逻辑）。 */
export interface CompiledTextFragments {
  portraitText: string
  costumeText: string
  poseText: string
  modifierFragments: string
  /** v1.5：人物 B 的面部 + 身材（独立字段，不混入 A 的 portrait_text）。 */
  personBPortraitText: string
  /** v1.5：人物 B 的服饰（独立字段，不混入 A 的 costume_text）。 */
  personBCostumeText: string
}

/**
 * 按契约把八类碎片编译成提交体字段（方案 §4.2）：
 * - 人物面部 + 人物身材（A）→ `portrait_text`；
 * - 人物服饰（A）→ `costume_text`；
 * - 姿态动作 → `pose_text`；
 * - 拍摄视角 / 场景环境 / 光影色调 / 画风技术 → `modifier_fragments`
 *   （多行 `• 类型：内容`，同类多条各占一行）；
 * - v1.5：人物 B 的三类碎片 → `personBPortraitText` / `personBCostumeText`，
 *   与 A 完全隔离；旧数据缺 `person` 一律归 A。
 */
export function compileRecipeTextFragments(
  fragments: RecipeTextFragments | undefined,
): CompiledTextFragments {
  const portrait = [
    ...fragmentsOfPerson(fragments, '人物面部', 'A'),
    ...fragmentsOfPerson(fragments, '人物身材', 'A'),
  ]
  const personBPortrait = [
    ...fragmentsOfPerson(fragments, '人物面部', 'B'),
    ...fragmentsOfPerson(fragments, '人物身材', 'B'),
  ]

  const modifierLines: string[] = []
  for (const type of MODIFIER_FRAGMENT_TYPES) {
    for (const item of fragmentsOf(fragments, type)) {
      const content = item.content.trim()
      if (!content) continue
      modifierLines.push(`${MODIFIER_LINE_PREFIX} ${type}：${content}`)
    }
  }

  return {
    portraitText: joinFragmentContents(portrait),
    costumeText: joinFragmentContents(fragmentsOfPerson(fragments, '人物服饰', 'A')),
    poseText: joinFragmentContents(fragmentsOf(fragments, '姿态动作')),
    modifierFragments: modifierLines.join('\n'),
    personBPortraitText: joinFragmentContents(personBPortrait),
    personBCostumeText: joinFragmentContents(
      fragmentsOfPerson(fragments, '人物服饰', 'B'),
    ),
  }
}

/**
 * 人物 B 文字变体（v1.5）。
 *
 * 一组 B 专属碎片（面部 / 身材 / 服饰）+ 一段自由文字；批量生成时按序号与
 * A 人像 1:1 配对，避免 A × B 的笛卡尔积爆炸。
 */
export interface RecipePersonBVariant {
  id: string
  fragments: RecipeTextFragments
  freeText: string
  /** 2026-11-08：本变体绑定的 B 身份图（第 4 槽单图）。 */
  identity: RecipePersonBImage
  /** 2026-11-08：本变体绑定的 B 服装图（第 5 槽单图）。 */
  costume: RecipePersonBImage
}

/**
 * 人物B变体内绑定的单张图片。
 *
 * 与 `StoredReferenceExtraSlot` / `StoredReferenceCostumeSlot` 同构（少一个
 * text 字段），让「变体」在持久化里自包含，不依赖页面全局的第 4/5 槽。
 */
export interface RecipePersonBImage {
  source: 'empty' | 'library' | 'upload'
  library: string
  id: string
  path: string
  name: string
}

/** 空图片（未选）。 */
export function createEmptyPersonBImage(): RecipePersonBImage {
  return { source: 'empty', library: '', id: '', path: '', name: '' }
}

/** 单张图片容错归一；非法 / 缺字段按空处理。 */
export function clonePersonBImage(source: unknown): RecipePersonBImage {
  if (!source || typeof source !== 'object' || Array.isArray(source)) {
    return createEmptyPersonBImage()
  }
  const record = source as Record<string, unknown>
  const kind =
    record.source === 'library' || record.source === 'upload' ? record.source : 'empty'
  if (kind === 'empty') return createEmptyPersonBImage()
  const text = (value: unknown): string => (typeof value === 'string' ? value : '')
  return {
    source: kind,
    library: text(record.library),
    id: text(record.id),
    path: text(record.path),
    name: text(record.name),
  }
}

/** 变体数量软上限：超过后批量配对产物过多，UI 直接禁止新增。 */
export const MAX_PERSON_B_VARIANTS = 8

/** 新建一个空变体（只清空三类人物碎片，其余类不使用但保持结构完整）。 */
export function createEmptyPersonBVariant(id: string): RecipePersonBVariant {
  return {
    id,
    fragments: createEmptyRecipeTextFragments(),
    freeText: '',
    identity: createEmptyPersonBImage(),
    costume: createEmptyPersonBImage(),
  }
}

/** 变体只描述 B 的人物特征：保留三类人物碎片，强制 person='B'，其余类清空。 */
function normalizeVariantFragments(source: unknown): RecipeTextFragments {
  const fragments = cloneRecipeTextFragments(source)
  for (const type of FRAGMENT_TYPES) {
    if (isPersonFragmentType(type)) {
      fragments[type] = fragments[type].map((item) => ({ ...item, person: 'B' as const }))
    } else {
      fragments[type] = []
    }
  }
  return fragments
}

/** 单条变体容错归一；脏数据返回 null。 */
export function clonePersonBVariant(
  source: unknown,
  index = 0,
): RecipePersonBVariant | null {
  if (!source || typeof source !== 'object' || Array.isArray(source)) return null
  const record = source as {
    id?: unknown
    fragments?: unknown
    freeText?: unknown
    identity?: unknown
    costume?: unknown
  }
  const id =
    typeof record.id === 'string' && record.id.trim()
      ? record.id.trim()
      : `b-${index + 1}`
  return {
    id,
    fragments: normalizeVariantFragments(record.fragments),
    freeText: typeof record.freeText === 'string' ? record.freeText : '',
    identity: clonePersonBImage(record.identity),
    costume: clonePersonBImage(record.costume),
  }
}

/**
 * 变体表容错归一：非法项丢弃、id 重复时用序号补全、总数裁剪到上限。
 *
 * 旧快照没有该字段 → 空数组；迁移由 `useReferenceRecipeDraft` 负责
 * （把旧的 `personBText` 放进第一条变体的自由文字）。
 */
export function clonePersonBVariants(source: unknown): RecipePersonBVariant[] {
  if (!Array.isArray(source) || source.length === 0) return []
  const seen = new Set<string>()
  const variants: RecipePersonBVariant[] = []
  for (let index = 0; index < source.length; index += 1) {
    const variant = clonePersonBVariant(source[index], index)
    if (!variant) continue
    const id = seen.has(variant.id) ? `${variant.id}-${index + 1}` : variant.id
    seen.add(id)
    variants.push({ ...variant, id })
    if (variants.length >= MAX_PERSON_B_VARIANTS) break
  }
  return variants
}

/** 变体编译结果；空串表示该字段不发送。 */
export interface CompiledPersonBVariant {
  portraitText: string
  costumeText: string
  freeText: string
}

/** 编译一个 B 变体（只取 B 的三类人物碎片 + 自由文字）。 */
export function compilePersonBVariant(
  variant: RecipePersonBVariant | null | undefined,
): CompiledPersonBVariant {
  if (!variant) return { portraitText: '', costumeText: '', freeText: '' }
  const compiled = compileRecipeTextFragments(variant.fragments)
  return {
    portraitText: compiled.personBPortraitText,
    costumeText: compiled.personBCostumeText,
    freeText: variant.freeText.trim(),
  }
}

/** 是否选了「画风技术」碎片（选中即与画风预设互斥，方案 §5.4）。 */
export function hasStyleFragment(fragments: RecipeTextFragments | undefined): boolean {
  return fragmentsOf(fragments, '画风技术').length > 0
}

/** 三槽的编译后文本（提交体 / 矩阵 / 组键共用）。 */
export interface RecipeSlotTexts {
  portrait: string
  costume: string
  pose: string
}

/** 空文本表。 */
export const EMPTY_SLOT_TEXTS: Readonly<RecipeSlotTexts> = {
  portrait: '',
  costume: '',
  pose: '',
}

/** 从八类碎片编译出三槽文本（人像槽合并面部 + 身材）。 */
export function compileSlotTexts(
  fragments: RecipeTextFragments | undefined,
): RecipeSlotTexts {
  const compiled = compileRecipeTextFragments(fragments)
  return {
    portrait: compiled.portraitText,
    costume: compiled.costumeText,
    pose: compiled.poseText,
  }
}

/**
 * 只编译「本次真正会发送」的三槽文本（P4）：
 * text 模式 → 替代；image 模式 → 仅 supplement 开关打开时作为补充；
 * empty / 开关关闭 → 空串。矩阵组键与批量清单必须用这份口径，
 * 否则未生效的文本会把两个实际相同的组合拆成不同组。
 */
export function compileActiveSlotTexts(
  fragments: RecipeTextFragments | undefined,
  modes: RecipeSlotModes,
  supplements: RecipeSupplementFlags | undefined,
): RecipeSlotTexts {
  const compiled = compileRecipeTextFragments(fragments)
  return {
    portrait: isSlotTextActive('portrait', modes.portrait, supplements)
      ? compiled.portraitText
      : '',
    costume: isSlotTextActive('costume', modes.costume, supplements)
      ? compiled.costumeText
      : '',
    pose: isSlotTextActive('pose', modes.pose, supplements)
      ? compiled.poseText
      : '',
  }
}

/** 文本前 N 字预览；超长追加省略号（矩阵组头 / 组名用）。 */
export function slotTextPreview(text: string, maxChars = 12): string {
  const trimmed = text.trim()
  if (trimmed.length <= maxChars) return trimmed
  return `${trimmed.slice(0, maxChars)}…`
}

/** 矩阵 / 组键使用的槽位展示输入。 */
export interface RecipeSlotDisplaySlot {
  id: string
  name: string
}

export interface RecipeSlotDisplayInput {
  /** 每个槽当前的代表条目（image 模式使用；text / empty 可为 null）。 */
  slots: Record<RecipeSlotKey, RecipeSlotDisplaySlot | null>
  modes: RecipeSlotModes
  texts: RecipeSlotTexts
  /** P4：image 模式 + 开关打开时，文本作为补充进入组键 / 展示。 */
  supplements?: RecipeSupplementFlags
}

/**
 * 一个槽在矩阵里的展示片段。
 *
 * - `key`：组键片段 —— image 用条目 id（有补充时再拼文本），text 用完整文本
 *   （避免不同文本碰撞成同一组），empty 为空串；
 * - `label`：组名片段 —— text 用前 12 字，image 用条目名（有补充时加标记）；
 * - `textLabel` / `textPreview`：文本槽 chip（「文本 · 类型」+ 前 12 字）；
 * - `supplementLabel` / `supplementPreview`：image 槽的「补充」小标。
 */
export interface RecipeSlotDisplay {
  slot: RecipeSlotKey
  mode: RecipeSlotMode
  key: string
  label: string
  textLabel: string
  textPreview: string
  supplementLabel: string
  supplementPreview: string
}

/** 把槽位 / 模式 / 文本合并成矩阵需要的三联展示（纯函数，可直接单测）。 */
export function buildRecipeSlotDisplays(
  input: RecipeSlotDisplayInput,
): RecipeSlotDisplay[] {
  const supplements = input.supplements ?? EMPTY_SUPPLEMENT_FLAGS
  return RECIPE_SLOT_KEYS.map((slot) => {
    const mode = input.modes[slot]
    const text = (input.texts[slot] ?? '').trim()
    const supplement = mode === 'image' && supplements[slot] ? text : ''
    if (mode === 'text') {
      const preview = slotTextPreview(text)
      return {
        slot,
        mode,
        // 组键必须包含文本内容：不同文本要分成不同组（方案 §4.4）。
        key: text ? `text:${text}` : '',
        label: preview,
        textLabel: `文本 · ${SLOT_TEXT_TYPE_LABELS[slot]}`,
        textPreview: preview,
        supplementLabel: '',
        supplementPreview: '',
      }
    }
    if (mode === 'image') {
      const item = input.slots[slot]
      const supplementPreview = supplement ? slotTextPreview(supplement) : ''
      return {
        slot,
        mode,
        // image + 补充：同一张图配不同补充文本必须落不同组。
        key: `${item?.id ?? ''}${supplement ? `|supp:${supplement}` : ''}`,
        label: item ? `${item.name}${supplement ? '（+文本补充）' : ''}` : '',
        textLabel: '',
        textPreview: '',
        supplementLabel: supplement ? `补充 · ${SLOT_TEXT_TYPE_LABELS[slot]}` : '',
        supplementPreview,
      }
    }
    return {
      slot,
      mode,
      key: '',
      label: '',
      textLabel: '',
      textPreview: '',
      supplementLabel: '',
      supplementPreview: '',
    }
  })
}

/** 组键：三个槽的 key 片段按固定顺序拼接（不可见分隔符，避免 id 冲突）。 */
export function slotDisplaysGroupKey(displays: readonly RecipeSlotDisplay[]): string {
  return displays.map((display) => display.key).join('\u0000')
}

/** 组名：只保留非空片段，text 槽已经用前 12 字代替槽名。 */
export function slotDisplaysGroupLabel(displays: readonly RecipeSlotDisplay[]): string {
  const labels = displays.map((display) => display.label).filter((label) => label.length > 0)
  return labels.length > 0 ? labels.join(' · ') : '未选参考图'
}

/** 替代态校验输入。 */
export interface AlternateModeConflictInput {
  modes: RecipeSlotModes
  fragments?: RecipeTextFragments
  /** 各槽的条目数（image 模式才有意义）。 */
  imageCounts: Record<RecipeSlotKey, number>
  /** 第 4 张是否已上传（也算 1 张参考图）。 */
  extraFilled?: boolean
  /** 用户显式选择的体态模式（不看 effective，避免掩盖冲突）。 */
  bodyMode?: 'costume' | 'bare'
  /** 当前 / 上次选择的姿势 id（用于识别 `pair*` 双人姿势）。 */
  poseId?: string
}

/**
 * 替代态提交校验（方案 §4.4）。返回空串表示通过。
 *
 * 顺序按「最容易解释」排：
 * 1. 至少 1 张图（文本不计入参考图）；
 * 2. text 模式必须有对应类碎片；
 * 3. 素体展示 + 服装文本；
 * 4. 姿势文本 + 双人姿势。
 */
export function describeAlternateModeConflicts(
  input: AlternateModeConflictInput,
): string {
  const { modes } = input

  const hasImageSlot = RECIPE_SLOT_KEYS.some(
    (slot) => modes[slot] === 'image' && (input.imageCounts[slot] ?? 0) > 0,
  )
  if (!hasImageSlot && !input.extraFilled) return NO_IMAGE_SLOT_HINT

  for (const slot of RECIPE_SLOT_KEYS) {
    if (modes[slot] !== 'text') continue
    if (slotFragmentItems(input.fragments, slot).length > 0) continue
    return `${SLOT_LABELS[slot]}槽：${TEXT_MODE_FRAGMENT_REQUIRED_HINT}`
  }

  // 素体展示 + 服装文本：与「不穿衣服却描述衣服」同源。
  // 注意按「碎片非空」判断而不是只看 text 模式：三槽文本始终按映射发送，
  // image / empty 模式下残留的服装碎片同样会进入提交体（方案 §4.4）。
  if (
    input.bodyMode === 'bare' &&
    slotFragmentItems(input.fragments, 'costume').length > 0
  ) {
    return `服装槽：${BARE_COSTUME_TEXT_CONFLICT_HINT}`
  }

  if (modes.pose === 'text' && (input.poseId ?? '').startsWith('pair')) {
    return POSE_TEXT_PAIR_CONFLICT_HINT
  }

  return ''
}