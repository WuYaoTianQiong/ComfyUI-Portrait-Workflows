import { computed, ref, watch } from 'vue'

import type { Ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import {
  inspectWorkflow,
  listWorkflows,
  validateWorkflow,
  type WorkflowInspection,
  type WorkflowRow,
} from '../api/workflows'
import { useSettings } from './useSettings'
import type { SizePreview } from './useWorkflowCaps'

export type { WorkflowRow }

interface CustomWorkflow extends WorkflowRow {
  content: string
}

const CUSTOM_KEY = 'pb.customWorkflows'
const HIDDEN_KEY = 'pb.hiddenWorkflows'
const ORDER_KEY = 'pb.workflowOrder'

/** localStorage 读写包装 —— 隐私模式下不可用时静默降级。 */
function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

function writeJson(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* 隐私模式下 localStorage 可能不可用，忽略即可 */
  }
}

/**
 * 模块级单例：自定义工作流与隐藏 / 排序状态。
 *
 * 放模块级而不是组件级 —— `useGenerate` 在别处也要读自定义工作流的内容，
 * 组件级状态它拿不到。
 */
const customWorkflows = ref<CustomWorkflow[]>(readJson<CustomWorkflow[]>(CUSTOM_KEY, []))
const hiddenPaths = ref<string[]>(readJson<string[]>(HIDDEN_KEY, []))
const workflowOrder = ref<string[]>(readJson<string[]>(ORDER_KEY, []))

/** 自定义工作流的能力探测缓存：内容哈希 → 后端 inspect 结果。 */
const inspectionCache = ref<Record<string, WorkflowInspection>>({})
const inspecting = new Set<string>()
let inspectionStarted = false

/** FNV-1a：只用于缓存键，碰撞概率足够低，不需要密码学哈希。 */
function contentKey(content: string): string {
  let hash = 0x811c9dc5
  for (let i = 0; i < content.length; i += 1) {
    hash ^= content.charCodeAt(i)
    hash = Math.imul(hash, 0x01000193)
  }
  return `${content.length}:${(hash >>> 0).toString(36)}`
}

async function ensureInspection(workflow: CustomWorkflow) {
  const key = contentKey(workflow.content)
  if (inspectionCache.value[key] || inspecting.has(key)) return
  inspecting.add(key)
  try {
    const result = await inspectWorkflow({
      workflow_path: workflow.path,
      workflow_content: workflow.content,
    })
    inspectionCache.value = { ...inspectionCache.value, [key]: result }
  } catch {
    // 后端不可用时保持旧行为：caps/params 留空，由 useWorkflowCaps 回退默认值
  } finally {
    inspecting.delete(key)
  }
}

/**
 * 取自定义工作流的 JSON 内容。
 *
 * 出图时后端要同时拿到 `workflow_path` 和 `workflow_content` —— 自定义工作流
 * 不在后端磁盘上，只有内容，所以路径传一个 `custom://名字` 的伪路径，
 * 内容从这里取。后端 `load_workflow(path, content)` 两个都收。
 */
export function customWorkflowContent(path: string): string | undefined {
  if (!path?.startsWith('custom://')) return undefined
  return customWorkflows.value.find((w) => w.path === path)?.content
}

/**
 * 工作流列表（提示词页 / 组合器 / 分类与标签页共用）。
 *
 * 三件事合在一起：
 * - 后端磁盘上的工作流（`/api/workflows`）
 * - 本地自定义上传的（localStorage，出图时带 `workflow_content`）
 * - 隐藏与排序（都是本地状态 —— 不该写进数据库，那是"这台机器的偏好"）
 */
