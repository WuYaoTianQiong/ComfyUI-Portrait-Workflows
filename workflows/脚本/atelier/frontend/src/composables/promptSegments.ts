/**
 * 合成台提示词分段解析 / 拼装（P3，方案 §14）。
 *
 * 后端 `build_recipe_prompt` 产出的正向提示词是纯文本，结构固定为：
 *
 * ```
 * 请根据提供的 3 张参考图，生成一张完整的真实人物照片：
 * • 人物：图1中的人物，……
 * • 服装：让人物穿上图2中展示的整套服装和配饰……
 * • 姿势：严格复现图3中人体模型的身体姿态与镜头角度。……
 * • 拍摄视角：低角度仰拍
 * • 补充要求：暖色灯光
 * • 风格：……（画风预设段）
 * 画面中没有任何文字、标志或水印。
 * ```
 *
 * 本模块把它拆成「开头 / `• 标签：内容` 段 / 结尾」三类卡片，
 * 供 `StudioPromptEditor` 展示与手动改写；拼装后必须能**逐字还原原文**，
 * 这样手动改写才有「按原文提交」的语义。
 *
 * 纯函数：不读写状态、不发请求、不依赖 Vue，可直接单测。
 */

/** 段落类型：开头 / 后端生成的 `• 标签：内容` / 结尾。 */
export type PromptSegmentKind = 'head' | 'bullet' | 'tail'

/** 彩色标签的色调枚举（颜色映射在组件 CSS 里，用 `var(--token)`）。 */
export type PromptSegmentTone = 'portrait' | 'costume' | 'pose' | 'modifier' | 'neutral'

/** 一个可展示 / 可编辑的提示词段。 */
export interface PromptSegment {
  /** 段 id（同一份解析结果内唯一，可直接作为 `v-for` 的 key）。 */
  id: string
  /** `• 标签：` 里的标签；head / tail 为空串。 */
  label: string
  /** 段正文，不含 `• 标签：` 前缀，不含行尾换行。 */
  text: string
  kind: PromptSegmentKind
}

/**
 * 段首格式：`• 标签：内容`。
 *
 * - 兼容半角冒号（`• 人物: …`），解析后统一按全角冒号拼装；
 * - 标签不跨冒号，正文允许为空（例如只写了 `• 补充要求：`）。
 */
const BULLET_PATTERN = /^\s*•\s*([^：:\r\n]+?)\s*[：:]\s?(.*)$/

/** 标签 → 来源提示（方案 §14：让用户一眼看出这一段是碎片还是图片来的）。 */
const SOURCE_HINTS: ReadonlyArray<readonly [string, string]> = [
  ['人物', '图片 + 补充碎片'],
  ['服装', '图片 + 补充碎片'],
  ['姿势', '图片 + 补充碎片'],
  ['拍摄视角', '碎片'],
  ['场景环境', '碎片'],
  ['光影色调', '碎片'],
  ['画风技术', '碎片'],
  ['风格', '画风预设'],
  ['补充要求', '自由文本'],
]

/** 修饰层标签：在 UI 里统一用同一色调。 */
const MODIFIER_LABELS: readonly string[] = [
  '拍摄视角',
  '场景环境',
  '光影色调',
  '画风技术',
  '风格',
  '补充要求',
]

/** 标签是否以某个已知前缀开头（后端可能写「人物（补充）」这类变体）。 */
function labelStartsWith(label: string, prefix: string): boolean {
  return label.trim().startsWith(prefix)
}

/**
 * 按行解析提示词。
 *
 * - 首个 `• 标签：内容` 之前的非空行 = head（可多行）；
 * - 末个 bullet 之后的非空行 = tail（可多行，例如「画面中没有任何文字…」）；
 * - 没有 bullet 时整段为一个 head；
 * - 空串 / 全空白返回空数组。
 *
 * 说明：后端只在末尾补一句固定尾注，正文不会出现「bullet 中间夹非 bullet 行」，
 * 因此这里不做跨行续写推断，保持语义简单可测。
 */
export function parsePromptSegments(prompt: string): PromptSegment[] {
  const source = typeof prompt === 'string' ? prompt : ''
  if (!source.trim()) return []

  const lines = source.split('\n').map((line) => line.replace(/\r$/, ''))
  const segments: PromptSegment[] = []
  let headLines: string[] = []
  let tailLines: string[] = []
  let current: PromptSegment | null = null
  let bulletIndex = 0

  for (const line of lines) {
    const matched = BULLET_PATTERN.exec(line)
    if (matched) {
      // 第一个 bullet 出现时，把之前收集的行固化为 head。
      if (!current && headLines.length > 0) {
        segments.push({
          id: 'head',
          label: '',
          text: headLines.join('\n'),
          kind: 'head',
        })
      }
      current = {
        id: `bullet-${bulletIndex}`,
        label: matched[1].trim(),
        text: matched[2],
        kind: 'bullet',
      }
      bulletIndex += 1
      segments.push(current)
      continue
    }

    if (current) tailLines.push(line)
    else headLines.push(line)
  }

  // head 段只在有非空内容时存在：空行不算「开头内容」，避免出现空卡片。
  if (!segments.length && headLines.join('\n').trim()) {
    return [{ id: 'head', label: '', text: headLines.join('\n'), kind: 'head' }]
  }

  if (tailLines.join('\n').trim()) {
    segments.push({
      id: 'tail',
      label: '',
      text: tailLines.join('\n'),
      kind: 'tail',
    })
  }

  return segments
}

/**
 * 拼装分段，保持原顺序与换行。
 *
 * - bullet 段还原为 `• 标签：内容`；
 * - head / tail 原样输出；
 * - 空的 head / tail / 无标签 bullet 直接忽略，避免手动改写时凭空多出空行。
 */
export function composePromptSegments(segments: readonly PromptSegment[]): string {
  const parts: string[] = []
  for (const segment of segments) {
    if (!segment) continue
    if (segment.kind === 'bullet') {
      const label = segment.label.trim()
      if (!label) continue
      parts.push(`• ${label}：${segment.text}`)
      continue
    }
    if (segment.text.trim()) parts.push(segment.text)
  }
  return parts.join('\n')
}

/**
 * 段来源提示：告诉用户这一段由什么生成。
 *
 * 人物 / 服装 / 姿势 → 图片 + 补充碎片；四类修饰 → 碎片；
 * 风格 → 画风预设；补充要求 → 自由文本；其它（双人要求、素体展示…）→ 自动生成。
 */
export function segmentSourceHint(label: string): string {
  const name = label.trim()
  for (const [prefix, hint] of SOURCE_HINTS) {
    if (labelStartsWith(name, prefix)) return hint
  }
  return '自动生成'
}

/**
 * 段色调枚举：供模板拼类名 `prompt-segment--${tone}`，颜色映射只写在组件 CSS 里，
 * 纯函数不引入任何色值（硬约束：禁止硬编码十六进制）。
 */
export function segmentTone(label: string): PromptSegmentTone {
  const name = label.trim()
  if (labelStartsWith(name, '人物')) return 'portrait'
  if (labelStartsWith(name, '服装')) return 'costume'
  if (labelStartsWith(name, '姿势')) return 'pose'
  if (MODIFIER_LABELS.some((prefix) => labelStartsWith(name, prefix))) return 'modifier'
  return 'neutral'
}

/** 段展示名：head / tail 没有 `• 标签`，用「开头 / 结尾」占位。 */
export function segmentDisplayLabel(segment: PromptSegment): string {
  if (segment.kind === 'head') return '开头'
  if (segment.kind === 'tail') return '结尾'
  return segment.label
}