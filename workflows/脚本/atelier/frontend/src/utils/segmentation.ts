import { apiPost } from '../api/client'
import { FRAGMENT_TYPES } from '../constants'

/**
 * 智能分段 + `【类型】` 文本的读写。
 *
 * 分层（命名规范 §9）：
 * · **语法** —— `【类型】\n内容`、块之间空行分隔、渲染顺序 —— 只有后端一份实现
 *   （`app/services/fragment_syntax.py`）。这里的 `parseMarkedSegments` /
 *   `renderSegments` / `batchReplaceSegments` 都只是 `POST /api/composition/*`
 *   的薄封装，前端不再自带第二份正则。
 * · **启发式** —— `smartSegmentText` 按关键词把一整段话归类。后端没有对应实现，
 *   它属于纯前端的"猜测"，猜错了用户还能手改，所以留在这里。
 */

/** 一条 `【类型】` 碎片（与后端 `Fragment` 同形）。 */
export interface FragmentItem {
  type: string
  content: string
}

// ---------------------------------------------------------------------------
// 关键词分段（纯前端启发式）
// ---------------------------------------------------------------------------

/** 关键词字典：类型 → 命中即归入该类的关键词。 */
export const FRAGMENT_SEGMENT_DICT: Record<string, string[]> = {
  拍摄视角: [
    'close-up', 'close up', 'portrait', 'full body', 'fullbody', 'upper body', 'lower body',
    'from side', 'from above', 'from below', 'low angle', 'high angle', 'cowboy shot',
    'wide shot', 'extreme close', 'pov', 'selfie', 'dutch angle', 'birds eye', 'top-down', 'aerial',
    '视角', '特写', '半身', '全身', '侧身', '俯视', '仰视', '远景', '近景', '自拍', '广角', '鱼眼', '第一人称',
  ],
  人物身材: [
    'tall', 'slender', 'slim', 'petite', 'curvy', 'muscular', 'flat chest', 'small chest',
    'big breasts', 'large breasts', 'wide hips', 'long legs', 'short stature', 'athletic', 'chubby',
    '身材', '高挑', '苗条', '纤细', '丰满', '微胖', '肌肉', '巨乳', '贫乳', '长腿', '小蛮腰', '体型', '胸部',
  ],
  人物服饰: [
    'dress', 'shirt', 'skirt', 'jacket', 'coat', 'sweater', 'gown', 'kimono', 'uniform', 'bikini',
    'suit', 'hoodie', 'tshirt', 't-shirt', 'pants', 'shorts', 'jeans', 'boots', 'hat', 'crown',
    'ribbon', 'headband', 'glasses', 'scarf', 'armor', 'robe', 'maid', 'sailor', 'wedding',
    '服饰', '连衣裙', '裙子', '上衣', '外套', '毛衣', '和服', '制服', '衬衫', '短裤', '裤子', '牛仔裤',
    '靴子', '帽子', '皇冠', '丝带', '发箍', '眼镜', '围巾', '盔甲', '长袍', '女仆', '水手服', '婚纱', '鞋子', '袜子',
  ],
  人物面部: [
    'blue eyes', 'green eyes', 'red eyes', 'brown eyes', 'black eyes', 'golden eyes',
    'heterochromia', 'blonde hair', 'red hair', 'black hair', 'white hair', 'silver hair',
    'pink hair', 'blue hair', 'purple hair', 'long hair', 'short hair', 'medium hair',
    'twintails', 'twin tails', 'ponytail', 'braid', 'bob cut', 'curly hair', 'facial', 'face',
    'eyes', 'hair',
    '双眸', '蓝眼', '绿眼', '红眼', '棕眼', '黑眼', '金眼', '异色瞳', '金发', '红发', '黑发', '白发',
    '银发', '粉发', '蓝发', '紫发', '长发', '短发', '中发', '双马尾', '单马尾', '麻花辫', '波波头',
    '卷发', '面容', '五官', '大眼睛', '可爱', '清纯', '脸', '瞳',
  ],
  姿态动作: [
    'standing', 'sitting', 'lying', 'laying', 'sleeping', 'jumping', 'running', 'walking',
    'waving', 'smiling', 'laughing', 'crying', 'looking at viewer', 'looking back',
    'looking at camera', 'arms up', 'hands on hips', 'pointing', 'holding', 'leaning',
    'kneeling', 'squatting', 'stretching', 'dancing', 'winking', 'blush', 'pose',
    '姿态', '站立', '坐着', '躺', '睡', '跳', '跑', '走', '挥手', '微笑', '大笑', '哭', '回头',
    '比心', '叉腰', '指', '抱', '靠', '跪', '蹲', '伸展', '跳舞', '眨眼', '害羞', '动作',
  ],
  场景环境: [
    'outdoors', 'indoors', 'forest', 'city', 'beach', 'room', 'garden', 'school', 'cafe',
    'street', 'park', 'mountain', 'sky', 'ocean', 'water', 'flower', 'cherry blossoms',
    'sakura', 'library', 'temple', 'playground', 'pool', 'bedroom', 'office', 'scene',
    'background', 'scenery',
    '户外', '室内', '森林', '城市', '海边', '房间', '花园', '校园', '咖啡馆', '街道', '公园', '山',
    '天空', '海洋', '水', '花', '樱花', '图书馆', '神社', '操场', '泳池', '卧室', '办公室', '背景',
    '场景', '草地', '夜景', '雨天', '雪',
  ],
  光影色调: [
    'sunny', 'sunlight', 'soft light', 'cinematic lighting', 'rim light', 'backlight',
    'back light', 'volumetric light', 'studio light', 'moonlight', 'glow', 'lens flare',
    'ambient', 'shadows', 'dramatic lighting', 'warm tone', 'cool tone', 'dim', 'bright',
    '光影', '阳光', '柔光', '逆光', '轮廓光', '体积光', '影棚光', '月光', '辉光', '暖色调',
    '冷色调', '暗调', '明亮', '光线', '打光', '光晕', '氛围光',
  ],
  画风技术: [
    'anime', 'realistic', 'real life', 'illustration', 'masterpiece', 'best quality',
    'high quality', '3d', 'cg', 'oil painting', 'watercolor', 'cel shading', 'flat color',
    'sketch', 'digital art', 'render', 'niji', 'noobai', 'contrast', 'saturation', 'sharp focus',
    'detailed', 'ultra-detailed', '8k', '4k', 'hdr',
    '画风', '动漫', '写实', '真人', '插画', '杰作', '最佳质量', '高清', '厚涂', '赛璐璐',
    '二次元', '水彩', '油画', '素描', '对比度', '饱和度', '锐焦', '精细', '细节', '风格',
  ],
}

