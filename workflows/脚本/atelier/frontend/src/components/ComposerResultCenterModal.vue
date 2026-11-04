<script setup lang="ts">
import { ref, watch } from 'vue'

import EmptyState from './EmptyState.vue'
import Modal from './Modal.vue'
import { statusLabel } from '../utils/format'
import { thumbnailUrl } from '../api/client'
import { useImageLocation } from '../composables/useImageLocation'
import type { JobSnapshot } from '../api/types'

/**
 * 组合器「结果中心」。
 *
 * 旧版把预览文本和一组操作塞在底部，长文本看不全、也没法一次看多组。
 * 这里改成统一弹窗，三个页签：
 * · 画布：当前组合的完整文本 + 复制 / 存为提示词 / 试跑
 * · 随机组：组数 chips + 逐组勾选 / 重抽 / 删除，确认后才出图
 * · 任务结果：**本次会话提交过的所有任务**，逐条展开看每组的预览文本、状态与缩略图
 *
 * 组件只负责展示，所有状态都留在 ComposerView。
 */
const props = withDefaults(
  defineProps<{
    open: boolean
    tab: 'canvas' | 'random' | 'job'
    composed: string
    combos: string[]
    selected: number[]
    /** 本次会话提交过的任务（新→旧）；只显示最近一个会让多批次的图"看着丢了"。 */
    jobs: JobSnapshot[]
    count: number
    canvasCount: number
    fixedCount: number
    generating: boolean
    /** 队列里还没跑完的任务数：>1 说明后面还排着别的批次 */
    activeCount: number
  }>(),
  { jobs: () => [], count: 1, canvasCount: 0, fixedCount: 0, generating: false, activeCount: 0 },
)

/** 展开的任务 id；默认展开最新的那个，之后每来一个新任务都自动展开。 */
const expanded = ref<number[]>([])
watch(
  () => props.jobs.map((j) => j.id).join(','),
  () => {
    const newest = props.jobs[0]?.id
    if (newest && !expanded.value.includes(newest)) expanded.value = [newest, ...expanded.value]
  },
  { immediate: true },
)

function isOpen(jobId: number): boolean {
  return expanded.value.includes(jobId)
}

function toggleJob(jobId: number) {
  expanded.value = isOpen(jobId)
    ? expanded.value.filter((id) => id !== jobId)
    : [jobId, ...expanded.value]
}

const emit = defineEmits<{
  close: []
  'set-tab': [tab: 'canvas' | 'random' | 'job']
  'set-count': [n: number]
  regenerate: []
  confirm: []
  reroll: [index: number]
  remove: [index: number]
  toggle: [index: number]
  'run-canvas': []
  'copy-canvas': []
  'save-prompt': []
  'go-jobs': []
  /** 点缩略图看原图（原本只是链到 240px 缩略图，等于看了个更糊的版本）。 */
  'preview-image': [image: { filename: string; subfolder?: string | null; type?: string | null }]
}>()

const { revealImage } = useImageLocation()

/** 任务快照里的图片项用 `type` 而不是 `img_type`，这里做一次字段名转换。 */
function thumbUrl(image: { filename: string; subfolder?: string | null; type?: string | null }): string {
  return thumbnailUrl({ filename: image.filename, subfolder: image.subfolder, img_type: image.type }, 240)
}
</script>

