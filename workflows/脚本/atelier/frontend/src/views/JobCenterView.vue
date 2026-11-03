<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { useRouter } from 'vue-router'

import { cancelJob, listJobs, retryJob, stopAllJobs } from '../api/endpoints'
import { thumbnailUrl } from '../api/client'
import { useEscapeLayer } from '../composables/useEscapeLayer'
import { useImageLocation } from '../composables/useImageLocation'
import { useJobStream } from '../composables/useJobStream'
import EmptyState from '../components/EmptyState.vue'
import Lightbox from '../components/Lightbox.vue'
import QueryState from '../components/QueryState.vue'
import { useToast } from '../composables/useToast'
import { useImagePreview } from '../composables/useImagePreview'
import { useWorkflows } from '../composables/useWorkflows'
import type { JobSnapshot } from '../api/types'
import { formatDateTime, formatElapsed, statusLabel } from '../utils/format'
import { confirmDialog } from '../utils/naive'
import { readSession, writeSession } from '../composables/useSessionState'

const TERMINAL = new Set(['done', 'error', 'cancelled', 'stopped'])

/**
 * 任务中心：进行中 / 历史任务的实时视图。
 *
 * 用 SSE（`/api/jobs/events`）而不是轮询：后端本来就广播任务状态变化，
 * 前端再每 N 秒拉一次 /api/jobs 是把已经推过来的信息再问一遍。
 */
