<script setup lang="ts">
/**
 * 合成台「批次结果区」（方案 §5 M5）。
 *
 * 纯展示组件：批次列表、进度、逐组结果全部来自父级（`useReferenceRecipe` 的
 * `batches`），本组件只负责三件事：
 * 1. 最新批次在最上方，批号仍按创建顺序（最早 = 批次 1）；
 * 2. 按 `batch.groupResults` 渲染网格，每张图带 `#组号 · 工作流短名 · 尺寸`；
 * 3. 失败组用灰块展示原因，运行中批次禁止折叠。
 *
 * 组件不请求后端、不持有批次数据；折叠状态是唯一的内部 UI 状态。
 * 灯箱翻页由父级负责（本组件只 emit `preview(urls, index)`）。
 */

import { computed, ref } from 'vue'

import type {
  RecipeBatch,
  RecipeBatchGroup,
  RecipeGroupResult,
  StudioWorkflowOption,
} from '../../../../composables/useReferenceRecipe'
import {
  compilePersonBVariant,
  slotTextPreview,
} from '../../../../composables/recipeTextFragments'
import {
  describeRecipeBatchStatus,
  isRecipeBatchRunning,
  recipeBatchPercent,
  workflowDisplayName,
} from '../../../../composables/useReferenceRecipe'

const props = defineProps<{
  /** 已按显示顺序排列：最新批次在前。 */
  batches: readonly RecipeBatch[]
  /**
   * 姿势槽当前是否使用深度图。
   *
   * 结果区不需要按深度/原图切换渲染，但父级会把该口径带下来；这里透出为根节点的
   * `data-pose-depth`，便于父级与样式/调试工具确认本批结果的输入口径。
   */
  poseUseDepth: boolean
  /** 工作流目录：把 `group.workflow` 路径映射成短名。 */
  workflows: readonly StudioWorkflowOption[]
}>()

const emit = defineEmits<{
  preview: [urls: string[], index: number]
  reuse: [batch: RecipeBatch]
  clearFinished: []
  jobCenter: []
}>()

/** 灰块内错误原因的最大展示长度；全量文本放在 `title`。 */
const ERROR_TEXT_LIMIT = 120

/** 已折叠的批次 id；默认全部展开，运行中的批次永远不折叠。 */
const collapsedBatchIds = ref<string[]>([])

/** 展示序号 → 批次号：最早的批次为 1，最新批次为 `batches.length`。 */
function batchNumberOf(displayIndex: number): number {
  return props.batches.length - displayIndex
}

