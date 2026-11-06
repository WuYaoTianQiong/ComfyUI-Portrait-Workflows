<script setup lang="ts">
/**
 * 合成台「生成清单」（方案 §5 M3）。
 *
 * 纯展示组件：数据完全来自父级传入的 `buildBatchGroups()` 结果，**不请求后端**，
 * 也不产生任何 emit（行级「跳过该组」是 P2，需要先给提交链路加 `skipIndexes`）。
 *
 * 信息层级：
 * - 常驻计数 `N / 上限 100` + 线性进度条（方案 §3.7「常驻展示」要求）；
 * - 按槽位三元组（人像 id / 服装 id / 姿势 id）分组，组内保持 `groups` 原顺序；
 * - 默认仅第一组展开，其余折叠（折叠只隐藏视觉，行仍留在 DOM，便于计数与 a11y）；
 * - 超限时整块转危险色，并按「减少哪一维影响最大」给出可执行的减量提示。
 *
 * 性能：最多 100 行 × 3 图 = 300 个 `<img loading="lazy">`，不做虚拟滚动（方案已拍板）。
 */

import { computed, ref, watch } from 'vue'

import type {
  RecipeBatchGroup,
  RecipeSlots,
  StudioWorkflowOption,
} from '../../../../composables/useReferenceRecipe'
import { workflowDisplayName } from '../../../../composables/useReferenceRecipe'
import { costumeSlotName, costumeSlotThumb, poseSlotName, poseSlotThumb, portraitSlotName, portraitSlotThumb } from './slotView'

const props = defineProps<{
  /** 来自 `buildBatchGroups()` 的完整组合清单（顺序即提交/种子顺序）。 */
  groups: readonly RecipeBatchGroup[]
  /** 全组合数 N。 */
  total: number
  /** 全组合上限（当前契约 100）。 */
  limit: number
  /** 是否超过上限（由父级判定，组件不重复计算，避免口径漂移）。 */
  overLimit: boolean
  /** 后端 / composable 给出的超限文案。 */
  limitMessage: string
  /** 三槽各自选中的条目数，用于推算「减少 1 张能减多少组」。 */
  slotCounts: { portrait: number; costume: number; pose: number }
  /** 已选工作流数（至少按 1 计）。 */
  workflowCount: number
  /** 已选画质档数（能力不支持时按 1 计）。 */
  qualityCount: number
  /** 已选比例数（能力不支持时按 1 计）。 */
  ratioCount: number
  /** 工作流目录：用于把 `group.workflow` 路径映射成短名。 */
  workflows: readonly StudioWorkflowOption[]
  /** 姿势槽当前是否按深度图取缩略图。 */
  poseUseDepth: boolean
  /** 非空槽数（0 = 三槽都为空）。 */
  activeSlotCount: number
}>()

/** 分组键分隔符：用不可见控制字符避免真实 id 中可能出现的分隔符冲突。 */
const GROUP_KEY_SEPARATOR = '\u0000'

/** 单槽缩略图展示数据。 */
interface MatrixThumb {
  key: 'portrait' | 'costume' | 'pose'
  name: string
  url: string | null
}

/** 一个「槽位组合」分组（= 清单里可折叠的一块）。 */
interface MatrixGroup {
  key: string
  rows: RecipeBatchGroup[]
  thumbs: MatrixThumb[]
  /** 组头槽位名称：人像名 · 服装名 · 姿势名（空槽跳过）。 */
  title: string
  /** 组内去重后的工作流数（N）。 */
  workflowCount: number
  /** 组内去重后的尺寸档数（M，画质 + 比例组合）。 */
  sizeCount: number
}

/** 超限提示要建议减少的维度。 */
type ReduceDimension = 'portrait' | 'costume' | 'pose'

const DIMENSION_LABELS: Readonly<Record<ReduceDimension, string>> = {
  portrait: '人像',
  costume: '服装',
  pose: '姿势',
}

/** 槽位三元组 → 稳定的分组键（槽位为空时用空串占位，三段固定顺序）。 */
function groupKeyOf(group: RecipeBatchGroup): string {
  return [
    group.slots.portrait?.id ?? '',
    group.slots.costume?.id ?? '',
    group.slots.pose?.id ?? '',
  ].join(GROUP_KEY_SEPARATOR)
}

