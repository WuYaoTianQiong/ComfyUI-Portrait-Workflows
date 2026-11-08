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

import {
  EMPTY_SLOT_TEXTS,
  buildRecipeSlotDisplays,
  compilePersonBVariant,
  resolveSlotModes,
  slotDisplaysGroupKey,
  slotDisplaysGroupLabel,
  slotTextPreview,
} from '../../../../composables/recipeTextFragments'
import type {
  RecipeSlotDisplaySlot,
  RecipeSlotKey,
  RecipeSlotMode,
  RecipeSlotModes,
  RecipeSlotTexts,
  RecipeSupplementFlags,

} from '../../../../composables/recipeTextFragments'
import type {
  RecipeBatchGroup,

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
  /**
   * 当前三槽模式（P2）。
   *
   * group 自带同名字段时优先用 group 的（每批可能不同）；这里作为旧批次 / 直接
   * 构造 groups 时的回退来源。
   */
  slotModes?: RecipeSlotModes
  /** 当前三槽文本（同上，作为 group.slotTexts 的回退）。 */
  slotTexts?: RecipeSlotTexts
  /** P4 跨源补充开关：image 槽的补充文本进入组键并在缩略图标「补充」。 */
  supplementFlags?: RecipeSupplementFlags
  /**
   * P0-5：当前批次级人物 B 信息（身份图 / B 服装 / 文字变体数）。
   *
   * 身份图与 B 服装是整批共享输入，不进入逐组组合，因此在清单头单独列一行，
   * 避免用户只看到逐组的 B 文字却不知道身份图与服装是否已选。
   */
  personBInfo?: string
}>()

/** 分组键分隔符：用不可见控制字符避免真实 id 中可能出现的分隔符冲突。 */
const GROUP_KEY_SEPARATOR = '\u0000'

