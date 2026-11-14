<script setup lang="ts">
/**
 * 合成台工作流下拉（`/api/workflows?scope=studio`），**受控多选**。
 *
 * 契约 C-REF-WF-SLOTS@1：下拉项按「当前已选槽位」判定适用性，
 * 缺少对应业务角色（`slots`）的项显示原因并禁止勾选；空槽位不参与判定。
 *
 * `slots` 三态（收紧点 1）：`undefined` = 旧后端字段缺失，不判定；
 * `[]` = 角色不可识别（可能是 UI 格式工作流），对所有非空槽位都禁用并提示；
 * 非空 = 按角色匹配。
 *
 * 为什么不用主站 `WorkflowPicker.vue`：共享组件只接受 `WorkflowRow[]` 且是单选，
 * 也不支持 `scope=studio` 的目录过滤；白名单不允许改共享组件，因此这里重做，
 * 交互约定保持一致（点击触发器展开、点击外部 / Esc 关闭）。
 *
 * §5 尺寸基线：触发器 336.33 × 36px、圆角 8px、字号 12px；
 * 下拉行 435.13 × 28px、圆角 6px、字号 12px、内边距 6px 32px 6px 8px。
 */

import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import type {
  StudioWorkflowOption,
  StudioWorkflowSlot,
} from '../../../../composables/useReferenceRecipe'
import {
  describeWorkflowUnavailableFor,
  workflowDisplayName,
} from '../../../../composables/useReferenceRecipe'

const props = withDefaults(
  defineProps<{
    /** 多选值：有序、去重；空数组 = 使用后端默认工作流。 */
    modelValue: string[]
    /** 只读即可：本组件只遍历目录，不会就地修改（放宽后兼容 readonly 调用方）。 */
    workflows: readonly StudioWorkflowOption[]
    /** 当前已选**非空**槽位的业务角色；空槽不传。 */
    selectedRoles?: readonly StudioWorkflowSlot[]
    /** 后端默认工作流路径（空选择时 UI 明示）。 */
    defaultPath?: string
    loading?: boolean
    disabled?: boolean
    /**
     * 外观形态：
     * - `select`（默认）：原有下拉触发器，渲染与行为对旧调用方完全不变；
     * - `chips`：触发器固定「＋ 添加工作流」，已选项以 chips 平铺在触发器下方。
     */
    variant?: 'select' | 'chips'
  }>(),
  {
    selectedRoles: () => [],
    defaultPath: '',
    loading: false,
    disabled: false,
    variant: 'select',
  },
)

const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const listEl = ref<HTMLElement | null>(null)

const selectedSet = computed(() => new Set(props.modelValue))

/** 已选工作流对应的目录项（保序、过滤目录中已消失的路径）。 */
const selectedItems = computed(() =>
  props.modelValue
    .map((path) => props.workflows.find((item) => item.path === path))
    .filter((item): item is StudioWorkflowOption => Boolean(item)),
)

/** 后端默认项：路径恰好等于 defaultPath。 */
const defaultItem = computed(
  () => props.workflows.find((item) => item.path === props.defaultPath) ?? null,
)

/** 是否 chips 形态：默认 `select` 时下面所有 chips 相关分支都不渲染。 */
const isChips = computed(() => props.variant === 'chips')

/**
 * chips 显示名：**不再按字数截断**。
 *
 * 2026-11-06 改为「一行一条」的纵向列表后，每行都有整行宽度可用，
 * 截断交给 CSS `text-overflow: ellipsis` 处理（窄卡时自动省略），
 * 不再因为固定 20 字而在宽卡上提前丢失信息。
 */
function chipName(item: StudioWorkflowOption): string {
  return workflowDisplayName(item.name)
}

/** chips 图数徽章：优先后端 `input_count`，旧响应回退 `image_slots`。 */
function chipInputCount(item: StudioWorkflowOption): string {
  return `${item.inputCount || item.imageSlots} 图`
}

/**
 * 移除已选工作流（chips 上的 `×`）。
 *
 * 只过滤该 path，顺序保持不变；过滤后为空数组即回落后端默认工作流。
 */
function removeChip(path: string): void {
  if (props.disabled || props.loading) return
  emit(
    'update:modelValue',
    props.modelValue.filter((value) => value !== path),
  )
}

