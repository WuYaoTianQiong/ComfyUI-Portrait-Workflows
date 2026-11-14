<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import EmptyState from './EmptyState.vue'
import { thumbnailUrl } from '../api/client'
import type { MatrixCell, MatrixImage, MatrixPlan } from '../composables/useWorkflowMatrix'
import { useImageLocation } from '../composables/useImageLocation'

/**
 * 横评结果矩阵：列 = 工作流，行 = 第 N 张（种子 +1）。
 *
 * 为什么是矩阵而不是瀑布流：横评要回答「同一句话在不同模型下差在哪」，
 * 只有把同一提示词、同一种子的结果按模型对齐，差异才是可比的。
 * 竖图为主的内容按列并排才能吃满横向宽度——行式布局会把格子
 * 限死在窄条里，弹窗右半整片留白。每格标注真实尺寸与种子，
 * 各流原生尺寸不同，不标出来就会拿不同条件比。
 *
 * 纯展示 + 选择：提交、任务跟踪、图片回填都在宿主视图，
 * 对比与灯箱复用画廊既有组件，这里只把选中的成图引用抛上去。
 */
const props = defineProps<{
  plan: MatrixPlan
  cells: MatrixCell[]
  running: boolean
  bestPath: string
  lockSeed: boolean
  /** 基准种子是否已定：未提交且没有保存种子时，预览格不该显示 0 / 1 这种假种子 */
  seedResolved: boolean
  /** 堆叠多批次时区分标题；默认横评矩阵 */
  title?: string
}>()

const emit = defineEmits<{
  submit: []
  retry: [key: string]
  rerun: [keys: string[]]
  compare: [items: MatrixImage[]]
  'open-image': [payload: { items: MatrixImage[]; index: number }]
  best: [path: string]
  'use-workflow': [path: string]
  favorite: [item: MatrixImage]
  clear: []
}>()

const { revealImage } = useImageLocation()
const selected = ref<string[]>([])
const collapsed = ref(false)

const byKey = computed(() => new Map(props.cells.map((c) => [c.key, c])))
const doneCells = computed(() => props.cells.filter((c) => c.status === 'done' && c.image))
const doneImages = computed(() => doneCells.value.map((c) => c.image as MatrixImage))
const errorCount = computed(() => props.cells.filter((c) => c.status === 'error').length)
const activeCount = computed(() =>
  props.cells.filter((c) => c.status === 'queued' || c.status === 'running').length,
)
const selectedItems = computed(() =>
  selected.value
    .map((key) => byKey.value.get(key))
    .filter((c): c is MatrixCell => Boolean(c && c.image))
    .map((c) => c.image as MatrixImage),
)

/** 行 = 第 N 张，列对齐 plan.usable；旧批结果缺的列补 null 占位，列才不会错位。 */
const shotRows = computed<(MatrixCell | null)[][]>(() =>
  Array.from({ length: props.plan.count }, (_, n) =>
    props.plan.usable.map(
      (row) => props.cells.find((c) => c.path === row.path && c.col === n) ?? null,
    ),
  ),
)

/** 计划变了（换流 / 换档 / 换张数）旧的勾选就不再指向同一批图。 */
watch(
  () => props.cells.map((c) => c.key).join('|'),
  () => {
    selected.value = selected.value.filter((key) => byKey.value.has(key))
  },
)

function toggleSelect(cell: MatrixCell) {
  if (!cell.image) return
  if (selected.value.includes(cell.key)) {
    selected.value = selected.value.filter((k) => k !== cell.key)
    return
  }
  if (selected.value.length >= 4) return
  selected.value = [...selected.value, cell.key]
}

function clearSelection() {
  selected.value = []
}

function openImage(cell: MatrixCell) {
  if (!cell.image) return
  const index = doneImages.value.findIndex((img) => img.filename === cell.image?.filename)
  emit('open-image', { items: doneImages.value, index: Math.max(0, index) })
}

function reveal(cell: MatrixCell) {
  if (cell.image) revealImage(cell.image)
}

function statusText(cell: MatrixCell): string {
  if (cell.status === 'queued') return '排队中'
  if (cell.status === 'running') return '生成中'
  return ''
}

/** 预览格还没定种子（提交时才落定），不要显示成 0 / 1 这种假值。 */
function seedText(cell: MatrixCell | undefined): string {
  if (!cell) return '—'
  if (!props.seedResolved && !cell.jobId) return '提交时确定'
  return String(cell.seed)
}

