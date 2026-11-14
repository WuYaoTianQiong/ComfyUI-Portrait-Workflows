import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'

import type { HistoryItem, JobSnapshot } from '../api/types'
import type { WorkflowRow } from '../api/workflows'
import { usePromptMatrix, type MatrixRunRequest } from './usePromptMatrix'

const store = new Map<string, string>()

beforeEach(() => {
  store.clear()
  Object.defineProperty(globalThis, 'localStorage', {
    value: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value)
      },
      removeItem: (key: string) => {
        store.delete(key)
      },
    },
    configurable: true,
  })
})

function wf(path: string, sizes: Record<string, [number, number]>): WorkflowRow {
  const size_preview: WorkflowRow['size_preview'] = {}
  for (const [tier, [w, h]] of Object.entries(sizes)) {
    size_preview[tier] = { '2:3': { width: w, height: h } }
  }
  return {
    path,
    name: `${path}.json`,
    size_preview,
    caps: { prompt: true, negative: false, negative_effective: false, negative_cfg: null, quality: true, orientation: true },
    params: { quality_mode: 'scale', orientation_mode: 'swap' },
  }
}

const WORKFLOWS = [
  wf('moss', { '1.0x': [1024, 1536] }),
  wf('moody', { '1.0x': [1232, 1840] }),
]

function snapshot(id: number, status: string, error = ''): JobSnapshot {
  return {
    id,
    status,
    job_type: 'single',
    title: '',
    total: 1,
    done_count: status === 'done' ? 1 : 0,
    error_count: status === 'error' ? 1 : 0,
    created_at: '',
    updated_at: '',
    items: [{ status, seed: 1, error, images: [] }],
  } as unknown as JobSnapshot
}

function shot(id: number, jobId: number): HistoryItem {
  return { id, job_id: jobId, filename: `img${id}.png`, is_favorite: false } as unknown as HistoryItem
}

function setup() {
  const jobs = ref<JobSnapshot[]>([])
  const shots = ref<HistoryItem[]>([])
  const submitted: MatrixRunRequest[] = []
  const tracked: number[] = []
  const notices: Array<[string, string]> = []
  const used: string[] = []
  let nextJob = 100
  let text = '当前编辑框文本'
  const refreshShots = vi.fn()

  const api = usePromptMatrix({
    scope: () => 'p:7',
    promptText: () => text,
    negativeText: () => '负向文本',
    savedSeed: () => 42,
    workflows: () => WORKFLOWS,
    currentWorkflow: () => 'moody',
    ratio: () => '2:3',
    tier: () => '1.0x',
    orientation: () => 'portrait',
    submit: async (body) => {
      submitted.push(body)
      nextJob += 1
      return { success: true, job_id: nextJob }
    },
    track: (id) => tracked.push(id),
    jobs: () => jobs.value,
    shots: () => shots.value,
    refreshShots,
    useWorkflow: (path) => used.push(path),
    notify: (kind, message) => notices.push([kind, message]),
  })
  api.setPaths(['moss', 'moody'])
  return { api, jobs, shots, submitted, tracked, notices, used, refreshShots, setText: (t: string) => { text = t } }
}