/** 泛型去重计数（保持简单：只关心「有几个不同值」）。 */
function countDistinct<T>(items: readonly T[], keyOf: (item: T) => string): number {
  const seen = new Set<string>()
  for (const item of items) seen.add(keyOf(item))
  return seen.size
}

/** 三槽缩略图（24 × 32）；缺槽或缺图时由模板渲染灰底「空」。 */
function buildThumbs(slots: RecipeSlots): MatrixThumb[] {
  return [
    {
      key: 'portrait',
      name: portraitSlotName(slots.portrait) || '人像（空）',
      url: portraitSlotThumb(slots.portrait),
    },
    {
      key: 'costume',
      name: costumeSlotName(slots.costume) || '服装（空）',
      url: costumeSlotThumb(slots.costume),
    },
    {
      key: 'pose',
      name: poseSlotName(slots.pose) || '姿势（空）',
      url: poseSlotThumb(slots.pose, props.poseUseDepth),
    },
  ]
}

/** 组头文案：只列非空槽的名称，全部为空时给通用占位。 */
function titleOf(slots: RecipeSlots): string {
  const names = [
    portraitSlotName(slots.portrait),
    costumeSlotName(slots.costume),
    poseSlotName(slots.pose),
  ].filter((name) => name.length > 0)
  return names.length ? names.join(' · ') : '未选参考图'
}

/**
 * 按槽位三元组分组（Map 保持首次出现顺序 → 组顺序与 `groups` 一致；
 * 组内 `push` 保持原顺序，绝不排序）。
 */
const groupedGroups = computed<MatrixGroup[]>(() => {
  const buckets = new Map<string, RecipeBatchGroup[]>()
  for (const group of props.groups) {
    const key = groupKeyOf(group)
    const bucket = buckets.get(key)
    if (bucket) bucket.push(group)
    else buckets.set(key, [group])
  }

  const result: MatrixGroup[] = []
  for (const [key, rows] of buckets) {
    const first = rows[0]
    if (!first) continue
    result.push({
      key,
      rows,
      thumbs: buildThumbs(first.slots),
      title: titleOf(first.slots),
      workflowCount: countDistinct(rows, (row) => row.workflow),
      sizeCount: countDistinct(rows, (row) => `${row.quality}${GROUP_KEY_SEPARATOR}${row.aspectRatio}`),
    })
  }
  return result
})

/** 当前展开的组键集合；默认只有第一组。 */
const expandedKeys = ref<Set<string>>(new Set())
/** 是否已完成「默认展开第一组」的初始化（用户主动收起后不再强行展开）。 */
const expansionInitialized = ref(false)

watch(
  groupedGroups,
  (list) => {
    if (!list.length) {
      expandedKeys.value = new Set()
      return
    }
    const validKeys = new Set(list.map((group) => group.key))
    // 过滤前先记录「上一次是否有展开组」：用来区分「用户主动收起全部」与
    // 「原展开组因删图/换图失效」——前者保持收起，后者应自动展开新首组。
    const hadExpanded = expandedKeys.value.size > 0
    const kept = [...expandedKeys.value].filter((key) => validKeys.has(key))
    if (!expansionInitialized.value) {
      expansionInitialized.value = true
      expandedKeys.value = new Set([list[0]!.key])
      return
    }
    if (hadExpanded && kept.length === 0) {
      // 删掉 1 张人像会让首组的组合键变化，旧 key 全部失效；
      // 此时若维持空集合，用户看到的是一份「全部收起」的死清单。
      expandedKeys.value = new Set([list[0]!.key])
      return
    }
    // 数据变化时保留仍然有效的展开项；用户「收起全部」后保持收起。
    expandedKeys.value = new Set(kept)
  },
  { immediate: true },
)

function isExpanded(key: string): boolean {
  return expandedKeys.value.has(key)
}

