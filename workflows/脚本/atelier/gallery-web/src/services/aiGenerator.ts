import type { ApiConfig, ExtraReferenceImage, ImageProviderId, RecipeState } from '@/types/gallery'
import { applyWorkflowOverrides, getWorkflowImages, validateReferenceCombinations, workflowIdentity, type ComfyObjectInfo } from '@/lib/comfyWorkflowParameters'
import { poseImagePath, referenceImageUrl } from '@/lib/recipeImages'


export interface ProviderModelOption {
  value: string
  label: string
}

export interface PreparedComfyGeneration {
  workflow: Record<string, unknown>
}

export const PROVIDER_META: Record<
  ImageProviderId,
  {
    id: ImageProviderId
    name: string
    shortName: string
    defaultBaseUrl: string
    docUrl: string
    models: ProviderModelOption[]
  }
> = {

  comfyui: {
    id: 'comfyui',
    name: '本地 ComfyUI',
    shortName: 'ComfyUI',
    // 本地开发时走 /comfy 同源代理；线上站点直连 ComfyUI Desktop 默认端口 8000
    defaultBaseUrl: defaultComfyBaseUrl(),
    docUrl: 'https://docs.comfy.org/essentials/comfyui_server',
    models: [
      { value: 'qwen_image_edit_2509', label: 'qwen_image_edit_2509（由工作流决定）' },
      { value: 'custom', label: '自定义名称（仅用于记录显示）' },
    ],
  },
}

export const STYLE_PRESETS: Record<string, { label: string; prompt: string }> = {
  none: {
    label: '无预设（跟随参考图）',
    prompt: '',
  },
  realistic: {
    label: '写实人像写真',
    prompt: '写实商业摄影级质感，85mm 人像镜头，自然柔和光影，真实肌肤纹理与织物细节，8k 高清画质。',
  },
  fashion: {
    label: '日韩杂志画报',
    prompt: '日韩时尚穿搭杂志画报风格，干净极简摄影棚背景，高级色调，突出人物颜值与服装剪裁。',
  },
  film: {
    label: '复古胶片写真',
    prompt: '35mm 富士胶片摄影质感，轻微胶片颗粒，柔和复古暖调，自然街拍光影与电影呼吸感。',
  },
  semi_real: {
    label: '2.5D 游戏原画立绘',
    prompt: '2.5D 半写实高精度游戏角色原画，唯美厚涂光影，精致五官与华丽布料金属质感。',
  },
  anime: {
    label: '日系二次元插画',
    prompt: '日系精致二次元插画风格，细腻赛璐璐与厚涂光影过渡，动漫角色立绘质感，色彩通透干净。',
  },
  cel_anime: {
    label: '新海诚感动画电影',
    prompt: '动画电影级画面质感，清澈高饱和光影，细腻体积光与发丝高光，干净唯美的动漫色彩。',
  },
  manga: {
    label: '日式黑白漫画网点',
    prompt: '日本黑白漫画原稿风格，利落精准的G笔线稿，细腻漫画网点纸阴影与层次对比。',
  },
  render3d: {
    label: '3D 次世代角色渲染',
    prompt: 'Unreal Engine 5 / Octane Render 次世代 3D 角色渲染，细腻次表面散射肌肤材质，电影级布光。',
  },
  chibi_box: {
    label: '3D 潮玩手办质感',
    prompt: '高品质 PVC 涂装完成品手办质感，柔和摄影棚柔光箱布光，精致材质高光与微距景深。',
  },
  cyberpunk: {
    label: '赛博朋克霓虹',
    prompt: '赛博朋克科幻视觉风格，雨夜霓虹冷暖双色轮廓光，未来感材质反光与电影级氛围。',
  },
  concept_sheet: {
    label: '角色设定集立绘（纯白底）',
    prompt: '标准角色设定集全身立绘，纯白干净无杂物背景，均匀漫反射布光，清晰展示全身服装结构与配饰细节。',
  },
}

// 按实际传入模型的图片顺序动态生成「图1 / 图2 / 图3...」明确指代，支持附加上传图片
// 用自然语言逐项描述（人物 / 服装 / 姿势），实测比堆砌要点更能让多图编辑模型还原服装、避免照搬人体模型线条
const PHOTO_STYLES = new Set(['realistic', 'fashion', 'film'])

export function buildRecipePrompt(recipe: RecipeState, stylePreset = 'realistic', workflowImages: ExtraReferenceImage[] = []): string {
  const styleInfo = STYLE_PRESETS[stylePreset] ?? STYLE_PRESETS.realistic
  const isPhoto = PHOTO_STYLES.has(stylePreset)
  const faceless = !recipe.portrait && !workflowImages.some((image) => image.role === 'character_sheet') && Boolean(recipe.costume && recipe.pose)
  const clauses: string[] = []
  let idx = 1
  let costumeIdx = 0

  workflowImages.filter((image) => image.role === 'character_sheet').forEach(() => {
    clauses.push('• 角色设定参考：提供的设定集展示同一角色的多个视角与细节，不是多个不同人物。保持角色的脸型、五官、发型、发色、肤色及服装配饰一致；只把它作为角色参考，成品布局遵循当前工作流的输出设置。')
    idx++
  })

  if (recipe.portrait) {
    const hairDesc =
      recipe.portrait.发型名称 && recipe.portrait.发型名称 !== '标准基础款'
        ? recipe.portrait.标题
        : recipe.portrait.发长
    const skin = '人物的肤色必须与图一人物一致，所有裸露皮肤（包括服装镂空处露出的皮肤）必须与脸部肤色统一，统一后的肤色与质感按风格要求呈现。'
    const outfit = recipe.costume ? '' : '保留图1人物原有可见服装与配饰，不复制姿势参考图的服装或白模外观。'
    clauses.push(
      recipe.portrait.source === 'upload'
        ? `• 人物：图${idx}中的人物，保持其脸型、五官、发型和发色一致。${skin}${outfit}`
        : `• 人物：图${idx}中的人物，保持其脸型、五官、发型（${hairDesc}）和发色一致。${skin}${outfit}`
    )
    idx++
  }
  if (recipe.costume) {
    costumeIdx = idx
    clauses.push(
      recipe.costume.source === 'upload'
        ? `• 服装：让人物穿上图${idx}中展示的整套服装和配饰，每件单品的颜色、款式、面料与配饰都以图${idx}为准。`
        : `• 服装：让人物穿上图${idx}中展示的整套服装和配饰（参考名称：${recipe.costume.服装名称}），每件单品的颜色、款式、面料与配饰都以图${idx}为准，名称仅作辅助说明。`
    )
    idx++
  }
  if (recipe.pose) {
    const wear = costumeIdx ? `，穿着图${costumeIdx}的服装` : ''
    const body = isPhoto
      ? `最终画面中的人物是真人，皮肤真实自然${wear}`
      : `人物的肤色与质感按风格要求呈现${wear}`
    clauses.push(
      recipe.pose.source === 'upload'
        ? `• 姿势：按照图${idx}中的人物动作和镜头角度摆姿势；仅参考姿势与构图，不复制图${idx}人物的外观与服装，${body}。`
        : `• 姿势：按照图${idx}中人体模型的动作和镜头角度摆姿势（${recipe.pose.姿势名称}，${recipe.pose.角度}）；图${idx}只是动作示意，${body}。`
    )
    idx++
  }
  if (faceless) {
    clauses.push('• 无脸展示：生成一位穿着参考服装的成年展示人物，脸部保持无五官的自然肤色表面，不添加眼睛、鼻子、嘴巴或具体人物身份；全身裸露皮肤的颜色统一，不照搬服装图或姿势图的灰白人台材质。')
  }
  for (const reference of workflowImages.filter((image) => image.role !== 'character_sheet')) {
    clauses.push(`• 工作流参考：参考图${idx}（${reference.name || '补充参考'}）中的相关元素，具体用途以工作流要求为准。`)
    idx++
  }
  for (const extra of recipe.extraImages || []) {
    clauses.push(
      `• 附加参考：融合图${idx}（${extra.name || '补充元素'}）中的元素、配饰、背景或光影细节。`
    )
    idx++
  }

  if (clauses.length === 0) {
    return '请先选择人像/服装/姿势或上传附加参考图。'
  }

  const lines = [
    `请根据${workflowImages.some((image) => image.role === 'character_sheet') ? '提供的角色设定参考' : `提供的 ${idx - 1} 张参考图`}，生成一张完整的${faceless ? '人物穿搭展示图' : isPhoto ? '真实人物照片' : '人物图像'}：`,
    ...clauses,
  ]
  if (styleInfo.prompt) {
    lines.push(`• 风格：${styleInfo.prompt} ${faceless ? '人物比例协调，手部自然，脸部无五官，光影统一。' : '人物比例协调，手部与五官自然，光影统一。'}`)
  }
  lines.push('画面中没有任何文字、标志或水印。')
  return lines.join('\n')
}

