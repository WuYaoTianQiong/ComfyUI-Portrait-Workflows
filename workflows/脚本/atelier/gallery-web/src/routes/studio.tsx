import { ImageViewer } from '@/components/common/ImageViewer'
import { useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import {
  ChevronDownIcon,
  CircleAlertIcon,
  CircleCheckIcon,
  ChevronUpIcon,
  CodeXmlIcon,
  CopyIcon,
  DicesIcon,
  DownloadIcon,
  ExternalLinkIcon,
  FileUpIcon,
  ImagePlusIcon,
  KeyRoundIcon,
  LayoutGridIcon,
  LinkIcon,
  LoaderCircleIcon,
  PersonStandingIcon,
  ScanSearchIcon,
  RotateCcwIcon,
  ShirtIcon,
  SlidersHorizontalIcon,
  SparklesIcon,

  UserRoundIcon,
  XIcon,
} from 'lucide-react'
import { type ChangeEvent, type DragEvent, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { costumesQuery, portraitsQuery, posesQuery } from '@/api/gallery'
import {
  fetchWorkflowCatalog,
  fetchWorkflowContent,
  type WorkflowCatalogItem,
} from '@/api/workflows'
import { Field, Section } from '@/components/common/FormSection'
import { WorkflowParameters } from '@/components/studio/WorkflowParameters'
import { applyWorkflowOverrides, workflowIdentity } from '@/lib/comfyWorkflowParameters'
import { PageHeader } from '@/components/common/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import {
  autoDetectComfyMappings,
  buildRecipePrompt,
  type ComfyCheckResult,
  checkComfyWorkflow,
  detectComfyUi,
  fileToDataUrl,
  fetchComfyObjectInfo,
  parseComfyWorkflowNodes,

  stitchRecipeCanvas,
  STYLE_PRESETS,
} from '@/services/aiGenerator'
import { poseImagePath, poseThumbPath, referenceImageUrl, uploadedReferences } from '@/lib/recipeImages'
import { useStudio } from '@/store/studioStore'


export const Route = createFileRoute('/studio')({
  staticData: { title: 'AI 合成台' },
  component: StudioPage,
})

/** 与后端 STYLE_PRESETS 对齐的画风选项；其余旧画风提交时降级为 realistic。 */
const STYLE_PRESET_OPTIONS = ['none', 'realistic'] as const

/** 未决任务提交时间展示：时间戳缺失或非法时给出可读回退，避免渲染 Invalid Date。 */
function formatSubmittedAt(timestamp: number): string {
  const date = new Date(timestamp)
  return Number.isNaN(date.getTime()) ? '时间未知' : date.toLocaleString('zh-CN', { hour12: false })
}

function StudioPage() {
  const {
    hydrated, activeTask, resumeGeneration, stopTracking,
    recipe,
    apiConfig,
    history,
    customPrompt,
    setCustomPrompt,
    previewUrl,
    isGenerating,
    generatingModel,
    generationProgress,
    generationError,
    startGeneration,
    setPortrait,
    setCostume,
    setPose,
    toggleRecipePoseDepth,
    addExtraImage,
    removeExtraImage,
    updateExtraImageName,
    updateApiConfig,
    updateProviderConfig,

    updateComfyUiParams,
    randomizeRecipe,

  } = useStudio()
  const qc = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const comfyFileInputRef = useRef<HTMLInputElement | null>(null)
  const slotInputRef = useRef<HTMLInputElement | null>(null)
  const uploadSlotRef = useRef<'portrait' | 'costume' | 'pose'>('portrait')
  const [uploadingSlot, setUploadingSlot] = useState<string | null>(null)


  const providerCfg = apiConfig.providers.comfyui

  // 后端 recipes 只支持 none / realistic（C-REF-RECIPES@2）：
  // 旧画风配置一律按写实预览与提交，避免下拉显示与后端出图不一致。
  const submitStylePreset = apiConfig.stylePreset === 'none' ? 'none' : 'realistic'

  const activeWorkflowImages = recipe.workflowImagesIdentity === workflowIdentity(apiConfig.comfyuiParams.workflowJson) ? Object.values(recipe.workflowImages || {}) : []
  const defaultPrompt = buildRecipePrompt(recipe, submitStylePreset, activeWorkflowImages)
  const prompt = customPrompt ?? defaultPrompt
  const [showAdvanced, setShowAdvanced] = useState(false)
  // 只读预览由槽位生成；提交只发送这段独立的补充要求（prompt_suffix）。
  const [promptSuffix, setPromptSuffix] = useState('')
  const [extraUrlInput, setExtraUrlInput] = useState('')
  const [showUrlInput, setShowUrlInput] = useState(false)
  const [stitchModalUrl, setStitchModalUrl] = useState<string | null>(null)
  const [zoomImageUrl, setZoomImageUrl] = useState<string | null>(null)
  const [showComfyJsonModal, setShowComfyJsonModal] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [comfyCheck, setComfyCheck] = useState<(ComfyCheckResult & { info?: string }) | null>(null)
  const [checkingComfy, setCheckingComfy] = useState(false)

  // 本机工作流列表（/api/workflows）：选中后再按需加载 JSON 内容。
  const [workflowList, setWorkflowList] = useState<WorkflowCatalogItem[]>([])
  const [workflowListLoading, setWorkflowListLoading] = useState(true)
  const [workflowListError, setWorkflowListError] = useState('')
  const [loadingWorkflowPath, setLoadingWorkflowPath] = useState<string | null>(null)
  const autoSelectingRef = useRef(false)
  // 列表可能晚于用户操作完成，用 ref 读取最新的配置，避免异步闭包拿到旧值。
  const apiConfigRef = useRef(apiConfig)
  useEffect(() => {
    apiConfigRef.current = apiConfig
  }, [apiConfig])

  // 当前选中工作流在目录里的元信息（来源 / 相对路径 / 图片槽位数），用于下拉下方的说明行
  const selectedWorkflow = workflowList.find(
    (w) => w.path === apiConfig.comfyuiParams.workflowPreset
  )

  const parsedComfyNodes = useMemo(
    () => parseComfyWorkflowNodes(apiConfig.comfyuiParams.workflowJson),
    [apiConfig.comfyuiParams.workflowJson]
  )

  /** 读取一个本机工作流并写入 comfyuiParams；失败时保留当前配置，不把下拉置空。 */
  const loadWorkflowIntoConfig = async (path: string, fallbackName?: string): Promise<boolean> => {
    setLoadingWorkflowPath(path)
    setComfyCheck(null)
    try {
      const data = await fetchWorkflowContent(path)
      const workflowJson = JSON.stringify(data.content, null, 2)
      updateComfyUiParams({
        workflowPreset: path,
        workflowJson,
        ...autoDetectComfyMappings(workflowJson),
      })
      toast.success(`已加载工作流：${data.name || fallbackName || path}`)
      return true
    } catch (e) {
      toast.error(`加载工作流失败：${e instanceof Error ? e.message : '未知错误'}`)
      return false
    } finally {
      setLoadingWorkflowPath(null)
    }
  }

  /** 拉取本机工作流列表；若当前选中项已失效（旧内置模板/文件被删），自动回落到默认工作流。 */
  const loadWorkflowList = async () => {
    setWorkflowListLoading(true)
    setWorkflowListError('')
    try {
      // 合成台只看"能塞参考图"的工作流（参考库专用 + 画廊旧版 + 库根里的编辑类），
      // 文生图 / 超分这类会被后端过滤掉，避免选中后才报「工作流与本机不匹配」。
      const data = await fetchWorkflowCatalog('studio')
      setWorkflowList(data.workflows)

      const current = apiConfigRef.current.comfyuiParams.workflowPreset
      const usable = current === 'custom' || data.workflows.some((w) => w.path === current)
      if (!usable && !autoSelectingRef.current) {
        // 优先用后端下发的 default（通常文件名含「文生图」）；它缺失或不在列表中时
        // 回落到 mtime 最新的第一条，保证下拉始终有可用的选中项。
        const preferred =
          data.workflows.find((w) => w.path === data.default) ?? data.workflows[0]
        if (preferred) {
          autoSelectingRef.current = true
          try {
            await loadWorkflowIntoConfig(preferred.path, preferred.name)
          } finally {
            autoSelectingRef.current = false
          }
        }
      }
    } catch (e) {
      setWorkflowListError(e instanceof Error ? e.message : '未知错误')
    } finally {
      setWorkflowListLoading(false)
    }
  }

  useEffect(() => {
    void loadWorkflowList()
    // 只在挂载时拉取一次；重试由错误提示里的按钮触发。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleSelectWorkflow = (value: string) => {
    setComfyCheck(null)
    if (value === 'custom') {
      updateComfyUiParams({ workflowPreset: 'custom' })
      return
    }
    void loadWorkflowIntoConfig(value)
  }

  // 自动识别 ComfyUI 地址 + 检测工作流所需节点/模型是否在本机存在
  const handleCheckComfy = async () => {
    setCheckingComfy(true)
    setComfyCheck(null)
    try {
      const cfg = apiConfig.providers.comfyui
      const found = await detectComfyUi(cfg.baseUrl, cfg.apiKey)
      if (!found) {
        setComfyCheck({
          ok: false,
          errors: [
            `未找到可用的 ComfyUI 服务（已尝试：${cfg.baseUrl || '默认地址'}、127.0.0.1:8000、127.0.0.1:8188）。请确认 ComfyUI 已启动，并检查跨域 (CORS) 设置。`,
          ],
          warnings: [],
          fixes: [],
        })
        return
      }
      if (found.baseUrl !== cfg.baseUrl.trim().replace(/\/+$/, '')) {
        updateProviderConfig('comfyui', { baseUrl: found.baseUrl })
        toast.success(`已自动识别 ComfyUI 地址：${found.baseUrl}`)
      }
      const cp = apiConfig.comfyuiParams
      const result = await checkComfyWorkflow(found.baseUrl, cfg.apiKey, cp.workflowJson, [
        cp.portraitNodeId,
        cp.costumeNodeId,
        cp.poseNodeId,
        cp.stitchedNodeId,
      ])
      // 自动修复仅用于提交副本，保留导入的原始 API。
      setComfyCheck({ ...result, info: `${found.info}（${found.baseUrl}）` })
    } catch (e) {
      setComfyCheck({ ok: false, errors: [e instanceof Error ? e.message : '检测失败'], warnings: [], fixes: [] })
    } finally {
      setCheckingComfy(false)
    }
  }

  const handleComfyFileUpload = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    try {
      const text = await file.text()
      const info = parseComfyWorkflowNodes(text)
      if (!info.valid) {
        toast.error(info.error || '工作流 JSON 无效')
        return
      }
      const detected = autoDetectComfyMappings(text)
      setComfyCheck(null)
      updateComfyUiParams({
        workflowPreset: 'custom',
        workflowJson: text,
        ...detected,
      })
      setShowAdvanced(true)
      toast.success(
        `已导入工作流：识别到 ${info.imageNodes.length} 个图片节点、${info.promptNodes.length} 个提示词节点`
      )
    } catch {
      toast.error('读取 JSON 文件失败')
    }
  }

  const handleExportComfyJson = async (original = false) => {
    try {
      const cp = apiConfig.comfyuiParams
      const schemas = !original && cp.parameterOverrides?.workflowId === workflowIdentity(cp.workflowJson) ? await fetchComfyObjectInfo(providerCfg.baseUrl, providerCfg.apiKey, cp.workflowJson) : undefined
      const wf = JSON.parse(original ? cp.workflowJson : applyWorkflowOverrides(cp.workflowJson, cp.parameterOverrides, schemas))
      if (!original && cp.promptNodeId && cp.promptNodeId !== 'none' && wf[cp.promptNodeId]?.inputs) {
        const inputs = wf[cp.promptNodeId].inputs
        for (const field of ['prompt', 'text', 'string', 'positive']) {
          if (typeof inputs[field] === 'string') {
            inputs[field] = prompt
            break
          }
        }
      }
      const blob = new Blob([JSON.stringify(wf, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `comfyui-workflow-${Date.now()}.api.json`
      a.click()
      URL.revokeObjectURL(url)
      toast.success('已导出 ComfyUI API 工作流 JSON')
    } catch {
      toast.error('当前工作流 JSON 格式有误，无法导出')
    }
  }

  const handleSlotUpload = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    const slot = uploadSlotRef.current
    e.target.value = ''
    if (!file) return
    if (!file.type.startsWith('image/')) {
      toast.error('请选择图片文件')
      return
    }
    setUploadingSlot(slot)
    try {
      const url = await fileToDataUrl(file)
      const image = new Image()
      image.src = url
      await image.decode()
      const name = file.name.replace(/\.[^.]+$/, '') || '上传图片'
      const items = uploadedReferences(name, url, image.width, image.height, file.size)
      if (slot === 'portrait') setPortrait(items.portrait)
      if (slot === 'costume') setCostume(items.costume)
      if (slot === 'pose') setPose(items.pose)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '图片读取失败')
    } finally {
      setUploadingSlot(null)
    }
  }

  // 后端 recipes 只接受图库条目 id：上传图当前只能本地预览，提交会被拦截。
  const uploadedSlots = [
    recipe.portrait?.source === 'upload' ? '人像' : '',
    recipe.costume?.source === 'upload' ? '服装' : '',
    recipe.pose?.source === 'upload' ? '姿势' : '',
  ].filter(Boolean)

  // 后端只在任务有总量时给 percent；这里再夹紧一次，避免脏数据画出越界进度条。
  const rawPercent = generationProgress?.percent
  const progressValue =
    typeof rawPercent === 'number' && Number.isFinite(rawPercent)
      ? Math.min(100, Math.max(0, Math.round(rawPercent)))
      : null

  const extraImages = recipe.extraImages || []
  const hasStitchRefs = Boolean(recipe.portrait || recipe.costume || recipe.pose || extraImages.length > 0)
  const hasAnyRef = hasStitchRefs || activeWorkflowImages.length > 0

  const processFiles = async (files: File[]) => {
    const imgFiles = files.filter((f) => f.type.startsWith('image/'))
    if (!imgFiles.length) return
    try {
      for (const file of imgFiles) {
        const dataUrl = await fileToDataUrl(file)
        const baseName = file.name.replace(/\.[^.]+$/, '').slice(0, 16)
        addExtraImage({ name: baseName || '附加图', url: dataUrl })
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '图片读取失败')
    }
  }

  // 支持在合成台直接 Cmd+V / Ctrl+V 粘贴剪贴板图片作为附加参考图
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const target = e.target as HTMLElement | null
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) return
      const items = Array.from(e.clipboardData?.items || [])
      const files = items
        .filter((it) => it.type.startsWith('image/'))
        .map((it) => it.getAsFile())
        .filter(Boolean) as File[]
      if (files.length > 0) {
        e.preventDefault()
        void processFiles(files)
      }
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  })

  const handleRandom = async () => {
    const [posesRes, costumes, portraits] = await Promise.all([
      qc.ensureQueryData(posesQuery),
      qc.ensureQueryData(costumesQuery),
      qc.ensureQueryData(portraitsQuery),
    ])
    randomizeRecipe({
      poses: posesRes.items,
      costumes,
      portraits,
    })
  }

  const handleUploadFiles = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    await processFiles(files)
    e.target.value = ''
  }

  const handleDropFiles = async (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(false)
    const files = Array.from(e.dataTransfer.files || [])
    await processFiles(files)
  }

  const handleAddUrl = () => {
    const trimmed = extraUrlInput.trim()
    if (!trimmed) return
    if (!/^https?:\/\//i.test(trimmed) && !trimmed.startsWith('data:image/')) {
      toast.error('请输入有效的 http(s):// 图片链接')
      return
    }
    addExtraImage({ name: '外部参考图', url: trimmed })
    setExtraUrlInput('')
    setShowUrlInput(false)
  }

  const handleOpenStitchModal = async () => {
    try {
      const url = await stitchRecipeCanvas(recipe)
      setStitchModalUrl(url)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '拼图失败')
    }
  }

  // 提交不再做节点映射校验：槽位由后端固定节点映射解析，参数面板只影响本地预览。
  // 只把独立补充要求作为 prompt_suffix 发出；空串用于覆盖可能存在的历史复用词，
  // 避免把 textarea 里的完整提示词当成补充要求重复提交。
  const handleGenerate = () => {
    void startGeneration(promptSuffix.trim())
  }

  return (
    <>
      <PageHeader
        title="AI 角色合成台"
        actions={
          <Button variant="outline" size="sm" asChild>
            <Link to="/settings">
              <KeyRoundIcon className="size-4" />
              ComfyUI 设置
            </Link>
          </Button>
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12 lg:gap-6">
        {/* 左栏：参考图、模型参数与 Prompt */}
        <div
          className="flex min-w-0 flex-col gap-4 lg:col-span-7"
          onDragOver={(e) => {
            e.preventDefault()
            setIsDragging(true)
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDropFiles}
        >
          {/* 1. 参考图组合 */}
          <Section
            title="1. 参考图组合"
            className="@lg/section:grid-cols-1"
            actions={
              <div className="flex flex-wrap items-center gap-1.5">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  multiple
                  className="hidden"
                  onChange={handleUploadFiles}
                />
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 px-2.5 text-xs"
                  onClick={handleRandom}
                >
                  <DicesIcon className="size-3.5" />
                  随机
                </Button>
                {hasAnyRef && hasStitchRefs && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-8 px-2.5 text-xs"
                    onClick={handleOpenStitchModal}
                  >
                    <LayoutGridIcon className="size-3.5" />
                    参考拼图
                  </Button>
                )}
              </div>
            }
          >

            <input ref={slotInputRef} type="file" accept="image/*" className="hidden" onChange={handleSlotUpload} />

            {/* 3 个核心图库槽位：手机端单列舒展展示，平板/桌面端三列并排 */}
            <div className="grid min-w-0 grid-cols-1 gap-2 @min-[42rem]/section:grid-cols-3">
              {/* 人像槽 */}
              <div className="relative flex min-w-0 items-start gap-2.5 rounded-xl bg-background p-2.5">
                {recipe.portrait ? (
                  <>
                    <button type="button" aria-label="放大人像参考图" className="shrink-0 cursor-zoom-in overflow-hidden rounded-lg transition-opacity hover:opacity-80 focus-visible:outline-2 focus-visible:outline-ring" onClick={() => {
                      const item = recipe.portrait
                      if (item) setZoomImageUrl(referenceImageUrl(item.原图 || item.缩略图))
                    }}>
                      <img
                        src={referenceImageUrl(recipe.portrait.缩略图)}
                        alt={recipe.portrait.标题}
                        className="h-12 w-10 shrink-0 rounded-lg object-cover"
                      />
                    </button>
                    <div className="flex min-h-12 min-w-0 flex-1 flex-col justify-between gap-1">
                      <div className="flex items-center justify-between gap-1">
                        <span className="shrink-0 text-[11px] text-muted-foreground">人像</span>
                        <button
                          type="button"
                          aria-label="清除人像参考图"
                          onClick={() => setPortrait(null)}
                          className="-mr-0.5 -mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
                        >
                          <XIcon className="size-3.5" />
                        </button>
                      </div>
                      <div className="line-clamp-2 text-xs font-medium leading-snug" title={recipe.portrait.发型名称}>
                        {recipe.portrait.发型名称}
                      </div>
                    </div>
                  </>
                ) : (
                  <>
                    <Link
                      to="/portraits"
                      className="flex min-h-12 min-w-0 flex-1 items-center gap-2 rounded-lg text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
                    >
                      <div className="flex h-10 w-8 shrink-0 items-center justify-center rounded-lg bg-muted">
                        <UserRoundIcon className="size-4" />
                      </div>
                      <span className="truncate text-xs">+ 选人像</span>
                    </Link>
                    <Button type="button" variant="ghost" size="sm" aria-label="上传人像参考图" aria-busy={uploadingSlot === 'portrait'} disabled={uploadingSlot !== null} className="h-12 shrink-0 border-l px-2 text-xs" onClick={() => { uploadSlotRef.current = 'portrait'; slotInputRef.current?.click() }}>
                      {uploadingSlot === 'portrait' ? <LoaderCircleIcon className="size-3.5 animate-spin motion-reduce:animate-none" /> : <ImagePlusIcon className="size-3.5" />}
                      {uploadingSlot === 'portrait' ? '处理中' : '上传'}
                    </Button>
                  </>
                )}
              </div>

              {/* 服装槽 */}
              <div className="relative flex min-w-0 items-start gap-2.5 rounded-xl bg-background p-2.5">
                {recipe.costume ? (
                  <>
                    <button type="button" aria-label="放大服装参考图" className="shrink-0 cursor-zoom-in overflow-hidden rounded-lg transition-opacity hover:opacity-80 focus-visible:outline-2 focus-visible:outline-ring" onClick={() => {
                      const item = recipe.costume
                      if (item) setZoomImageUrl(referenceImageUrl(item.预览图 || item.原图 || item.缩略图))
                    }}>
                      <img
                        src={referenceImageUrl(recipe.costume.缩略图)}
                        alt={recipe.costume.服装名称}
                        className="h-12 w-10 shrink-0 rounded-lg object-cover"
                      />
                    </button>
                    <div className="flex min-h-12 min-w-0 flex-1 flex-col justify-between gap-1">
                      <div className="flex items-center justify-between gap-1">
                        <span className="shrink-0 text-[11px] text-muted-foreground">服装</span>
                        <button
                          type="button"
                          aria-label="清除服装参考图"
                          onClick={() => setCostume(null)}
                          className="-mr-0.5 -mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
                        >
                          <XIcon className="size-3.5" />
                        </button>
                      </div>
                      <div className="line-clamp-2 text-xs font-medium leading-snug" title={recipe.costume.服装名称}>
                        {recipe.costume.服装名称}
                      </div>
                    </div>
                  </>
                ) : (
                  <>
                    <Link
                      to="/costumes"
                      className="flex min-h-12 min-w-0 flex-1 items-center gap-2 rounded-lg text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
                    >
                      <div className="flex h-10 w-8 shrink-0 items-center justify-center rounded-lg bg-muted">
                        <ShirtIcon className="size-4" />
                      </div>
                      <span className="truncate text-xs">+ 选服装</span>
                    </Link>
                    <Button type="button" variant="ghost" size="sm" aria-label="上传服装参考图" aria-busy={uploadingSlot === 'costume'} disabled={uploadingSlot !== null} className="h-12 shrink-0 border-l px-2 text-xs" onClick={() => { uploadSlotRef.current = 'costume'; slotInputRef.current?.click() }}>
                      {uploadingSlot === 'costume' ? <LoaderCircleIcon className="size-3.5 animate-spin motion-reduce:animate-none" /> : <ImagePlusIcon className="size-3.5" />}
                      {uploadingSlot === 'costume' ? '处理中' : '上传'}
                    </Button>
                  </>
                )}
              </div>

              {/* 姿势槽 */}
              <div className="relative flex min-w-0 items-start gap-2.5 rounded-xl bg-background p-2.5">
                {recipe.pose ? (
                  <>
                    <button type="button" aria-label="放大姿势参考图" className="shrink-0 cursor-zoom-in overflow-hidden rounded-lg transition-opacity hover:opacity-80 focus-visible:outline-2 focus-visible:outline-ring" onClick={() => {
                      const item = recipe.pose
                      if (item) setZoomImageUrl(referenceImageUrl(poseImagePath(item)))
                    }}>
                      <img
                        src={referenceImageUrl(poseThumbPath(recipe.pose))}
                        alt={recipe.pose.姿势名称}
                        className="h-12 w-10 shrink-0 rounded-lg object-cover"
                      />
                    </button>
                    <div className="flex min-h-12 min-w-0 flex-1 flex-col justify-between gap-1">
                      <div className="flex items-center justify-between gap-1">
                        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                          <span className="shrink-0 text-[11px] text-muted-foreground">姿势</span>
                          {recipe.pose.source !== 'upload' && (
                            <div
                              role="group"
                              aria-label="切换素体白模或深度图"
                              className="inline-flex shrink-0 items-center rounded-md border border-border/70 bg-muted/70 p-0.5 text-[10px] leading-none"
                            >
                              <button
                                type="button"
                                onClick={() => {
                                  if (recipe.pose?.useDepth) toggleRecipePoseDepth()
                                }}
                                className={`rounded px-1.5 py-0.5 font-medium transition ${
                                  !recipe.pose.useDepth
                                    ? 'bg-background text-foreground shadow-xs'
                                    : 'text-muted-foreground hover:text-foreground'
                                }`}
                              >
                                白模
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  if (!recipe.pose?.useDepth) toggleRecipePoseDepth()
                                }}
                                className={`rounded px-1.5 py-0.5 font-medium transition ${
                                  recipe.pose.useDepth
                                    ? 'bg-primary text-primary-foreground shadow-xs'
                                    : 'text-muted-foreground hover:text-foreground'
                                }`}
                              >
                                深度
                              </button>
                            </div>
                          )}
                        </div>
                        <button
                          type="button"
                          aria-label="清除姿势参考图"
                          onClick={() => setPose(null)}
                          className="-mr-0.5 -mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
                        >
                          <XIcon className="size-3.5" />
                        </button>
                      </div>
                      <div
                        className="line-clamp-2 text-xs font-medium leading-snug"
                        title={recipe.pose.角度 ? `${recipe.pose.姿势名称} · ${recipe.pose.角度}` : recipe.pose.姿势名称}
                      >
                        {recipe.pose.角度 ? `${recipe.pose.姿势名称} · ${recipe.pose.角度}` : recipe.pose.姿势名称}
                      </div>
                    </div>
                  </>
                ) : (
                  <>
                    <Link
                      to="/poses"
                      className="flex min-h-12 min-w-0 flex-1 items-center gap-2 rounded-lg text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
                    >
                      <div className="flex h-10 w-8 shrink-0 items-center justify-center rounded-lg bg-muted">
                        <PersonStandingIcon className="size-4" />
                      </div>
                      <span className="truncate text-xs">+ 选姿势</span>
                    </Link>
                    <Button type="button" variant="ghost" size="sm" aria-label="上传姿势参考图" aria-busy={uploadingSlot === 'pose'} disabled={uploadingSlot !== null} className="h-12 shrink-0 border-l px-2 text-xs" onClick={() => { uploadSlotRef.current = 'pose'; slotInputRef.current?.click() }}>
                      {uploadingSlot === 'pose' ? <LoaderCircleIcon className="size-3.5 animate-spin motion-reduce:animate-none" /> : <ImagePlusIcon className="size-3.5" />}
                      {uploadingSlot === 'pose' ? '处理中' : '上传'}
                    </Button>
                  </>
                )}
              </div>
            </div>

            {uploadedSlots.length > 0 && (
              <div
                role="note"
                className="rounded-lg border border-amber-500/40 bg-amber-500/8 px-3 py-2 text-xs leading-relaxed text-amber-700 dark:text-amber-300"
              >
                本地图片上传暂未接入后端，请从图库选择参考图（当前 {uploadedSlots.join('、')} 槽位是上传图，提交时会被拦截）。
              </div>
            )}

            {/* 附加参考图列表 + 可视化拖拽/粘贴上传框 */}
            <div className="space-y-2 pt-1">
              {extraImages.length > 0 && (
                <div className="grid min-w-0 grid-cols-1 gap-2 @min-[42rem]/section:grid-cols-3">
                  {extraImages.map((img, idx) => (
                    <div
                      key={img.id}
                      className="flex items-center gap-2 rounded-xl border border-border/60 bg-background p-1.5"
                    >
                      <img
                        src={img.url}
                        alt={img.name}
                        className="h-11 w-9 shrink-0 rounded-lg object-cover"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="text-[10px] text-muted-foreground">附图 #{idx + 1}</div>
                        <input
                          type="text"
                          value={img.name}
                          onChange={(e) => updateExtraImageName(img.id, e.target.value)}
                          placeholder="备注(如:配饰/背景)"
                          className="w-full truncate bg-transparent text-xs font-medium outline-none focus:underline"
                        />
                      </div>
                      <button
                        type="button"
                        onClick={() => removeExtraImage(img.id)}
                        className="rounded-full p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                      >
                        <XIcon className="size-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* 显式虚线上传/拖拽/粘贴提示区 */}
              <div
                onClick={() => fileInputRef.current?.click()}
                className={`flex cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border border-dashed px-3 py-2.5 text-center transition sm:flex-row sm:justify-between ${
                  isDragging
                    ? 'border-primary bg-primary/8 text-primary'
                    : 'border-border bg-background/60 text-muted-foreground hover:border-primary/50 hover:bg-background hover:text-foreground'
                }`}
              >
                <div className="flex items-center gap-2 text-xs">
                  <ImagePlusIcon className="size-4 shrink-0" />
                  <span>
                    {isDragging
                      ? '松开鼠标添加附加参考图'
                      : '添加附加参考图：点击上传、拖拽图片至此，或直接按 Ctrl+V / ⌘V 粘贴'}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    setShowUrlInput((s) => !s)
                  }}
                  className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium text-primary hover:bg-primary/10"
                >
                  <LinkIcon className="size-3" />
                  输入图片 URL
                </button>
              </div>

              {showUrlInput && (
                <div className="flex items-center gap-2">
                  <Input
                    value={extraUrlInput}
                    onChange={(e) => setExtraUrlInput(e.target.value)}
                    placeholder="粘贴 https://... 图片地址"
                    className="bg-background text-xs"
                    onKeyDown={(e) => e.key === 'Enter' && handleAddUrl()}
                  />
                  <Button size="sm" onClick={handleAddUrl}>
                    添加
                  </Button>
                </div>
              )}
            </div>
          </Section>

          {/* 2. 协议、模型与可折叠高级参数 */}
          <Section
            title="2. 模型与参数"
            actions={
              <Button variant="ghost" size="sm" onClick={() => setShowAdvanced((v) => !v)}>
                <SlidersHorizontalIcon className="size-3.5" />
                高级参数
                {showAdvanced ? (
                  <ChevronUpIcon className="size-3.5" />
                ) : (
                  <ChevronDownIcon className="size-3.5" />
                )}
              </Button>
            }
          >
            <Field label="工作流 (本机工作流目录)">
                <div className="space-y-2">
                  <Select
                    value={apiConfig.comfyuiParams.workflowPreset || undefined}
                    onValueChange={handleSelectWorkflow}
                    disabled={workflowListLoading}
                  >
                    <SelectTrigger className="w-full text-xs">
                      <SelectValue
                        placeholder={workflowListLoading ? '正在读取本机工作流…' : '选择本机工作流'}
                      />
                    </SelectTrigger>
                    <SelectContent>
                      {workflowList.map((workflow) => (
                        <SelectItem
                          key={workflow.path}
                          value={workflow.path}
                          className="text-xs"
                          textValue={`${workflow.source !== '库根' && !workflow.name.startsWith(workflow.source) ? `${workflow.source} · ` : ''}${workflow.name.replace(/\.api\.json$/i, '').replace(/\.json$/i, '')}${workflow.image_slots ? `（${workflow.image_slots} 图）` : ''}`}
                        >
                          {workflow.recommended && (
                            <span className="mr-1 inline-flex items-center rounded bg-emerald-500/15 px-1 py-0.5 text-[9px] font-medium leading-none text-emerald-600 align-middle">
                              推荐
                            </span>
                          )}
                          {workflow.source !== '库根' && !workflow.name.startsWith(workflow.source)
                            ? `${workflow.source} · `
                            : ''}
                          {workflow.name.replace(/\.api\.json$/i, '').replace(/\.json$/i, '')}
                          {workflow.image_slots ? `（${workflow.image_slots} 图）` : ''}
                        </SelectItem>
                      ))}
                      <SelectItem value="custom" className="text-xs">
                        自定义工作流 (已导入 JSON)
                      </SelectItem>
                    </SelectContent>
                  </Select>
                  {workflowListLoading && (
                    <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                      <LoaderCircleIcon className="size-3.5 animate-spin" />
                      正在读取本机工作流列表…
                    </p>
                  )}
                  {!workflowListLoading && workflowListError && (
                    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-destructive/40 bg-destructive/10 px-3 py-2 text-[11px] text-destructive">
                      <CircleAlertIcon className="size-3.5 shrink-0" />
                      <span className="break-all">读取工作流列表失败：{workflowListError}</span>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-6 px-2 text-[11px]"
                        onClick={() => void loadWorkflowList()}
                      >
                        重试
                      </Button>
                    </div>
                  )}
                  {!workflowListLoading && !workflowListError && workflowList.length === 0 && (
                    <p className="text-[11px] text-muted-foreground">
                      本机库目录中没有可用工作流，可手动导入 .json。
                    </p>
                  )}
                  {loadingWorkflowPath && (
                    <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                      <LoaderCircleIcon className="size-3.5 animate-spin" />
                      正在加载工作流 JSON…
                    </p>
                  )}
                  {selectedWorkflow && (
                    <p className="text-[11px] leading-relaxed text-muted-foreground">
                      {selectedWorkflow.source} · {selectedWorkflow.rel_path} · 图片槽位{' '}
                      {selectedWorkflow.image_slots}
                      {selectedWorkflow.image_slots !== 3 && (
                        <span className="text-amber-500">
                          {' '}
                          （不是「人像+服装+姿势」三槽，参考图会多出或缺一张）
                        </span>
                      )}
                    </p>
                  )}
                  <p className="text-[11px] leading-relaxed text-muted-foreground/80">
                    新增工作流：把 .api.json 放进库的「图库专用工作流/」（官方）或「我的工作流/」（自建），
                    刷新本页即出现；也可用下方「导入 .json」临时使用。
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    <input
                      ref={comfyFileInputRef}
                      type="file"
                      accept=".json,application/json"
                      onChange={handleComfyFileUpload}
                      className="hidden"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-7 px-2 text-xs"
                      onClick={() => comfyFileInputRef.current?.click()}
                    >
                      <FileUpIcon className="size-3.5" />
                      导入 .json
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-7 px-2 text-xs"
                      onClick={() => setShowComfyJsonModal(true)}
                    >
                      <CodeXmlIcon className="size-3.5" />
                      编辑 JSON
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-7 px-2 text-xs"
                      onClick={() => void handleExportComfyJson()}
                    >
                      <DownloadIcon className="size-3.5" />
                      导出 .json
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-7 px-2 text-xs"
                      onClick={handleCheckComfy}
                      disabled={checkingComfy}
                    >
                      {checkingComfy ? (
                        <LoaderCircleIcon className="size-3.5 animate-spin" />
                      ) : (
                        <ScanSearchIcon className="size-3.5" />
                      )}
                      检测本机模型
                    </Button>
                  </div>
                  {comfyCheck && (
                    <div
                      className={`space-y-1 rounded-xl border px-3 py-2 text-[11px] leading-relaxed ${
                        comfyCheck.ok
                          ? 'border-emerald-500/40 bg-emerald-500/8 text-emerald-700 dark:text-emerald-300'
                          : 'border-destructive/40 bg-destructive/10 text-destructive'
                      }`}
                    >
                      <div className="flex items-center gap-1.5 font-semibold">
                        {comfyCheck.ok ? (
                          <CircleCheckIcon className="size-3.5" />
                        ) : (
                          <CircleAlertIcon className="size-3.5" />
                        )}
                        {comfyCheck.ok ? '工作流与本机模型/节点匹配，可以生成' : '检测未通过'}
                      </div>
                      {comfyCheck.info && <div className="opacity-80">{comfyCheck.info}</div>}
                      {comfyCheck.errors.map((m, i) => (
                        <div key={`e${i}`} className="whitespace-pre-wrap break-all">
                          • {m}
                        </div>
                      ))}
                      {comfyCheck.fixes.map((m, i) => (
                        <div key={`f${i}`} className="break-all">
                          ✓ {m}
                        </div>
                      ))}
                      {comfyCheck.warnings.map((m, i) => (
                        <div key={`w${i}`} className="break-all opacity-80">
                          ! {m}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </Field>

            <Field label="画风预设">
              <Select
                value={submitStylePreset}
                onValueChange={(v) => updateApiConfig({ stylePreset: v })}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STYLE_PRESET_OPTIONS.map((key) => (
                    <SelectItem key={key} value={key}>
                      {STYLE_PRESETS[key]?.label ?? key}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

              <>
                {!parsedComfyNodes.valid && (
                  <div className="col-span-full rounded-xl border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                    {parsedComfyNodes.error}
                  </div>
                )}

                <Field label="人像图节点 (LoadImage)">
                  <Select
                    value={apiConfig.comfyuiParams.portraitNodeId}
                    onValueChange={(v) => updateComfyUiParams({ portraitNodeId: v })}
                  >
                    <SelectTrigger className="w-full text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">不绑定</SelectItem>
                      {parsedComfyNodes.imageNodes.map((n) => (
                        <SelectItem key={n.id} value={n.id} className="text-xs">
                          #{n.id} {n.title}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>

                <Field label="服装图节点 (LoadImage)">
                  <Select
                    value={apiConfig.comfyuiParams.costumeNodeId}
                    onValueChange={(v) => updateComfyUiParams({ costumeNodeId: v })}
                  >
                    <SelectTrigger className="w-full text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">不绑定</SelectItem>
                      {parsedComfyNodes.imageNodes.map((n) => (
                        <SelectItem key={n.id} value={n.id} className="text-xs">
                          #{n.id} {n.title}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>

                <Field label="姿势图节点 (LoadImage)">
                  <Select
                    value={apiConfig.comfyuiParams.poseNodeId}
                    onValueChange={(v) => updateComfyUiParams({ poseNodeId: v })}
                  >
                    <SelectTrigger className="w-full text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">不绑定</SelectItem>
                      {parsedComfyNodes.imageNodes.map((n) => (
                        <SelectItem key={n.id} value={n.id} className="text-xs">
                          #{n.id} {n.title}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>

                <Field label="正向提示词节点 (Prompt)">
                  <Select
                    value={apiConfig.comfyuiParams.promptNodeId}
                    onValueChange={(v) => updateComfyUiParams({ promptNodeId: v })}
                  >
                    <SelectTrigger className="w-full text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">保留工作流原提示词</SelectItem>
                      {parsedComfyNodes.promptNodes.map((n) => (
                        <SelectItem key={n.id} value={n.id} className="text-xs">
                          #{n.id} {n.title} ({n.field})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
              </>

            {showAdvanced && <WorkflowParameters onPreview={setZoomImageUrl} onUploadingChange={setUploadingSlot} />}

            {/* 展开的高级 ComfyUI 参数 */}
            {showAdvanced && (
              <>
                    <Field label="三合一拼图节点 (可选)">
                      <Select
                        value={apiConfig.comfyuiParams.stitchedNodeId}
                        onValueChange={(v) => updateComfyUiParams({ stitchedNodeId: v })}
                      >
                        <SelectTrigger className="w-full text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="none">不绑定</SelectItem>
                          {parsedComfyNodes.imageNodes.map((n) => (
                            <SelectItem key={n.id} value={n.id} className="text-xs">
                              #{n.id} {n.title}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </Field>
                    <Field label="最长等待时间（秒）">
                      <Input
                        type="number"
                        min={60}
                        step={60}
                        value={apiConfig.comfyuiParams.timeoutSec}
                        onChange={(e) =>
                          updateComfyUiParams({ timeoutSec: Math.max(60, Number(e.target.value) || 600) })
                        }
                        className="bg-background text-xs"
                      />
                    </Field>
                    <Field label="随机种子 (seed)">
                      <div className="flex h-9 items-center justify-between rounded-xl border bg-background px-3">
                        <span className="text-xs text-muted-foreground">
                          {apiConfig.comfyuiParams.randomizeSeed ? '每次随机种子' : '固定工作流种子'}
                        </span>
                        <Switch
                          checked={apiConfig.comfyuiParams.randomizeSeed}
                          onCheckedChange={(v) => updateComfyUiParams({ randomizeSeed: v })}
                        />
                      </div>
                    </Field>
              </>
            )}
            {/* D4 冻结：参数面板保留给用户预览/导出，但后端出图不读取它 */}
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              参数面板不改变后端出图的节点与工作流（D4 冻结）：提交只发送槽位库标识、画风与补充要求，节点映射由后端固定。
            </p>
          </Section>

          {activeTask && (
            <Section title="未决任务" className="@lg/section:grid-cols-1">
              <p className="break-all text-xs">
                任务 #{activeTask.jobId}：{activeTask.summary}。刷新页面或切换回来后可按任务号恢复追踪，不会重复提交。
              </p>
              <p className="text-[11px] text-muted-foreground">提交于 {formatSubmittedAt(activeTask.submittedAt)}</p>
              <div className="flex flex-wrap gap-2">
                <Button disabled={isGenerating} onClick={() => void resumeGeneration()}>恢复追踪</Button>
                <Button variant="outline" onClick={() => void stopTracking()}>停止跟踪（不取消后端）</Button>
              </div>
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                停止跟踪只中止本页轮询，后端任务可能仍在执行；如需取消该任务，请前往任务中心。
              </p>
            </Section>
          )}
          {/* 3. 提示词与生成按钮 */}
          <Section
            title="3. 提示词 (Prompt)"
            className="@lg/section:grid-cols-1"
            actions={
              <div className="flex items-center gap-1.5">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setCustomPrompt(null)
                    setPromptSuffix('')
                  }}
                >
                  <RotateCcwIcon className="size-3.5" />
                  重置
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    void navigator.clipboard.writeText(prompt)
                    toast.success('已复制')
                  }}
                >
                  <CopyIcon className="size-3.5" />
                  复制
                </Button>
              </div>
            }
          >
            <Textarea
              value={prompt}
              readOnly
              rows={5}
              aria-label="提示词预览（只读，由槽位生成）"
              className="bg-background font-mono text-xs leading-relaxed"
            />
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              提示词由所选槽位自动生成，仅用于预览与复制；需要追加要求请填写下方「补充要求」。
            </p>

            <Field label="补充要求（可选）">
              <Textarea
                value={promptSuffix}
                onChange={(e) => setPromptSuffix(e.target.value)}
                rows={2}
                placeholder="例如：暖色灯光、浅景深；作为 prompt_suffix 提交"
                className="bg-background text-xs leading-relaxed"
              />
            </Field>

            <Button
              onClick={handleGenerate}
              disabled={!hydrated || !!activeTask || isGenerating || uploadingSlot !== null}
              className="h-11 w-full text-sm font-semibold"
            >
              {isGenerating ? (
                <>
                  <LoaderCircleIcon className="size-4 animate-spin" />
                  生成中…
                </>
              ) : (
                <>
                  <SparklesIcon className="size-4" />
                  生成角色图
                </>
              )}
            </Button>
          </Section>
        </div>

        {/* 右栏：专注展示 AI 生成结果与生成状态 */}
        <div className="min-w-0 lg:col-span-5">
          <Section
            title="生成结果"
            className="@lg/section:grid-cols-1"
            actions={
              previewUrl && !isGenerating ? (
                <Button variant="outline" size="sm" asChild>
                  <a href={previewUrl} download="image.png">
                    <DownloadIcon className="size-3.5" />
                    下载图片
                  </a>
                </Button>
              ) : null
            }
          >
            <div className="relative flex min-h-[340px] items-center justify-center overflow-hidden rounded-2xl bg-background p-4 sm:min-h-[460px]">
              {isGenerating ? (
                <div className="flex flex-col items-center gap-3 text-center">
                  <div className="flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                    <LoaderCircleIcon className="size-6 animate-spin" />
                  </div>
                  <div className="w-full max-w-xs space-y-1">
                    <div className="text-sm font-semibold">正在生成角色图…</div>
                    {generatingModel && (
                      <Badge variant="secondary" className="font-mono text-[11px]">
                        {generatingModel}
                      </Badge>
                    )}
                    <div className="space-y-1.5 pt-1">
                      <div className="text-xs text-foreground/80">
                        {generationProgress?.message ||
                          (activeTask ? `任务 #${activeTask.jobId} 已提交，等待进度更新…` : '正在提交任务…')}
                      </div>
                      {progressValue !== null && (
                        <div className="space-y-1">
                          <div
                            role="progressbar"
                            aria-label="生成进度"
                            aria-valuemin={0}
                            aria-valuemax={100}
                            aria-valuenow={progressValue}
                            className="h-1.5 overflow-hidden rounded-full bg-muted"
                          >
                            <div
                              className="h-full rounded-full bg-primary transition-all"
                              style={{ width: `${progressValue}%` }}
                            />
                          </div>
                          <div className="text-right text-[11px] text-muted-foreground">{progressValue}%</div>
                        </div>
                      )}
                    </div>
                    <p className="pt-1 text-xs text-muted-foreground">
                      切换页面不会中断当前任务
                    </p>
                  </div>
                </div>
              ) : generationError ? (
                <div className="flex max-w-md flex-col items-center gap-2 text-center">
                  <CircleAlertIcon className="size-7 text-destructive" />
                  <div className="text-sm font-semibold text-destructive">生成失败</div>
                  <p className="whitespace-pre-wrap break-all text-left text-xs leading-relaxed text-muted-foreground">
                    {generationError}
                  </p>
                  <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleGenerate}
                      disabled={!hydrated || !!activeTask || isGenerating || uploadingSlot !== null}
                    >
                      <RotateCcwIcon className="size-3.5" />
                      重试
                    </Button>
                    {previewUrl && (
                      <Button variant="ghost" size="sm" onClick={() => setZoomImageUrl(previewUrl)}>
                        查看上一张结果
                      </Button>
                    )}
                  </div>
                </div>
              ) : previewUrl ? (
                <button type="button" aria-label="放大生成结果" onClick={() => setZoomImageUrl(previewUrl)} className="cursor-zoom-in rounded-xl focus-visible:outline-2 focus-visible:outline-ring"><img src={previewUrl} alt="生成结果" className="max-h-[480px] w-auto rounded-xl object-contain transition hover:opacity-95" /></button>
              ) : (
                <div className="flex flex-col items-center gap-2 text-center text-muted-foreground">
                  <SparklesIcon className="size-7 opacity-35" />
                  <span className="text-xs">点击「生成角色图」后在此处展示生成结果</span>
                </div>
              )}
            </div>

            {/* 任务中心是 atelier 的原生路由 /jobs；用 <a> 而不是 TanStack Link，
                避免 basepath 把它拼成 /ref-web/jobs。 */}
            <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-2 text-[11px] text-muted-foreground">
              <span>{activeTask ? `当前任务 #${activeTask.jobId}` : '任务由 atelier 后端排队执行'}</span>
              <a
                href="/jobs"
                className="inline-flex items-center gap-1 font-medium text-primary hover:underline focus-visible:outline-2 focus-visible:outline-ring"
              >
                <ExternalLinkIcon className="size-3.5" />
                任务中心
              </a>
            </div>
          </Section>
        </div>
      </div>

      {/* 生成历史记录：来自 atelier 画廊（后端 GET /api/images），只读展示 */}
      {history.length > 0 && (
        <Section
          title={`来自 atelier 画廊的历史 (${history.length})`}
          className="grid-cols-2 @lg/section:grid-cols-3 @3xl/section:grid-cols-4"
        >
          {history.map((h) => (
            <div
              key={h.id}
              className="group flex flex-col justify-between overflow-hidden rounded-2xl bg-background p-2"
            >
              <div className="relative aspect-3/4 overflow-hidden rounded-xl bg-muted">
                {h.imageUrl ? (
                  <button type="button" aria-label={`查看生成记录：${h.recipeSummary}`} onClick={() => setZoomImageUrl(h.imageUrl)} className="block h-full w-full cursor-zoom-in focus-visible:outline-2 focus-visible:outline-ring">
                    <img
                      src={h.imageUrl}
                      alt={h.recipeSummary}
                      className="h-full w-full object-cover transition group-hover:scale-105"
                    />
                  </button>
                ) : (
                  <div className="flex h-full w-full items-center justify-center px-2 text-center">
                    <span className="text-[11px] text-muted-foreground">图片不可用</span>
                  </div>
                )}
                {h.model && (
                  <span className="absolute bottom-1.5 left-1.5 max-w-[calc(100%-12px)] truncate rounded-md bg-black/70 px-1.5 py-0.5 font-mono text-[10px] text-white">
                    {h.model}
                  </span>
                )}
              </div>

              <div className="mt-2 space-y-1.5 px-0.5">
                <div className="truncate text-xs font-medium">{h.recipeSummary}</div>
                <div className="grid grid-cols-2 gap-1.5">
                  <button
                    type="button"
                    onClick={() => {
                      setCustomPrompt(h.prompt)
                      toast.success('已恢复该图提示词')
                    }}
                    className="flex h-7 items-center justify-center rounded-lg bg-muted text-[11px] font-medium whitespace-nowrap text-foreground transition hover:bg-muted/70"
                  >
                    复用词
                  </button>
                  {h.imageUrl ? (
                    <a
                      href={h.imageUrl}
                      download={`character-${h.id}.png`}
                      className="flex h-7 items-center justify-center rounded-lg bg-primary/10 text-[11px] font-medium whitespace-nowrap text-primary transition hover:bg-primary/20"
                    >
                      下载
                    </a>
                  ) : (
                    <span className="flex h-7 items-center justify-center rounded-lg bg-muted text-[11px] font-medium whitespace-nowrap text-muted-foreground">
                      下载
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </Section>
      )}

      {/* 生成结果全屏放大灯箱 */}
      <ImageViewer imageUrl={zoomImageUrl || ''} open={Boolean(zoomImageUrl)} onOpenChange={(open) => !open && setZoomImageUrl(null)} />

      {/* 参考拼图独立弹窗（不占用主画布） */}
      <Dialog open={Boolean(stitchModalUrl)} onOpenChange={(o) => !o && setStitchModalUrl(null)}>
        <DialogContent className="max-h-[90dvh] w-[95vw] max-w-3xl overflow-y-auto p-4 sm:max-w-3xl">
          <DialogHeader className="flex flex-row flex-wrap items-center justify-between gap-3 pr-8">
            <DialogTitle className="text-base">参考图拼合卡片</DialogTitle>
            {stitchModalUrl && (
              <Button size="sm" variant="outline" asChild>
                <a href={stitchModalUrl} download="reference-sheet.jpg">
                  <DownloadIcon className="size-3.5" />
                  下载拼图
                </a>
              </Button>
            )}
          </DialogHeader>
          {stitchModalUrl && (
            <div className="mt-2 flex items-center justify-center overflow-hidden rounded-xl bg-muted p-2">
              <img
                src={stitchModalUrl}
                alt="参考拼图"
                className="max-h-[70dvh] w-auto rounded-lg object-contain"
              />
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* ComfyUI API 工作流 JSON 编辑器弹窗 */}
      <Dialog open={showComfyJsonModal} onOpenChange={setShowComfyJsonModal}>
        <DialogContent className="max-h-[90dvh] w-[95vw] max-w-3xl overflow-y-auto p-4 sm:max-w-3xl">
          <DialogHeader className="flex flex-row flex-wrap items-center justify-between gap-3 pr-8">
            <DialogTitle className="text-base">ComfyUI API 工作流 JSON</DialogTitle>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                const info = parseComfyWorkflowNodes(apiConfig.comfyuiParams.workflowJson)
                if (!info.valid) {
                  toast.error(info.error || '工作流 JSON 无效')
                  return
                }
                const detected = autoDetectComfyMappings(apiConfig.comfyuiParams.workflowJson)
                updateComfyUiParams(detected)
                toast.success(
                  `已自动重新识别节点：${info.imageNodes.length} 个图片节点、${info.promptNodes.length} 个提示词节点`
                )
              }}
            >
              自动识别节点
            </Button>
          </DialogHeader>
          <p className="text-xs text-muted-foreground">
            请在 ComfyUI 设置中开启「启用开发模式选项」，点击菜单中的「导出 (API)」获取 JSON 并粘贴于下方。
          </p>
          <Button type="button" size="sm" variant="outline" onClick={() => void handleExportComfyJson(true)}>导出原始 API</Button>
          <Textarea
            value={apiConfig.comfyuiParams.workflowJson}
            onChange={(e) =>
              updateComfyUiParams({
                workflowPreset: 'custom',
                workflowJson: e.target.value,
              })
            }
            rows={18}
            className="font-mono text-xs leading-relaxed"
          />
        </DialogContent>
      </Dialog>
    </>
  )
}