/** 多命中时的优先顺序（越靠前越具体，优先收纳）。 */
const SEG_PRIORITY = [
  '人物面部',
  '人物服饰',
  '人物身材',
  '姿态动作',
  '场景环境',
  '光影色调',
  '拍摄视角',
  '画风技术',
]

/**
 * 切分成 token：换行 / 中英文逗号顿号分号 / 句号都算分隔符。
 *
 * 句号必须算 —— 否则「黑色长发，正脸看向镜头。身穿连衣裙」会粘成一个 token，
 * 里面的「脸」把整段抢进「人物面部」，服饰那一类就没了。
 */
function tokenize(text: string): string[] {
  return text
    .split(/\r?\n|，|、|；|;|,|。|\.(?=\s|$)/)
    .map((t) => t.trim())
    .filter((t) => t && !/^[\s，,、；;。.]+$/.test(t))
}

/**
 * 把扁平文本按关键词拆成「类型 → 内容」。
 *
 * 返回的 map 只含命中过的类型，顺序按 `SEG_PRIORITY`（保证生成的文本稳定）。
 */
export function smartSegmentText(text: string): Record<string, string> {
  if (!text) return {}

  const buckets: Record<string, string[]> = {}
  for (const k of SEG_PRIORITY) buckets[k] = []
  const other: string[] = []

  const lowerDict: Record<string, string[]> = {}
  for (const k of SEG_PRIORITY) lowerDict[k] = FRAGMENT_SEGMENT_DICT[k].map((s) => s.toLowerCase())

  for (const token of tokenize(text)) {
    const low = token.toLowerCase()
    let matched: string | null = null
    for (const k of SEG_PRIORITY) {
      if (lowerDict[k].some((kw) => low.includes(kw))) {
        matched = k
        break
      }
    }
    if (matched) buckets[matched].push(token)
    else other.push(token)
  }

  const hasCJK = (s: string) => /[一-龥]/.test(s)
  const result: Record<string, string> = {}
  for (const k of SEG_PRIORITY) {
    if (!buckets[k].length) continue
    const joined = buckets[k].join(hasCJK(buckets[k].join('')) ? '，' : ', ')
    result[k] = joined
  }
  // 没命中任何关键词的单独归到「画风技术」不合适 —— 放回原顺序末尾的兜底类型
  if (other.length) {
    const fallback = '画风技术'
    const merged = result[fallback] ? `${result[fallback]}，${other.join('，')}` : other.join('，')
    result[fallback] = merged
  }
  return result
}

