import { createContext, type ReactNode, useContext, useEffect, useEffectEvent, useRef, useState } from 'react'
import { toast } from 'sonner'
import { isNsfwCostume, isNsfwPose } from '@/api/gallery'
import { fetchHistory } from '@/api/history'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { idbRead, idbWrite } from '@/lib/idbStorage'
import { parseParameterWorkflow, workflowIdentity } from '@/lib/comfyWorkflowParameters'
import { recipeBackup } from '@/lib/recipeImages'
import { buildRecipePrompt, PROVIDER_META, stitchRecipeCanvas } from '@/services/aiGenerator'
import {
  describeJobProgress,
  isJobSucceeded,
  jobErrorMessages,
  jobResultUrls,
  pollJob,
  submitRecipe,
  type ActiveJobInfo,
  type GenerationProgress,
  type JobSnapshotDto,
  type RecipeSubmitRequest,
} from '@/services/recipeClient'
import type {
  ApiConfig,
  ComfyUiParams,
  CostumeItem,
  ExtraReferenceImage,
  GenerationHistoryItem,
  ImageProviderId,
  PortraitItem,
  PoseItem,
  ProviderEndpointConfig,
  RecipeState,
} from '@/types/gallery'

const CFG_KEY = 'pose_atlas_api_config_v3'
const RECIPE_KEY = 'pose_atlas_recipe_v3'
// 仅保留常量供旧记录导出复用同一 key；本模块不再读写该 IndexedDB 历史。
export const HISTORY_KEY = 'pose_atlas_history_v3'
const TASK_KEY = 'pose_atlas_active_task_v1'
const SAFE_MODE_KEY = 'pose_atlas_safe_mode_v1'
// 18+ 首次确认标记：确认一次后本浏览器不再弹年龄确认框。
// 顶栏「18+ 完整模式 → 安全模式」即撤销该确认（下次解锁会重新询问）。
const NSFW_CONFIRMED_KEY = 'pose_atlas_nsfw_confirmed_v1'

/** 后端 `RecipeRequest.seed` 的固定种子默认值与后端保持一致。 */
const DEFAULT_RECIPE_SEED = 100000
/** 任务完成但快照无结果图时，回退取画廊最新一条。 */
const LATEST_IMAGE_ENDPOINT = '/api/images?page=1&page_size=1&sort=newest'

/** 提交给后端的画风只有两项；旧 12 条预设统一降级为写实。 */
type RecipeStyle = 'none' | 'realistic'

function toRecipeStyle(preset: string): RecipeStyle {
  return preset === 'none' ? 'none' : 'realistic'
}

function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === 'AbortError') ||
    (error instanceof Error && error.name === 'AbortError')
  )
}

/** 任务已进入失败终态（与网络抖动区分：失败终态才清除恢复记录）。 */
class JobFailedError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'JobFailedError'
  }
}

/**
 * 旧 `TASK_KEY` 结构为 `{task: {promptId, clientId, baseUrl}}`，无法映射到
 * 后端的数字 jobId；读取时安全迁移为 null，避免刷新后反复尝试已失效的直连任务。
 */
function migrateActiveJob(raw: unknown): ActiveJobInfo | null {
  if (!raw || typeof raw !== 'object') return null
  const record = raw as Record<string, unknown>
  if ('task' in record) return null
  const jobId = typeof record.jobId === 'number' ? record.jobId : Number(record.jobId)
  if (!Number.isInteger(jobId) || jobId <= 0) return null
  return {
    jobId,
    prompt: typeof record.prompt === 'string' ? record.prompt : '',
    summary: typeof record.summary === 'string' ? record.summary : '',
    submittedAt: typeof record.submittedAt === 'number' ? record.submittedAt : Date.now(),
  }
}

/**
 * 仅当图片地址明确位于 uploads 目录时才转成 `*_path`。
 * `data:`、参考库图片和媒体端点都无法可靠映射为后端 uploads 路径。
 */
function toUploadPath(url: string): string {
  const match = /(?:^|\/)uploads\/(.+)$/.exec(url)
  return match ? `uploads/${match[1]}` : ''
}

/**
 * 第 4 张参考（计划 2.3.5-4）：库标识与条目 id 同时存在才发送 `extra_*`；
 * 否则只在图片明确位于 uploads 内时发送 `extra_path`；两者都没有则不发送。
 */
function resolveExtraFields(
  extra?: ExtraReferenceImage
): Pick<RecipeSubmitRequest, 'extra_library' | 'extra_id' | 'extra_path'> {
  if (!extra) return {}
  if (extra.library && extra.id) {
    return { extra_library: extra.library, extra_id: extra.id }
  }
  const uploadPath = toUploadPath(extra.url)
  return uploadPath ? { extra_path: uploadPath } : {}
}