/** 批次时间 HH:MM:SS；异常时间给占位，避免渲染 `NaN:NaN:NaN`。 */
function formatBatchTime(createdAt: number): string {
  const date = new Date(createdAt)
  if (Number.isNaN(date.getTime())) return '--:--:--'
  const pad = (value: number): string => String(value).padStart(2, '0')
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

function isBatchCollapsed(batch: RecipeBatch): boolean {
  return collapsedBatchIds.value.includes(batch.id)
}

/**
 * 折叠 / 展开批次。
 *
 * 运行中批次直接忽略：隐藏进度会让用户误以为任务已经结束（按钮同时 disabled）。
 */
function toggleBatchCollapse(batch: RecipeBatch): void {
  if (isRecipeBatchRunning(batch)) return
  collapsedBatchIds.value = isBatchCollapsed(batch)
    ? collapsedBatchIds.value.filter((id) => id !== batch.id)
    : [...collapsedBatchIds.value, batch.id]
}

/**
 * 组号 = 组在提交前完整清单里的位置（1 起）。
 *
 * `groupResults` 由 `runBatch` 按 `batch.groups` 顺序建槽，正常情况下引用相同；
 * 极端情况下（数据被克隆）引用对不上时回退到 `group.index`，避免显示 `#0`。
 */
function groupNumberOf(batch: RecipeBatch, entry: RecipeGroupResult): number {
  const position = batch.groups.indexOf(entry.group)
  return position >= 0 ? position + 1 : entry.group.index + 1
}

/** 失败组口径：有错误原因，或没有任何结果图。 */
function isFailedEntry(entry: RecipeGroupResult): boolean {
  const reason = entry.error ?? ''
  const urls = entry.urls ?? []
  return reason.trim().length > 0 || urls.length === 0
}

/** 工作流短名：空路径 = 后端默认工作流；目录里查不到时回退文件名。 */
function workflowNameOf(group: RecipeBatchGroup): string {
  if (!group.workflow) return '默认工作流'
  const option = props.workflows.find((item) => item.path === group.workflow)
  if (option) return workflowDisplayName(option.name)
  const filename = group.workflow.split(/[\\/]/).pop() ?? group.workflow
  return workflowDisplayName(filename)
}

/**
 * P0-5：结果字幕补人物 B 变体（与生成清单同口径）。
 *
 * 2026-11-08 起 B 身份图 / B 服装按变体绑定并写入每个批次组，因此结果区直接读
 * 本组自己的图名，不用「当前选择」误标历史批次。
 */
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

/** 尺寸文案：画质与比例都有 → `quality · ratio`；都空表示跟随参考图。 */
function sizeTextOf(group: RecipeBatchGroup): string {
  const quality = (group.quality ?? '').trim()
  const ratio = (group.aspectRatio ?? '').trim()
  if (quality && ratio) return `${quality} · ${ratio}`
  if (quality) return quality
  if (ratio) return ratio
  return '跟随参考图'
}

function truncateText(text: string, limit: number): string {
  return text.length > limit ? `${text.slice(0, limit)}…` : text
}

/**
 * 灰块正文。
 *
 * - 有 `error`：截断 120 字展示（全量在 `title`）；
 * - 无 `error` 但 `urls` 为空：运行中说明「出图中…」，已结束说明「未返回图片」，
 *   避免出现只有底色、没有任何文字的空灰块。
 */
function errorTextOf(batch: RecipeBatch, entry: RecipeGroupResult): string {
  const reason = (entry.error ?? '').trim()
  if (reason) return truncateText(reason, ERROR_TEXT_LIMIT)
  return isRecipeBatchRunning(batch) ? '出图中…' : '该组未返回图片'
}

/** `title` 放全量错误原因；没有原因时与可见文案一致。 */
function errorTitleOf(batch: RecipeBatch, entry: RecipeGroupResult): string {
  const reason = (entry.error ?? '').trim()
  return reason || errorTextOf(batch, entry)
}

/** 进度百分比（复用 composable 口径；`null` 表示暂不可计算）。 */
function batchProgressOf(batch: RecipeBatch): number | null {
  return recipeBatchPercent(batch)
}

/**
 * 最新批（展示顺序第一项）中第一张成功结果的位置。
 *
 * 只给这一张 `data-testid="studio-result-image"`，避免同页多图出现重复选择器；
 * 失败组（`urls` 为空）会被跳过，仍指向真正的第一张结果图。
 */
const latestFirstResultPosition = computed<{ entryIndex: number; urlIndex: number } | null>(() => {
  const latest = props.batches[0]
  if (!latest) return null
  const entries = latest.groupResults ?? []
  for (let entryIndex = 0; entryIndex < entries.length; entryIndex += 1) {
    const entry = entries[entryIndex]
    if (entry && (entry.urls?.length ?? 0) > 0) return { entryIndex, urlIndex: 0 }
  }
  return null
})

function resultImageTestId(
  batch: RecipeBatch,
  entryIndex: number,
  urlIndex: number,
): string | undefined {
  const latest = props.batches[0]
  if (!latest || latest.id !== batch.id) return undefined
  const first = latestFirstResultPosition.value
  if (!first) return undefined
  return first.entryIndex === entryIndex && first.urlIndex === urlIndex
    ? 'studio-result-image'
    : undefined
}

/** 点击某组第 `index` 张图：把该组 url 列表交给父级灯箱翻页。 */
function openPreview(entry: RecipeGroupResult, index: number): void {
  emit('preview', [...(entry.urls ?? [])], index)
}
</script>

<template>
  <section
    class="result-board"
    :data-pose-depth="poseUseDepth ? 'depth' : 'rgb'"
    aria-label="批次结果"
  >
    <!-- 空态：180px 轻量块（方案 §5 M5），不再占 460px 高度 -->
    <div v-if="!batches.length" class="result-board__empty" data-testid="studio-preview">
      提交后会在这里按批次展示；GPU 串行执行，新批次可继续提交
    </div>

    <template v-else>
      <!-- 列表顶部工具栏：批数 + 清理 + 任务中心 -->
      <div class="result-board__toolbar">
        <span class="result-board__count">共 {{ batches.length }} 批</span>
        <button
          type="button"
          class="result-board__action"
          data-testid="studio-batch-clear"
          @click="emit('clearFinished')"
        >
          清理已结束
        </button>
        <button
          type="button"
          class="result-board__action"
          data-testid="studio-job-center"
          @click="emit('jobCenter')"
        >
          任务中心
        </button>
      </div>

      <div class="result-board__list" data-testid="studio-batch-list">
        <article
          v-for="(batch, displayIndex) in batches"
          :key="batch.id"
          class="result-board__batch"
          :data-testid="`studio-batch-${batchNumberOf(displayIndex)}`"
          :aria-label="`批次 ${batchNumberOf(displayIndex)}`"
        >
          <header class="result-board__head">
            <button
              type="button"
              class="result-board__toggle"
              :disabled="isRecipeBatchRunning(batch)"
              :aria-expanded="!isBatchCollapsed(batch)"
              @click="toggleBatchCollapse(batch)"
            >
              <span class="result-board__caret" aria-hidden="true">
                {{ isBatchCollapsed(batch) ? '▸' : '▾' }}
              </span>
              <span class="result-board__title">
                批次 {{ batchNumberOf(displayIndex) }} · {{ formatBatchTime(batch.createdAt) }} ·
                {{ batch.groups.length }} 组 / {{ batch.results.length }} 张
              </span>
            </button>
            <span
              class="result-board__status"
              :data-status="batch.status"
              :data-testid="`studio-batch-status-${batchNumberOf(displayIndex)}`"
            >
              {{ describeRecipeBatchStatus(batch) }}
            </span>
            <button
              type="button"
              class="result-board__action"
              data-testid="studio-batch-reuse"
              @click="emit('reuse', batch)"
            >
              复用参数
            </button>
          </header>

          <!-- 运行中批次：进度条 + 任务号（折叠按钮已 disabled） -->
          <div v-if="isRecipeBatchRunning(batch)" class="result-board__running">
            <div
              v-if="batchProgressOf(batch) !== null"
              class="result-board__progress"
              role="progressbar"
              aria-label="生成进度"
              aria-valuemin="0"
              aria-valuemax="100"
              :aria-valuenow="batchProgressOf(batch) ?? 0"
            >
              <span
                class="result-board__progress-fill"
                :style="{ width: `${batchProgressOf(batch) ?? 0}%` }"
              />
            </div>
            <span v-if="batchProgressOf(batch) !== null" class="result-board__percent">
              {{ batchProgressOf(batch) }}%
            </span>
            <p v-if="batch.jobIds.length" class="result-board__jobs">
              任务 {{ batch.jobIds.map((id) => `#${id}`).join('、') }}
            </p>
          </div>

          <!-- v-show：折叠只隐藏视觉，图片与 testid 仍保留在 DOM -->
          <div v-show="!isBatchCollapsed(batch)" class="result-board__body">
            <div class="result-board__grid" data-testid="studio-result-grid">
              <template
                v-for="(entry, entryIndex) in batch.groupResults"
                :key="`${batch.id}-${entryIndex}`"
              >
                <!-- 成功组：每个 url 一个 cell，容器 3/4 + contain（不裁图） -->
                <template v-if="!isFailedEntry(entry)">
                  <div
                    v-for="(url, urlIndex) in entry.urls"
                    :key="`${url}-${urlIndex}`"
                    class="result-board__cell"
                  >
                    <button
                      type="button"
                      class="result-board__thumb"
                      :aria-label="`查看批次 ${batchNumberOf(displayIndex)} 第 ${groupNumberOf(batch, entry)} 组第 ${urlIndex + 1} 张结果大图`"
                      @click="openPreview(entry, urlIndex)"
                    >
                      <img
                        :src="url"
                        :alt="`批次 ${batchNumberOf(displayIndex)} · #${groupNumberOf(batch, entry)} 结果图 ${urlIndex + 1}`"
                        class="result-board__image"
                        loading="lazy"
                        :data-testid="resultImageTestId(batch, entryIndex, urlIndex)"
                      />
                    </button>
                    <p class="result-board__caption" data-testid="studio-result-caption">
                      #{{ groupNumberOf(batch, entry) }} · {{ workflowNameOf(entry.group) }} ·
                      {{ sizeTextOf(entry.group) }}<template v-if="personBLabelOf(entry.group)">
                        · {{ personBLabelOf(entry.group) }}</template>
                    </p>
                  </div>
                </template>

                <!-- 失败 / 未出图组：灰块 + 原因（截断展示，title 放全量） -->
                <div
                  v-else
                  class="result-board__cell result-board__cell--error"
                  data-testid="studio-result-error"
                  :title="errorTitleOf(batch, entry)"
                >
                  <p class="result-board__error-label">
                    #{{ groupNumberOf(batch, entry) }} · {{ workflowNameOf(entry.group) }} ·
                    {{ sizeTextOf(entry.group) }}<template v-if="personBLabelOf(entry.group)">
                      · {{ personBLabelOf(entry.group) }}</template>
                  </p>
                  <p class="result-board__error-text">{{ errorTextOf(batch, entry) }}</p>
                </div>
              </template>
            </div>
          </div>
        </article>
      </div>
    </template>
  </section>
</template>

<style scoped>
/*
 * 颜色一律走 styles/tokens.css（本块十六进制色值 0 处）。
 * 结果卡最小列宽 / 空态高度走全局令牌，并带 180px 兜底。
 * 所有说明文字 ≥ 12px（--fs-sm），不使用 --fs-xs。
 */

.result-board {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  color: var(--text-body);
}

/* 空态：96px 单行块（180px 会在没有结果时白占一屏高度） */
.result-board__empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: var(--result-empty-min, 96px);
  padding: var(--gap);
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius);
  background: var(--surface-result);
  color: var(--text-body-soft);
  font-size: var(--fs-sm);
  line-height: var(--lh-md);
  text-align: center;
}