export function useWorkflows(defaultTarget?: Ref<string>) {
  const { workflowPath } = useSettings()
  // 工作流按页独立后，默认值要写到调用方自己的那份，而不是固定写提示词页
  const target = defaultTarget ?? workflowPath

  const { data } = useQuery({
    queryKey: ['workflows'],
    queryFn: listWorkflows,
    staleTime: 60_000,
  })

  // 自定义工作流只在浏览器里，必须把内容发给后端做一次统一探测（含尺寸预演）
  if (!inspectionStarted) {
    inspectionStarted = true
    watch(
      customWorkflows,
      (list) => {
        for (const workflow of list) void ensureInspection(workflow)
      },
      { deep: true, immediate: true },
    )
  }

  watch(
    () => data.value?.default,
    (fallback) => {
      if (!target.value && fallback) target.value = fallback
    },
    { immediate: true },
  )

  /** 后端磁盘上的 + 本地自定义的，合并去重。 */
  const allWorkflows = computed<WorkflowRow[]>(() => {
    const seen = new Set<string>()
    const merged: WorkflowRow[] = []
    for (const w of [...(data.value?.workflows ?? []), ...customWorkflows.value]) {
      if (seen.has(w.path)) continue
      seen.add(w.path)
      // 自定义工作流的内容只存在本地，能力来自后端 inspect；磁盘工作流直接用列表结果
      const inspection = 'content' in w
        ? inspectionCache.value[contentKey(String(w.content))]
        : undefined
      merged.push({
        path: w.path,
        name: w.name,
        custom: w.custom,
        caps: w.caps ?? inspection?.caps,
        params: w.params ?? inspection?.params,
        size_preview: (w.size_preview ?? inspection?.size_preview) as SizePreview | undefined,
      })
    }
    return merged
  })

  /** 排过序的在前，其余按名称（中文按拼音）。 */
  const sortedWorkflows = computed<WorkflowRow[]>(() => {
    const idx = new Map(workflowOrder.value.map((p, i) => [p, i]))
    return [...allWorkflows.value].sort((a, b) => {
      const ia = idx.get(a.path)
      const ib = idx.get(b.path)
      if (ia !== undefined && ib !== undefined) return ia - ib
      if (ia !== undefined) return -1
      if (ib !== undefined) return 1
      return a.name.localeCompare(b.name, 'zh')
    })
  })

  /** 可见列表（去掉被隐藏的）。 */
  const workflows = computed<WorkflowRow[]>(() =>
    sortedWorkflows.value.filter((w) => !hiddenPaths.value.includes(w.path)),
  )

  /**
   * 上传一个自定义工作流（JSON 文件）。
   *
   * 存本地而不是后端磁盘：工作流是"这台机器的素材"，不该混进共享目录；
   * 出图时把内容一起带上，后端 `load_workflow(path, content)` 认这个组合。
   */
  async function addCustomWorkflow(file: File): Promise<string> {
    const text = await file.text()
    try {
      JSON.parse(text)
    } catch {
      throw new Error('不是合法的 JSON 文件')
    }
    const name = file.name.replace(/\.json$/i, '') || '自定义工作流'
    const path = `custom://${name}`
    customWorkflows.value = [
      ...customWorkflows.value.filter((w) => w.path !== path),
      { path, name, content: text, custom: true },
    ]
    writeJson(CUSTOM_KEY, customWorkflows.value)
    return path
  }

  function removeCustomWorkflow(path: string) {
    customWorkflows.value = customWorkflows.value.filter((w) => w.path !== path)
    writeJson(CUSTOM_KEY, customWorkflows.value)
    hiddenPaths.value = hiddenPaths.value.filter((p) => p !== path)
    writeJson(HIDDEN_KEY, hiddenPaths.value)
  }

  /** 隐藏 / 取消隐藏。隐藏的只是从下拉里消失，文件还在。 */
  function setHidden(path: string, hide: boolean) {
    hiddenPaths.value = hide
      ? [...new Set([...hiddenPaths.value, path])]
      : hiddenPaths.value.filter((p) => p !== path)
    writeJson(HIDDEN_KEY, hiddenPaths.value)
  }

  /** 上移 / 下移（只对已经排过序的生效，其余按名称）。 */
  function moveWorkflow(path: string, delta: -1 | 1) {
    const list = sortedWorkflows.value.map((w) => w.path)
    const i = list.indexOf(path)
    const j = i + delta
    if (i < 0 || j < 0 || j >= list.length) return
    const tmp = list[i]
    list[i] = list[j]
    list[j] = tmp
    workflowOrder.value = list
    writeJson(ORDER_KEY, workflowOrder.value)
  }

  return {
    workflows,
    allWorkflows,
    sortedWorkflows,
    hiddenPaths,
    customWorkflows,
    addCustomWorkflow,
    removeCustomWorkflow,
    setHidden,
    moveWorkflow,
  }
}

/**
 * 校验当前选中的工作流文件。
 *
 * 后端只检查格式（API 格式或 UI 格式），不做节点类型检查 —— 换脸页另有
 * 专门的节点映射探测。这里提前拦的是"文件损坏 / 格式不对"这类低级错误，
 * 免得提交后才报错。
 */
export function useWorkflowValidation(path: Ref<string>) {
  return useQuery({
    queryKey: computed(() => ['validate-workflow', path.value]),
    queryFn: () => validateWorkflow(path.value),
    // 自定义工作流不在后端磁盘上，校验必然报"文件不存在"；出图时内容会随请求带上
    enabled: computed(() => !!path.value && !path.value.startsWith('custom://')),
    staleTime: 30_000,
  })
}