/** 参数改过但结果还是上一批：必须说清楚，否则会拿旧图当新条件的结论。 */
const stale = computed(() =>
  props.cells.some((c) => {
    if (!c.jobId) return false
    const row = props.plan.usable.find((r) => r.path === c.path)
    return Boolean(row && (row.tier !== c.tier || row.width !== c.width || row.height !== c.height))
  }),
)

/** 回退不是静默改写：把该流的档位机制与可用档说清楚。 */
function fallbackReason(row: MatrixPlan['usable'][number]): string {
  const mode = row.qualityMode === 'megapixels' ? '目标 MP' : '倍率'
  return `「${row.shortName}」按${mode}机制只有 ${row.tiers.join(' / ') || '—'} 档；你选的 ${row.requestedTier} 不在其中，已改用 ${row.tier}。比例与方向仍按你的设定。`
}
</script>

<template>
  <section class="matrix" aria-label="多工作流横评结果">
    <div class="matrix-head">
      <span class="matrix-title">{{ title ?? '横评矩阵' }}</span>
      <span class="matrix-sub">列 = 工作流 · 行 = 第 N 张{{ lockSeed ? '（同种子）' : '（各自随机种子）' }}</span>
      <span class="grow" />
      <span v-if="running" class="matrix-stat running">
        进行中 · {{ doneCells.length }} / {{ cells.length }}
      </span>
      <span v-else-if="doneCells.length || errorCount" class="matrix-stat">
        完成 {{ doneCells.length }}<template v-if="errorCount"> · 失败 {{ errorCount }}</template>
        / {{ cells.length }}
      </span>
      <span v-else class="matrix-stat">待提交 {{ cells.length }} 张</span>
      <button class="btn btn-sm" type="button" @click="collapsed = !collapsed">
        {{ collapsed ? '展开' : '折叠' }}
      </button>
      <button
        class="btn btn-sm"
        type="button"
        :disabled="running || !cells.length"
        title="清空本批结果（不删除已出的图）"
        @click="emit('clear'); clearSelection()"
      >
        清除
      </button>
    </div>

    <div v-if="!collapsed" class="matrix-body">
      <EmptyState
        v-if="!plan.usable.length"
        compact
        text="还没有可横评的工作流"
        hint="在上方工作流选择器里勾选多个文生图工作流；编辑 / 超分 / 视频类不参与文本横评。"
      />

      <div v-else class="matrix-scroll">
        <div class="matrix-grid" :style="{ '--cols': plan.usable.length }">
          <div v-for="row in plan.usable" :key="`head-${row.path}`" class="col-head">
            <span class="col-name">
              {{ row.shortName }}
              <span v-if="bestPath === row.path" class="best-tag">★ 最佳</span>
            </span>
            <span class="col-meta">{{ row.width }}×{{ row.height }} · {{ row.tier }}</span>
            <span v-if="row.tierFallback" class="col-warn" :title="fallbackReason(row)">档位已回退</span>
            <span v-if="Math.abs(row.deviation) > 0.02" class="col-warn">
              偏差 {{ row.deviation > 0 ? '+' : '' }}{{ Math.round(row.deviation * 100) }}%
            </span>
            <div class="col-actions">
              <button class="btn btn-sm" type="button" @click="emit('best', row.path)">
                {{ bestPath === row.path ? '★ 已选最佳' : '选为最佳' }}
              </button>
              <button
                class="btn btn-sm"
                type="button"
                title="退出横评，改用这个工作流单跑"
                @click="emit('use-workflow', row.path)"
              >
                用它单跑
              </button>
            </div>
          </div>

          <template v-for="(shots, n) in shotRows" :key="`shot-${n}`">
            <div class="shot-head">
              第 {{ n + 1 }} 张
              <span class="shot-seed">种子 {{ seedText(shots[0] ?? undefined) }}</span>
            </div>
            <div
              v-for="(cell, i) in shots"
              :key="cell ? cell.key : `miss-${n}-${i}`"
              class="cell"
              :class="cell ? [cell.status, { picked: selected.includes(cell.key) }] : 'missing'"
              :style="cell && cell.status === 'done' ? { '--ar': `${cell.width} / ${cell.height}` } : undefined"
            >
              <template v-if="cell && cell.status === 'done' && cell.image">
                <button class="cell-shot" type="button" :title="cell.image.filename" @click="openImage(cell)">
                  <img
                    :src="thumbnailUrl(cell.image, 400)"
                    :alt="`${plan.usable[i].shortName} 第 ${n + 1} 张`"
                    loading="lazy"
                  />
                </button>
                <input
                  class="cell-pick"
                  type="checkbox"
                  :checked="selected.includes(cell.key)"
                  :aria-label="`选择 ${plan.usable[i].shortName} 第 ${n + 1} 张用于对比`"
                  @change="toggleSelect(cell)"
                />
                <div class="cell-marks">
                  <span v-if="cell.image.is_favorite" class="mark fav">♥</span>
                  <span v-if="bestPath === cell.path" class="mark best">★</span>
                </div>
                <div class="cell-foot">
                  <span>{{ cell.width }}×{{ cell.height }}</span>
                  <span class="grow" />
                  <button class="mini" type="button" title="在资源管理器定位" @click="reveal(cell)">📂</button>
                  <button
                    v-if="cell.image.id"
                    class="mini"
                    type="button"
                    :title="cell.image.is_favorite ? '取消收藏' : '加入精选'"
                    @click="emit('favorite', cell.image)"
                  >
                    {{ cell.image.is_favorite ? '♥' : '♡' }}
                  </button>
                </div>
              </template>

              <div v-else-if="cell && cell.status === 'error'" class="cell-state error">
                <span class="state-title">失败</span>
                <span class="state-detail">{{ cell.error || '任务失败' }}</span>
                <button class="btn btn-sm" type="button" @click="emit('retry', cell.key)">重试这一格</button>
              </div>

              <div v-else-if="cell && (cell.status === 'queued' || cell.status === 'running')" class="cell-state busy">
                <span class="spinner" aria-hidden="true" />
                <span class="state-title">{{ statusText(cell) }}</span>
                <span class="state-detail">种子 {{ seedText(cell) }}</span>
                <span v-if="cell.jobId" class="state-detail">任务 #{{ cell.jobId }}</span>
              </div>

              <div v-else-if="cell" class="cell-state idle">
                <span class="state-title">待提交</span>
                <span class="state-detail">{{ cell.width }}×{{ cell.height }}</span>
                <span class="state-detail">种子 {{ seedText(cell) }}</span>
              </div>

              <div v-else class="cell-state idle">
                <span class="state-title">不在上一批</span>
                <span class="state-detail">重新提交后出图</span>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>

    <div v-if="selected.length" class="matrix-bar" role="group" aria-label="横评结果批量操作">
      <span class="bar-count">已选 {{ selected.length }} 张</span>
      <button
        class="btn btn-sm"
        type="button"
        :disabled="selected.length < 2"
        @click="emit('compare', selectedItems)"
      >
        并排对比
      </button>
      <button
        class="btn btn-sm"
        type="button"
        @click="emit('best', byKey.get(selected[0])?.path ?? '')"
      >
        选为最佳
      </button>
      <button class="btn btn-sm" type="button" @click="emit('rerun', selected)">重跑选中</button>
      <button class="btn btn-sm" type="button" @click="clearSelection">清除选择</button>
    </div>

    <p v-if="stale" class="matrix-note warn">
      参数已改动：下方结果来自上一批提交，重新点「横评出图」才会按新条件出图。
    </p>
    <p v-if="activeCount" class="matrix-note">
      任务在 ComfyUI 里排队执行；关掉页面不会取消，回来可在任务中心继续看。
    </p>
  </section>