function toggleGroup(key: string): void {
  const next = new Set(expandedKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedKeys.value = next
}

function expandAll(): void {
  expandedKeys.value = new Set(groupedGroups.value.map((group) => group.key))
}

function collapseAll(): void {
  expandedKeys.value = new Set()
}

/** 空态：三槽都为空，或没有任何可展示的组合。 */
const isEmpty = computed(() => props.activeSlotCount === 0 || props.groups.length === 0)

/** 进度百分比：钳制在 0 ~ 100，`limit <= 0` 时按 0 处理，避免除零。 */
const progressPercent = computed(() => {
  if (!Number.isFinite(props.total) || !Number.isFinite(props.limit) || props.limit <= 0) {
    return 0
  }
  const raw = (props.total / props.limit) * 100
  const clamped = Math.min(100, Math.max(0, raw))
  // 保留两位小数，避免 33.333333333333336% 这类噪声写进 style。
  return Math.round(clamped * 100) / 100
})
const progressStyle = computed(() => `width: ${progressPercent.value}%`)
const progressValue = computed(() => Math.round(progressPercent.value))

/**
 * 超限减量提示：按「减少 1 张 X 可减 N 组」推算影响最大的维度。
 *
 * 公式（方案 §5 M3）：
 * - 减人像 = 服装数 × 姿势数 × 工作流数 × 画质档数 × 比例数
 * - 减服装 = 人像数 × 姿势数 × 工作流数 × 画质档数 × 比例数
 * - 减姿势 = 人像数 × 服装数 × 工作流数 × 画质档数 × 比例数
 *
 * 乘法里空槽按 1 档计（与 `countSlotCombinations` 同口径），否则空槽会把
 * 结果乘成 0，给出「减少工作流」的错误结论；而「是否可减」只看该维自身
 * 是否真的多于 1 张。
 */
const reductionHint = computed<string>(() => {
  const portraitDim = Math.max(1, props.slotCounts.portrait)
  const costumeDim = Math.max(1, props.slotCounts.costume)
  const poseDim = Math.max(1, props.slotCounts.pose)
  const workflowDim = Math.max(1, props.workflowCount)
  const sizeDim = Math.max(1, props.qualityCount) * Math.max(1, props.ratioCount)

  const candidates: Array<{ dimension: ReduceDimension; count: number; removed: number }> = [
    {
      dimension: 'portrait',
      count: props.slotCounts.portrait,
      removed: costumeDim * poseDim * workflowDim * sizeDim,
    },
    {
      dimension: 'costume',
      count: props.slotCounts.costume,
      removed: portraitDim * poseDim * workflowDim * sizeDim,
    },
    {
      dimension: 'pose',
      count: props.slotCounts.pose,
      removed: portraitDim * costumeDim * workflowDim * sizeDim,
    },
  ]

  let best: (typeof candidates)[number] | null = null
  for (const candidate of candidates) {
    if (candidate.count <= 1 || candidate.removed <= 0) continue
    if (!best || candidate.removed > best.removed) best = candidate
  }

  if (!best) return '减少工作流或尺寸档位可以更快降到上限以内'
  return `减少 1 张${DIMENSION_LABELS[best.dimension]}可减 ${best.removed} 组`
})

/** 行内工作流短名：空路径 = 后端默认工作流；目录里查不到时回退文件名。 */
function workflowNameOf(workflow: string): string {
  if (!workflow) return '默认工作流'
  const option = props.workflows.find((item) => item.path === workflow)
  if (option) return workflowDisplayName(option.name)
  const filename = workflow.split(/[\\/]/).pop() ?? workflow
  return workflowDisplayName(filename)
}

/** 行内尺寸：优先画质，其次比例；都没有表示「跟随参考图」。 */
function sizeTextOf(group: RecipeBatchGroup): string {
  const quality = group.quality.trim()
  const ratio = group.aspectRatio.trim()
  if (quality && ratio) return `${quality} · ${ratio}`
  if (quality) return quality
  if (ratio) return ratio
  return '跟随参考图'
}
</script>

<template>
  <section
    class="matrix"
    :class="{ 'is-over': overLimit }"
    data-testid="studio-matrix"
    aria-label="生成清单"
  >
    <header class="matrix__head">
      <h3 class="matrix__title">生成清单</h3>
      <span class="matrix__total" data-testid="studio-matrix-total">
        {{ total }} / 上限 {{ limit }}
      </span>
    </header>

    <!-- 常驻计数条：无论空态 / 超限都在，宽度永不超过 100% -->
    <div
      class="matrix__progress"
      data-testid="studio-matrix-progress"
      role="progressbar"
      aria-label="组合数占上限的比例"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-valuenow="progressValue"
    >
      <span
        class="matrix__progress-fill"
        data-testid="studio-matrix-progress-fill"
        :style="progressStyle"
      />
    </div>

    <p v-if="overLimit" class="matrix__limit" data-testid="studio-matrix-limit">
      <span v-if="limitMessage" class="matrix__limit-message">{{ limitMessage }}</span>
      <span class="matrix__limit-hint">{{ reductionHint }}</span>
    </p>

    <p v-if="isEmpty" class="matrix__empty" data-testid="studio-matrix-empty">
      三槽都为空：先选素材，这里会逐行列出每一张要生成的图
    </p>

    <template v-else>
      <div class="matrix__toolbar">
        <button type="button" class="matrix__tool" @click="expandAll">展开全部</button>
        <button type="button" class="matrix__tool" @click="collapseAll">收起全部</button>
      </div>

      <ul class="matrix__groups">
        <li
          v-for="group in groupedGroups"
          :key="group.key"
          class="matrix__group"
          data-testid="studio-matrix-group"
        >
          <div class="matrix__group-head">
            <button
              type="button"
              class="matrix__toggle"
              :aria-expanded="isExpanded(group.key)"
              @click="toggleGroup(group.key)"
            >
              <span class="matrix__caret" aria-hidden="true">{{ isExpanded(group.key) ? '▾' : '▸' }}</span>
              <span class="matrix__thumbs">
                <span
                  v-for="thumb in group.thumbs"
                  :key="thumb.key"
                  class="matrix__thumb"
                  :class="{ 'is-empty': !thumb.url }"
                  :title="thumb.name"
                >
                  <img
                    v-if="thumb.url"
                    :src="thumb.url"
                    :alt="thumb.name"
                    class="matrix__thumb-img"
                    loading="lazy"
                  />
                  <span v-else class="matrix__thumb-empty">空</span>
                </span>
              </span>
              <span class="matrix__group-name" :title="group.title">{{ group.title }}</span>
            </button>
            <span class="matrix__group-count">
              {{ group.workflowCount }} 工作流 × {{ group.sizeCount }} 尺寸 = {{ group.rows.length }} 组
            </span>
          </div>

          <!-- v-show 而非 v-if：折叠组仍留在 DOM，行可被计数，图片有 lazy 兜底 -->
          <ul v-show="isExpanded(group.key)" class="matrix__rows">
            <li
              v-for="row in group.rows"
              :key="row.index"
              class="matrix__row"
              data-testid="studio-matrix-row"
            >
              <span class="matrix__index">#{{ row.index + 1 }}</span>
              <span class="matrix__thumbs">
                <span
                  v-for="thumb in group.thumbs"
                  :key="thumb.key"
                  class="matrix__thumb"
                  :class="{ 'is-empty': !thumb.url }"
                  :title="thumb.name"
                >
                  <img
                    v-if="thumb.url"
                    :src="thumb.url"
                    :alt="thumb.name"
                    class="matrix__thumb-img"
                    loading="lazy"
                  />
                  <span v-else class="matrix__thumb-empty">空</span>
                </span>
              </span>
              <span class="matrix__workflow" :title="workflowNameOf(row.workflow)">
                {{ workflowNameOf(row.workflow) }}
              </span>
              <span class="matrix__size">{{ sizeTextOf(row) }}</span>
              <span class="matrix__seed">seed {{ row.seed }}</span>
            </li>
          </ul>
        </li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
/*
 * 颜色一律走 styles/tokens.css：本块内不允许出现十六进制色值（CI 基线 0）。
 * 行高 / 缩略图尺寸走局部变量并带兜底，父级布局需要时可直接覆盖。
 */
.matrix {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  padding: var(--gap);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-raised);
  color: var(--text-body);
}

