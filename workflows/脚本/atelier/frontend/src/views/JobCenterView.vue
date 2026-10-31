<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import { apiGet, apiPost } from '../api/client'
import EmptyState from '../components/EmptyState.vue'
import { useToast } from '../composables/useToast'
import type { JobSnapshot } from '../api/types'
import { statusLabel } from '../utils/format'
import { confirmDialog } from '../utils/naive'
import { readSession, writeSession } from '../composables/useSessionState'

/**
 * 任务中心：进行中 / 历史任务的实时视图。
 *
 * 用 SSE（`/api/jobs/events`）而不是轮询：后端本来就广播任务状态变化，
 * 前端再每 N 秒拉一次 /api/jobs 是把已经推过来的信息再问一遍。
 */
const { data, isFetching } = useQuery<{ jobs: JobSnapshot[] }>({
  queryKey: ['jobs', 60],
  queryFn: () => apiGet('/api/jobs', { limit: 60 }),
  staleTime: 10_000,
})

const jobs = ref<JobSnapshot[]>([])
watch(
  data,
  (value) => {
    if (value?.jobs) jobs.value = value.jobs
  },
  { immediate: true },
)

/** 停止所有进行中的任务（后端是定向取消，不会清空整个 ComfyUI 队列）。 */
const toast = useToast()
const queryClient = useQueryClient()
const stopAll = useMutation({
  mutationFn: () => apiPost<{ success: boolean; stopped: number }>('/api/batch_stop'),
  onSuccess: (result) => {
    toast.success(`已停止 ${result.stopped} 个任务`)
    queryClient.invalidateQueries({ queryKey: ['jobs'] })
  },
  onError: (e) => {
    toast.error(`停止失败：${e instanceof Error ? e.message : String(e)}`)
  },
})

async function stopAllRunning() {
  const ok = await confirmDialog({
    title: '停止全部任务',
    content: '停止所有进行中的任务？已排队但还没开始的也会被取消。',
    positiveText: '停止',
    negativeText: '取消',
  })
  if (!ok) return
  stopAll.mutate()
}
/** 会话状态：筛选与展开的任务、滚动位置。 */
interface JobsSession {
  onlyActive: boolean
  expanded: number[]
  scrollTop: number
}

const SESSION_KEY = 'pb.session.jobs'
const savedSession = readSession<JobsSession>(SESSION_KEY, {
  onlyActive: false,
  expanded: [],
  scrollTop: 0,
})

const onlyActive = ref(savedSession.onlyActive)
const expanded = ref<Set<number>>(new Set(savedSession.expanded))

const listEl = ref<HTMLElement | null>(null)
let scrollSaveTimer: number | undefined

function saveSession() {
  writeSession(SESSION_KEY, {
    onlyActive: onlyActive.value,
    expanded: Array.from(expanded.value),
    scrollTop: listEl.value?.scrollTop ?? savedSession.scrollTop,
  })
}

watch(
  [onlyActive, expanded],
  saveSession,
  { deep: true },
)

/** 滚动很频繁，节流后再写。 */
function onListScroll() {
  if (scrollSaveTimer) return
  scrollSaveTimer = window.setTimeout(() => {
    scrollSaveTimer = undefined
    saveSession()
  }, 300)
}

/** 任务列表是异步到的，数据到位后再恢复滚动位置。 */
let scrollRestored = false
watch(jobs, async () => {
  if (scrollRestored || !savedSession.scrollTop) return
  scrollRestored = true
  await new Promise((resolve) => requestAnimationFrame(resolve))
  if (listEl.value) listEl.value.scrollTop = savedSession.scrollTop
})

const visible = computed(() =>
  onlyActive.value
    ? jobs.value.filter((j) => j.status === 'pending' || j.status === 'running')
    : jobs.value,
)

const activeCount = computed(
  () => jobs.value.filter((j) => j.status === 'pending' || j.status === 'running').length,
)

let source: EventSource | null = null