export function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('读取文件失败'))
    reader.onload = () => {
      const img = new Image()
      img.onload = () => {
        const maxSide = 1024
        const scale = Math.min(1, maxSide / Math.max(img.width, img.height))
        const c = document.createElement('canvas')
        c.width = Math.round(img.width * scale)
        c.height = Math.round(img.height * scale)
        c.getContext('2d')!.drawImage(img, 0, 0, c.width, c.height)
        resolve(c.toDataURL('image/png'))
      }
      img.onerror = () => reject(new Error('解析图片失败'))
      img.src = reader.result as string
    }
    reader.readAsDataURL(file)
  })
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error(`加载图片失败: ${src}`))
    img.src = referenceImageUrl(src)
  })
}

export async function stitchRecipeCanvas(recipe: RecipeState): Promise<string> {
  const list: Array<{ tag: string; sub: string; src: string }> = []
  let idx = 1

  if (recipe.portrait) {
    list.push({
      tag: `图${idx++} · 人像`,
      sub: recipe.portrait.标题,
      src: recipe.portrait.原图 || recipe.portrait.缩略图,
    })
  }
  if (recipe.costume) {
    list.push({
      tag: `图${idx++} · 服装`,
      sub: `${recipe.costume.分类} · ${recipe.costume.服装名称}`,
      src: recipe.costume.预览图 || recipe.costume.原图 || recipe.costume.缩略图,
    })
  }
  if (recipe.pose) {
    list.push({
      tag: `图${idx++} · 姿势`,
      sub: `${recipe.pose.姿势名称}（${recipe.pose.角度}${recipe.pose.useDepth ? ' · 深度图' : ''}）`,
      src: poseImagePath(recipe.pose),
    })
  }
  for (const extra of recipe.extraImages || []) {
    list.push({
      tag: `图${idx++} · 附加`,
      sub: extra.name || '自定义参考图',
      src: extra.url,
    })
  }

  if (!list.length) {
    throw new Error('请至少选择或上传 1 张参考图')
  }

  const imgs = await Promise.all(list.map((x) => loadImage(x.src)))
  const cardW = 480
  const cardH = 640
  const pad = 20
  const headH = 62
  const canvas = document.createElement('canvas')
  canvas.width = list.length * cardW + (list.length + 1) * pad
  canvas.height = cardH + headH + pad * 2
  const ctx = canvas.getContext('2d')!

  ctx.fillStyle = '#111318'
  ctx.fillRect(0, 0, canvas.width, canvas.height)

  imgs.forEach((img, i) => {
    const x = pad + i * (cardW + pad)
    const y = pad
    ctx.fillStyle = '#1e222b'
    ctx.fillRect(x, y, cardW, cardH + headH)
    ctx.fillStyle = '#f4f5f7'
    ctx.fillRect(x, y + headH, cardW, cardH)

    const scale = Math.min(cardW / img.width, cardH / img.height)
    const dw = img.width * scale
    const dh = img.height * scale
    ctx.drawImage(img, x + (cardW - dw) / 2, y + headH + (cardH - dh) / 2, dw, dh)

    ctx.fillStyle = '#a1a1aa'
    ctx.font = '600 12px Inter, -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif'
    ctx.fillText(list[i].tag, x + 14, y + 23)

    ctx.fillStyle = '#ffffff'
    ctx.font = '700 15px Inter, -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif'
    ctx.fillText(list[i].sub.slice(0, 26), x + 14, y + 46)
  })

  return canvas.toDataURL('image/jpeg', 0.92)
}

// 将本地参考图压到最长边 1024 后转 PNG Data URL，用于上传到本地 ComfyUI
async function srcToPngDataUrl(src: string): Promise<string> {
  if (src.startsWith('data:image/')) return src
  const img = await loadImage(src)
  const maxSide = 1024
  const scale = Math.min(1, maxSide / Math.max(img.width, img.height))
  const c = document.createElement('canvas')
  c.width = Math.round(img.width * scale)
  c.height = Math.round(img.height * scale)
  c.getContext('2d')!.drawImage(img, 0, 0, c.width, c.height)
  return c.toDataURL('image/png')
}

function dataUrlToBlob(dataUrl: string): Blob {
  const [head, b64] = dataUrl.split(',')
  const mime = head.match(/:(.*?);/)?.[1] || 'image/png'
  const bin = atob(b64)
  const arr = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i)
  return new Blob([arr], { type: mime })
}


// ============================================================================
// 本地 ComfyUI API 工作流节点解析 / 提交工具
// ============================================================================

type ComfyNode = { class_type: string; inputs: Record<string, any>; _meta?: { title?: string; studio?: { imageRole?: string } } }
type ComfyWorkflow = Record<string, ComfyNode>

export interface ComfyNodeMappings {
  promptNodeId: string
  portraitNodeId: string
  costumeNodeId: string
  poseNodeId: string
  stitchedNodeId: string
}

/** 本地开发 / 本地预览时使用的同源代理前缀（见 vite.config.ts），可绕开 ComfyUI 的 CORS 白名单限制 */
export const COMFY_DEV_PROXY = '/comfy'

export function isLocalDevHost(): boolean {
  return (
    typeof window !== 'undefined' &&
    ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname)
  )
}

/** ComfyUI Desktop 默认端口 8000；便携版 / 源码版默认 8188 */
// 注意：PROVIDER_META 在模块初始化时就会调用本函数，这里不能引用后面定义的 const
export function defaultComfyBaseUrl(): string {
  return isLocalDevHost() ? '/comfy' : 'http://127.0.0.1:8000'
}

export function comfyCandidateUrls(current = ''): string[] {
  const list = [
    current.trim(),
    isLocalDevHost() ? defaultComfyBaseUrl() : '',
    'http://127.0.0.1:8000',
    'http://127.0.0.1:8188',
  ]
    .map((x) => x.replace(/\/+$/, ''))
    .filter(Boolean)
  return Array.from(new Set(list))
}

