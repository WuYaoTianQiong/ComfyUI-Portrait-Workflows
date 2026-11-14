import { computed, reactive, ref, watch } from 'vue'

import type { JobSnapshot, HistoryItem } from '../api/types'
import type { WorkflowRow } from '../api/workflows'
import { formatApiError } from '../utils/errors'
import {
  MATRIX_MAX_TOTAL,
  buildCells,
  buildMatrixPlan,
  cellKey,
  matrixSupport,
  useWorkflowMatrix,
  type MatrixAlign,
  type MatrixCell,
  type MatrixRow,
} from './useWorkflowMatrix'

/**
 * 提示词页「同一提示词 × 多工作流」横评的状态与提交。
 *
 * 关键约束（见文档 A15）：
 * 1. **一格一 job**：图片的工作流归属取 job 级字段（`images.py` 的 image_detail），
 *    把多个工作流塞进同一个 batch job 会让灯箱把模型标错，所以按格提交 `/api/runs`。
 * 2. **同种子**：锁定基准种子后列方向 +1，各工作流同列用同一个种子，差异才归因于模型。
 * 3. **逐流档位**：画质档按各工作流 caps 求解（`buildMatrixPlan`），不是一套参数打天下。
 * 4. 跑的是**编辑框当前文本**（与单跑一致，所见即所得），不写回提示词库。
 */

const TERMINAL = new Set(['done', 'error', 'cancelled', 'stopped'])
const BEST_KEY = (scope: string) => `pb.matrixBest.${scope}`
const BATCH_KEY = (scope: string) => `pb.matrixBatch.${scope}`
/** 与合成台提交并发同口径，避免一次把后端提交线程打满。 */
const SUBMIT_CONCURRENCY = 2

export interface MatrixRunRequest {
  path: string
  tier: string
  ratio: string
  orientation: string
  seed: number
  prompt: string
  negative: string
}

export interface PromptMatrixDeps {
  /**
   * 持久化命名空间：详情页用 `p:<提示词id>`，试跑弹窗用 `trial`。
   * 试跑没有载体，不能按提示词 id 存批次。
   */
  scope: () => string
  /** 工作流选择集合的持久化键：详情页与试跑弹窗各存各的，互不覆盖 */
  storeKey?: string
  promptText: () => string
  negativeText: () => string
  savedSeed: () => number | null
  workflows: () => readonly WorkflowRow[]
  /** 当前单跑工作流：开横评时用它打底，而不是列表里的第一个（可能是超分流） */
  currentWorkflow: () => string
  ratio: () => string
  tier: () => string
  orientation: () => string
  /**
   * 由调用方决定投哪个端点：详情页 `/api/runs`（挂提示词），
   * 试跑 `/api/runs/text`（不挂载体）。引擎只关心拿到 job id。
   */
  submit: (req: MatrixRunRequest) => Promise<{ success: boolean; job_id?: number | null }>
  track: (jobId: number) => void
  /** 恢复批次时先取一次快照：已完成的直接落地，只对未完成的任务开 SSE。 */
  fetchJob?: (jobId: number) => Promise<JobSnapshot | null>
  jobs: () => readonly JobSnapshot[]
  /** 画廊回流（可选）：把只有文件名的成图升级成带 id 的完整记录 */
  shots?: () => readonly HistoryItem[]
  refreshShots?: () => void
  useWorkflow: (path: string) => void
  notify: (kind: 'success' | 'error' | 'info', message: string) => void
}

interface StoredBatch {
  baseSeed: number
  lock: boolean
  count: number
  cells: Array<Pick<MatrixCell, 'path' | 'col' | 'seed' | 'tier' | 'width' | 'height' | 'jobId'>>
}

/** 一次提交 = 一个批次：文本与条件在提交瞬间冻结，之后改编辑框不影响它。 */
export interface MatrixBatch {
  id: number
  createdAt: string
  prompt: string
  negative: string
  ratio: string
  orientation: string
  baseSeed: number
  lock: boolean
  count: number
  rows: MatrixRow[]
  cells: MatrixCell[]
}

interface StoredV2 {
  version: 2
  batches: Array<Omit<MatrixBatch, 'cells'> & { cells: StoredBatch['cells'] }>
}