/** 结果快照无图时回退到画廊最新一条 `view_url`；失败不抛错。 */
async function fetchLatestPreviewUrl(): Promise<string> {
  try {
    const response = await fetch(LATEST_IMAGE_ENDPOINT)
    if (!response.ok) return ''
    const body = (await response.json()) as { items?: Array<{ view_url?: string | null }> }
    const url = body?.items?.[0]?.view_url
    return typeof url === 'string' ? url : ''
  } catch {
    return ''
  }
}

function readNsfwConfirmed(): boolean {
  try {
    return localStorage.getItem(NSFW_CONFIRMED_KEY) === 'true'
  } catch {
    return false
  }
}

function writeNsfwConfirmed(confirmed: boolean): void {
  try {
    if (confirmed) localStorage.setItem(NSFW_CONFIRMED_KEY, 'true')
    else localStorage.removeItem(NSFW_CONFIRMED_KEY)
  } catch {
    // 隐私模式/存储被禁用时降级为每次解锁都确认，不影响功能
  }
}

const COMFY_CONFIG_VERSION = 3

const DEFAULT_API_CONFIG: ApiConfig = {
  activeProvider: 'comfyui',
  stylePreset: 'realistic',
  providers: {
    comfyui: {
      baseUrl: PROVIDER_META.comfyui.defaultBaseUrl,
      apiKey: '',
      model: PROVIDER_META.comfyui.models[0].value,
      customModel: '',
    },
  },
  comfyuiParams: {
    // 空串表示「尚未选择本机工作流」：studio 会在拉取 /api/workflows 后
    // 自动选中后端推荐的工作流并载入其 JSON。
    workflowPreset: '',
    workflowJson: '',
    promptNodeId: 'none',
    portraitNodeId: 'none',
    costumeNodeId: 'none',
    poseNodeId: 'none',
    stitchedNodeId: 'none',
    randomizeSeed: true,
    timeoutSec: 600,
    configVersion: COMFY_CONFIG_VERSION,
  },
}

// v1 → v2：旧版默认的 Qwen 2.1 预设引用了本机通常不存在的模型，自动切换为 Qwen Image Edit 2509
const LEGACY_COMFY_BASE_URLS = ['http://127.0.0.1:8188', 'http://localhost:8188']

// 旧版前端写死的 4 条 Qwen 模板已删除：升级后一律标记为失效，
// 由 studio 从 /api/workflows 重新选择本机实际可用的工作流。
// 用正则匹配旧 id 家族（qwen + 年份 + 图数），不在源码/产物中保留完整旧 id 字面量。
const LEGACY_WORKFLOW_PRESET_PATTERN = /^qwen(?:2509|21)_(?:2|3)img$/

function isLegacyWorkflowPreset(value: string): boolean {
  return LEGACY_WORKFLOW_PRESET_PATTERN.test(value)
}

function migrateComfy(
  provider: ApiConfig['providers']['comfyui'],
  params: ApiConfig['comfyuiParams']
): { provider: ApiConfig['providers']['comfyui']; params: ApiConfig['comfyuiParams'] } {
  const nextParams = { ...params }
  const nextProvider = { ...provider }

  // 1) 清理旧内置模板残留（无论 configVersion 是否已是最新：当前线上版本就是 3）。
  //    只清工作流相关字段，不碰用户的基地址、超时、随机种子等其它配置。
  if (isLegacyWorkflowPreset(String(nextParams.workflowPreset ?? ''))) {
    Object.assign(nextParams, {
      workflowPreset: '',
      workflowJson: '',
      promptNodeId: 'none',
      portraitNodeId: 'none',
      costumeNodeId: 'none',
      poseNodeId: 'none',
      stitchedNodeId: 'none',
      parameterOverrides: undefined,
    })
  }

  // 2) v1/v2 → v3：修正旧的 ComfyUI 地址与模型记录
  if ((nextParams.configVersion ?? 1) < COMFY_CONFIG_VERSION) {
    nextParams.configVersion = COMFY_CONFIG_VERSION
    if (!nextProvider.baseUrl.trim() || LEGACY_COMFY_BASE_URLS.includes(nextProvider.baseUrl.trim())) {
      nextProvider.baseUrl = PROVIDER_META.comfyui.defaultBaseUrl
    }
    if (!PROVIDER_META.comfyui.models.some((m) => m.value === nextProvider.model)) {
      nextProvider.model = PROVIDER_META.comfyui.models[0].value
    }
  }
  return { provider: nextProvider, params: nextParams }
}