export interface ComfyParsedNodes {
  valid: boolean
  isUiFormat: boolean
  error?: string
  imageNodes: Array<{ id: string; title: string; classType: string; currentImage: string; emptyValue?: string; role?: 'character_sheet' }>
  promptNodes: Array<{ id: string; title: string; classType: string; field: string }>
}

export function parseComfyWorkflowNodes(workflowJson: string): ComfyParsedNodes {
  if (!workflowJson.trim()) {
    return { valid: false, isUiFormat: false, error: '工作流 JSON 为空', imageNodes: [], promptNodes: [] }
  }
  try {
    const parsed = JSON.parse(workflowJson)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { valid: false, isUiFormat: false, error: '无效的 JSON 对象', imageNodes: [], promptNodes: [] }
    }
    if (Array.isArray(parsed.nodes) && Array.isArray(parsed.links)) {
      return {
        valid: false,
        isUiFormat: true,
        error: '检测到普通画布格式 JSON，请在 ComfyUI 中使用「工作流 → 导出 (API)」得到 API 格式 JSON',
        imageNodes: [],
        promptNodes: [],
      }
    }

    const imageNodes: ComfyParsedNodes['imageNodes'] = []
    const promptNodes: ComfyParsedNodes['promptNodes'] = []

    for (const [id, node] of Object.entries<any>(parsed)) {
      if (!node || typeof node !== 'object' || !node.class_type) continue
      const classType = String(node.class_type)
      const title = String(node._meta?.title || classType)
      const inputs = node.inputs || {}

      if (classType === 'LoadImage' || typeof inputs.image === 'string') {
        imageNodes.push({ id, title, classType, currentImage: String(inputs.image || ''), ...(classType === 'LoadImageGoohai' ? { emptyValue: '无' } : {}), ...(node._meta?.studio?.imageRole === 'character_sheet' ? { role: 'character_sheet' as const } : {}) })
      }

      for (const field of ['prompt', 'text', 'string', 'positive']) {
        if (Array.isArray(node._meta?.studio?.hiddenInputs) && node._meta.studio.hiddenInputs.includes(field)) continue
        if (typeof inputs[field] === 'string') {
          promptNodes.push({ id, title, classType, field })
          break
        }
      }
    }

    if (imageNodes.length === 0 && promptNodes.length === 0) {
      return { valid: false, isUiFormat: false, error: '未在 JSON 中找到任何 ComfyUI 节点', imageNodes, promptNodes }
    }
    return { valid: true, isUiFormat: false, imageNodes, promptNodes }
  } catch (err: any) {
    return {
      valid: false,
      isUiFormat: false,
      error: `JSON 解析失败: ${err?.message || '语法错误'}`,
      imageNodes: [],
      promptNodes: [],
    }
  }
}

export function autoDetectComfyMappings(workflowJson: string): ComfyNodeMappings {
  const parsed = parseComfyWorkflowNodes(workflowJson)
  let promptNodeId = 'none'
  let portraitNodeId = 'none'
  let costumeNodeId = 'none'
  let poseNodeId = 'none'
  let stitchedNodeId = 'none'

  const posPrompt =
    parsed.promptNodes.find((n) => !/negative|反向|负面/i.test(n.title)) || parsed.promptNodes[0]
  if (posPrompt) promptNodeId = posPrompt.id

  const usedIds = new Set<string>()
  const slotImages = parsed.imageNodes.filter((node) => node.role !== 'character_sheet')
  for (const n of slotImages) {
    if (/人像|脸|人物|portrait|face|person/i.test(n.title) && portraitNodeId === 'none') {
      portraitNodeId = n.id
      usedIds.add(n.id)
    } else if (/服装|衣|穿搭|costume|cloth|outfit/i.test(n.title) && costumeNodeId === 'none') {
      costumeNodeId = n.id
      usedIds.add(n.id)
    } else if (/姿势|动作|骨架|pose/i.test(n.title) && poseNodeId === 'none') {
      poseNodeId = n.id
      usedIds.add(n.id)
    } else if (/拼图|合成|stitch/i.test(n.title) && stitchedNodeId === 'none') {
      stitchedNodeId = n.id
      usedIds.add(n.id)
    }
  }

  const remaining = slotImages.filter((n) => !usedIds.has(n.id))
  if (portraitNodeId === 'none' && remaining[0]) portraitNodeId = remaining.shift()!.id
  if (costumeNodeId === 'none' && remaining[0]) costumeNodeId = remaining.shift()!.id
  if (poseNodeId === 'none' && remaining[0]) poseNodeId = remaining.shift()!.id

  return { promptNodeId, portraitNodeId, costumeNodeId, poseNodeId, stitchedNodeId }
}

// ---------------------------------------------------------------------------
// 网络请求与中文错误
// ---------------------------------------------------------------------------

function normalizeComfyBase(baseUrl: string): string {
  return (baseUrl.trim() || defaultComfyBaseUrl()).replace(/\/+$/, '')
}

function describeComfyNetworkError(baseUrl: string, timedOut: boolean): string {
  if (timedOut) {
    return `[ComfyUI] 请求 ${baseUrl} 超时：ComfyUI 可能正忙或无响应，请查看 ComfyUI 终端日志。`
  }
  if (baseUrl.startsWith('/')) {
    return `[ComfyUI] 本地代理 ${baseUrl} 无法连通 ComfyUI：请确认 ComfyUI 已启动，且端口与启动网页时的 COMFYUI_URL 一致（默认 http://127.0.0.1:8000）。`
  }
  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  const reasons = [
    `① ComfyUI 未启动，或地址/端口不对（Desktop 版默认 8000，便携版默认 8188）`,
    `② 跨域 (CORS) 被拦截：ComfyUI 启动参数需包含 --enable-cors-header "${origin}"（该参数只能填一个来源）`,
  ]
  if (typeof window !== 'undefined' && window.location.protocol === 'https:') {
    reasons.push('③ 浏览器「本地网络访问」权限被拒绝：请点击地址栏左侧图标允许访问本地设备')
    if (/^http:/i.test(baseUrl) && !/\/\/(127\.0\.0\.1|localhost|\[::1\])/i.test(baseUrl)) {
      reasons.push('④ HTTPS 页面不能访问局域网 HTTP 地址（混合内容限制），请改用 127.0.0.1 或本地运行本站')
    }
  }
  return `[ComfyUI] 无法连接 ${baseUrl}。可能原因：\n${reasons.join('\n')}`
}

async function comfyFetch(
  baseUrl: string,
  path: string,
  init: RequestInit = {},
  apiKey = '',
  timeoutMs = 30000
): Promise<Response> {
  const headers = new Headers(init.headers)
  if (apiKey.trim()) headers.set('Authorization', `Bearer ${apiKey.trim()}`)
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  let res: Response
  try {
    res = await fetch(`${baseUrl}${path}`, { ...init, headers, signal: ctrl.signal })
  } catch (e: any) {
    throw new Error(describeComfyNetworkError(baseUrl, e?.name === 'AbortError'))
  } finally {
    clearTimeout(timer)
  }
  // 开发代理连不上后端时会返回非 JSON 的 5xx
  if (
    baseUrl.startsWith('/') &&
    res.status >= 500 &&
    !(res.headers.get('content-type') || '').includes('json')
  ) {
    throw new Error(describeComfyNetworkError(baseUrl, false))
  }
  return res
}