</template>

<style scoped>
.matrix {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  padding: var(--gap) var(--gap-lg);
  border-bottom: 1px solid var(--border);
  background: var(--panel);
}

.matrix-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  flex-wrap: wrap;
}

.matrix-title {
  font-size: var(--fs-sm);
  font-weight: 500;
}

.matrix-sub,
.matrix-note {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.matrix-note {
  margin: 0;
}

.matrix-note.warn {
  color: var(--warn);
}

.matrix-stat {
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--muted);
  font-size: var(--fs-xs);
}

.matrix-stat.running {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-soft);
}

.grow {
  flex: 1 1 auto;
}

.matrix-body {
  min-width: 0;
}

/* 工作流多于可视宽度时横向滚动；滚动条跟面板配色。 */
.matrix-scroll {
  overflow-x: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border-strong) var(--panel);
  padding-bottom: 2px;
}

.matrix-scroll::-webkit-scrollbar {
  height: 10px;
}

.matrix-scroll::-webkit-scrollbar-track {
  background: var(--panel);
}

.matrix-scroll::-webkit-scrollbar-thumb {
  background: var(--border-strong);
  border: 2px solid var(--panel);
  border-radius: 999px;
}

.matrix-scroll::-webkit-scrollbar-thumb:hover {
  background: var(--muted);
}