describe('usePromptMatrix 提交', () => {

  it('一格一 job：2 个工作流 × 2 张 = 4 次提交，各带自己工作流与档位', async () => {
    const { api, submitted } = setup()
    api.setCount(2)
    await api.submit(20261112)
    expect(submitted).toHaveLength(4)
    expect(submitted.every((b) => b.path.length > 0)).toBe(true)
    expect(new Set(submitted.map((b) => b.path))).toEqual(new Set(['moss', 'moody']))
    expect(submitted.every((b) => b.prompt === '当前编辑框文本')).toBe(true)
    expect(submitted.every((b) => b.negative === '负向文本')).toBe(true)
  })

  it('锁定同种子：各工作流同列同种子，列方向 +1', async () => {
    const { api, submitted } = setup()
    api.setCount(2)
    await api.submit(20261112)
    const seeds = submitted.map((b) => `${b.path}:${b.seed}`).sort()
    expect(seeds).toEqual(['moody:20261112', 'moody:20261113', 'moss:20261112', 'moss:20261113'])
  })

  it('留空种子时沿用提示词保存的种子', async () => {
    const { api, submitted } = setup()
    api.setCount(1)
    await api.submit(null)
    expect(submitted.every((b) => b.seed === 42)).toBe(true)
  })

  it('没选工作流时不提交并给出提示', async () => {
    const { api, submitted, notices } = setup()
    api.setPaths([])
    await api.submit(1)
    expect(submitted).toHaveLength(0)
    expect(notices.some(([kind]) => kind === 'error')).toBe(true)
  })

  it('提交后每格拿到自己的 job id', async () => {
    const { api } = setup()
    api.setCount(1)
    await api.submit(1)
    const ids = api.cells.map((c) => c.jobId)
    expect(ids.every((id) => typeof id === 'number')).toBe(true)
    expect(new Set(ids).size).toBe(2)
  })

  it('提交途中改参数不会把在飞的批次重建掉', async () => {
    const { api } = setup()
    api.setCount(1)
    const pending = api.submit(1)
    api.setCount(4)
    api.setAlign('ref')
    await pending
    await nextTick()
    expect(api.cells).toHaveLength(2)
    expect(api.cells.every((c) => typeof c.jobId === 'number')).toBe(true)
  })

  it('未提交时先铺出待提交预览格', async () => {
    const { api } = setup()
    api.setCount(2)
    await nextTick()
    expect(api.cells).toHaveLength(4)
    expect(api.cells.every((c) => c.status === 'idle' && c.jobId === null)).toBe(true)
  })
})

describe('usePromptMatrix 任务与图片回填', () => {

  it('任务终态 done → 格子 done，并刷一次图库', async () => {
    const { api, jobs, refreshShots } = setup()
    api.setCount(1)
    await api.submit(1)
    const id = api.cells[0].jobId as number
    jobs.value = [snapshot(id, 'running')]
    await nextTick()
    expect(api.cells[0].status).toBe('running')
    jobs.value = [snapshot(id, 'done')]
    await nextTick()
    expect(api.cells[0].status).toBe('done')
    expect(refreshShots).toHaveBeenCalledTimes(1)
    jobs.value = [snapshot(id, 'done')]
    await nextTick()
    expect(refreshShots).toHaveBeenCalledTimes(1)
  })

  it('任务失败 → 格子 error 并带原因', async () => {
    const { api, jobs } = setup()
    api.setCount(1)
    await api.submit(1)
    const id = api.cells[0].jobId as number
    jobs.value = [snapshot(id, 'error', 'CUDA out of memory')]
    await nextTick()
    expect(api.cells[0].status).toBe('error')
    expect(api.cells[0].error).toContain('CUDA out of memory')
  })

  it('按 job_id 把成图挂回格子', async () => {
    const { api, jobs, shots } = setup()
    api.setCount(1)
    await api.submit(1)
    const id = api.cells[0].jobId as number
    jobs.value = [snapshot(id, 'done')]
    await nextTick()
    shots.value = [shot(555, id)]
    await nextTick()
    expect(api.cells[0].image?.id).toBe(555)
    expect(api.cells[0].status).toBe('done')
  })

  it('重试只重跑那一格', async () => {
    const { api, jobs, submitted } = setup()
    api.setCount(1)
    await api.submit(1)
    const key = api.cells[0].key
    jobs.value = [snapshot(api.cells[0].jobId as number, 'error', 'boom')]
    await nextTick()
    const before = submitted.length
    await api.retry(key)
    expect(submitted.length).toBe(before + 1)
    expect(api.cells[0].status).toBe('queued')
    expect(api.cells[0].error).toBe('')
  })

  it('running 只在还有未完成格子时为真', async () => {
    const { api, jobs } = setup()
    api.setCount(1)
    await api.submit(1)
    expect(api.running).toBe(true)
    jobs.value = api.cells.map((c) => snapshot(c.jobId as number, 'done'))
    await nextTick()
    expect(api.running).toBe(false)
  })
})