async function readJsonSafe(res: Response): Promise<any> {
  const text = await res.text()
  try {
    return JSON.parse(text)
  } catch {
    return { _raw: text.slice(0, 300) }
  }
}

export async function testComfyConnection(baseUrl: string, apiKey = ''): Promise<string> {
  const cleanUrl = normalizeComfyBase(baseUrl)
  const res = await comfyFetch(cleanUrl, '/system_stats', {}, apiKey, 8000)
  if (res.status === 401 || res.status === 403) {
    throw new Error(`[ComfyUI] ${cleanUrl} 拒绝访问 (HTTP ${res.status})，请检查 API Key / 鉴权设置`)
  }
  if (!res.ok) throw new Error(`[ComfyUI] ${cleanUrl}/system_stats 返回 HTTP ${res.status}，该地址可能不是 ComfyUI`)
  const data = await readJsonSafe(res)
  if (!data?.system) throw new Error(`[ComfyUI] ${cleanUrl} 的响应不是 ComfyUI 格式，请检查地址`)
  const ver = data.system.comfyui_version || '未知版本'
  const dev = data.devices?.[0]
  const gpu = dev?.name ? String(dev.name).replace(/^cuda:\d+\s*/, '').replace(/\s*:\s*\w+$/, '') : '本地设备'
  const vram = dev?.vram_total ? ` · 显存 ${(dev.vram_total / 1024 ** 3).toFixed(1)} GB` : ''
  return `ComfyUI ${ver} · ${gpu}${vram}`
}

/** 依次尝试候选地址，返回第一个可用的 ComfyUI 地址 */
export async function detectComfyUi(
  current = '',
  apiKey = ''
): Promise<{ baseUrl: string; info: string } | null> {
  for (const url of comfyCandidateUrls(current)) {
    try {
      const info = await testComfyConnection(url, apiKey)
      return { baseUrl: url, info }
    } catch {
      /* try next */
    }
  }
  return null
}

// ---------------------------------------------------------------------------
// 工作流与本机模型/节点匹配检测（基于 /object_info）
// ---------------------------------------------------------------------------

export interface ComfyCheckResult {
  ok: boolean
  errors: string[]
  warnings: string[]
  fixes: string[]
  /** 自动修正模型路径后的工作流 JSON（无修正时为 undefined） */
  fixedJson?: string
}

function comboOptions(spec: any): string[] | null {
  if (!Array.isArray(spec)) return null
  if (Array.isArray(spec[0])) return spec[0].map(String)
  if (spec[0] === 'COMBO' && Array.isArray(spec[1]?.options)) return spec[1].options.map(String)
  return null
}

const baseName = (s: string) => s.split(/[\\/]/).pop()!.toLowerCase()

export async function fetchComfyObjectInfo(baseUrl: string, apiKey: string, workflowJson: string): Promise<ComfyObjectInfo> {
  const parsed = parseComfyWorkflowNodes(workflowJson)
  if (!parsed.valid) throw new Error(parsed.error || '工作流 JSON 无效')
  const workflow: ComfyWorkflow = JSON.parse(workflowJson)
  const base = normalizeComfyBase(baseUrl)
  const classes = Array.from(new Set(Object.values(workflow).map((node) => node.class_type).filter(Boolean)))
  const entries = await Promise.all(classes.map(async (cls) => {
    const res = await comfyFetch(base, `/object_info/${encodeURIComponent(cls)}`, {}, apiKey, 15000)
    if (!res.ok) throw new Error(`[ComfyUI] 无法读取节点「${cls}」的定义（HTTP ${res.status}），请检查连接地址、访问令牌和网关接口权限。`)
    const json = await readJsonSafe(res)
    return [cls, json?.[cls]] as const
  }))
  return Object.fromEntries(entries.filter(([, definition]) => definition))
}

export async function checkComfyWorkflow(
  baseUrl: string,
  apiKey: string,
  workflowJson: string,
  mappedImageNodeIds: string[] = [],
  objectInfo?: ComfyObjectInfo
): Promise<ComfyCheckResult> {
  const parsedInfo = parseComfyWorkflowNodes(workflowJson)
  if (!parsedInfo.valid) {
    return { ok: false, errors: [parsedInfo.error || '工作流 JSON 无效'], warnings: [], fixes: [] }
  }
  const wf: ComfyWorkflow = JSON.parse(workflowJson)
  const info = objectInfo ?? await fetchComfyObjectInfo(baseUrl, apiKey, workflowJson)

  const errors: string[] = []
  const warnings: string[] = []
  const fixes: string[] = []
  const mapped = new Set(mappedImageNodeIds.filter((x) => x && x !== 'none'))
  const imageLoaders = new Set(getWorkflowImages(workflowJson, [], info).map((node) => node.nodeId))

  for (const [id, node] of Object.entries(wf)) {
    if (!node?.class_type) continue
    const title = node._meta?.title || node.class_type
    const def = info[node.class_type]
    if (!def) {
      errors.push(
        `缺少节点「${node.class_type}」（节点 ${id}：${title}）。请在 ComfyUI Manager 安装对应的自定义节点，或升级 ComfyUI。`
      )
      continue
    }
    const required = def.input?.required || {}
    const optional = def.input?.optional || {}
    const inputs = node.inputs || {}

    for (const [name, spec] of Object.entries<any>(required)) {
      // V3 自动扩展组使用 images.image_1 等扁平输入，组名本身不参与执行。
      if (spec?.[0] === 'COMFY_AUTOGROW_V3') {
        const template = spec[1]?.template
        if (template?.input?.required) {
          for (let i = 0; i < (template.min ?? 0); i++) {
            const child = template.names?.[i] ?? `${template.prefix}${i}`
            if (!(`${name}.${child}` in inputs)) {
              errors.push(`节点 ${id}「${title}」缺少必填输入 ${name}.${child}`)
            }
          }
        }
        continue
      }
      if (!(name in inputs)) errors.push(`节点 ${id}「${title}」缺少必填输入 ${name}`)
    }

    for (const [name, value] of Object.entries(inputs)) {
      if (Array.isArray(value)) continue // 节点连线
      const spec = required[name] ?? optional[name]
      const options = comboOptions(spec)
      if (!options || typeof value !== 'string') continue
      if (name === 'image' && mapped.has(id) && imageLoaders.has(id)) continue
      if (node.class_type === 'LoadImage' && name === 'image') {
        if (!mapped.has(id) && !options.includes(value)) {
          warnings.push(`节点 ${id}「${title}」引用的图片 ${value} 不在 ComfyUI input 目录中，且未映射到人像/服装/姿势槽位`)
        }
        continue
      }
      if (options.includes(value)) continue
      const sameFile = options.find((o) => baseName(o) === baseName(value))
      if (sameFile) {
        inputs[name] = sameFile
        fixes.push(`节点 ${id}「${title}」${name}：${value} → ${sameFile}（自动修正路径）`)
        continue
      }
      const sample = options.slice(0, 12).join('、')
      errors.push(
        `节点 ${id}「${title}」的 ${name} = ${value} 在本机不存在（通常是模型文件未安装或路径不同）。本机可选：${sample || '（空）'}${options.length > 12 ? ' …' : ''}`
      )
    }
  }

  return {
    ok: errors.length === 0,
    errors,
    warnings,
    fixes,
    fixedJson: fixes.length ? JSON.stringify(wf, null, 2) : undefined,
  }
}