<template>
  <Modal
    :open="open"
    title="结果中心"
    width="min(1180px, 96vw)"
    height="min(84vh, 920px)"
    @close="emit('close')"
  >
    <template #head>
      <div class="tabs">
        <button
          class="btn btn-sm"
          :class="{ active: tab === 'canvas' }"
          @click="emit('set-tab', 'canvas')"
        >
          画布 · {{ canvasCount }} 个碎片
        </button>
        <button
          class="btn btn-sm"
          :class="{ active: tab === 'random' }"
          @click="emit('set-tab', 'random')"
        >
          随机组{{ combos.length ? ` · ${combos.length}` : '' }}
        </button>
        <button
          class="btn btn-sm"
          :class="{ active: tab === 'job' }"
          @click="emit('set-tab', 'job')"
        >
          任务结果{{ jobs.length ? ` · ${jobs.length}` : '' }}
        </button>
      </div>
    </template>

    <div v-if="tab === 'canvas'" class="pane canvas-pane">
      <pre class="full">{{ composed || '（画布为空：点左侧碎片填入）' }}</pre>
      <div v-if="fixedCount" class="muted">已锁定 {{ fixedCount }} 列（随机时保持不变）</div>
    </div>

    <div v-else-if="tab === 'random'" class="pane random-pane">
      <div class="chips">
        <span class="muted">组数</span>
        <button
          v-for="n in [1, 3, 5, 10]"
          :key="n"
          class="res-chip"
          :class="{ on: count === n }"
          @click="emit('set-count', n)"
        >
          {{ n }} 组
        </button>
        <button class="btn btn-sm" @click="emit('regenerate')">重新抽取 {{ count }} 组</button>
        <span class="spacer" />
        <span class="muted">已选 {{ selected.length }} / {{ combos.length }}</span>
      </div>

      <div v-if="combos.length" class="res-grid" :class="{ single: combos.length === 1 }">
        <div
          v-for="(text, idx) in combos"
          :key="idx"
          class="res-card"
          :class="{ on: selected.includes(idx) }"
        >
          <div class="res-head">
            <label class="pick">
              <input
                type="checkbox"
                :checked="selected.includes(idx)"
                @change="emit('toggle', idx)"
              />
              <span>#{{ idx + 1 }}</span>
            </label>
            <span class="spacer" />
            <button class="btn btn-sm" title="重新抽取这一组" @click="emit('reroll', idx)">
              重抽
            </button>
            <button class="btn btn-sm danger" title="删除这一组" @click="emit('remove', idx)">
              删
            </button>
          </div>
          <pre class="res-text">{{ text }}</pre>
        </div>
      </div>
      <EmptyState v-else compact text="点「重新抽取」生成组合，再勾选确认出图" />
    </div>

    <div v-else class="pane job-pane">
      <div class="job-head">
        <span v-if="jobs.length" class="muted">
          本次会话共 {{ jobs.length }} 个任务<span v-if="activeCount">（{{ activeCount }} 个进行中）</span>
        </span>
        <span v-else class="muted">还没有提交任务</span>
      </div>

      <div class="job-list">
        <div v-for="jb in jobs" :key="jb.id" class="job-card">
          <button class="job-title" type="button" @click="toggleJob(jb.id)">
            <span class="caret">{{ isOpen(jb.id) ? '▾' : '▸' }}</span>
            <span :class="['st', jb.status]">{{ statusLabel(jb.status) }}</span>
            <span class="muted">{{ jb.done_count ?? 0 }} / {{ jb.total ?? 0 }}</span>
            <span class="job-name" :title="jb.title">{{ jb.title || `任务 #${jb.id}` }}</span>
            <span class="spacer" />
            <span class="muted">#{{ jb.id }}</span>
          </button>

          <div v-if="isOpen(jb.id)" class="job-items">
            <div v-for="(item, idx) in jb.items ?? []" :key="idx" class="job-row">
              <button
                v-if="item.images?.[0]"
                class="shot"
                type="button"
                :title="`查看原图：${item.images[0].filename}`"
                @click="emit('preview-image', item.images[0])"
              >
                <img :src="thumbUrl(item.images[0])" :alt="item.images[0].filename" loading="lazy" />
              </button>
              <button
                v-if="item.images?.[0]"
                class="locate"
                type="button"
                title="在资源管理器中定位原图"
                @click="revealImage(item.images[0])"
              >
                定位
              </button>
              <div v-else class="shot placeholder">{{ idx + 1 }}</div>
              <div class="job-body">
                <pre class="job-pre">{{ item.prompt_preview || '（无预览）' }}</pre>
                <div class="meta">
                  <span :class="['st', item.status]">{{ statusLabel(item.status || 'pending') }}</span>
                  <span v-if="item.seed" class="muted">seed {{ item.seed }}</span>
                  <span v-if="item.error" class="err">{{ item.error }}</span>
                </div>
              </div>
            </div>
            <EmptyState v-if="!jb.items?.length" compact text="正在提交，稍等…" />
          </div>
        </div>

        <EmptyState v-if="!jobs.length" compact text="先试跑，或在随机组里勾选确认出图" />
      </div>
    </div>

    <template #footer>
      <template v-if="tab === 'canvas'">
        <span class="spacer" />
        <button class="btn btn-sm" :disabled="!canvasCount" @click="emit('copy-canvas')">
          复制
        </button>
        <button class="btn btn-sm" :disabled="!canvasCount" @click="emit('save-prompt')">
          存为提示词
        </button>
        <button
          class="btn btn-sm primary"
          :class="{ loading: generating }"
          :disabled="generating || !canvasCount"
          @click="emit('run-canvas')"
        >
          {{ generating ? '提交中…' : '🚀 试跑' }}
        </button>
      </template>
      <template v-else-if="tab === 'random'">
        <span class="spacer" />
        <button class="btn btn-sm" :disabled="generating" @click="emit('close')">取消</button>
        <button
          class="btn btn-sm primary"
          :class="{ loading: generating }"
          :disabled="generating || !selected.length"
          @click="emit('confirm')"
        >
          {{ generating ? '提交中…' : `确认出图 ${selected.length} 组` }}
        </button>
      </template>
      <template v-else>
        <span class="spacer" />
        <button class="btn btn-sm" @click="emit('close')">关闭</button>
        <button class="btn btn-sm primary" @click="emit('go-jobs')">去任务页</button>
      </template>
    </template>
  </Modal>