/** 触发器文案：空选择明示「使用默认工作流」，而不是留空白。 */
const triggerLabel = computed(() => {
  if (props.loading) return '正在读取本机工作流…'
  if (selectedItems.value.length === 0) {
    if (defaultItem.value) {
      return `使用默认工作流：${workflowDisplayName(defaultItem.value.name)}`
    }
    return '选择本机工作流'
  }
  if (selectedItems.value.length === 1) {
    const item = selectedItems.value[0]
    return `${workflowDisplayName(item.name)}${inputLabel(item)}`
  }
  const first = selectedItems.value[0]
  return `已选 ${selectedItems.value.length} 个工作流（首个：${workflowDisplayName(first.name)}）`
})

const triggerTitle = computed(() => {
  if (props.modelValue.length) return props.modelValue.join('\n')
  return defaultItem.value?.path ?? '选择工作流'
})

/** 输入数文案：优先后端 `input_count`，旧响应回退 `image_slots`。 */
function inputLabel(item: StudioWorkflowOption): string {
  const count = item.inputCount || item.imageSlots
  return count ? `（${count} 输入）` : ''
}

/** 行内展示：来源前缀（库根本身不加）+ 名称 + 输入数。 */
function optionLabel(item: StudioWorkflowOption): string {
  const name = workflowDisplayName(item.name)
  const prefix =
    item.source && item.source !== '库根' && !name.startsWith(item.source) ? `${item.source} · ` : ''
  return `${prefix}${name}${inputLabel(item)}`
}

function isSelected(path: string): boolean {
  return selectedSet.value.has(path)
}

/**
 * 不可用原因：缺少当前已选槽位对应的输入、或 slots 为空导致角色不可识别时，
 * 返回中文原因；否则空串。
 *
 * 三态口径（收紧点）：`slots === undefined`（旧后端字段缺失）不判定；
 * `slots === []`（UI 格式工作流 / 解析失败）一律视为不可识别并禁用。
 */
function reasonFor(item: StudioWorkflowOption): string {
  return describeWorkflowUnavailableFor(item, props.selectedRoles)
}

function toggle(): void {
  if (props.disabled || props.loading) return
  open.value = !open.value
  if (open.value) {
    void nextTick(() => {
      listEl.value?.querySelector<HTMLElement>('.wf-option.is-active')?.scrollIntoView({
        block: 'nearest',
      })
    })
  }
}

/** 勾选 / 取消：不可用项直接忽略（禁止选中）。 */
function toggleOption(item: StudioWorkflowOption): void {
  if (props.disabled || props.loading) return
  if (reasonFor(item)) return

  const next = isSelected(item.path)
    ? props.modelValue.filter((path) => path !== item.path)
    : [...props.modelValue, item.path]
  emit('update:modelValue', next)
}

function onDocMouseDown(event: MouseEvent): void {
  if (open.value && root.value && !root.value.contains(event.target as Node)) {
    open.value = false
  }
}

function onKey(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    open.value = false
    root.value?.querySelector<HTMLElement>('.wf-trigger')?.focus()
  }
}