function translateNodeError(er: any): string {
  const detail = er?.details ? `（${er.details}）` : ''
  switch (er?.type) {
    case 'value_not_in_list':
      return `${er.extra_info?.input_name ?? '输入'} 的值不在本机可选列表中${detail}——通常是模型文件不存在或路径不同`
    case 'required_input_missing':
      return `缺少必填输入 ${er.extra_info?.input_name ?? ''}`
    case 'invalid_input_type':
    case 'return_type_mismatch':
      return `节点连线类型不匹配${detail}`
    case 'value_bigger_than_max':
    case 'value_smaller_than_min':
      return `参数超出范围${detail}`
    case 'image_not_found':
    case 'custom_validation_failed':
      return `${er.message || '校验失败'}${detail}`
    default:
      return `${er?.message || '校验失败'}${detail}`
  }
}

function formatComfyPromptError(json: any, wf: ComfyWorkflow, status: number): string {
  const parts: string[] = []
  const e = json?.error
  if (e) {
    if (e.type === 'missing_node_type' || /does not exist|not found/i.test(String(e.message))) {
      parts.push(`缺少节点类型：${e.details || e.message}。请在 ComfyUI Manager 安装缺失的自定义节点或升级 ComfyUI`)
    } else if (e.type === 'prompt_no_outputs') {
      parts.push('工作流没有输出节点（SaveImage / PreviewImage）')
    } else if (e.type !== 'prompt_outputs_failed_validation') {
      parts.push(`${e.message || e.type}${e.details ? `：${e.details}` : ''}`)
    }
  }
  for (const [id, ne] of Object.entries<any>(json?.node_errors || {})) {
    const title = wf[id]?._meta?.title || ne?.class_type || id
    for (const er of ne?.errors || []) {
      parts.push(`节点 ${id}「${title}」：${translateNodeError(er)}`)
    }
  }
  if (!parts.length) parts.push(json?._raw || `HTTP ${status}`)
  return `[ComfyUI] 提交工作流失败：\n${parts.join('\n')}`
}

function formatExecutionError(messages: any[], wf: ComfyWorkflow): { text: string; oom: boolean } {
  const errMsg = (messages || []).find((m) => m?.[0] === 'execution_error')?.[1]
  if (errMsg) {
    const title = wf[errMsg.node_id]?._meta?.title || errMsg.node_type || errMsg.node_id
    const raw = `${errMsg.exception_type || ''} ${errMsg.exception_message || ''}`
    if (/out of memory|OutOfMemory|CUDA error: out of memory|allocat/i.test(raw)) {
      return {
        oom: true,
        text:
          `[ComfyUI] 显存不足（节点 ${errMsg.node_id}「${title}」）。已请求 ComfyUI 释放显存。\n` +
          '建议：关闭其他占用显卡的程序；在工作流中把「按姿势图比例确定输出尺寸」节点的 megapixels 从 1.0 调低到 0.6；然后重试。',
      }
    }
    return {
      oom: false,
      text: `[ComfyUI] 执行出错（节点 ${errMsg.node_id}「${title}」）：${String(errMsg.exception_message || raw).trim().slice(0, 400)}`,
    }
  }
  if ((messages || []).some((m) => m?.[0] === 'execution_interrupted')) {
    return { oom: false, text: '[ComfyUI] 任务已被中断（可能在 ComfyUI 界面中点击了取消）' }
  }
  return { oom: false, text: `[ComfyUI] 工作流执行出错：${JSON.stringify(messages || '').slice(0, 300)}` }
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('读取生成结果失败'))
    reader.onload = () => resolve(reader.result as string)
    reader.readAsDataURL(blob)
  })
}

async function uploadImageToComfy(
  baseUrl: string,
  src: string,
  filenamePrefix: string,
  apiKey: string
): Promise<string> {
  let dataUrl: string
  try {
    dataUrl = await srcToPngDataUrl(src)
  } catch {
    throw new Error(`读取参考图失败：${src.slice(0, 80)}`)
  }
  const form = new FormData()
  form.append('image', dataUrlToBlob(dataUrl), `${filenamePrefix}_${Date.now()}.png`)
  form.append('subfolder', 'pose_studio')
  form.append('overwrite', 'true')

  const res = await comfyFetch(baseUrl, '/upload/image', { method: 'POST', body: form }, apiKey, 60000)
  if (!res.ok) {
    throw new Error(`[ComfyUI] 上传参考图失败 (HTTP ${res.status})：${(await res.text()).slice(0, 200)}`)
  }
  const json = await res.json()
  return json.subfolder ? `${json.subfolder}/${json.name}` : json.name
}

export interface ComfyTaskHandle {
  promptId: string
  clientId: string
  baseUrl: string
  submittedAt: number
}

export class ComfyTaskError extends Error {
  readonly task: ComfyTaskHandle
  readonly reason: 'auth' | 'failed' | 'timeout' | 'tracking' | 'storage'
  constructor(message: string, task: ComfyTaskHandle, reason: ComfyTaskError['reason'] = 'tracking') {
    super(message)
    this.task = task
    this.reason = reason
    this.name = 'ComfyTaskError'
  }
}

export class ComfySubmissionRejectedError extends Error {
  readonly status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ComfySubmissionRejectedError'
    this.status = status
  }
}

export class ComfySubmissionUnknownError extends Error {
  constructor() {
    super('[ComfyUI] 提交结果未知：服务端可能已接受任务，请先检查队列与历史记录，勿直接重复提交。')
    this.name = 'ComfySubmissionUnknownError'
  }
}

export interface GenerationProgress {
  stage: 'check' | 'upload' | 'queue' | 'running' | 'download'
  message: string
  /** 当前节点 0-100，并非整个工作流百分比。 */
  percent?: number
  connection?: 'connecting' | 'connected' | 'reconnecting' | 'degraded'
}

type GenerationResult = { imageUrl: string; modelUsed: string; providerUsed: ImageProviderId }

function checkTrackingSignal(signal?: AbortSignal) {
  if (signal?.aborted) throw new DOMException('已停止跟踪，后台任务继续执行', 'AbortError')
}

interface ComfySocketSession {
  connection: NonNullable<GenerationProgress['connection']>
  onMessage: (msg: any) => void
  onConnection: (state: NonNullable<GenerationProgress['connection']>) => void
  close: () => void
}