/** 单槽缩略图展示数据。 */
interface MatrixThumb {
  key: RecipeSlotKey
  name: string
  url: string | null
  /** 槽位模式：text 时渲染「文本 · 类型」chip，而不是空图占位。 */
  mode: RecipeSlotMode
  /** `文本 · 类型`；image / empty 为空串。 */
  textLabel: string
  /** 文本前 12 字；image / empty 为空串。 */
  textPreview: string
  /** P4：image 模式 + 补充开关打开时的「补充 · 类型」小标。 */
  supplementLabel: string
  supplementPreview: string
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

/** 空槽缩略图标题（与原矩阵口径一致）。 */
const EMPTY_THUMB_LABELS: Readonly<Record<RecipeSlotKey, string>> = {
  portrait: '人像（空）',
  costume: '服装（空）',
  pose: '姿势（空）',
}

/** group 自带模式优先；旧批次没有字段时回退到父级传入 / 全 image。 */
function modesOf(group: RecipeBatchGroup): RecipeSlotModes {
  return resolveSlotModes(group.slotModes ?? props.slotModes)
}

/** group 自带文本优先；旧批次回退到父级 / 全空。 */
function textsOf(group: RecipeBatchGroup): RecipeSlotTexts {
  return group.slotTexts ?? props.slotTexts ?? { ...EMPTY_SLOT_TEXTS }
}

/** 槽位条目 → 组键 / 组名需要的 id + name（空槽为 null）。 */
function displaySlotOf<T extends { id: string }>(
  item: T | null,
  nameOf: (value: T) => string,
): RecipeSlotDisplaySlot | null {
  return item ? { id: item.id, name: nameOf(item) } : null
}

/** 三槽展示片段：image 用条目 id / 名称，text 用文本内容 / 前 12 字。 */
function displaysOf(group: RecipeBatchGroup) {
  return buildRecipeSlotDisplays({
    slots: {
      portrait: displaySlotOf(group.slots.portrait, portraitSlotName),
      costume: displaySlotOf(group.slots.costume, costumeSlotName),
      pose: displaySlotOf(group.slots.pose, poseSlotName),
    },
    modes: modesOf(group),
    texts: textsOf(group),
    supplements: props.supplementFlags,
  })
}

/**
 * 组键：image 槽用条目 id，text 槽用完整文本内容。
 *
 * 不同文本必须落到不同组（方案 §4.4），否则矩阵会把两个替代态合并成一组。
 */
function groupKeyOf(group: RecipeBatchGroup): string {
  const key = slotDisplaysGroupKey(displaysOf(group))
  // v1.5：同一张 A 人像配不同 B 变体必须落不同组，否则矩阵会把它们合并成一行。
  return group.personBVariant ? `${key}${GROUP_KEY_SEPARATOR}b:${group.personBVariant.id}` : key
}

/** B 变体组头文案：身份图 / 服装图名称 + 文字前 12 字。 */
function personBLabelOf(group: RecipeBatchGroup): string {
  const variant = group.personBVariant
  if (!variant) return ''
  const parts: string[] = []
  if (variant.identity.source !== 'empty' && variant.identity.name) {
    parts.push(`身份「${slotTextPreview(variant.identity.name)}」`)
  }
  if (variant.costume.source !== 'empty' && variant.costume.name) {
    parts.push(`服装「${slotTextPreview(variant.costume.name)}」`)
  }
  const compiled = compilePersonBVariant(variant)
  const text = [compiled.portraitText, compiled.costumeText, compiled.freeText]
    .filter(Boolean)
    .join('；')
  if (text) parts.push(`文字「${slotTextPreview(text)}」`)
  return parts.length ? `B：${parts.join(' · ')}` : 'B（空设定）'
}

/** 泛型去重计数（保持简单：只关心「有几个不同值」）。 */
function countDistinct<T>(items: readonly T[], keyOf: (item: T) => string): number {
  const seen = new Set<string>()
  for (const item of items) seen.add(keyOf(item))
  return seen.size
}

/** 槽位缩略图地址（text 模式不显示图片，调用方按 mode 忽略）。 */
function thumbUrlOf(group: RecipeBatchGroup, slot: RecipeSlotKey): string | null {
  if (slot === 'portrait') return portraitSlotThumb(group.slots.portrait)
  if (slot === 'costume') return costumeSlotThumb(group.slots.costume)
  return poseSlotThumb(group.slots.pose, props.poseUseDepth)
}

/** 三槽缩略图；text 槽带 chip 数据，empty 槽由模板渲染灰底「空」。 */
function buildThumbs(group: RecipeBatchGroup): MatrixThumb[] {
  return displaysOf(group).map((display) => {
    const label = display.textLabel
      ? `${display.textLabel}｜${display.textPreview || '未填写'}`
      : display.supplementLabel
        ? `${display.label}｜${display.supplementLabel}：${display.supplementPreview || '未填写'}`
        : display.label || EMPTY_THUMB_LABELS[display.slot]
    return {
      key: display.slot,
      name: label,
      url: display.mode === 'image' ? thumbUrlOf(group, display.slot) : null,
      mode: display.mode,
      textLabel: display.textLabel,
      textPreview: display.textPreview,
      supplementLabel: display.supplementLabel,
      supplementPreview: display.supplementPreview,
    }
  })
}

/** 组头文案：text 槽用碎片前 12 字代替槽名（方案 §8 P2）；有 B 变体时追加 B 摘要。 */
function titleOf(group: RecipeBatchGroup): string {
  const base = slotDisplaysGroupLabel(displaysOf(group))
  const bLabel = personBLabelOf(group)
  return bLabel ? `${base} · ${bLabel}` : base
}

/**
 * 按槽位三元组 + 文本内容分组（Map 保持首次出现顺序 → 组顺序与 `groups` 一致；
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
      thumbs: buildThumbs(first),
      title: titleOf(first),
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

    <!-- P0-5：人物B身份图 / B 服装是整批共享输入，单独列一行 -->
    <p v-if="personBInfo" class="matrix__personb" data-testid="studio-matrix-personb">
      {{ personBInfo }}
    </p>

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
          :class="{ 'is-expanded': isExpanded(group.key) }"
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
                  :class="{
                    'is-empty': !thumb.url && thumb.mode !== 'text',
                    'matrix__thumb--text': thumb.mode === 'text',
                  }"
                  :title="thumb.name"
                  :data-testid="`studio-matrix-thumb-${thumb.key}`"
                >
                  <!-- text 槽：显示「文本 · 类型」+ 前 12 字，不显示空图占位 -->
                  <template v-if="thumb.mode === 'text'">
                    <span class="matrix__text-label">{{ thumb.textLabel }}</span>
                    <span class="matrix__text-preview">{{ thumb.textPreview || '未填写' }}</span>
                  </template>
                  <img
                    v-else-if="thumb.url"
                    :src="thumb.url"
                    :alt="thumb.name"
                    class="matrix__thumb-img"
                    loading="lazy"
                  />
                  <span v-else class="matrix__thumb-empty">空</span>
                  <span
                    v-if="thumb.mode === 'image' && thumb.supplementLabel"
                    class="matrix__supplement"
                    :title="`${thumb.supplementLabel}：${thumb.supplementPreview || '未填写'}`"
                  >
                    补充
                  </span>
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
              :class="{ 'matrix__row--has-b': row.personBVariant }"
              data-testid="studio-matrix-row"
            >
              <span class="matrix__index">#{{ row.index + 1 }}</span>
              <span class="matrix__thumbs">
                <span
                  v-for="thumb in group.thumbs"
                  :key="thumb.key"
                  class="matrix__thumb"
                  :class="{
                    'is-empty': !thumb.url && thumb.mode !== 'text',
                    'matrix__thumb--text': thumb.mode === 'text',
                  }"
                  :title="thumb.name"
                  :data-testid="`studio-matrix-thumb-${thumb.key}`"
                >
                  <!-- text 槽：显示「文本 · 类型」+ 前 12 字，不显示空图占位 -->
                  <template v-if="thumb.mode === 'text'">
                    <span class="matrix__text-label">{{ thumb.textLabel }}</span>
                    <span class="matrix__text-preview">{{ thumb.textPreview || '未填写' }}</span>
                  </template>
                  <img
                    v-else-if="thumb.url"
                    :src="thumb.url"
                    :alt="thumb.name"
                    class="matrix__thumb-img"
                    loading="lazy"
                  />
                  <span v-else class="matrix__thumb-empty">空</span>
                  <span
                    v-if="thumb.mode === 'image' && thumb.supplementLabel"
                    class="matrix__supplement"
                    :title="`${thumb.supplementLabel}：${thumb.supplementPreview || '未填写'}`"
                  >
                    补充
                  </span>
                </span>
              </span>
              <span class="matrix__workflow" :title="workflowNameOf(row.workflow)">
                {{ workflowNameOf(row.workflow) }}
              </span>
              <!-- P0-5：逐行 B 变体可见（不同变体会落不同组，行内仍需能核对） -->
              <span
                v-if="row.personBVariant"
                class="matrix__personb-row"
                :title="personBLabelOf(row)"
                data-testid="studio-matrix-row-personb"
              >
                {{ personBLabelOf(row) }}
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
  /* 行内三联缩略图放大到 30 × 40：清单是逐组核对用的，24 × 32 看不清 */
  --matrix-thumb-w: 30px;
  --matrix-thumb-h: 40px;
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

/* P0-5：整批共享的人物B身份图 / B 服装摘要 */
.matrix__personb {
  margin: 0;
  color: var(--text-body-soft);
  font-size: var(--fs-sm);
  line-height: var(--lh-sm);
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

/* 空态只做一行提示，不再用 120px 的大虚线框占位 */
.matrix__empty {
  margin: 0;
  padding: 10px var(--gap);
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

/*
 * 组卡片两列并排（≥760px）：清单在 8/12 栏时约 900px，单列会让每组一行只占
 * 左侧一小截、右侧大片空白。展开的组跨全宽，避免把右边的组顶出空洞。
 */
.matrix__groups {
  display: grid;
  /* min(340px, 100%)：容器窄于 340 时按容器宽度收，避免 340 撑破 390 屏 */
  grid-template-columns: repeat(auto-fill, minmax(min(340px, 100%), 1fr));
  gap: var(--gap-xs);
  align-items: start;
}

.matrix__group.is-expanded {
  grid-column: 1 / -1;
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
  position: relative;
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

/* P4：image 槽带跨源补充文本时，右下角标「补充」 */
.matrix__supplement {
  position: absolute;
  right: 1px;
  bottom: 1px;
  padding: 0 2px;
  border-radius: var(--radius-pill);
  background: var(--surface-raised);
  color: var(--accent-green-text);
  font-size: 9px;
  line-height: 1.4;
  pointer-events: none;
}

.matrix__thumb.is-empty {
  background: var(--surface-card);
  color: var(--text-muted);
}

/*
 * 文本槽 chip：宽度随内容（上限 150px），高度与三联缩略图对齐。
 * 两行都保证 12px（--fs-sm），不用 9/10px 小字。
 */
.matrix__thumb--text {
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 1px;
  box-sizing: border-box;
  width: auto;
  max-width: 150px;
  height: auto;
  min-height: var(--matrix-thumb-h, 32px);
  padding: 2px 6px;
  border: 1px solid var(--border-soft);
  background: var(--surface-inset);
  color: var(--text-body);
}

.matrix__text-label {
  max-width: 100%;
  overflow: hidden;
  color: var(--accent-link);
  font-size: var(--fs-sm);
  font-weight: 600;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.matrix__text-preview {
  max-width: 100%;
  overflow: hidden;
  color: var(--text-body);
  font-size: var(--fs-sm);
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
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

/*
 * 行内固定列对齐（#序号 / 三联图 / 工作流 / 尺寸 / 种子）。
 * 旧写法是 flex + 工作流 `flex:1 1 auto`，名字一短就把空白全吃在中间，
 * 视觉上像“右半边没用上”；改成网格后各列位置固定，便于逐行对比。
 * 窄容器（<760）回落 flex 换行，避免列宽挤压。
 */
.matrix__row {
  display: grid;
  grid-template-columns: 40px auto minmax(0, 1fr) 96px 104px;
  align-items: center;
  gap: var(--gap-sm);
  min-height: var(--matrix-row-h, 48px);
  padding: var(--gap-xs) var(--gap-sm);
  border-top: 1px solid var(--border-faint);
}

/* P0-5：带 B 变体的行多一列，避免长文本把工作流名挤成省略号 */
.matrix__row--has-b {
  grid-template-columns: 40px auto minmax(0, 1fr) minmax(0, 132px) 96px 104px;
}

.matrix__personb-row {
  min-width: 0;
  overflow: hidden;
  color: var(--text-body-soft);
  font-size: var(--fs-sm);
  line-height: var(--lh-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.matrix__row:hover {
  background: var(--fill-faint);
}

@media (max-width: 760px) {
  .matrix__row {
    display: flex;
    flex-wrap: wrap;
  }
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