.matrix.is-over {
  border-color: var(--danger-border);
  background: var(--danger-surface-faint);
}

.matrix__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--gap-sm);
}

.matrix__title {
  margin: 0;
  color: var(--text-strong);
  font-size: var(--fs-md);
  font-weight: 600;
  line-height: var(--lh-lg);
}

.matrix__total {
  flex: none;
  color: var(--text-muted);
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
  line-height: var(--lh-lg);
}

.matrix.is-over .matrix__total {
  color: var(--danger-text);
  font-weight: 600;
}

.matrix__progress {
  height: 6px;
  overflow: hidden;
  border-radius: var(--radius-pill);
  background: var(--fill-soft);
}

.matrix__progress-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--primary);
  transition: width var(--dur) var(--ease);
}

.matrix.is-over .matrix__progress-fill {
  background: var(--danger);
}

.matrix__limit {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-xs) var(--gap-sm);
  margin: 0;
  padding: var(--gap-sm);
  border-radius: var(--radius-sm);
  background: var(--danger-surface);
  color: var(--danger-text);
  font-size: var(--fs-sm);
  line-height: var(--lh-sm);
}

.matrix__limit-message {
  font-weight: 600;
}

.matrix__limit-hint {
  color: var(--danger-text-soft);
}

.matrix__empty {
  margin: 0;
  padding: var(--gap-md);
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: var(--lh-sm);
  text-align: center;
}