function openComfySocket(
  task: Pick<ComfyTaskHandle, 'baseUrl' | 'clientId'>, apiKey: string,
): ComfySocketSession {
  let socket: WebSocket | undefined
  let stopped = false
  let failures = 0
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined
  let handshakeTimer: ReturnType<typeof setTimeout> | undefined
  const session: ComfySocketSession = {
    connection: 'connecting', onMessage: () => {}, onConnection: () => {},
    close: () => { stopped = true; clearTimeout(reconnectTimer); disconnect() },
  }
  const connection = (state: ComfySocketSession['connection']) => {
    session.connection = state
    session.onConnection(state)
  }
  const disconnect = () => {
    clearTimeout(handshakeTimer)
    if (socket) {
      socket.onopen = socket.onclose = socket.onerror = socket.onmessage = null
      socket.close()
      socket = undefined
    }
  }
  const reconnect = () => {
    disconnect()
    if (stopped) return
    failures++
    connection(failures >= 3 ? 'degraded' : 'reconnecting')
    reconnectTimer = setTimeout(connect, Math.min(30000, 1000 * 2 ** Math.min(failures - 1, 5)))
  }
  const connect = () => {
    if (stopped) return
    connection(failures ? 'reconnecting' : 'connecting')
    try {
      const u = new URL(task.baseUrl, window.location.href)
      u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:'
      u.pathname = `${u.pathname.replace(/\/+$/, '')}/ws`
      u.search = new URLSearchParams({ clientId: task.clientId }).toString()
      u.hash = ''
      socket = apiKey.trim()
        ? new WebSocket(u.toString(), ['comfyui', `comfyui-auth.${apiKey.trim()}`])
        : new WebSocket(u.toString())
      handshakeTimer = setTimeout(reconnect, 8000)
      socket.onopen = () => { clearTimeout(handshakeTimer); failures = 0; connection('connected') }
      socket.onclose = reconnect
      socket.onerror = reconnect
      socket.onmessage = (e) => {
        if (typeof e.data !== 'string') return
        let msg: any
        try { msg = JSON.parse(e.data) } catch { return }
        session.onMessage(msg)
      }
    } catch { reconnect() }
  }
  connect()
  return session
}

export async function resumeComfyTask(params: {
  task: ComfyTaskHandle
  apiKey: string
  timeoutSec: number
  onProgress?: (p: GenerationProgress) => void
  signal?: AbortSignal
}): Promise<GenerationResult> {
  return trackComfyTask(params)
}

// WS drives updates; history confirms results and recovers missed events.
async function trackComfyTask(params: {
  task: ComfyTaskHandle
  apiKey: string
  timeoutSec: number
  onProgress?: (p: GenerationProgress) => void
  signal?: AbortSignal
}, workflow: Record<string, any> = {}, existingSocket?: ComfySocketSession): Promise<GenerationResult> {
  const { task, apiKey, signal } = params
  const ctrl = new AbortController()
  const abort = () => ctrl.abort()
  signal?.addEventListener('abort', abort, { once: true })
  if (signal?.aborted) abort()
  const deadline = setTimeout(abort, Math.max(1, params.timeoutSec || 600) * 1000)
  let progress: GenerationProgress = { stage: 'queue', message: '正在确认 ComfyUI 任务状态…', connection: 'connecting' }
  const report = (next: Partial<GenerationProgress>) => {
    progress = { ...progress, ...next }
    params.onProgress?.(progress)
  }
  let socket = existingSocket
  let nextHistoryAt = 0
  let nextQueueAt = 0
  let queueRequested = true
  let terminalRetries = 0
  let terminalFailure: any[] | undefined
  let wakePending = false
  let wakeWait: (() => void) | undefined
  const wake = () => { wakePending = true; wakeWait?.() }
  const reconcile = () => { nextHistoryAt = 0; queueRequested = true; wake() }
  const activate = () => { if (document.visibilityState === 'visible') reconcile() }
  const interval = () => socket?.connection === 'connected' ? 30000 : 3000
  const wait = (ms: number): Promise<void> => {
    if (wakePending) { wakePending = false; return Promise.resolve() }
    return new Promise((resolve, reject) => {
      const done = () => { clearTimeout(timer); ctrl.signal.removeEventListener('abort', stop); wakeWait = undefined }
      const finish = () => { done(); wakePending = false; resolve() }
      const stop = () => { done(); reject(new DOMException('已停止跟踪', 'AbortError')) }
      const timer = setTimeout(finish, Math.max(0, ms))
      wakeWait = finish
      ctrl.signal.addEventListener('abort', stop, { once: true })
      if (ctrl.signal.aborted) stop()
    })
  }
  // Both per-request and tracking deadlines cover body reads, not only response headers.
  async function read(path: string, image = false): Promise<any> {
    const request = new AbortController()
    const stop = () => request.abort()
    ctrl.signal.addEventListener('abort', stop, { once: true })
    if (ctrl.signal.aborted) stop()
    const timer = setTimeout(stop, image ? 60000 : 15000)
    try {
      const headers = new Headers()
      if (apiKey.trim()) headers.set('Authorization', `Bearer ${apiKey.trim()}`)
      const res = await fetch(`${task.baseUrl}${path}`, { headers, signal: request.signal })
      if (res.status === 401 || res.status === 403) throw new ComfyTaskError(`[ComfyUI] 访问被拒绝 (HTTP ${res.status})，请检查凭据和来源后恢复任务。`, task, 'auth')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return image ? await res.blob() : await res.json()
    } finally { clearTimeout(timer); ctrl.signal.removeEventListener('abort', stop) }
  }
  try {
    checkTrackingSignal(ctrl.signal)
    socket ??= openComfySocket(task, apiKey)
    socket.onMessage = (msg) => {
      const d = msg?.data
      if (msg?.type === 'status') {
        queueRequested = true
        wake()
        return
      }
      if (!d || d.prompt_id !== task.promptId) return
      if (msg.type === 'executing' && d.node) {
        const title = workflow[d.node]?._meta?.title || workflow[d.node]?.class_type || d.node
        report({ stage: 'running', message: `正在执行：${title}`, percent: undefined })
      } else if (msg.type === 'progress' && d.max > 0) {
        report({ stage: 'running', message: `当前节点（${d.value}/${d.max}）`, percent: Math.round(d.value / d.max * 100) })
      } else if (msg.type === 'execution_start' || msg.type === 'execution_cached' || msg.type === 'executed') {
        report({ stage: 'running', message: msg.type === 'execution_cached' ? '正在复用已缓存节点…' : msg.type === 'executed' ? '节点已完成，继续执行工作流…' : 'ComfyUI 开始执行任务…', percent: undefined })
      }
      if (['execution_success', 'execution_error', 'execution_interrupted'].includes(msg.type) || (msg.type === 'executing' && d.node === null)) {
        if (msg.type === 'execution_error' || msg.type === 'execution_interrupted') terminalFailure = [[msg.type, d]]
        // execution_success precedes the history write; retry briefly while it lands.
        terminalRetries = 6
        reconcile()
      }
    }
    socket.onConnection = (connection) => {
      const wasConnected = progress.connection === 'connected'
      report({ connection })
      if (connection === 'connected' || wasConnected) reconcile()
      else { nextHistoryAt = Math.min(nextHistoryAt, Date.now() + 3000); wake() }
    }
    report({ connection: socket.connection })
    window.addEventListener('online', reconcile)
    document.addEventListener('visibilitychange', activate)
    for (;;) {
      checkTrackingSignal(ctrl.signal)
      if (Date.now() >= nextHistoryAt) {
        nextHistoryAt = Date.now() + interval()
        let item: any
        try { item = (await read(`/history/${encodeURIComponent(task.promptId)}`))?.[task.promptId] } catch (error) {
          if (error instanceof ComfyTaskError) throw error
          checkTrackingSignal(ctrl.signal)
          report({ message: '任务状态查询暂时失败，正在重试…' })
          nextHistoryAt = Math.min(nextHistoryAt, Date.now() + 3000)
        }
        if (item?.status?.status_str === 'error') throw new ComfyTaskError(formatExecutionError(item.status.messages, workflow).text, task, 'failed')
        if (!item || (item.status && item.status.completed === false && item.status.status_str !== 'success')) {
          if (terminalRetries > 0) {
            terminalRetries--
            nextHistoryAt = Math.min(nextHistoryAt, Date.now() + 500)
          } else if (terminalFailure) {
            throw new ComfyTaskError(formatExecutionError(terminalFailure, workflow).text, task, 'failed')
          }
          queueRequested = true
        } else {
          let outImg: { filename: string; subfolder?: string; type?: string } | undefined
          for (const nodeOut of Object.values<any>(item.outputs || {})) {
            for (const im of nodeOut?.images || []) {
              if (im?.filename && (!outImg || (im.type === 'output' && outImg.type !== 'output'))) outImg = im
            }
          }
          if (!outImg) {
            if (item.status?.completed) throw new ComfyTaskError('[ComfyUI] 工作流完成但没有输出图片，请检查 SaveImage 节点。', task, 'failed')
            nextHistoryAt = Math.min(nextHistoryAt, Date.now() + 3000)
          } else {
            report({ stage: 'download', message: '正在获取生成结果…', percent: undefined })
            const qs = new URLSearchParams({ filename: outImg.filename, subfolder: outImg.subfolder || '', type: outImg.type || 'output' })
            let blob: Blob | undefined
            try { blob = await read(`/view?${qs.toString()}`, true) } catch (error) {
              if (error instanceof ComfyTaskError) throw error
              checkTrackingSignal(ctrl.signal)
              report({ message: '图片下载暂时失败，正在重试…' })
              nextHistoryAt = Math.min(nextHistoryAt, Date.now() + 3000)
            }
            if (blob) {
              if (!blob.size || !blob.type.startsWith('image/')) throw new ComfyTaskError('[ComfyUI] 生成结果不是有效图片，可恢复后重新下载。', task)
              const imageUrl = await blobToDataUrl(blob)
              checkTrackingSignal(ctrl.signal)
              return { imageUrl, modelUsed: 'ComfyUI 工作流', providerUsed: 'comfyui' }
            }
          }
        }
      }
      if (queueRequested && Date.now() >= nextQueueAt) {
        queueRequested = false
        nextQueueAt = Date.now() + 3000
        try {
          const q = await read('/queue')
          const pending = (q?.queue_pending || []).findIndex((x: any) => x?.[1] === task.promptId)
          if (pending >= 0) report({ stage: 'queue', message: `排队中，前方还有 ${pending + (q.queue_running?.length || 0)} 个任务`, percent: undefined })
          else if ((q?.queue_running || []).some((x: any) => x?.[1] === task.promptId)) {
            if (progress.stage !== 'running') report({ stage: 'running', message: 'ComfyUI 正在执行任务…', percent: undefined })
          } else report({ message: '暂未在队列或历史中找到任务，继续确认…', percent: undefined })
        } catch (error) {
          if (error instanceof ComfyTaskError) throw error
          checkTrackingSignal(ctrl.signal)
          report({ message: '队列查询暂时失败，正在等待任务状态…' })
        }
      }
      await wait(Math.min(nextHistoryAt, queueRequested ? nextQueueAt : Infinity) - Date.now())
    }
  } catch (error) {
    if (error instanceof ComfyTaskError) throw error
    const message = ctrl.signal.aborted
      ? signal?.aborted ? '[ComfyUI] 已停止跟踪，后台任务继续执行，可恢复查看。' : '[ComfyUI] 等待结果超时，后台任务继续执行，可恢复查看。'
      : error instanceof Error ? error.message : '[ComfyUI] 跟踪任务失败，可恢复查看。'
    throw new ComfyTaskError(message, task, ctrl.signal.aborted && !signal?.aborted ? 'timeout' : 'tracking')
  } finally {
    socket?.close()
    clearTimeout(deadline)
    signal?.removeEventListener('abort', abort)
    window.removeEventListener('online', reconcile)
    document.removeEventListener('visibilitychange', activate)
  }
}