/** 历史批次上限：localStorage 与界面都不该无限膨胀。 */
const MAX_BATCHES = 8
/** 单调 id：同毫秒连续提交也不撞 key 前缀。 */
let batchSeq = Date.now()

function readJson<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}

function writeJson(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* 隐私模式下忽略 */
  }
}

function removeKey(key: string) {
  try {
    localStorage.removeItem(key)
  } catch {
    /* 忽略 */
  }
}

/** 简单的定并发执行池：提交本身很轻，但一次几十个 POST 仍会压住后端。 */
async function pool<T>(items: readonly T[], size: number, worker: (item: T) => Promise<void>) {
  let cursor = 0
  const runners = Array.from({ length: Math.min(size, items.length) }, async () => {
    while (cursor < items.length) {
      const item = items[cursor]
      cursor += 1
      await worker(item)
    }
  })
  await Promise.all(runners)
}

export function usePromptMatrix(deps: PromptMatrixDeps) {
  const { enabled, paths, align, seedFrom, setPaths } = useWorkflowMatrix(deps.storeKey)
  const lockSeed = ref(true)
  const count = ref(2)
  const baseSeed = ref(0)
  /** 新提交追加到头部；旧批次保留进度与结果，不被覆盖。 */
  const batches = ref<MatrixBatch[]>([])
  /** 未提交的下一轮预览格，与批次完全独立。 */
  const previewCells = ref<MatrixCell[]>([])
  /** 兼容旧宿主：最新批次的格子；没有批次时退回顾览。 */
  const cells = computed<MatrixCell[]>(() => batches.value[0]?.cells ?? previewCells.value)
  const allCells = computed<MatrixCell[]>(() => [
    ...batches.value.flatMap((b) => b.cells),
    ...previewCells.value,
  ])
  const submitting = ref(false)
  const bestPath = ref('')
  /** 已经为终态任务刷过图库，避免 shots 变化 → 刷新 → shots 变化的循环。 */
  const refreshed = new Set<number>()
  let restoredFor: string | null = null

  const plan = computed(() =>
    buildMatrixPlan({
      workflows: deps.workflows(),
      paths: paths.value,
      ratio: deps.ratio(),
      tier: deps.tier(),
      align: align.value,
      count: count.value,
    }),
  )

  /** 选择器里置灰的项：需要喂图的编辑 / 参考 / 超分类，以及不注入提示词的视频 / 反推类。 */
  const unavailable = computed<Record<string, string>>(() => {
    const map: Record<string, string> = {}
    for (const wf of deps.workflows()) {
      const support = matrixSupport(wf)
      if (!support.supported) map[wf.path] = support.reason
    }
    return map
  })

  const activeCount = computed(
    () => allCells.value.filter((c) => c.status === 'queued' || c.status === 'running').length,
  )
  const running = computed(() => submitting.value || activeCount.value > 0)

  function persist() {
    const scope = deps.scope()
    if (!scope) return
    if (!batches.value.length) {
      removeKey(BATCH_KEY(scope))
      return
    }
    const payload: StoredV2 = {
      version: 2,
      batches: batches.value.map((b) => ({
        id: b.id,
        createdAt: b.createdAt,
        prompt: b.prompt,
        negative: b.negative,
        ratio: b.ratio,
        orientation: b.orientation,
        baseSeed: b.baseSeed,
        lock: b.lock,
        count: b.count,
        rows: b.rows,
        cells: b.cells.map((c) => ({
          path: c.path,
          col: c.col,
          seed: c.seed,
          tier: c.tier,
          width: c.width,
          height: c.height,
          jobId: c.jobId,
        })),
      })),
    }
    writeJson(BATCH_KEY(scope), payload)
  }

  function loadBest() {
    const scope = deps.scope()
    if (!scope) {
      bestPath.value = ''
      return
    }
    try {
      bestPath.value = localStorage.getItem(BEST_KEY(scope)) ?? ''
    } catch {
      bestPath.value = ''
    }
  }

  /** 换提示词：接回这条自己的历史批次（还在跑就继续订阅进度）。 */
  function restore() {
    const scope = deps.scope()
    if (!scope || restoredFor === scope) return
    restoredFor = scope
    loadBest()
    refreshed.clear()
    const stored = readJson<StoredV2 | StoredBatch>(BATCH_KEY(scope))
    const revive = (batchId: number, c: StoredBatch['cells'][number]): MatrixCell => ({
      key: `${batchId}:${cellKey(c.path, c.col)}`,
      path: c.path,
      col: c.col,
      seed: c.seed,
      tier: c.tier,
      width: c.width,
      height: c.height,
      status: c.jobId ? 'queued' : 'idle',
      jobId: c.jobId ?? null,
      error: '',
      image: null,
    })
    if (stored && 'version' in stored && stored.version === 2 && Array.isArray(stored.batches)) {
      batches.value = stored.batches.map((b) => ({ ...b, cells: b.cells.map((c) => revive(b.id, c)) }))
    } else if (stored && Array.isArray((stored as StoredBatch).cells) && (stored as StoredBatch).cells.length) {
      // 旧单批格式：升级成一个批次；当时没记文本，批头会标「未记录提示词」。
      const old = stored as StoredBatch
      const id = ++batchSeq
      batches.value = [{
        id,
        createdAt: '',
        prompt: '',
        negative: '',
        ratio: '',
        orientation: '',
        baseSeed: old.baseSeed,
        lock: old.lock !== false,
        count: old.count,
        rows: [],
        cells: old.cells.map((c) => revive(id, c)),
      }]
    } else {
      batches.value = []
    }
    const latest = batches.value[0]
    baseSeed.value = latest?.baseSeed ?? deps.savedSeed() ?? 0
    lockSeed.value = latest?.lock ?? true
    count.value = Math.max(1, Math.min(4, latest?.count || 2))
    if (!latest) {
      // 切载体后计划串不变，预览 watch 不会重发：这里直接铺预览格。
      previewCells.value = buildCells(plan.value, baseSeed.value, lockSeed.value)
    }
    void subscribeRestored()
  }

  /** 已完成的任务不该再开 SSE：既省连接，刷新后也能立刻看到结果而不是「排队中」。 */
  async function subscribeRestored() {
    for (const cell of allCells.value) {
      if (!cell.jobId) continue
      if (!deps.fetchJob) {
        deps.track(cell.jobId)
        continue
      }
      const snap = await deps.fetchJob(cell.jobId).catch(() => null)
      if (!snap) {
        deps.track(cell.jobId)
        continue
      }
      if (applySnapshot(cell, snap)) deps.refreshShots?.()
      if (!TERMINAL.has(snap.status)) deps.track(cell.jobId)
    }
    persist()
  }

  /** 把一份任务快照落到格子上；返回是否需要刷图库。 */
  function applySnapshot(cell: MatrixCell, snap: JobSnapshot): boolean {
    const item = snap.items?.[0]
    // 快照自带文件名，先挂上：试跑没有载体，图不会出现在任何提示词的历史里。
    const produced = item?.images?.[0]
    if (produced && !cell.image) {
      cell.image = {
        filename: produced.filename,
        subfolder: produced.subfolder ?? '',
        img_type: produced.type ?? 'output',
      }
    }
    if (!TERMINAL.has(snap.status)) {
      cell.status = snap.status === 'queued' ? 'queued' : 'running'
      return false
    }
    if (snap.status === 'done') {
      cell.status = 'done'
      cell.error = ''
    } else {
      cell.status = 'error'
      cell.error = item?.error || `任务${snap.status === 'cancelled' ? '已取消' : '失败'}`
    }
    if (!cell.jobId || refreshed.has(cell.jobId)) return false
    refreshed.add(cell.jobId)
    return true
  }

  watch(() => deps.scope(), restore, { immediate: true })

  /**
   * 下一轮的「待提交」预览格：随当前控件实时重铺。
   * 批次格子独立存放，改参数不会再碰在飞的任务。
   */
  watch(
    () =>
      [
        plan.value.usable.map((r) => `${r.path}:${r.tier}:${r.width}x${r.height}`).join('|'),
        plan.value.count,
        lockSeed.value,
      ].join('~'),
    () => {
      if (submitting.value) return
      previewCells.value = buildCells(plan.value, baseSeed.value, lockSeed.value)
    },
    { immediate: true },
  )

  /** 任务快照 → 格子状态；终态时刷一次图库把成图取回来。 */
  watch(
    () => deps.jobs(),
    (snapshots) => {
      if (!allCells.value.length) return
      const byId = new Map(snapshots.map((s) => [s.id, s]))
      let needRefresh = false
      for (const cell of allCells.value) {
        if (!cell.jobId) continue
        const snap = byId.get(cell.jobId)
        if (!snap) continue
        if (applySnapshot(cell, snap)) needRefresh = true
      }
      if (needRefresh) deps.refreshShots?.()
      persist()
    },
    { deep: true },
  )

  /** 图库回流：按 job_id 把成图升级成带 id 的完整记录（一格一 job，join 键唯一）。 */
  watch(
    () => deps.shots?.() ?? [],
    (shots) => {
      if (!allCells.value.length || !shots.length) return
      const byJob = new Map<number, HistoryItem>()
      for (const shot of shots) {
        if (shot.job_id) byJob.set(shot.job_id, shot)
      }
      for (const cell of allCells.value) {
        if (!cell.jobId) continue
        const image = byJob.get(cell.jobId)
        if (image) {
          cell.image = image
          if (cell.status !== 'error') cell.status = 'done'
        }
      }
    },
    { deep: true, immediate: true },
  )

  function setEnabled(next: boolean) {
    enabled.value = next
    if (!next) return
    const current = deps.currentWorkflow()
    const usable = deps.workflows().filter((wf) => matrixSupport(wf).supported)
    // 优先沿用当前单跑工作流；它本身不可横评时退到第一个可横评的流
    const seed = usable.some((wf) => wf.path === current) ? current : (usable[0]?.path ?? '')
    seedFrom(seed)
  }

  function setAlign(next: MatrixAlign) {
    align.value = next
  }

  function setCount(next: number) {
    count.value = Math.max(1, Math.min(4, next))
  }

  /** 提交上下文：批次冻结的条件；旧格式批次 rows 为空时退回到当前计划。 */
  interface RunContext {
    rows: MatrixRow[]
    prompt: string
    negative: string
    ratio: string
    orientation: string
  }

  function contextOf(batch: MatrixBatch | undefined): RunContext {
    return {
      rows: batch?.rows.length ? batch.rows : plan.value.usable,
      prompt: batch ? batch.prompt : deps.promptText(),
      negative: batch ? batch.negative : deps.negativeText(),
      ratio: batch?.ratio || deps.ratio(),
      orientation: batch?.orientation || deps.orientation(),
    }
  }

  function batchOf(key: string): MatrixBatch | undefined {
    return batches.value.find((b) => b.cells.some((c) => c.key === key))
  }

  async function runCell(cell: MatrixCell, ctx: RunContext) {
    const row = ctx.rows.find((r) => r.path === cell.path)
    if (!row) {
      cell.status = 'error'
      cell.error = '该工作流已不在本次计划里'
      return
    }
    cell.status = 'queued'
    cell.error = ''
    cell.image = null
    try {
      const result = await deps.submit({
        path: cell.path,
        tier: row.tier,
        ratio: ctx.ratio,
        orientation: ctx.orientation,
        seed: cell.seed,
        prompt: ctx.prompt,
        negative: ctx.negative,
      })
      if (!result.success || !result.job_id) {
        cell.status = 'error'
        cell.error = '提交失败'
        return
      }
      cell.jobId = result.job_id
      refreshed.delete(result.job_id)
      persist()
    } catch (error) {
      cell.status = 'error'
      cell.error = formatApiError(error)
    }
  }

  async function submit(seed: number | null) {
    restore()
    if (!deps.promptText().trim()) {
      deps.notify('error', '提示词是空的')
      return
    }
    const p = plan.value
    if (!p.usable.length) {
      deps.notify('error', '先勾选至少一个可注入提示词的工作流')
      return
    }
    if (p.overLimit) {
      deps.notify('error', `一次最多 ${MATRIX_MAX_TOTAL} 张，请减少工作流或张数`)
      return
    }
    const fallback = deps.savedSeed()
    baseSeed.value =
      seed ?? (lockSeed.value ? (fallback || Math.floor(Math.random() * 2 ** 31)) : Math.floor(Math.random() * 2 ** 31))
    // 追加而不是覆盖：上一批还在跑也保留它的格子与进度。
    const id = ++batchSeq
    const batch: MatrixBatch = {
      id,
      createdAt: new Date().toISOString(),
      prompt: deps.promptText(),
      negative: deps.negativeText(),
      ratio: deps.ratio(),
      orientation: deps.orientation(),
      baseSeed: baseSeed.value,
      lock: lockSeed.value,
      count: p.count,
      rows: p.usable.map((r) => ({ ...r })),
      // key 带批次前缀：不同批次的同流同列格子不能串。
      cells: buildCells(p, baseSeed.value, lockSeed.value).map((c) => ({
        ...c,
        key: `${id}:${c.key}`,
      })),
    }
    batches.value = [batch, ...batches.value].slice(0, MAX_BATCHES)
    refreshed.clear()
    submitting.value = true
    persist()
    const ctx = contextOf(batch)
    try {
      await pool(batch.cells, SUBMIT_CONCURRENCY, (cell) => runCell(cell, ctx))
      const failed = batch.cells.filter((c) => c.status === 'error').length
      deps.notify(
        failed ? 'info' : 'success',
        `已提交 ${batch.cells.length - failed} 张横评任务（${p.usable.length} 个工作流 × ${p.count} 张）${failed ? `，${failed} 格提交失败` : ''}`,
      )
    } finally {
      submitting.value = false
      previewCells.value = buildCells(plan.value, baseSeed.value, lockSeed.value)
      persist()
    }
  }

  async function retry(key: string) {
    const cell = allCells.value.find((c) => c.key === key)
    if (!cell) return
    submitting.value = true
    try {
      await runCell(cell, contextOf(batchOf(key)))
    } finally {
      submitting.value = false
    }
  }

  async function rerun(keys: readonly string[]) {
    const targets = allCells.value.filter((c) => keys.includes(c.key))
    if (!targets.length) return
    submitting.value = true
    try {
      await pool(targets, SUBMIT_CONCURRENCY, (cell) => runCell(cell, contextOf(batchOf(cell.key))))
    } finally {
      submitting.value = false
    }
  }

  /** 只清一个批次；其它批次的进度与结果不受影响。 */
  function clearBatch(id: number) {
    batches.value = batches.value.filter((b) => b.id !== id)
    persist()
  }

  function clearPreview() {
    previewCells.value = []
  }

  function clear() {
    batches.value = []
    previewCells.value = []
    refreshed.clear()
    const scope = deps.scope()
    if (scope) removeKey(BATCH_KEY(scope))
  }

  function setBest(path: string) {
    if (!path) return
    bestPath.value = path
    const scope = deps.scope()
    // 纯字符串存取：与 loadBest 的 getItem 对称，别一边 JSON 一边裸串
    if (scope) {
      try {
        localStorage.setItem(BEST_KEY(scope), path)
      } catch {
        /* 隐私模式下忽略 */
      }
    }
    const row = plan.value.rows.find((r) => r.path === path)
    deps.notify('success', `已把「${row?.shortName ?? path}」记为这条提示词的最佳工作流`)
  }

  /** 横评的闭环：选完最好的流，退出横评用它继续单跑。 */
  function useWorkflow(path: string) {
    if (!path) return
    deps.useWorkflow(path)
    enabled.value = false
    const row = plan.value.rows.find((r) => r.path === path)
    deps.notify('success', `已切到「${row?.shortName ?? path}」单跑`)
  }

  // reactive 而不是裸对象：模板里 `matrix.paths` 要直接拿到数组，
  // 嵌套在普通对象里的 ref 在模板中不会自动解包。
  return reactive({
    enabled,
    paths,
    align,
    lockSeed,
    count,
    baseSeed,
    plan,
    batches,
    previewCells,
    cells,
    running,
    submitting,
    bestPath,
    unavailable,
    setEnabled,
    setPaths,
    setAlign,
    setCount,
    setBest,
    useWorkflow,
    submit,
    retry,
    rerun,
    clearBatch,
    clearPreview,
    clear,
  })
}

export type PromptMatrixApi = ReturnType<typeof usePromptMatrix>