function mergeStoredConfig(raw: unknown): ApiConfig {
  if (!raw || typeof raw !== 'object') return DEFAULT_API_CONFIG
  const obj = raw as Partial<ApiConfig>
  const comfy = migrateComfy(
    { ...DEFAULT_API_CONFIG.providers.comfyui, ...obj.providers?.comfyui },
    { ...DEFAULT_API_CONFIG.comfyuiParams, configVersion: 1, ...obj.comfyuiParams }
  )
  return {
    activeProvider: 'comfyui',
    stylePreset: obj.stylePreset ?? DEFAULT_API_CONFIG.stylePreset,
    providers: { comfyui: comfy.provider },
    comfyuiParams: comfy.params,
  }
}

interface StudioContextValue {
  hydrated: boolean
  activeTask: ActiveJobInfo | null
  resumeGeneration: () => Promise<void>
  stopTracking: () => Promise<void>
  recipe: RecipeState
  apiConfig: ApiConfig
  history: GenerationHistoryItem[]
  safeMode: boolean
  toggleSafeMode: () => void
  requestUnlockNsfw: (onUnlocked?: () => void) => void
  poseDepthMode: boolean
  setPoseDepthMode: (val: boolean) => void
  toggleRecipePoseDepth: () => void
  // 全局持久化的合成台状态（切换页面不丢失、不断开请求）
  customPrompt: string | null
  setCustomPrompt: (val: string | null) => void
  previewUrl: string
  setPreviewUrl: (url: string) => void
  isGenerating: boolean
  generatingModel: string
  generationProgress: GenerationProgress | null
  generationError: string
  startGeneration: (overridePrompt?: string) => Promise<void>
  refreshStitchPreview: () => Promise<void>
  setPortrait: (item: PortraitItem | null) => void
  setCostume: (item: CostumeItem | null) => void
  setPose: (item: PoseItem | null) => void
  togglePortrait: (item: PortraitItem) => void
  toggleCostume: (item: CostumeItem) => void
  togglePose: (item: PoseItem) => void
  addExtraImage: (item: { name: string; url: string }) => void
  removeExtraImage: (id: string) => void
  updateExtraImageName: (id: string, name: string) => void
  setWorkflowImage: (nodeId: string, image: ExtraReferenceImage | null, identity: string) => void
  clearRecipe: () => void
  randomizeRecipe: (pools: { portraits?: PortraitItem[]; costumes?: CostumeItem[]; poses?: PoseItem[] }) => void
  updateApiConfig: (patch: Partial<ApiConfig>) => void
  updateProviderConfig: (provider: ImageProviderId, patch: Partial<ProviderEndpointConfig>) => void

  updateComfyUiParams: (patch: Partial<ComfyUiParams>) => void

}

const StudioContext = createContext<StudioContextValue | null>(null)

