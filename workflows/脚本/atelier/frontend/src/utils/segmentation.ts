import { FRAGMENT_TYPES } from '../constants'

/**
 * 智能分段：把一段扁平提示词拆成【类型】结构。
 *
 * 旧版（static/prompt.js 的 smartSegmentText / FRAGMENT_SEGMENT_DICT）就有这个
 * 能力，重构时漏了 —— 它的价值在于：库里很多提示词是「一整段话」，
 * 拆成【人物面部】【人物服饰】… 之后才能直接喂给组合器。
 *
 * 做法：先按换行 / 中英文逗号顿号分号切成 token，再用关键词字典归类；
 * 一个 token 命中多类时按 `_SEG_PRIORITY` 的顺序取最具体的那类。
 */

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

/**
 * 分段结果渲染成【类型】格式的文本（与组合器的输出格式一致）。
 *
 * 没有命中任何类型的碎片会原样返回 —— 总比把内容弄丢强。
 */
export function renderSegmented(segments: Record<string, string>): string {
  const keys = FRAGMENT_TYPES.filter((t) => segments[t])
  if (!keys.length) return ''
  return keys.map((t) => `【${t}】\n${segments[t]}`).join('\n\n')
}

/**
 * 把已有【类型】标记的提示词拆成「已标记块 / 未标记文字」。
 *
 * 智能分段必须只在未标记部分上跑，否则对已经是分段格式的提示词再点一次，
 * 会把标题也当成正文重新归类，越分越乱。旧版 static/prompt.js 的
 * `_segmentParse` 就是这个作用，重构成 Vue 时漏掉了。
 */
export function parseMarkedSegments(text: string): {
  marked: Record<string, string>
  leftover: string
} {
  const marked: Record<string, string> = {}
  const leftoverBlocks: string[] = []
  const blocks = (text || '').split(/\n\s*\n/)
  for (const block of blocks) {
    const match = block.match(/^\s*【([^】]+)】\s*([\s\S]*)$/)
    if (match) {
      marked[match[1].trim()] = (match[2] || '').trim()
    } else if (block.trim()) {
      leftoverBlocks.push(block.trim())
    }
  }
  return { marked, leftover: leftoverBlocks.join('\n\n').trim() }
}

/**
 * 只替换指定【类型】块的内容，其他块原样保留。
 *
 * 找不到该类型时返回 null —— 批量替换要据此跳过"本来就没有这一片"的提示词，
 * 而不是凭空给它加一段。
 */
export function replaceMarkedSegment(
  text: string,
  type: string,
  content: string,
): string | null {
  let replaced = false
  const blocks = (text || '').split(/\n\s*\n/)
  const next = blocks.map((block) => {
    const match = block.match(/^\s*【([^】]+)】\s*([\s\S]*)$/)
    if (!match || match[1].trim() !== type) return block
    replaced = true
    return `【${type}】\n${content}`
  })
  if (!replaced) return null
  return next.join('\n\n').trim()
}

/** 渲染任意类型键（包括库里自定义的碎片名），不会像 renderSegmented 那样过滤。 */
export function renderAllSegments(segments: Record<string, string>): string {
  return Object.entries(segments)
    .filter(([, content]) => content)
    .map(([type, content]) => `【${type}】\n${content}`)
    .join('\n\n')
}