.matrix-grid {
  display: grid;
  grid-template-columns: repeat(var(--cols), minmax(168px, 1fr));
  gap: var(--gap-sm);
  align-items: stretch;
  /* 流很少时不让单列被拉成超宽横条，竖图两侧留白反而浪费。 */
  max-width: calc(var(--cols) * 380px + (var(--cols) - 1) * var(--gap-sm));
}

.col-head {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  padding: var(--gap-sm);
  border: 1px solid var(--border);
  border-top: 3px solid var(--primary);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
}

.col-name {
  font-size: var(--fs-sm);
  font-weight: 500;
  word-break: break-word;
}

.best-tag {
  color: var(--warn);
  font-size: var(--fs-xs);
}

.col-meta {
  color: var(--muted);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
}

.col-warn {
  color: var(--warn);
  font-size: var(--fs-xs);
}

.col-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-xs);
  margin-top: auto;
  padding-top: var(--gap-xs);
}

.col-actions .btn {
  padding: 2px 6px;
  font-size: var(--fs-xs);
}

.shot-head {
  grid-column: 1 / -1;
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: var(--gap-sm);
  color: var(--muted);
  font-size: var(--fs-xs);
}

.shot-seed {
  font-variant-numeric: tabular-nums;
}

.cell {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 150px;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
}

/* 成图格按真实出图比例取高，同行未完成的格子被网格拉伸对齐。 */
.cell.done {
  aspect-ratio: var(--ar);
  min-height: 220px;
  max-height: 520px;
}

.cell.picked {
  outline: 2px solid var(--primary);
  outline-offset: -2px;
}

.cell.error {
  border-color: var(--danger);
}

.cell-shot {
  flex: 1 1 auto;
  min-height: 0;
  padding: 0;
  border: none;
  background: var(--panel-3);
  cursor: zoom-in;
}

.cell-shot img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.cell-pick {
  position: absolute;
  top: 6px;
  left: 6px;
  width: 18px;
  height: 18px;
  accent-color: var(--primary);
  cursor: pointer;
}

.cell-marks {
  position: absolute;
  top: 6px;
  right: 6px;
  display: flex;
  gap: 4px;
}

.mark {
  padding: 0 6px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: var(--panel);
  font-size: var(--fs-xs);
}

.mark.best {
  color: var(--warn);
  border-color: var(--warn);
}

.mark.fav {
  color: var(--danger);
  border-color: var(--danger);
}

.cell-foot {
  flex: none;
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  padding: 3px 6px;
  border-top: 1px solid var(--border);
  background: var(--panel);
  color: var(--muted);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
}

.cell-foot > span:first-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mini {
  padding: 0 3px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: var(--fs-xs);
}

.mini:hover {
  background: var(--panel-3);
  color: var(--text);
}

.cell-state {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: var(--gap-sm);
  text-align: center;
}

.cell-state.error {
  background: var(--danger-surface);
}

.state-title {
  font-size: var(--fs-sm);
}

.cell-state.error .state-title {
  color: var(--danger);
}

.state-detail {
  color: var(--muted);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
  word-break: break-word;
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--border-strong);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: matrix-spin 0.9s linear infinite;
}

@keyframes matrix-spin {
  to {
    transform: rotate(360deg);
  }
}

.matrix-bar {
  position: sticky;
  bottom: var(--gap-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--gap-xs);
  flex-wrap: wrap;
  align-self: center;
  max-width: 100%;
  padding: 6px 14px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: var(--panel);
  box-shadow: var(--shadow-2);
}

.bar-count {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.matrix-bar .btn {
  border-radius: 999px;
}

@media (max-width: 720px) {
  .matrix {
    padding: var(--gap-sm);
  }

  .matrix-grid {
    grid-template-columns: repeat(var(--cols), minmax(150px, 1fr));
  }
}

@media (prefers-reduced-motion: reduce) {
  .spinner {
    animation: none;
  }
}
</style>