</template>

<style scoped>
.btn {
  transition:
    color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}

.tabs {
  display: flex;
  gap: var(--gap-xs);
}

.pane {
  height: 100%;
  box-sizing: border-box;
  padding: var(--gap);
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}

.full {
  flex: 1;
  min-height: 0;
  margin: 0;
  overflow: auto;
  white-space: pre-wrap;
  font-size: var(--fs-sm);
  line-height: 1.6;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-sm);
}

.chips {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
  font-size: var(--fs-xs);
}

.res-chip {
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--muted);
  font-size: var(--fs-xs);
  padding: 1px 8px;
  transition:
    color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease);
}

.res-chip.on {
  border-color: var(--primary);
  background: var(--primary-soft);
  color: var(--primary);
}

.res-grid {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--gap);
  align-content: start;
}

/* 只有一组时铺满可用区域：不再限宽/垂直居中，否则四周留出大片空白，
   而正文反而挤在 34vh 的小滚动框里。让卡片吃满高度，正文自己滚。 */
.res-grid.single {
  grid-template-columns: minmax(0, 1fr);
  grid-auto-rows: minmax(0, 1fr);
  align-content: stretch;
}

.res-grid.single .res-card {
  height: 100%;
  min-height: 0;
}

.res-grid.single .res-text {
  flex: 1;
  min-height: 0;
  max-height: none;
}

.res-card {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel-2);
  padding: 4px 8px 6px;
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  transition: border-color var(--dur-fast) var(--ease);
}

.res-card.on {
  border-color: var(--primary);
}

.res-head {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
  font-size: var(--fs-xs);
  color: var(--muted);
}

.pick {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
  cursor: pointer;
}

.res-text {
  margin: 2px 0 0;
  font-size: var(--fs-xs);
  line-height: var(--lh-sm);
  white-space: pre-wrap;
  max-height: 34vh;
  overflow-y: auto;
}

.job-head {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-sm);
}

.job-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

/* 一个任务一张卡：标题行常驻，明细按需展开（多批次时不用一次铺满） */
.job-card {
  flex: none;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
  overflow: hidden;
}

.job-title {
  width: 100%;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: 5px 8px;
  border: none;
  background: transparent;
  font-size: var(--fs-sm);
  text-align: left;
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease);
}

.job-title:hover {
  background: var(--panel-3);
}

.caret {
  flex: none;
  width: 10px;
  color: var(--muted);
}

.job-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.job-items {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  padding: 0 6px 6px;
}

.job-row {
  display: flex;
  gap: var(--gap-sm);
  align-items: flex-start;
  padding: 5px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
}

.shot {
  flex: none;
  width: 52px;
  height: 52px;
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: var(--panel-3);
  display: grid;
  place-items: center;
  color: var(--muted);
  font-size: var(--fs-xs);
  /* 缩略图现在是按钮（点开看原图），抹掉浏览器默认外观 */
  border: none;
  padding: 0;
  cursor: zoom-in;
  transition: opacity var(--dur-fast) var(--ease);
}

.shot:hover img {
  opacity: 0.85;
}

.shot img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.locate {
  flex: none;
  align-self: center;
  padding: 1px 6px;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--muted);
  font-size: var(--fs-xs);
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease);
}

.locate:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.job-body {
  flex: 1;
  min-width: 0;
}

.job-pre {
  margin: 0;
  font-size: var(--fs-xs);
  line-height: var(--lh-sm);
  white-space: pre-wrap;
  max-height: 12vh;
  overflow-y: auto;
}

.meta {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-xs);
  margin-top: 2px;
}

.st {
  font-size: var(--fs-xs);
}

.st.running,
.st.pending {
  color: var(--primary);
}

.st.done {
  color: var(--success);
}

.st.error {
  color: var(--danger);
}

.muted {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.err {
  color: var(--danger);
  font-size: var(--fs-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.spacer {
  flex: 1;
}

@media (max-width: 900px) {
  .res-grid {
    grid-template-columns: 1fr;
  }
}
</style>