.matrix__toolbar {
  display: flex;
  justify-content: flex-end;
  gap: var(--gap-xs);
}

.matrix__tool {
  padding: 3px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
  color: var(--text-body-soft);
  font-size: var(--fs-sm);
  line-height: var(--lh-lg);
  cursor: pointer;
  transition:
    border-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.matrix__tool:hover {
  border-color: var(--primary);
  color: var(--text-strong);
}

.matrix__tool:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}

.matrix__groups,
.matrix__rows {
  margin: 0;
  padding: 0;
  list-style: none;
}

.matrix__groups {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
}

.matrix__group {
  overflow: hidden;
  border: 1px solid var(--border-faint);
  border-radius: var(--radius-sm);
  background: var(--surface-inset);
}

.matrix__group-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  min-height: 36px;
  padding: var(--gap-xs) var(--gap-sm);
}

.matrix__toggle {
  display: flex;
  flex: 1 1 auto;
  align-items: center;
  gap: var(--gap-sm);
  min-width: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.matrix__toggle:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 2px;
}

.matrix__caret {
  flex: none;
  width: 10px;
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1;
}

.matrix__thumbs {
  display: inline-flex;
  flex: none;
  gap: 2px;
}

/* 24 × 32；缺槽 / 缺图时灰底「空」 */
.matrix__thumb {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: var(--matrix-thumb-w, 24px);
  height: var(--matrix-thumb-h, 32px);
  overflow: hidden;
  border-radius: 3px;
  background: var(--surface-thumb);
}

.matrix__thumb.is-empty {
  background: var(--surface-card);
  color: var(--text-muted);
}

.matrix__thumb-img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.matrix__thumb-empty {
  font-size: var(--fs-sm);
  line-height: 1;
}

.matrix__group-name {
  min-width: 0;
  overflow: hidden;
  color: var(--text-strong);
  font-size: var(--fs-sm);
  font-weight: 500;
  line-height: var(--lh-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.matrix__group-count {
  flex: none;
  color: var(--text-muted);
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
  line-height: var(--lh-sm);
  white-space: nowrap;
}

.matrix__rows {
  border-top: 1px solid var(--border-faint);
}

.matrix__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-sm);
  min-height: var(--matrix-row-h, 44px);
  padding: var(--gap-xs) var(--gap-sm);
  border-top: 1px solid var(--border-faint);
}

.matrix__row:first-child {
  border-top: 0;
}

.matrix__index {
  flex: none;
  min-width: 34px;
  color: var(--text-muted);
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
  line-height: var(--lh-sm);
}

.matrix__workflow {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  color: var(--text-body-soft);
  font-size: var(--fs-sm);
  line-height: var(--lh-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.matrix__size {
  flex: none;
  color: var(--text-body-soft);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: var(--fs-sm);
  line-height: var(--lh-sm);
  white-space: nowrap;
}

.matrix__seed {
  flex: none;
  color: var(--text-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
  line-height: var(--lh-sm);
  white-space: nowrap;
}
</style>