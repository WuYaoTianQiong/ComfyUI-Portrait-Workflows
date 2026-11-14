<script setup lang="ts">
import EmptyState from './EmptyState.vue'
import PromptMatrixBoard from './PromptMatrixBoard.vue'
import Icon from './Icon.vue'
import type { PromptMatrixApi, MatrixBatch } from '../composables/usePromptMatrix'
import type { MatrixImage, MatrixPlan } from '../composables/useWorkflowMatrix'

/**
 * 横评批次堆叠：顶部是「下一轮」预览板，下面按新→旧叠历史批次。
 * 每次提交追加一个批次而不是覆盖——上一批还在跑时再跑别的提示词，
 * 旧批次的进度与结果原样保留，各自跟踪、各自清除、各自存为提示词。
 */
defineProps<{
  matrix: PromptMatrixApi
  /** 试跑弹窗里每个批次可存为提示词；详情页已有载体，不显示。 */
  saveable?: boolean
}>()

const emit = defineEmits<{
  compare: [items: MatrixImage[]]
  'open-image': [payload: { items: MatrixImage[]; index: number; prompt?: string; negative?: string }]
  favorite: [item: MatrixImage]
  save: [batch: MatrixBatch]
}>()

function frozenPlan(batch: MatrixBatch): MatrixPlan {
  return {
    rows: batch.rows,
    usable: batch.rows,
    count: batch.count,
    total: batch.cells.length,
    overLimit: false,
    targetSize: null,
    warnings: [],
    negativeEffective: 0,
  }
}

function batchRunning(batch: MatrixBatch): boolean {
  return batch.cells.some((c) => c.status === 'queued' || c.status === 'running')
}

function doneCount(batch: MatrixBatch): number {
  return batch.cells.filter((c) => c.status === 'done' && c.image).length
}

function excerpt(text: string): string {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length > 56 ? `${flat.slice(0, 56)}…` : flat
}

function fmtTime(iso: string): string {
  if (!iso) return '时间未记录'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '时间未记录'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
</script>

<template>
  <div class="stack">
    <PromptMatrixBoard
      v-if="matrix.previewCells.length"
      :plan="matrix.plan"
      :cells="matrix.previewCells"
      :running="false"
      :best-path="matrix.bestPath"
      :lock-seed="matrix.lockSeed"
      :seed-resolved="matrix.baseSeed > 0"
      title="下一轮预览"
      @clear="matrix.clearPreview()"
      @best="matrix.setBest($event)"
      @use-workflow="matrix.useWorkflow($event)"
      @compare="emit('compare', $event)"
      @open-image="emit('open-image', $event)"
      @favorite="emit('favorite', $event)"
    />

    <section v-for="(batch, i) in matrix.batches" :key="batch.id" class="batch">
      <div class="batch-head">
        <span class="batch-index">#{{ matrix.batches.length - i }}</span>
        <span class="batch-prompt" :title="batch.prompt || '（旧版本未记录提示词）'">
          {{ excerpt(batch.prompt) || '（未记录提示词）' }}
        </span>
        <span class="batch-meta">
          {{ fmtTime(batch.createdAt) }} · 种子 {{ batch.baseSeed }} · {{ batch.cells.length }} 张
        </span>
        <span class="grow" />
        <button
          v-if="saveable"
          class="btn btn-sm primary"
          type="button"
          :disabled="!doneCount(batch)"
          title="把这一批的文本存为提示词，并认领这批出好的图"
          @click="emit('save', batch)"
        >
          <Icon name="save" /> 存为提示词{{ doneCount(batch) ? `（${doneCount(batch)} 张）` : '' }}
        </button>
      </div>
      <PromptMatrixBoard
        :plan="frozenPlan(batch)"
        :cells="batch.cells"
        :running="batchRunning(batch)"
        :best-path="matrix.bestPath"
        :lock-seed="batch.lock"
        :seed-resolved="true"
        :title="`批次 #${matrix.batches.length - i}`"
        @retry="matrix.retry($event)"
        @rerun="matrix.rerun($event)"
        @clear="matrix.clearBatch(batch.id)"
        @best="matrix.setBest($event)"
        @use-workflow="matrix.useWorkflow($event)"
        @compare="emit('compare', $event)"
        @open-image="emit('open-image', { ...$event, prompt: batch.prompt, negative: batch.negative })"
        @favorite="emit('favorite', $event)"
      />
    </section>

    <EmptyState
      v-if="!matrix.batches.length && !matrix.previewCells.length"
      compact
      text="还没有试跑批次"
      hint="粘贴文本点「跑」开始；每次提交追加一个批次，旧批次的进度与结果会保留在这里。"
    />
  </div>
</template>

<style scoped>
.stack {
  display: flex;
  flex-direction: column;
}

.batch-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  flex-wrap: wrap;
  padding: var(--gap-sm) var(--gap-lg) 0;
  background: var(--panel);
}

.batch-index {
  flex: none;
  padding: 0 7px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  color: var(--muted);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
}

.batch-prompt {
  min-width: 0;
  max-width: 560px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-sm);
  font-weight: 500;
}

.batch-meta {
  color: var(--muted);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
}

.grow {
  flex: 1 1 auto;
}

.btn.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: rgb(255 255 255);
}

.btn.primary:disabled {
  opacity: 0.45;
  cursor: default;
}
</style>