watch(open, (value) => {
  if (value) {
    document.addEventListener('mousedown', onDocMouseDown)
    document.addEventListener('keydown', onKey)
  } else {
    document.removeEventListener('mousedown', onDocMouseDown)
    document.removeEventListener('keydown', onKey)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocMouseDown)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div
    ref="root"
    class="wf-select"
    :class="{ 'wf-select--chips': isChips }"
    data-testid="studio-workflow-select"
  >
    <button
      type="button"
      class="wf-trigger"
      :disabled="loading || disabled"
      :aria-expanded="open"
      aria-haspopup="listbox"
      :title="triggerTitle"
      data-testid="studio-workflow-trigger"
      @click="toggle"
    >
      <span class="wf-trigger__label">{{ isChips ? '＋ 添加工作流' : triggerLabel }}</span>
      <span
        v-if="!isChips && selectedItems.length === 1 && selectedItems[0].recommended"
        class="wf-badge"
        data-testid="studio-workflow-recommended"
      >推荐</span>
      <span class="wf-trigger__caret" aria-hidden="true">▾</span>
    </button>

    <!-- chips 形态：已选项平铺在触发器下方；下拉只承担「添加」 -->
    <div v-if="isChips" class="wf-chips" data-testid="studio-workflow-chips">
      <span
        v-if="!modelValue.length && defaultItem"
        class="wf-chip wf-chip--default"
        data-testid="studio-workflow-chip-default"
        title="未勾选时按 1 条默认工作流计入组合"
      >默认 · {{ chipName(defaultItem) }}</span>

      <span
        v-for="item in selectedItems"
        :key="item.path"
        class="wf-chip"
        :class="{ 'is-unavailable': Boolean(reasonFor(item)) }"
        :title="reasonFor(item) || item.path"
        :data-path="item.path"
        data-testid="studio-workflow-chip"
      >
        <span class="wf-chip__name">{{ chipName(item) }}</span>
        <span class="wf-chip__count">{{ chipInputCount(item) }}</span>
        <button
          type="button"
          class="wf-chip__remove"
          :aria-label="`移除工作流 ${chipName(item)}`"
          data-testid="studio-workflow-chip-remove"
          @click="removeChip(item.path)"
        >×</button>
      </span>
    </div>

    <div v-if="open" class="wf-menu">
      <!-- 未选时明示默认工作流；已选时明示多选数量 -->
      <p
        v-if="!modelValue.length && defaultItem"
        class="wf-default"
        data-testid="studio-workflow-default-hint"
      >
        当前使用默认工作流：{{ workflowDisplayName(defaultItem.name) }}
      </p>
      <p v-else-if="modelValue.length" class="wf-default" data-testid="studio-workflow-selected-hint">
        已选 {{ modelValue.length }} 个工作流；每组任务按所选工作流分别提交。
      </p>

      <div
        ref="listEl"
        class="wf-list"
        role="listbox"
        aria-label="本机工作流列表"
        aria-multiselectable="true"
      >
        <button
          v-for="item in workflows"
          :key="item.path"
          type="button"
          class="wf-option"
          :class="{
            'is-active': isSelected(item.path),
            'is-unavailable': Boolean(reasonFor(item)),
          }"
          role="option"
          :aria-selected="isSelected(item.path) || undefined"
          :aria-disabled="Boolean(reasonFor(item)) || undefined"
          :title="item.path"
          data-testid="studio-workflow-option"
          @click="toggleOption(item)"
        >
          <span class="wf-check" aria-hidden="true">{{ isSelected(item.path) ? '✓' : '' }}</span>
          <span class="wf-option__body">
            <span class="wf-option__text">{{ optionLabel(item) }}</span>
            <span
              v-if="reasonFor(item)"
              class="wf-option__reason"
              data-testid="studio-workflow-unavailable"
            >{{ reasonFor(item) }}</span>
          </span>
          <span v-if="item.recommended" class="wf-badge">推荐</span>
        </button>

        <p v-if="!loading && workflows.length === 0" class="wf-empty">
          本机库目录中没有可用工作流，请先放入出图工作流 JSON。
        </p>
        <p v-if="loading" class="wf-empty">正在读取本机工作流列表…</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wf-select {
  position: relative;
  width: 100%;
  max-width: 336.33px;
  min-width: 0;
}

/* chips 形态需要平铺多行，放开 336.33 上限（默认 select 形态不受影响） */
.wf-select--chips {
  max-width: none;
}

/*
 * 已选区：**一行一条**（2026-11-06 用户要求）。
 *
 * 旧的 flex-wrap 药丸在 300~400px 的窄栏里会挤成「左一行 1 条、右一行 2 条」，
 * 名字还被截成 20 字。改成纵向列表后每条占满整行，名字、图数、× 三者对齐。
 * 选很多时最高 264px 内部滚动，避免把参数卡无限拉长。
 */
.wf-chips {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  max-height: 264px;
  overflow-y: auto;
  scrollbar-width: thin;
  margin-top: 8px;
}

.wf-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  box-sizing: border-box;
  width: 100%;
  min-height: 30px;
  padding: 4px 4px 4px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-card);
  color: var(--text-strong);
  font-size: 12px;
  line-height: 1.4;
}

/* 名字吃掉整行剩余宽度，超出才省略（不再固定 20 字截断） */
.wf-chip__name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 「N 图」徽章：11px 元信息，不抢主名 */
.wf-chip__count {
  flex: none;
  padding: 0 5px;
  border-radius: var(--radius-pill);
  background: var(--fill-soft);
  color: var(--text-body-soft);
  font-size: 11px;
  line-height: 16px;
  white-space: nowrap;
}