export function StudioProvider({ children }: { children: ReactNode }) {
  const [recipe, setRecipe] = useState<RecipeState>(() => {
    try {
      const raw = localStorage.getItem(RECIPE_KEY)
      if (!raw) return { portrait: null, costume: null, pose: null, extraImages: [] }
      const parsed = JSON.parse(raw)
      return {
        portrait: parsed.portrait ?? null,
        costume: parsed.costume ?? null,
        pose: parsed.pose ?? null,
        extraImages: Array.isArray(parsed.extraImages) ? parsed.extraImages : [],
      }
    } catch {
      return { portrait: null, costume: null, pose: null, extraImages: [] }
    }
  })

  const [apiConfig, setApiConfig] = useState<ApiConfig>(() => {
    try {
      const raw = localStorage.getItem(CFG_KEY)
      return raw ? mergeStoredConfig(JSON.parse(raw)) : DEFAULT_API_CONFIG
    } catch {
      return DEFAULT_API_CONFIG
    }
  })

  // 生成记录改读后端画廊（GET /api/images）；这里是内存态，不再写 IndexedDB/localStorage。
  const [history, setHistory] = useState<GenerationHistoryItem[]>([])

  const [safeMode, setSafeMode] = useState<boolean>(() => {
    try {
      const raw = localStorage.getItem(SAFE_MODE_KEY)
      return raw === null ? true : raw !== 'false'
    } catch {
      return true
    }
  })
  const [ageGateOpen, setAgeGateOpen] = useState(false)
  const pendingUnlockCbRef = useRef<(() => void) | null>(null)
  const [poseDepthMode, setPoseDepthModeState] = useState<boolean>(() => Boolean(recipe.pose?.useDepth))

  // 提升到根部 Provider 的生成状态，路由切换不会卸载或中断
  const [customPrompt, setCustomPrompt] = useState<string | null>(null)
  // 初始为空；IDB 恢复完成后异步取后端最新一条历史作为初始预览。
  const [previewUrl, setPreviewUrl] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const [generatingModel, setGeneratingModel] = useState('')
  const [generationProgress, setGenerationProgress] = useState<GenerationProgress | null>(null)
  const [generationError, setGenerationError] = useState('')
  const isGeneratingRef = useRef(false)
  const [activeTask, setActiveTask] = useState<ActiveJobInfo | null>(null)
  const activeTaskRef = useRef<ActiveJobInfo | null>(null)
  const trackingRef = useRef<AbortController | null>(null)
  const styleDowngradeNotifiedRef = useRef(false)
  const [idbHydrated, setIdbHydrated] = useState(false)

  // 从 IndexedDB 异步恢复含附图的配方与未决任务（历史记录不再走 IDB）
  useEffect(() => {
    let active = true
    Promise.all([
      idbRead<RecipeState>(RECIPE_KEY),
      idbRead<unknown>(TASK_KEY),
    ]).then(([savedRecipe, savedTask]) => {
      if (!active) return
      if (savedRecipe) {
        if (savedRecipe.pose?.useDepth !== undefined) {
          setPoseDepthModeState(Boolean(savedRecipe.pose.useDepth))
        }
        setRecipe({
          portrait: savedRecipe.portrait ?? null,
          costume: savedRecipe.costume ?? null,
          pose: savedRecipe.pose ?? null,
          workflowImages: savedRecipe.workflowImages ?? {},
          workflowImagesIdentity: savedRecipe.workflowImagesIdentity,
          extraImages: Array.isArray(savedRecipe.extraImages) ? savedRecipe.extraImages : [],
        })
      }
      const restoredTask = migrateActiveJob(savedTask)
      activeTaskRef.current = restoredTask
      setActiveTask(restoredTask)
      // 旧直连任务结构无法恢复，顺手清空持久化记录，避免每次刷新重复判断。
      if (savedTask && !restoredTask) void idbWrite(TASK_KEY, null).catch(() => {})
      setIdbHydrated(true)
    }).catch(() => { if (active) toast.error('无法读取浏览器存储，已暂停生成以保护未决任务；请恢复存储后刷新') })
    return () => {
      active = false
    }
  }, [])

  // IDB 恢复后异步加载后端生成记录。失败只提示，不阻塞图库与合成台。
  useEffect(() => {
    if (!idbHydrated) return
    let active = true
    fetchHistory({ page: 1, pageSize: 30 })
      .then((items) => {
        if (!active) return
        setHistory(items)
        // 已有生成结果时保留当前预览，否则展示后端最新一条。
        setPreviewUrl((prev) => prev || items[0]?.imageUrl || '')
      })
      .catch((error: unknown) => {
        if (!active) return
        toast.error(error instanceof Error ? error.message : '加载生成记录失败：未知错误')
      })
    return () => {
      active = false
    }
  }, [idbHydrated])

  useEffect(() => {
    if (!idbHydrated) return
    void idbWrite(RECIPE_KEY, recipe).catch(() => toast.error('配方保存失败，请检查浏览器存储空间'))
    try {
      // 上传图片和附图完整保存在 IndexedDB，轻量备份不包含它们。
      localStorage.setItem(
        RECIPE_KEY,
        JSON.stringify(recipeBackup(recipe))
      )
    } catch {}
  }, [recipe, idbHydrated])

  useEffect(() => {
    try {
      localStorage.setItem(CFG_KEY, JSON.stringify(apiConfig))
    } catch {}
  }, [apiConfig])

  useEffect(() => {
    try {
      localStorage.setItem(SAFE_MODE_KEY, String(safeMode))
    } catch {}
  }, [safeMode])

  /** 完成解锁：切换安全模式并执行调用方回调（不写确认标记）。 */
  const unlockNsfw = (onUnlocked?: () => void) => {
    pendingUnlockCbRef.current = null
    setSafeMode(false)
    toast.success('已解锁 18+ 完整图库模式')
    onUnlocked?.()
  }

  const requestUnlockNsfw = (onUnlocked?: () => void) => {
    if (!safeMode) {
      onUnlocked?.()
      return
    }
    // 已在本浏览器确认过年满 18 周岁：直接解锁，不再重复弹窗。
    if (readNsfwConfirmed()) {
      unlockNsfw(onUnlocked)
      return
    }
    pendingUnlockCbRef.current = onUnlocked || null
    setAgeGateOpen(true)
  }

  const confirmUnlockNsfw = () => {
    // 仅首次确认写入标记，此后所有解锁都走 readNsfwConfirmed() 短路，不再弹窗。
    // 需要重新确认时不设 UI 入口：清除本站点 localStorage（或站点数据）即可重置。
    writeNsfwConfirmed(true)
    setAgeGateOpen(false)
    unlockNsfw(pendingUnlockCbRef.current ?? undefined)
  }

  const toggleSafeMode = () => {
    if (safeMode) {
      requestUnlockNsfw()
    } else {
      // 切回安全模式只切换显示，不影响 18+ 确认标记：下次解锁仍直接放行。
      setSafeMode(true)
      toast.success('已开启安全模式（已隐藏 18+ 敏感分类）')
    }
  }

  const setPortrait = (portrait: PortraitItem | null) => setRecipe((r) => ({ ...r, portrait }))
  const setCostume = (costume: CostumeItem | null) => setRecipe((r) => ({ ...r, costume }))
  const setPose = (pose: PoseItem | null) => setRecipe((r) => ({ ...r, pose }))

  const setPoseDepthMode = (val: boolean) => {
    setPoseDepthModeState(val)
    setRecipe((r) => {
      if (!r.pose || r.pose.source === 'upload' || Boolean(r.pose.useDepth) === val) return r
      return { ...r, pose: { ...r.pose, useDepth: val } }
    })
  }

  const toggleRecipePoseDepth = () => {
    const next = !(recipe.pose?.useDepth ?? poseDepthMode)
    setPoseDepthMode(next)
    toast.success(next ? '已切换姿势图为：深度图 (Depth)' : '已切换姿势图为：素体白模')
  }

  const togglePortrait = (item: PortraitItem) => {
    const remove = recipe.portrait?.id === item.id
    setRecipe((r) => ({ ...r, portrait: remove ? null : item }))
    toast.success(remove ? '已移除人像' : `已选人像：${item.发型名称}`)
  }
  const toggleCostume = (item: CostumeItem) => {
    const remove = recipe.costume?.id === item.id
    setRecipe((r) => ({ ...r, costume: remove ? null : item }))
    toast.success(remove ? '已移除服装' : `已选服装：${item.服装名称}`)
  }
  const togglePose = (item: PoseItem) => {
    const useDepth = item.source === 'upload' ? false : (item.useDepth ?? poseDepthMode)
    const remove = recipe.pose?.id === item.id && Boolean(recipe.pose?.useDepth) === useDepth
    setRecipe((r) => ({ ...r, pose: remove ? null : { ...item, useDepth } }))
    toast.success(remove ? '已移除姿势' : `已选姿势：${item.姿势名称}（${item.角度}${useDepth ? ' · 深度图' : ''}）`)
  }

  const addExtraImage = (item: { name: string; url: string }) => {
    const newImg: ExtraReferenceImage = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      name: item.name || '附加参考',
      url: item.url,
    }
    setRecipe((r) => ({
      ...r,
      extraImages: [...(r.extraImages || []), newImg],
    }))
    toast.success('已添加附加参考图')
  }

  const removeExtraImage = (id: string) => {
    setRecipe((r) => ({
      ...r,
      extraImages: (r.extraImages || []).filter((x) => x.id !== id),
    }))
  }

  const updateExtraImageName = (id: string, name: string) => {
    setRecipe((r) => ({
      ...r,
      extraImages: (r.extraImages || []).map((x) => (x.id === id ? { ...x, name } : x)),
    }))
  }

  const setWorkflowImage = (nodeId: string, image: ExtraReferenceImage | null, identity: string) => {
    if (identity !== workflowIdentity(apiConfig.comfyuiParams.workflowJson)) return
    setRecipe((r) => {
      const workflowImages = r.workflowImagesIdentity === identity ? { ...r.workflowImages } : {}
      if (image) workflowImages[nodeId] = image
      else delete workflowImages[nodeId]
      return { ...r, workflowImages, workflowImagesIdentity: identity }
    })
  }

  const activeComfyParams = apiConfig.comfyuiParams
  useEffect(() => {
    if (!idbHydrated) return
    const cp = activeComfyParams
    const identity = workflowIdentity(cp.workflowJson)
    const workflow = parseParameterWorkflow(cp.workflowJson)
    const mapped = [cp.portraitNodeId, cp.costumeNodeId, cp.poseNodeId, cp.stitchedNodeId]
    const ids = new Set(Object.entries(workflow || {}).filter(([id, node]) => !mapped.includes(id) && typeof node.inputs.image === 'string').map(([id]) => id))
    // IndexedDB 恢复与工作流变更同步时清理失效映射。
    // oxlint-disable-next-line react/set-state-in-effect
    setRecipe((r) => {
      const entries = Object.entries(r.workflowImages || {})
      const kept = r.workflowImagesIdentity === identity ? entries.filter(([id]) => ids.has(id)) : []
      if (entries.length === kept.length && r.workflowImagesIdentity === identity) return r
      return { ...r, workflowImages: Object.fromEntries(kept), workflowImagesIdentity: identity }
    })
  }, [activeComfyParams, idbHydrated])

  const clearRecipe = () => {
    setRecipe({ portrait: null, costume: null, pose: null, extraImages: [] })
    toast.success('已清空配方')
  }

  const randomizeRecipe = (pools: { portraits?: PortraitItem[]; costumes?: CostumeItem[]; poses?: PoseItem[] }) => {
    const posePool = safeMode ? (pools.poses || []).filter((p) => !isNsfwPose(p)) : pools.poses || []
    // 服装池不再按来源排除 charadb：缓存就绪的二次元条目可参与出图，只按 nsfw 过滤。
    const costumePool = safeMode ? (pools.costumes || []).filter((c) => !isNsfwCostume(c)) : pools.costumes || []
    const portraitPool = pools.portraits || []

    setRecipe((prev) => ({
      ...prev,
      portrait: portraitPool.length
        ? portraitPool[Math.floor(Math.random() * portraitPool.length)]
        : prev.portrait,
      costume: costumePool.length
        ? costumePool[Math.floor(Math.random() * costumePool.length)]
        : prev.costume,
      pose: posePool.length
        ? { ...posePool[Math.floor(Math.random() * posePool.length)], useDepth: poseDepthMode }
        : prev.pose,
    }))
    toast.success(safeMode ? '已随机抽取一套角色配方（安全模式）' : '已随机抽取一套角色配方')
  }

  const updateApiConfig = (patch: Partial<ApiConfig>) => {
    setApiConfig((prev) => ({ ...prev, ...patch }))
  }

  const updateProviderConfig = (provider: ImageProviderId, patch: Partial<ProviderEndpointConfig>) => {
    setApiConfig((prev) => ({
      ...prev,
      providers: {
        ...prev.providers,
        [provider]: {
          ...prev.providers[provider],
          ...patch,
        },
      },
    }))
  }


  const updateComfyUiParams = (patch: Partial<ComfyUiParams>) => {
    setApiConfig((prev) => ({ ...prev, comfyuiParams: { ...prev.comfyuiParams, ...patch } }))
  }


  const refreshStitchPreview = async () => {
    try {
      const url = await stitchRecipeCanvas(recipe)
      setPreviewUrl(url)
      toast.success('已合成参考拼图')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '拼图失败')
    }
  }

  const saveActive = async (value: ActiveJobInfo | null) => {
    await idbWrite(TASK_KEY, value)
    activeTaskRef.current = value
    setActiveTask(value)
  }

  /**
   * 终态快照 → 预览图：优先取任务结果图；成功但无图时回退画廊最新一条；
   * 失败终态抛 JobFailedError，调用方据此清除恢复记录。
   */
  const applyJobSnapshot = async (snapshot: JobSnapshotDto): Promise<boolean> => {
    const urls = jobResultUrls(snapshot)
    if (urls.length) {
      setPreviewUrl(urls[0])
      return true
    }
    if (!isJobSucceeded(snapshot)) {
      const errors = jobErrorMessages(snapshot)
      const status = String(snapshot?.status ?? '').trim() || '未知状态'
      throw new JobFailedError(errors.length ? errors.join('；') : `出图任务失败（${status}）`)
    }
    const fallback = await fetchLatestPreviewUrl()
    if (fallback) {
      setPreviewUrl(fallback)
      return true
    }
    return false
  }

  const completeGeneration = async (snapshot: JobSnapshotDto, signal: AbortSignal) => {
    signal.throwIfAborted()
    // 结果图直接使用后端同源 URL（/api/media/image?...），生成记录由后端画廊提供。
    const found = await applyJobSnapshot(snapshot)
    signal.throwIfAborted()
    await saveActive(null)
    if (found) {
      toast.success('角色图已完成并保存')
    } else {
      setGenerationProgress({ stage: 'download', message: '任务完成但未找到结果图，请前往任务中心查看' })
      toast.info('任务完成但未找到结果图，请前往任务中心查看')
    }
  }

  const resumeGeneration = async () => {
    const record = activeTaskRef.current
    if (!record?.jobId || isGeneratingRef.current) return
    isGeneratingRef.current = true
    setIsGenerating(true)
    setGenerationError('')
    setGenerationProgress({ stage: 'queued', message: '正在恢复任务状态…' })
    const controller = new AbortController()
    trackingRef.current = controller
    try {
      const snapshot = await pollJob(record.jobId, {
        signal: controller.signal,
        onUpdate: (next) => setGenerationProgress(describeJobProgress(next)),
      })
      controller.signal.throwIfAborted()
      await completeGeneration(snapshot, controller.signal)
    } catch (e) {
      if (e instanceof JobFailedError) {
        try { await saveActive(null) } catch { toast.error('任务记录清除失败') }
      }
      if (!controller.signal.aborted) setGenerationError(e instanceof Error ? e.message : '无法确认任务状态，记录已保留')
    } finally {
      isGeneratingRef.current = false
      setIsGenerating(false)
      if (trackingRef.current === controller) trackingRef.current = null
    }
  }

  const stopTracking = async () => {
    trackingRef.current?.abort()
    try { await saveActive(null); setGenerationError('已停止跟踪；后端任务可能仍在执行，请先确认队列再提交新任务') }
    catch { toast.error('停止跟踪记录保存失败') }
  }

  const resumeOnActivation = useEffectEvent(() => { void resumeGeneration() })
  // 刷新、重新激活与恢复联网只查询已有任务，不重新提交。
  useEffect(() => {
    if (!idbHydrated) return
    const resume = () => {
      if (document.visibilityState === 'visible' && activeTaskRef.current?.jobId && !isGeneratingRef.current) resumeOnActivation()
    }
    resume()
    window.addEventListener('online', resume)
    document.addEventListener('visibilitychange', resume)
    return () => { window.removeEventListener('online', resume); document.removeEventListener('visibilitychange', resume) }
  }, [idbHydrated])
  useEffect(() => () => trackingRef.current?.abort(), [])

  const startGeneration = async (overridePrompt?: string) => {
    if (!idbHydrated || isGeneratingRef.current) return
    if (activeTaskRef.current) { toast.error('存在未决任务，请先恢复或明确停止跟踪'); return }

    const recipeSnapshot = recipe
    const configSnapshot = apiConfig

    // 上传图（base64）尚未接入后端 uploads：提交前拦截，保留拼图与预览能力。
    const uploadSlots = [
      recipeSnapshot.portrait?.source === 'upload' ? '人像' : '',
      recipeSnapshot.costume?.source === 'upload' ? '服装' : '',
      recipeSnapshot.pose?.source === 'upload' ? '姿势' : '',
    ].filter(Boolean)
    if (uploadSlots.length) {
      toast.error('请从图库选择参考图；本地图片上传暂未接入后端')
      return
    }

    // 后端要求三个槽位全部存在（C-REF-RECIPES@2），缺失时直接提示，避免无谓请求。
    const missingSlots = [
      recipeSnapshot.portrait ? '' : '人像',
      recipeSnapshot.costume ? '' : '服装',
      recipeSnapshot.pose ? '' : '姿势',
    ].filter(Boolean)
    if (missingSlots.length) {
      toast.error(`请先选择：${missingSlots.join('、')}`)
      return
    }

    const localPrompt = buildRecipePrompt(
      recipeSnapshot,
      configSnapshot.stylePreset,
      recipeSnapshot.workflowImagesIdentity === workflowIdentity(configSnapshot.comfyuiParams.workflowJson)
        ? Object.values(recipeSnapshot.workflowImages || {})
        : []
    )
    // textarea 的完整提示词只用于本地预览；仅「独立补充要求」作为 prompt_suffix 提交。
    const requestedPrompt = overridePrompt ?? customPrompt ?? ''
    const promptSuffix = requestedPrompt && requestedPrompt !== localPrompt ? requestedPrompt : ''
    const style = toRecipeStyle(configSnapshot.stylePreset)
    if (style !== configSnapshot.stylePreset && !styleDowngradeNotifiedRef.current) {
      styleDowngradeNotifiedRef.current = true
      toast.info('当前画风不在后端支持范围，本次按「写实人像写真」提交')
    }

    const summary =
      [recipeSnapshot.portrait?.发型名称, recipeSnapshot.costume?.服装名称, recipeSnapshot.pose?.姿势名称]
        .filter(Boolean)
        .join(' + ') || '自定义合成'

    const request: RecipeSubmitRequest = {
      style,
      seed: DEFAULT_RECIPE_SEED,
      seed_mode: configSnapshot.comfyuiParams.randomizeSeed ? 'random' : 'fixed',
      ...(promptSuffix.trim() ? { prompt_suffix: promptSuffix.trim() } : {}),
      ...(recipeSnapshot.portrait ? { portrait_id: recipeSnapshot.portrait.id } : {}),
      ...(recipeSnapshot.costume
        ? {
            costume_id: recipeSnapshot.costume.id,
            costume_library: recipeSnapshot.costume.library ?? 'costume',
          }
        : {}),
      ...(recipeSnapshot.pose ? { pose_id: recipeSnapshot.pose.id } : {}),
      ...resolveExtraFields(recipeSnapshot.extraImages?.[0]),
    }

    isGeneratingRef.current = true
    setIsGenerating(true)
    setGeneratingModel(configSnapshot.activeProvider)
    setGenerationError('')
    setGenerationProgress({ stage: 'submit', message: '正在提交出图任务…' })

    const controller = new AbortController()
    trackingRef.current = controller
    try {
      const submitted = await submitRecipe(request)
      controller.signal.throwIfAborted()
      if (!submitted?.success || !submitted.job_id) {
        const detail = submitted?.errors?.filter(Boolean).join('；') || '后端未返回任务编号'
        throw new JobFailedError(detail)
      }

      const record: ActiveJobInfo = {
        jobId: submitted.job_id,
        prompt: submitted.prompt || localPrompt,
        summary,
        submittedAt: Date.now(),
      }
      await saveActive(record)
      controller.signal.throwIfAborted()
      setGenerationProgress({ stage: 'queued', message: '任务已提交，等待后端处理…' })

      const snapshot = await pollJob(submitted.job_id, {
        signal: controller.signal,
        onUpdate: (next) => setGenerationProgress(describeJobProgress(next)),
      })
      controller.signal.throwIfAborted()
      await completeGeneration(snapshot, controller.signal)
    } catch (e) {
      if (!isAbortError(e)) {
        if (e instanceof JobFailedError) {
          try { await saveActive(null) } catch { toast.error('任务失败记录未能清除，请停止跟踪后重试') }
        }
        const msg = e instanceof Error ? e.message : '调用失败'
        setGenerationError(msg)
        toast.error(msg.split('\n')[0])
      }
    } finally {
      isGeneratingRef.current = false
      setIsGenerating(false)
      if (trackingRef.current === controller) trackingRef.current = null
    }
  }

  return (
    <StudioContext.Provider
      value={{
        hydrated: idbHydrated,
        activeTask, resumeGeneration, stopTracking,
        recipe,
        apiConfig,
        history,
        safeMode,
        toggleSafeMode,
        requestUnlockNsfw,
        poseDepthMode,
        setPoseDepthMode,
        toggleRecipePoseDepth,
        customPrompt,
        setCustomPrompt,
        previewUrl,
        setPreviewUrl,
        isGenerating,
        generatingModel,
        generationProgress,
        generationError,
        startGeneration,
        refreshStitchPreview,
        setPortrait,
        setCostume,
        setPose,
        togglePortrait,
        toggleCostume,
        togglePose,
        addExtraImage,
        removeExtraImage,
        updateExtraImageName,
        setWorkflowImage,
        clearRecipe,
        randomizeRecipe,
        updateApiConfig,
        updateProviderConfig,

        updateComfyUiParams,

      }}
    >
      {children}

      <AlertDialog open={ageGateOpen} onOpenChange={setAgeGateOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>18+ 内容确认</AlertDialogTitle>
            <AlertDialogDescription className="space-y-2 text-left leading-relaxed">
              <span className="block">
                关闭安全模式后，图库将显示成人向艺术参考，仅供合法的 AI 绘画学习与创作使用。
              </span>
              <span className="block">
                须年满 18 周岁；禁止用于真人、未成年人，禁止图片再分发。
              </span>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              onClick={() => {
                pendingUnlockCbRef.current = null
              }}
            >
              保持安全模式
            </AlertDialogCancel>
            <AlertDialogAction onClick={confirmUnlockNsfw}>
              我已年满 18 周岁
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </StudioContext.Provider>
  )
}

// oxlint-disable-next-line react/only-export-components
export function useStudio() {
  const ctx = useContext(StudioContext)
  if (!ctx) throw new Error('useStudio must be used within StudioProvider')
  return ctx
}