async function generateWithComfyUi(params: {
  recipe: RecipeState
  prompt: string
  config: ApiConfig
  baseUrl: string
  apiKey: string
  onProgress?: (p: GenerationProgress) => void
  onSubmitting?: (prepared?: PreparedComfyGeneration) => Promise<void>
  onSubmitted?: (task: ComfyTaskHandle) => Promise<void>
  signal?: AbortSignal
}): Promise<{ imageUrl: string; modelUsed: string; providerUsed: ImageProviderId }> {
  const { recipe, prompt, config, baseUrl, apiKey } = params
  const report = params.onProgress ?? (() => {})
  const cp = config.comfyuiParams
  const timeoutSec = Math.max(60, cp.timeoutSec || 600)
  const parsedInfo = parseComfyWorkflowNodes(cp.workflowJson)
  if (!parsedInfo.valid) {
    throw new Error(`[ComfyUI] ${parsedInfo.error || '工作流 JSON 无效'}`)
  }

  // 0. 预检：服务在线 + 节点/模型与本机匹配
  report({ stage: 'check', message: '正在检查 ComfyUI 服务与模型…' })
  await testComfyConnection(baseUrl, apiKey)
  const schemas = await fetchComfyObjectInfo(baseUrl, apiKey, cp.workflowJson)
  const extraImageNodes = getWorkflowImages(cp.workflowJson, [cp.portraitNodeId, cp.costumeNodeId, cp.poseNodeId, cp.stitchedNodeId], schemas)
  const extraImages = recipe.workflowImagesIdentity === workflowIdentity(cp.workflowJson) ? recipe.workflowImages || {} : {}
  const selectedJson = applyWorkflowOverrides(cp.workflowJson, cp.parameterOverrides, schemas)
  const check = await checkComfyWorkflow(baseUrl, apiKey, selectedJson, [
    cp.portraitNodeId,
    cp.costumeNodeId,
    cp.poseNodeId,
    cp.stitchedNodeId,
    ...extraImageNodes.filter((node) => extraImages[node.nodeId]?.url || (node.optional && node.role === 'character_sheet')).map((node) => node.nodeId),
  ], schemas)
  if (!check.ok) {
    throw new Error(`[ComfyUI] 工作流与本机不匹配：\n${check.errors.join('\n')}`)
  }
  const workflow: ComfyWorkflow = JSON.parse(check.fixedJson ?? selectedJson)

  // 1. 按映射槽位上传参考图并注入节点
  const slotUploads: Array<{ nodeId: string; src: string | null; prefix: string; label: string }> = [
    {
      nodeId: cp.portraitNodeId,
      src: recipe.portrait ? recipe.portrait.原图 || recipe.portrait.缩略图 : null,
      prefix: 'studio_portrait',
      label: '人像',
    },
    {
      nodeId: cp.costumeNodeId,
      src: recipe.costume ? recipe.costume.预览图 || recipe.costume.原图 || recipe.costume.缩略图 : null,
      prefix: 'studio_costume',
      label: '服装',
    },
    {
      nodeId: cp.poseNodeId,
      src: recipe.pose ? poseImagePath(recipe.pose) : null,
      prefix: 'studio_pose',
      label: '姿势',
    },
  ]
  const combinationError = validateReferenceCombinations(cp.workflowJson, [
    ...slotUploads.filter((slot) => slot.src && slot.nodeId && slot.nodeId !== 'none').map((slot) => slot.nodeId),
    ...extraImageNodes.filter((node) => extraImages[node.nodeId]?.url).map((node) => node.nodeId),
  ])
  if (combinationError) throw new Error(`[ComfyUI] ${combinationError}`)

  const invalidSlots = slotUploads.filter((slot) => slot.nodeId && slot.nodeId !== 'none' && !parsedInfo.imageNodes.some((node) => node.id === slot.nodeId))
  if (invalidSlots.length) {
    throw new Error(`[ComfyUI] ${invalidSlots.map((slot) => slot.label).join('、')}节点映射已失效，请重新识别或选择节点`)
  }
  const missingSlots = slotUploads.filter((slot) => slot.nodeId && slot.nodeId !== 'none' && !slot.src && parsedInfo.imageNodes.find((node) => node.id === slot.nodeId)?.emptyValue === undefined)
  if (missingSlots.length) {
    throw new Error(`[ComfyUI] 请先选择或上传：${missingSlots.map((slot) => slot.label).join('、')}`)
  }

  for (const slot of slotUploads) {
    if (!slot.nodeId || slot.nodeId === 'none' || !workflow[slot.nodeId]?.inputs) continue
    if (!slot.src) {
      const emptyValue = parsedInfo.imageNodes.find((node) => node.id === slot.nodeId)?.emptyValue
      if (emptyValue !== undefined) {
        workflow[slot.nodeId].inputs.image = emptyValue
        continue
      }
      throw new Error(`当前工作流需要「${slot.label}」参考图（节点 ${slot.nodeId}），请先在图库中选择`)
    }
    report({ stage: 'upload', message: `正在上传${slot.label}参考图…` })
    workflow[slot.nodeId].inputs.image = await uploadImageToComfy(baseUrl, slot.src, slot.prefix, apiKey)
  }

  for (const node of extraImageNodes) {
    const image = extraImages[node.nodeId]
    if (!image?.url) {
      if (node.optional && node.role === 'character_sheet') workflow[node.nodeId].inputs.image = '无'
      continue
    }
    report({ stage: 'upload', message: `正在上传${node.label}…` })
    workflow[node.nodeId].inputs.image = await uploadImageToComfy(baseUrl, image.url, 'studio_reference', apiKey)
  }

  if (cp.stitchedNodeId && cp.stitchedNodeId !== 'none' && workflow[cp.stitchedNodeId]?.inputs) {
    report({ stage: 'upload', message: '正在上传参考拼图…' })
    const stitchedDataUrl = await stitchRecipeCanvas(recipe)
    workflow[cp.stitchedNodeId].inputs.image = await uploadImageToComfy(baseUrl, stitchedDataUrl, 'studio_stitched', apiKey)
  }

  // 2. 注入提示词节点
  if (cp.promptNodeId && cp.promptNodeId !== 'none' && workflow[cp.promptNodeId]?.inputs) {
    const inputs = workflow[cp.promptNodeId].inputs
    for (const field of ['prompt', 'text', 'string', 'positive']) {
      if (typeof inputs[field] === 'string') {
        inputs[field] = prompt
        break
      }
    }
  }

  // 3. 随机化种子
  if (cp.randomizeSeed) {
    const nextSeed = Math.floor(Math.random() * 90000000000000) + 1000000
    for (const node of Object.values<any>(workflow)) {
      if (!node?.inputs) continue
      if (typeof node.inputs.seed === 'number') node.inputs.seed = nextSeed
      if (typeof node.inputs.noise_seed === 'number') node.inputs.noise_seed = nextSeed
    }
  }

  // /prompt is not idempotent: never retry an ambiguous submission.
  checkTrackingSignal(params.signal)
  await params.onSubmitting?.({ workflow: JSON.parse(JSON.stringify(workflow)) })
  checkTrackingSignal(params.signal)
  const clientId = `pose_studio_${crypto.randomUUID()}`
  const submittedAt = Date.now()
  report({ stage: 'queue', message: '正在提交工作流…' })
  // Subscribe before submission; HTTP reconciliation covers events received before prompt_id is known.
  const socket = openComfySocket({ baseUrl, clientId }, apiKey)
  try {
    let promptRes: Response
    let promptJson: any
    const submission = new AbortController()
    const abortSubmission = () => submission.abort()
    params.signal?.addEventListener('abort', abortSubmission, { once: true })
    if (params.signal?.aborted) abortSubmission()
    const submissionTimer = setTimeout(abortSubmission, 60000)
    try {
      const headers = new Headers({ 'Content-Type': 'application/json' })
      if (apiKey.trim()) headers.set('Authorization', `Bearer ${apiKey.trim()}`)
      promptRes = await fetch(`${baseUrl}/prompt`, {
        method: 'POST', headers,
        body: JSON.stringify({ prompt: workflow, client_id: clientId }),
        signal: submission.signal,
      })
      promptJson = await readJsonSafe(promptRes)
    } catch { throw new ComfySubmissionUnknownError() } finally {
      clearTimeout(submissionTimer)
      params.signal?.removeEventListener('abort', abortSubmission)
    }
    if (!promptRes.ok) {
      if (promptRes.status >= 500) throw new ComfySubmissionUnknownError()
      throw new ComfySubmissionRejectedError(formatComfyPromptError(promptJson, workflow, promptRes.status), promptRes.status)
    }
    if (typeof promptJson?.prompt_id !== 'string' || !promptJson.prompt_id) throw new ComfySubmissionUnknownError()
    const task: ComfyTaskHandle = { promptId: promptJson.prompt_id, clientId, baseUrl, submittedAt }
    try { await params.onSubmitted?.(task) } catch {
      throw new ComfyTaskError('[ComfyUI] 任务已提交，但保存恢复记录失败。请保留任务编号后恢复，勿重复提交。', task, 'storage')
    }
    return await trackComfyTask({ task, apiKey, timeoutSec, onProgress: params.onProgress, signal: params.signal }, workflow, socket)
  } finally { socket.close() }
}