.result-board__toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-sm);
}

.result-board__count {
  margin-right: auto;
  color: var(--text-body-soft);
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
  line-height: var(--lh-lg);
}

.result-board__action {
  flex: none;
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

.result-board__action:hover {
  border-color: var(--primary);
  color: var(--text-strong);
}

.result-board__action:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}

.result-board__list {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}

.result-board__batch {
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-raised);
}

.result-board__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap);
  border-bottom: 1px solid var(--border-faint);
  background: var(--surface-panel);
}

.result-board__toggle {
  display: flex;
  flex: 1 1 240px;
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

.result-board__toggle:disabled {
  color: var(--text-body);
  cursor: default;
}

.result-board__toggle:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 2px;
}

.result-board__caret {
  flex: none;
  width: 10px;
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1;
}

.result-board__title {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  color: var(--text-strong);
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
  line-height: var(--lh-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 状态点只承载颜色语义，文字保持正文色以保证对比度 */
.result-board__status {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: var(--gap-xs);
  color: var(--text-body);
  font-size: var(--fs-sm);
  line-height: var(--lh-sm);
  white-space: nowrap;
}

.result-board__status::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-muted);
}

.result-board__status[data-status='submitting']::before,
.result-board__status[data-status='polling']::before {
  background: var(--primary);
}