onMounted(() => {
  source = new EventSource('/api/jobs/events')
  source.addEventListener('job', (event) => {
    try {
      const snapshot = JSON.parse((event as MessageEvent).data) as JobSnapshot
      const list = jobs.value.slice()
      const index = list.findIndex((j) => j.id === snapshot.id)
      if (index >= 0) list[index] = { ...list[index], ...snapshot }
      else list.unshift(snapshot)
      jobs.value = list
    } catch {
      /* 心跳/异常帧忽略 */
    }
  })
})

onBeforeUnmount(() => {
  source?.close()
  source = null
  if (scrollSaveTimer) window.clearTimeout(scrollSaveTimer)
  saveSession()
})

function toggle(id: number) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

const cancelling = ref<number | null>(null)

async function cancel(id: number) {
  const ok = await confirmDialog({
    title: '取消任务',
    content: '确定取消这个任务吗？已提交到 ComfyUI 的部分会继续跑完。',
    positiveText: '取消任务',
    negativeText: '返回',
  })
  if (!ok) return
  cancelling.value = id
  try {
    await apiPost(`/api/jobs/${id}/cancel`)
  } catch (e) {
    toast.error(`取消失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    cancelling.value = null
  }
}

function percent(job: JobSnapshot): number {
  if (!job.total) return job.status === 'done' ? 100 : 0
  return Math.min(100, Math.round(((job.done_count ?? 0) / job.total) * 100))
}

function elapsed(job: JobSnapshot): string {
  const start = new Date(job.created_at).getTime()
  const end =
    job.status === 'done' || job.status === 'error'
      ? new Date(job.updated_at).getTime()
      : Date.now()
  if (!start || Number.isNaN(start)) return ''
  const seconds = Math.max(0, Math.round((end - start) / 1000))
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m${String(seconds % 60).padStart(2, '0')}s`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h${String(minutes % 60).padStart(2, '0')}m`
  // 历史任务可能放了好几天，"485m01s" 这种读不出来
  return `${Math.floor(hours / 24)}天${hours % 24}h`
}

const TYPE_LABEL: Record<string, string> = {
  single: '单图',
  batch: '批量',
  faceswap: '图像编辑',
}

function thumbUrl(item: { filename: string; subfolder?: string; type?: string }): string {
  const search = new URLSearchParams({
    filename: item.filename,
    subfolder: item.subfolder ?? '',
    type: item.type ?? 'output',
    size: '200',
  })
  return `/api/thumbnail?${search.toString()}`
}
</script>

<template>
  <div class="jobs">
    <div class="toolbar">
      <span class="title">任务</span>
      <span v-if="activeCount" class="badge">{{ activeCount }} 个进行中</span>
      <span v-if="isFetching" class="muted">加载中…</span>
      <span class="spacer" />
      <button
        class="btn btn-sm danger"
        :disabled="!activeCount || stopAll.isPending.value"
        title="停止所有进行中的任务"
        @click="stopAllRunning"
      >
        {{ stopAll.isPending.value ? '停止中…' : '停止全部' }}
      </button>
      <label class="check">
        <input v-model="onlyActive" type="checkbox" />
        <span>只看进行中</span>
      </label>
    </div>

    <div ref="listEl" class="list" @scroll.passive="onListScroll">
      <article v-for="job in visible" :key="job.id" class="job">
        <header class="job-head" @click="toggle(job.id)">
          <span class="arrow">{{ expanded.has(job.id) ? '▾' : '▸' }}</span>
          <span class="type">{{ TYPE_LABEL[job.job_type] ?? job.job_type }}</span>
          <span class="job-title" :title="job.title">{{ job.title }}</span>
          <span class="status" :class="job.status">{{ statusLabel(job.status) }}</span>
          <span class="muted">{{ job.done_count ?? 0 }}/{{ job.total ?? 0 }}</span>
          <span class="muted">{{ elapsed(job) }}</span>
          <button
            v-if="job.status === 'pending' || job.status === 'running'"
            class="btn btn-sm cancel"
            :disabled="cancelling === job.id"
            @click.stop="cancel(job.id)"
          >
            取消
          </button>
        </header>

        <div class="progress">
          <div class="bar" :class="job.status" :style="{ width: `${percent(job)}%` }" />
        </div>

        <div v-if="expanded.has(job.id)" class="items">
          <div v-if="!job.items?.length" class="muted">无明细</div>
          <div v-for="(item, idx) in job.items ?? []" :key="idx" class="item">
            <img
              v-if="item.images?.[0]"
              :src="thumbUrl(item.images[0])"
              :alt="item.images[0].filename"
              loading="lazy"
            />
            <div class="item-body">
              <div class="item-preview">{{ item.prompt_preview || '（无预览）' }}</div>
              <div class="item-meta">
                <span :class="['item-status', item.status]">{{ statusLabel(item.status) }}</span>
                <span v-if="item.seed" class="muted">seed {{ item.seed }}</span>
                <span v-if="item.error" class="err">{{ item.error }}</span>
              </div>
            </div>
          </div>
        </div>
      </article>

      <EmptyState v-if="!visible.length" :text="onlyActive ? '没有进行中的任务' : '还没有任务记录'" />
    </div>
  </div>
</template>

<style scoped>
.jobs {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: var(--gap);
  padding: var(--gap) var(--gap-lg);
  border-bottom: 1px solid var(--border);
}

.title {
  font-weight: 600;
}

.badge {
  font-size: var(--fs-xs);
  color: var(--primary);
  border: 1px solid var(--primary);
  border-radius: 999px;
  padding: 1px 8px;
}

.spacer {
  flex: 1;
}

.check {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-sm);
  cursor: pointer;
}

.list {
  flex: 1;
  overflow-y: auto;
  padding: var(--gap) var(--gap-lg);
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.job {
  /* 关键：flex 容器里的子项默认可收缩，146 条任务会把每条压成几像素高的横线 */
  flex: none;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel);
  overflow: hidden;
}

.job-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap);
  cursor: pointer;
  font-size: var(--fs-sm);
}

.job-head:hover {
  background: var(--panel-2);
}

.arrow {
  color: var(--muted);
  width: 12px;
}

.type {
  font-size: var(--fs-xs);
  color: var(--muted);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0 6px;
  flex: none;
}

.job-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status {
  font-size: var(--fs-xs);
  flex: none;
}

.status.running,
.status.pending {
  color: var(--primary);
}

.status.done {
  color: var(--success);
}

.status.error {
  color: var(--danger);
}

.muted {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.cancel {
  flex: none;
}

.btn.cancel {
  border-color: var(--danger);
  color: #fecaca;
}

.progress {
  height: 3px;
  background: var(--panel-3);
}

.bar {
  height: 100%;
  background: var(--primary);
  transition: width 0.3s;
}

.bar.done {
  background: var(--success);
}

.bar.error {
  background: var(--danger);
}

.items {
  border-top: 1px solid var(--border);
  padding: var(--gap-sm) var(--gap);
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 320px;
  overflow-y: auto;
}

.item {
  display: flex;
  gap: var(--gap-sm);
  align-items: flex-start;
}

.item img {
  width: 46px;
  height: 46px;
  object-fit: contain;
  border-radius: var(--radius-sm);
  background: var(--panel-3);
  flex: none;
}

.item-body {
  flex: 1;
  min-width: 0;
}

.item-preview {
  font-size: var(--fs-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-meta {
  display: flex;
  gap: var(--gap-sm);
  font-size: 10px;
  align-items: center;
}

.item-status.done {
  color: var(--success);
}

.item-status.error {
  color: var(--danger);
}

.item-status.running,
.item-status.pending {
  color: var(--primary);
}

.err {
  color: var(--danger);
}

.empty {
  color: var(--muted);
  padding: 60px;
  text-align: center;
}
</style>