export async function generateCharacterImage(params: {
  recipe: RecipeState
  prompt: string
  config: ApiConfig
  onProgress?: (p: GenerationProgress) => void
  onSubmitting?: (prepared?: PreparedComfyGeneration) => Promise<void>
  onSubmitted?: (task: ComfyTaskHandle) => Promise<void>
  signal?: AbortSignal
}): Promise<{ imageUrl: string; modelUsed: string; providerUsed: ImageProviderId }> {
  const { recipe, prompt, config, onProgress } = params
  const provider = config.activeProvider
  const pCfg = config.providers[provider]
  const apiKey = pCfg.apiKey.trim()

  const rawSources = [
    recipe.portrait && (recipe.portrait.原图 || recipe.portrait.缩略图),
    recipe.costume && (recipe.costume.预览图 || recipe.costume.原图 || recipe.costume.缩略图),
    recipe.pose && poseImagePath(recipe.pose),
    ...(recipe.extraImages || []).map((x) => x.url),
    ...(recipe.workflowImagesIdentity === workflowIdentity(config.comfyuiParams.workflowJson)
      ? Object.values(recipe.workflowImages || {}).map((image) => image.url) : []),
  ].filter(Boolean) as string[]

  if (!rawSources.length) {
    throw new Error('请先选择或上传至少 1 张参考图')
  }

  const baseUrl = (pCfg.baseUrl.trim() || PROVIDER_META[provider].defaultBaseUrl).replace(/\/+$/, '')

  return generateWithComfyUi({ recipe, prompt, config, baseUrl, apiKey, onProgress, onSubmitting: params.onSubmitting, onSubmitted: params.onSubmitted, signal: params.signal })
}