.wf-chip__remove {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--text-muted);
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
}

.wf-chip__remove:hover {
  background: var(--fill-medium);
  color: var(--text-strong);
}

.wf-chip__remove:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}

/* 不可用项：红色边框 / 文字 + title 原因（不整体降透明度） */
.wf-chip.is-unavailable {
  border-color: var(--danger);
  color: var(--danger-text-soft);
}

.wf-chip.is-unavailable .wf-chip__count,
.wf-chip.is-unavailable .wf-chip__remove {
  color: var(--danger-text-soft);
}

/* 未选时的隐式默认项：虚线 + 「默认」前缀，明确它会计入组合 */
.wf-chip--default {
  padding-right: 10px;
  border-style: dashed;
  border-color: var(--border-strong);
  background: transparent;
  color: var(--text-muted);
}

/* 触发器 336.33 × 36、圆角 8、字号 12 */
.wf-trigger {
  display: flex;
  align-items: center;
  gap: 6px;
  box-sizing: border-box;
  width: 100%;
  height: 36px;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-deep);
  color: var(--text-strong);
  font-size: 12px;
  line-height: 1;
  text-align: left;
  cursor: pointer;
}

.wf-trigger:hover:not(:disabled) {
  border-color: var(--primary);
}

.wf-trigger:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.wf-trigger:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}

.wf-trigger__label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wf-trigger__caret {
  flex: none;
  color: var(--text-muted);
  font-size: 11px;
}

/* 「推荐」徽章 26 × 13、圆角 4、9px / 500、内边距 2px 4px */
.wf-badge {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  width: 26px;
  height: 13px;
  padding: 2px 4px;
  border-radius: 4px;
  background: var(--accent-green-soft);
  color: var(--accent-green);
  font-size: var(--fs-xs);
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
}

/*
 * 下拉面板：行宽 435.13（§5）。
 * 边框用 box-shadow 画而不是 border：border 会占 1px 宽度，把行宽压到 433。
 */
.wf-menu {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  z-index: 80;
  box-sizing: border-box;
  width: min(435.13px, calc(100vw - 64px));
  max-height: 360px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-radius: 10px;
  background: var(--surface-raised);
  box-shadow:
    0 0 0 1px var(--border-strong, var(--border)),
    var(--shadow-3);
}

/* 默认 / 多选说明：常驻在列表顶部，进下拉第一眼就能看到 */
.wf-default {
  margin: 0;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  color: var(--text-body-soft);
  font-size: 11px;
  line-height: 1.5;
}

.wf-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 0;
  overflow-y: auto;
}

/* 行 435.13 × 28、圆角 6、12px、内边距 6px 32px 6px 8px */
.wf-option {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  box-sizing: border-box;
  width: 100%;
  min-height: 28px;
  padding: 6px 32px 6px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-strong);
  font-size: 12px;
  line-height: 1.3;
  text-align: left;
  white-space: normal;
  word-break: break-all;
  cursor: pointer;
}

.wf-option:hover {
  background: var(--fill-subtle);
}

.wf-option.is-active {
  background: var(--primary-soft, rgba(91, 91, 214, 0.16));
  color: var(--text-strong);
}

/* 不适用项：名称保持可读，不整体降透明度（灰底灰字难辨认） */
.wf-option.is-unavailable {
  cursor: not-allowed;
}

.wf-option.is-unavailable:hover {
  background: transparent;
}

.wf-option.is-unavailable .wf-option__text {
  color: var(--text-muted);
}

.wf-option:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: -1px;
}

/* 多选勾选框：固定 14px，避免行高跳动 */
.wf-check {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  width: 14px;
  height: 14px;
  margin-top: 1px;
  border: 1px solid var(--border);
  border-radius: 3px;
  color: var(--on-inverse);
  font-size: var(--fs-xs);
  line-height: 1;
}

.wf-option.is-active .wf-check {
  border-color: transparent;
  background: var(--primary);
}

.wf-option__body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.wf-option__text {
  min-width: 0;
}

/* 不适用原因：红色可读，不靠浅灰 */
.wf-option__reason {
  color: var(--danger-text-soft);
  font-size: var(--fs-xs);
  line-height: 1.5;
  word-break: break-word;
}

.wf-empty {
  margin: 0;
  padding: 10px 8px;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.6;
}
</style>