// ---------------------------------------------------------------------------
// `【类型】` 语法：全部打后端（POST /api/composition/*）
// ---------------------------------------------------------------------------

interface ParseResponse {
  fragments: FragmentItem[]
  leftover: string
}

export interface ReplacementItem {
  type: string
  content: string
  /** 该类型不存在时：skip = 跳过；append = 在末尾追加 */
  missing?: 'skip' | 'append'
}

export interface TypeOutcome {
  type: string
  oldContent: string
  action: 'replaced' | 'appended' | 'skipped'
}

export interface ReplaceOutcome {
  /** 应用整份替换清单后的全文；所有类型都跳过时为 null */
  replaced: string | null
  outcomes: TypeOutcome[]
}

/** 解析一段提示词：已标记块（type → content）+ 未标记残留文字。 */
export async function parseMarkedSegments(
  text: string,
): Promise<{ marked: Record<string, string>; leftover: string }> {
  const data = await apiPost<ParseResponse>('/api/composition/parse', { text })
  const marked: Record<string, string> = {}
  for (const fragment of data.fragments) marked[fragment.type] = fragment.content
  return { marked, leftover: data.leftover }
}

/** 批量渲染：每组碎片渲染成一段文本（一次往返，N 组）。 */
export async function renderSegments(groups: FragmentItem[][]): Promise<string[]> {
  if (!groups.length) return []
  const data = await apiPost<{ texts: string[] }>('/api/composition/render', { items: groups })
  return data.texts
}

/** 「类型→内容」按对象键顺序转成碎片列表。 */
export function toFragments(segments: Record<string, string>): FragmentItem[] {
  return Object.entries(segments)
    .filter(([, content]) => content)
    .map(([type, content]) => ({ type, content }))
}

/** 「类型→内容」按 `types` 给定顺序转成碎片列表（`types` 之外的键被丢弃）。 */
export function fragmentsInOrder(
  segments: Record<string, string>,
  types: readonly string[] = FRAGMENT_TYPES,
): FragmentItem[] {
  return types
    .filter((t) => segments[t])
    .map((t) => ({ type: t, content: segments[t] }))
}

/** 渲染成【类型】格式的文本（只保留内置 8 类，与组合器输出格式一致）。 */
export function renderSegmented(segments: Record<string, string>): Promise<string> {
  return renderSegments([fragmentsInOrder(segments)]).then((texts) => texts[0] ?? '')
}

/** 渲染任意类型键（包括库里自定义的碎片名），不会像 renderSegmented 那样过滤。 */
export function renderAllSegments(segments: Record<string, string>): Promise<string> {
  return renderSegments([toFragments(segments)]).then((texts) => texts[0] ?? '')
}

/**
 * 按「替换清单」批量改写提示词：返回 id → { 替换后全文, 每个类型的结果 }。
 *
 * 清单里的类型按顺序由后端应用（`replace_types`），其他块原样保留 —— 前端不重排
 * 用户库里的换行格式，也不自己拼 `【类型】` 串。
 */
export async function batchReplaceSegments(
  texts: Array<{ id: number; text: string }>,
  replacements: ReplacementItem[],
): Promise<Map<number, ReplaceOutcome>> {
  const out = new Map<number, ReplaceOutcome>()
  if (!texts.length || !replacements.length) return out
  const data = await apiPost<{
    items: Array<{
      id: number
      replaced: string | null
      outcomes: Array<{
        type: string
        old_content: string
        action: TypeOutcome['action']
      }>
    }>
  }>('/api/composition/batch_replace', {
    texts,
    replacements: replacements.map((r) => ({
      type: r.type,
      content: r.content,
      missing: r.missing ?? 'skip',
    })),
  })
  for (const item of data.items) {
    out.set(item.id, {
      replaced: item.replaced,
      outcomes: item.outcomes.map((o) => ({
        type: o.type,
        oldContent: o.old_content,
        action: o.action,
      })),
    })
  }
  return out
}