describe('usePromptMatrix 最佳工作流与恢复', () => {

  it('选为最佳按提示词持久化', () => {
    const { api, notices } = setup()
    api.setBest('moss')
    expect(api.bestPath).toBe('moss')
    expect(localStorage.getItem('pb.matrixBest.p:7')).toBe('moss')
    expect(notices.some(([kind]) => kind === 'success')).toBe(true)
  })

  it('用它单跑：切工作流并退出横评', () => {
    const { api, used } = setup()
    api.setEnabled(true)
    api.useWorkflow('moody')
    expect(used).toEqual(['moody'])
    expect(api.enabled).toBe(false)
  })

  it('开横评时用当前单跑工作流打底，而不是列表第一个', () => {
    const { api } = setup()
    api.setPaths([])
    api.setEnabled(true)
    expect(api.paths).toEqual(['moody'])
  })

  it('批次落盘，清除后一并删掉', async () => {
    const { api } = setup()
    api.setCount(1)
    await api.submit(1)
    expect(localStorage.getItem('pb.matrixBatch.p:7')).toBeTruthy()
    api.clear()
    expect(api.cells).toHaveLength(0)
    expect(localStorage.getItem('pb.matrixBatch.p:7')).toBeNull()
  })

  it('刷新后按 job id 接回跟踪', async () => {
    const first = setup()
    first.api.setCount(1)
    await first.api.submit(1)
    await flushPromises()
    const ids = first.api.cells.map((c) => c.jobId)

    const second = setup()
    await flushPromises()
    expect(second.api.cells).toHaveLength(2)
    expect(second.api.cells.map((c) => c.jobId)).toEqual(ids)
    expect(second.tracked).toEqual(ids)
  })
})

describe('usePromptMatrix 多批次追加', () => {
  it('旧批还在跑时再提交：追加不覆盖，旧批进度继续跟踪', async () => {
    const { api, jobs } = setup()
    api.setCount(1)
    await api.submit(1)
    const oldIds = api.cells.map((c) => c.jobId as number)
    jobs.value = oldIds.map((id) => snapshot(id, 'running'))
    await nextTick()

    await api.submit(2)
    expect(api.batches).toHaveLength(2)
    expect(api.batches[1].cells.map((c) => c.jobId)).toEqual(oldIds)
    expect(api.batches[1].cells.every((c) => c.status === 'running')).toBe(true)
    expect(api.cells).toHaveLength(2)

    jobs.value = [
      ...oldIds.map((id) => snapshot(id, 'done')),
      ...api.batches[0].cells.map((c) => snapshot(c.jobId as number, 'running')),
    ]
    await nextTick()
    expect(api.batches[1].cells.every((c) => c.status === 'done')).toBe(true)
    expect(api.batches[0].cells.every((c) => c.status === 'running')).toBe(true)
  })

  it('重试旧批格子用该批冻结的文本，而不是编辑框当前文本', async () => {
    const { api, submitted, setText } = setup()
    api.setCount(1)
    await api.submit(1)
    const key = api.batches[0].cells[0].key
    setText('后来改的文本')
    await api.submit(2)
    setText('又改了')
    await api.retry(key)
    expect(submitted[submitted.length - 1].prompt).toBe('当前编辑框文本')
  })

  it('清除只删一个批次，其它批次保留', async () => {
    const { api } = setup()
    api.setCount(1)
    await api.submit(1)
    await api.submit(2)
    const keepId = api.batches[0].id
    api.clearBatch(api.batches[1].id)
    expect(api.batches).toHaveLength(1)
    expect(api.batches[0].id).toBe(keepId)
  })

  it('多批次落盘，刷新后全部接回', async () => {
    const first = setup()
    first.api.setCount(1)
    await first.api.submit(1)
    await first.api.submit(2)
    await flushPromises()

    const second = setup()
    await flushPromises()
    expect(second.api.batches).toHaveLength(2)
    expect(second.api.batches[0].baseSeed).toBe(2)
    expect(second.api.batches[1].baseSeed).toBe(1)
  })
})