.result-board__status[data-status='success']::before {
  background: var(--success);
}

.result-board__status[data-status='failed']::before {
  background: var(--danger);
}

.result-board__running {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap);
  border-bottom: 1px solid var(--border-faint);
}

.result-board__progress {
  flex: 1 1 120px;
  height: 6px;
  overflow: hidden;
  border-radius: var(--radius-pill);
  background: var(--fill-soft);
}

.result-board__progress-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--primary);
  transition: width var(--dur) var(--ease);
}

.result-board__percent {
  flex: none;
  color: var(--text-body-soft);
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
  line-height: var(--lh-sm);
}

.result-board__jobs {
  flex: none;
  margin: 0;
  color: var(--text-body-soft);
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
  line-height: var(--lh-sm);
}

.result-board__body {
  padding: var(--gap);
}

.result-board__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(var(--result-card-min, 180px), 1fr));
  gap: var(--gap-sm);
}

.result-board__cell {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  min-width: 0;
}

/* 结果容器固定 3/4，图片 contain，不裁图 */
.result-board__thumb {
  display: block;
  width: 100%;
  aspect-ratio: 3 / 4;
  padding: 0;
  overflow: hidden;
  border: 1px solid var(--border-faint);
  border-radius: var(--radius-sm);
  background: var(--surface-thumb);
  cursor: pointer;
  transition: border-color var(--dur-fast) var(--ease);
}

.result-board__thumb:hover {
  border-color: var(--primary);
}

.result-board__thumb:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}

.result-board__image {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.result-board__caption {
  margin: 0;
  color: var(--text-body-soft);
  font-size: var(--fs-sm);
  line-height: var(--lh-sm);
  overflow-wrap: anywhere;
}

/* 失败灰块：与成功 cell 同列宽，最小高度对齐空态令牌 */
.result-board__cell--error {
  justify-content: flex-start;
  min-height: var(--result-card-min, 180px);
  padding: var(--gap-sm);
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface-card);
}

.result-board__error-label {
  margin: 0;
  color: var(--text-body);
  font-size: var(--fs-sm);
  font-weight: 600;
  line-height: var(--lh-sm);
  overflow-wrap: anywhere;
}

.result-board__error-text {
  margin: 0;
  color: var(--text-body-soft);
  font-size: var(--fs-sm);
  line-height: var(--lh-sm);
  overflow-wrap: anywhere;
}
</style>