const {
  data,
  isFetching,
  isError: jobsError,
  error: jobsErr,
  refetch: refetchJobs,
} = useQuery({
  queryKey: ['jobs', 60],
  queryFn: () => listJobs({ limit: 60 }),
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
const router = useRouter()
/** 灯箱「出图档案」里的来源提示词：交给 App 路由到提示词页。 */
const emit = defineEmits<{ (e: 'jump-to-prompt', promptId: number): void }>()
const stopAll = useMutation({
  mutationFn: stopAllJobs,
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
/** 会话状态：筛选、当前打开的任务抽屉、滚动位置。 */
interface JobsSession {
  onlyActive: boolean
  selectedJobId: number | null
  scrollTop: number
}

const SESSION_KEY = 'pb.session.jobs'
const savedSession = readSession<JobsSession>(SESSION_KEY, {
  onlyActive: false,
  selectedJobId: null,
  scrollTop: 0,
})

const onlyActive = ref(savedSession.onlyActive)
const selectedJobId = ref<number | null>(savedSession.selectedJobId ?? null)

const listEl = ref<HTMLElement | null>(null)
let scrollSaveTimer: number | undefined

function saveSession() {
  writeSession(SESSION_KEY, {
    onlyActive: onlyActive.value,
    selectedJobId: selectedJobId.value,
    scrollTop: listEl.value?.scrollTop ?? savedSession.scrollTop,
  })
}

watch(
  [onlyActive, selectedJobId],
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

const stream = useJobStream((snapshot) => {
  const list = jobs.value.slice()
  const index = list.findIndex((j) => j.id === snapshot.id)
  if (index >= 0) list[index] = { ...list[index], ...snapshot }
  else list.unshift(snapshot)
  jobs.value = list
})

onMounted(() => {
  stream.open()
})

onBeforeUnmount(() => {
  if (scrollSaveTimer) window.clearTimeout(scrollSaveTimer)
  saveSession()
})

const selectedJob = computed(
  () => jobs.value.find((job) => job.id === selectedJobId.value) ?? null,
)
const selectedFirstImage = computed(
  () => selectedJob.value?.items?.[0]?.images?.[0] ?? null,
)

function openJob(id: number) {
  selectedJobId.value = id
}

function closeJob() {
  selectedJobId.value = null
}

useEscapeLayer(
  () => selectedJobId.value !== null,
  closeJob,
)

const cancelling = ref<number | null>(null)
const retrying = ref<number | null>(null)

function canRetry(job: JobSnapshot): boolean {
  if (job.error_count > 0) return true
  return (job.items ?? []).some(
    (item) => item.status === 'error' || item.status === 'cancelled' || item.status === 'stopped',
  )
}

async function retry(id: number) {
  retrying.value = id
  try {
    const result = await retryJob(id)
    if (result.success) {
      toast.success(
        result.idempotent
          ? `已接回重试任务 #${result.job_id}`
          : `已提交重试任务 #${result.job_id}（${result.submitted ?? 0} 条）`,
      )
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
    } else {
      toast.error(result.errors?.[0]?.error || '没有可重试的条目')
    }
  } catch (e) {
    toast.error(`重试失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    retrying.value = null
  }
}

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
    await cancelJob(id)
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
  const start = Date.parse(job.created_at)
  if (!start) return ''
  const end = TERMINAL.has(job.status) ? Date.parse(job.updated_at) : Date.now()
  if (!end) return ''
  return formatElapsed(Math.max(0, (end - start) / 1000))
}

/** 完成时间：只对终态任务有意义；运行中显示最近一次状态更新。 */
function finishTime(job: JobSnapshot): string {
  if (!job.updated_at) return ''
  return TERMINAL.has(job.status)
    ? formatDateTime(job.updated_at, true)
    : `更新于 ${formatDateTime(job.updated_at)}`
}

/** 工作流名：路径只取文件名，custom:// 伪路径直接显示名字。 */
function workflowName(job: JobSnapshot): string {
  const raw = job.workflow_path || ''
  if (!raw) return '未记录工作流'
  if (raw.startsWith('custom://')) return raw.slice('custom://'.length) || '自定义工作流'
  const base = raw.replace(/\\/g, '/').split('/').pop() || raw
  return base.replace(/\.json$/i, '')
}

function jobExtra(job: JobSnapshot): Record<string, unknown> {
  return (job.extra ?? {}) as Record<string, unknown>
}

function extraText(job: JobSnapshot, key: string, fallback = '—'): string {
  const value = jobExtra(job)[key]
  return value === null || value === undefined || value === '' ? fallback : String(value)
}

const TYPE_LABEL: Record<string, string> = {
  single: '单图',
  batch: '批量',
  faceswap: '图像编辑',
}

/** 任务快照里的图片项用 `type` 而不是 `img_type`，这里做一次字段名转换。 */
function thumbUrl(image: { filename: string; subfolder?: string | null; type?: string | null }): string {
  return thumbnailUrl({ filename: image.filename, subfolder: image.subfolder, img_type: image.type }, 200)
}

/** 点缩略图看原图：直接复用画廊那套灯箱（缩放/下载/收藏/投喂都在）。 */
const {
  items: previewItems,
  readonly: previewReadonly,
  open: previewOpen,
  preview: openPreviewImage,
  close: closePreviewImage,
} = useImagePreview()

const { revealImage } = useImageLocation()
/** 灯箱里的「投喂给工作流」需要工作流列表；与其他页共用同一份缓存。 */
const { workflows } = useWorkflows()

function openInGallery(filename: string) {
  closePreviewImage()
  router.push({ path: '/gallery', query: { image: filename } })
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

    <QueryState v-if="jobsError" :error="jobsErr" @retry="refetchJobs" />

    <div ref="listEl" class="list" @scroll.passive="onListScroll">
      <article v-for="job in visible" :key="job.id" class="job">
        <header class="job-head" @click="openJob(job.id)">
          <span class="type">{{ TYPE_LABEL[job.job_type] ?? job.job_type }}</span>
          <span class="job-title" :title="job.title">{{ job.title }}</span>
          <span class="status" :class="job.status">{{ statusLabel(job.status) }}</span>
          <div class="job-actions">
            <button
              v-if="canRetry(job)"
              class="btn btn-sm"
              :disabled="retrying === job.id"
              title="把失败/取消的条目重新提交"
              @click.stop="retry(job.id)"
            >
              {{ retrying === job.id ? '重试中…' : '重试' }}
            </button>
            <button
              v-if="job.status === 'pending' || job.status === 'running'"
              class="btn btn-sm cancel"
              :disabled="cancelling === job.id"
              @click.stop="cancel(job.id)"
            >
              取消
            </button>
          </div>

          <div class="job-subline">
            <span class="job-sub" :title="job.workflow_path ?? ''">
              {{ workflowName(job) }}
              <template v-if="job.quality"> · {{ job.quality }}</template>
              <template v-if="extraText(job, 'aspect_ratio', '')">
                · {{ extraText(job, 'aspect_ratio') }}
              </template>
            </span>
            <span class="job-meta">
              <span class="count" :title="`完成 ${job.done_count ?? 0} / 共 ${job.total ?? 0}`">
                {{ job.done_count ?? 0 }}/{{ job.total ?? 0 }}
              </span>
              <span class="meta-item" title="从提交到任务结束（含排队）">
                耗时 {{ elapsed(job) || '—' }}
              </span>
              <span class="meta-item" title="完成时间 / 最近状态更新">
                {{ finishTime(job) || '—' }}
              </span>
            </span>
          </div>
        </header>

        <div class="progress">
          <div class="bar" :class="job.status" :style="{ width: `${percent(job)}%` }" />
        </div>

      </article>

      <EmptyState v-if="!visible.length" :text="onlyActive ? '没有进行中的任务' : '还没有任务记录'" />
    </div>

    <div v-if="selectedJob" class="drawer-scrim" @click="closeJob" />
    <aside
      v-if="selectedJob"
      class="job-drawer"
      role="dialog"
      aria-modal="true"
      :aria-label="`任务详情：${selectedJob.title}`"
    >
      <header class="drawer-head">
        <div class="drawer-title">
          <span class="type">{{ TYPE_LABEL[selectedJob.job_type] ?? selectedJob.job_type }}</span>
          <h2 :title="selectedJob.title">{{ selectedJob.title }}</h2>
          <span class="status" :class="selectedJob.status">{{ statusLabel(selectedJob.status) }}</span>
        </div>
        <button class="btn btn-sm" @click="closeJob">关闭</button>
      </header>

      <div class="drawer-body">
        <div class="drawer-actions">
          <button
            v-if="canRetry(selectedJob)"
            class="btn btn-sm"
            :disabled="retrying === selectedJob.id"
            @click="retry(selectedJob.id)"
          >
            {{ retrying === selectedJob.id ? '重试中…' : '重试失败条目' }}
          </button>
          <button
            v-if="selectedJob.status === 'pending' || selectedJob.status === 'running'"
            class="btn btn-sm cancel"
            :disabled="cancelling === selectedJob.id"
            @click="cancel(selectedJob.id)"
          >
            取消任务
          </button>
          <button
            v-if="selectedFirstImage"
            class="btn btn-sm"
            @click="openPreviewImage(selectedFirstImage)"
          >
            查看首张原图
          </button>
        </div>

        <dl class="job-facts">
          <div><dt>工作流</dt><dd :title="selectedJob.workflow_path ?? ''">{{ workflowName(selectedJob) }}</dd></div>
          <div><dt>质量</dt><dd>{{ selectedJob.quality || '—' }}</dd></div>
          <div><dt>比例</dt><dd>{{ extraText(selectedJob, 'aspect_ratio') }}</dd></div>
          <div><dt>输出目录</dt><dd>{{ extraText(selectedJob, 'output_subfolder', '默认') }}</dd></div>
          <div><dt>提交</dt><dd>{{ formatDateTime(selectedJob.created_at, true) || '—' }}</dd></div>
          <div><dt>完成</dt><dd>{{ finishTime(selectedJob) || '—' }}</dd></div>
          <div><dt>进度</dt><dd>{{ selectedJob.done_count ?? 0 }}/{{ selectedJob.total ?? 0 }}</dd></div>
          <div><dt>耗时</dt><dd>{{ elapsed(selectedJob) || '—' }}</dd></div>
        </dl>

        <h3 class="drawer-subtitle">条目</h3>
        <div v-if="!selectedJob.items?.length" class="muted">无明细</div>
        <div v-for="(item, idx) in selectedJob.items ?? []" :key="idx" class="item">
          <button
            v-if="item.images?.[0]"
            class="thumb"
            type="button"
            :title="`查看原图：${item.images[0].filename}`"
            @click="openPreviewImage(item.images[0])"
          >
            <img :src="thumbUrl(item.images[0])" :alt="item.images[0].filename" loading="lazy" />
          </button>
          <button
            v-if="item.images?.[0]"
            class="btn btn-xs locate"
            type="button"
            title="在资源管理器中定位原图"
            @click="revealImage(item.images[0])"
          >
            定位
          </button>
          <div class="item-body">
            <div class="item-preview">{{ item.prompt_preview || '（无预览）' }}</div>
            <div class="item-meta">
              <span :class="['item-status', item.status]">
                {{ item.submit_state === 'queued' ? '排队中' : statusLabel(item.status) }}
              </span>
              <span v-if="item.seed" class="muted">seed {{ item.seed }}</span>
              <span v-if="item.error" class="err">{{ item.error }}</span>
            </div>
          </div>
        </div>
      </div>
    </aside>

    <Lightbox
      v-if="previewOpen"
      :items="previewItems"
      :index="0"
      :readonly="previewReadonly"
      :workflows="workflows"
      can-open-gallery
      @close="closePreviewImage"
      @open-in-gallery="openInGallery"
      @jump-to-prompt="(id) => { closePreviewImage(); emit('jump-to-prompt', id) }"
      @changed="queryClient.invalidateQueries({ queryKey: ['jobs'] })"
    />
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
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  /* 卡片是 overflow:hidden 的滚动容器，auto 行高只按最小内容算会把卡片压扁；
     max-content 才能让每行跟卡片实际高度走（展开后也自动变高） */
  grid-auto-rows: max-content;
  align-content: start;
  align-items: start;
  gap: var(--gap-sm);
}

.job {
  /* 多列卡片：宽度自适应，内容多时只撑高自己这一张 */
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel);
  overflow: hidden;
}

/* 两行表头：第一行标题/状态/操作，第二行工作流/进度/耗时/时间 */
.job-head {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  grid-template-areas:
    'type title status actions'
    'sub sub sub sub';
  align-items: center;
  gap: 2px var(--gap-sm);
  padding: 6px var(--gap);
  cursor: pointer;
  font-size: var(--fs-sm);
}

.job-head:hover {
  background: var(--panel-2);
}

.type {
  grid-area: type;
  font-size: var(--fs-xs);
  color: var(--muted);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0 6px;
  white-space: nowrap;
}

.job-title {
  grid-area: title;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status {
  grid-area: status;
  font-size: var(--fs-xs);
  white-space: nowrap;
}

.job-actions {
  grid-area: actions;
  display: flex;
  gap: var(--gap-xs);
}

.job-actions .btn {
  flex: none;
  white-space: nowrap;
}

.job-subline {
  grid-area: sub;
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  min-width: 0;
}

.job-sub {
  flex: 1;
  min-width: 0;
  font-size: var(--fs-xs);
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.job-meta {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
}

.count,
.meta-item {
  font-size: var(--fs-xs);
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.count {
  min-width: 30px;
  text-align: right;
}

.job-facts {
  margin: 0 0 var(--gap-sm);
  padding: 6px 8px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 4px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
}

.job-facts div {
  display: flex;
  gap: 8px;
  min-width: 0;
  font-size: var(--fs-xs);
}

.job-facts dt {
  flex: none;
  width: 48px;
  color: var(--muted);
}

.job-facts dd {
  margin: 0;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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

.thumb {
  border: none;
  padding: 0;
  background: none;
  cursor: zoom-in;
  flex: none;
  display: flex;
}

.locate {
  flex: none;
  align-self: center;
  font-size: 10px;
  padding: 1px 6px;
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

.drawer-scrim {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.32);
  z-index: var(--z-modal);
}

.job-drawer {
  position: fixed;
  top: 0;
  right: 0;
  width: min(560px, 94vw);
  height: 100%;
  z-index: calc(var(--z-modal) + 1);
  display: flex;
  flex-direction: column;
  background: var(--panel);
  border-left: 1px solid var(--border);
  box-shadow: -12px 0 32px rgba(0, 0, 0, 0.28);
}

.drawer-head {
  flex: none;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--gap);
  padding: var(--gap);
  border-bottom: 1px solid var(--border);
}

.drawer-title {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  min-width: 0;
  flex-wrap: wrap;
}

.drawer-title .type,
.drawer-title .status {
  grid-area: auto;
}

.drawer-title h2 {
  margin: 0;
  font-size: var(--fs-md);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.drawer-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--gap);
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}

.drawer-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-sm);
}

.drawer-subtitle {
  margin: 0;
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--muted);
}

.empty {
  color: var(--muted);
  padding: 60px;
  text-align: center;
}
</style>
