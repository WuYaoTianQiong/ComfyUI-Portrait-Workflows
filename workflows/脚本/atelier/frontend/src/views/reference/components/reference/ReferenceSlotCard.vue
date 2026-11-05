<script setup lang="ts">
/**
 * 合成台槽位卡（人像 / 服装 / 姿势，多选版）。
 *
 * 视觉按施工手册 §5「合成台」行：
 * - 空态 224.22 × 68px、已选态高度自适应（≥75px），内边距 10px、圆角 14px、底 `#0a0a0a`；
 * - 槽位缩略图 40 × 48px、圆角 10px；多选时展示**前 3 张**缩略图 + 溢出数量；
 * - 空槽位占位块 32 × 40px、圆角 10px、底 `#262626`。
 *
 * 宽度由父级三列栅格决定（736.66 内容区 - gap 16 → 224.22），不写死像素，
 * 这样 390px 单列时也不会横向溢出。
 *
 * 明确不出现槽位编号式按钮：只用「类型名 + 缩略图 / 占位块」表达槽位身份。
 */

import { computed } from 'vue'

import type { SlotSelectedItem } from './slotView'

/** 槽位内最多平铺展示的缩略图数量；其余用 `+N` 表示。 */
const MAX_PREVIEW_THUMBS = 3

const props = defineProps<{
  /** 类型名：人像 / 服装 / 姿势 */
  label: string
  /** 已选条目（顺序即加入顺序）；空数组表示空态 */
  items: readonly SlotSelectedItem[]
  /** 空态提示文案（如「+ 选人像」） */
  hint: string
  /** 姿势槽：是否显示白模 / 深度分段 */
  showDepthToggle?: boolean
  /** 姿势槽：当前是否深度图 */
  useDepth?: boolean
}>()

const emit = defineEmits<{
  /** 点击卡片主体：跳到对应库页签 */
  select: []
  /** 清除当前槽位全部条目 */
  clear: []
  /** 姿势槽切换白模 / 深度图 */
  depthChange: [useDepth: boolean]
}>()

const selected = computed(() => props.items.length > 0)
const selectedClass = computed(() => (selected.value ? 'is-selected' : 'is-empty'))
const previewThumbs = computed(() => props.items.slice(0, MAX_PREVIEW_THUMBS))
const overflowCount = computed(() => Math.max(0, props.items.length - MAX_PREVIEW_THUMBS))
const firstItem = computed(() => props.items[0] ?? null)

/** 已选文案：单张显示名称；多张显示「已选 N 张 · 首张名称」。 */
const nameText = computed(() => {
  if (!props.items.length) return ''
  if (props.items.length === 1) return firstItem.value?.name ?? ''
  const first = firstItem.value?.name ?? ''
  return first ? `已选 ${props.items.length} 张 · ${first}` : `已选 ${props.items.length} 张`
})

const testKey = computed(() =>
  props.label === '人像' ? 'portrait' : props.label === '服装' ? 'costume' : 'pose',
)

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    emit('select')
  }
}
</script>

<template>
  <div
    class="slot-card"
    :class="selectedClass"
    role="button"
    tabindex="0"
    :aria-label="
      selected
        ? `${label}槽已选 ${items.length} 张，点击前往${label}库继续多选`
        : `${label}槽未选择，点击前往${label}库`
    "
    :data-testid="`studio-slot-${testKey}`"
    @click="emit('select')"
    @keydown="onKeydown"
  >
    <!-- 多选缩略图：前 3 张 + 溢出数量 -->
    <span v-if="selected" class="slot-card__thumbs" aria-hidden="true">
      <template v-for="entry in previewThumbs" :key="entry.key">
        <img
          v-if="entry.thumb"
          :src="entry.thumb"
          :alt="entry.name"
          class="slot-card__thumb"
          loading="lazy"
        />
        <span v-else class="slot-card__thumb is-empty" />
      </template>
      <span v-if="overflowCount > 0" class="slot-card__more">+{{ overflowCount }}</span>
    </span>

    <!-- 空态占位块：32 × 40、圆角 10、底 #262626 -->
    <span v-else class="slot-card__placeholder" aria-hidden="true">
      <svg viewBox="0 0 16 16">
        <path d="M8 2.4v11.2M2.4 8h11.2" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
      </svg>
    </span>

    <span class="slot-card__body">
      <span class="slot-card__head">
        <span class="slot-card__head-left">
          <span class="slot-card__label">{{ label }}</span>
          <span v-if="selected" class="slot-card__count" :data-testid="`studio-slot-count-${testKey}`">
            {{ items.length }}
          </span>
          <span
            v-if="showDepthToggle && selected"
            class="depth-toggle"
            role="group"
            aria-label="切换素体白模或深度图"
            @click.stop
          >
            <button
              type="button"
              class="depth-toggle__btn"
              :class="{ 'is-active': !useDepth }"
              @click="emit('depthChange', false)"
            >
              白模
            </button>
            <button
              type="button"
              class="depth-toggle__btn"
              :class="{ 'is-active': useDepth }"
              @click="emit('depthChange', true)"
            >
              深度
            </button>
          </span>
        </span>

        <button
          v-if="selected"
          type="button"
          class="slot-card__clear"
          :aria-label="`清除${label}槽全部参考图`"
          @click.stop="emit('clear')"
        >
          <svg viewBox="0 0 12 12" aria-hidden="true">
            <path d="M3 3l6 6M9 3l-6 6" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
          </svg>
        </button>
      </span>

      <span v-if="selected" class="slot-card__name" :title="nameText">{{ nameText }}</span>
      <span v-else class="slot-card__hint">{{ hint }}</span>
    </span>
  </div>
</template>

<style scoped>
/* 空态 68px / 已选态 ≥75px（§5），宽度跟随三列栅格。 */
.slot-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  min-height: 68px;
  padding: 10px;
  border: 0;
  border-radius: 14px;
  background: var(--surface-deep);
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    background-color var(--dur-fast) var(--ease),
    min-height var(--dur-fast) var(--ease);
}

.slot-card.is-selected {
  min-height: 75px;
}

.slot-card:hover {
  background: var(--surface-inset-hover);
}

.slot-card:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

/* 多选缩略图条：最多 3 张，单张 24 × 30、圆角 6、gap 2 */
.slot-card__thumbs {
  display: flex;
  flex: none;
  flex-wrap: wrap;
  align-content: flex-start;
  gap: 2px;
  width: 40px;
}

/* 缩略图 24 × 30、圆角 6（多选时收窄，保证 3 张仍能塞进 40px 列） */
.slot-card__thumb {
  display: block;
  width: 19px;
  height: 28px;
  border-radius: 6px;
  background: var(--surface-thumb);
  object-fit: cover;
}

/* 无缩略图的条目：保留同尺寸占位，避免缩略图条抖动 */
.slot-card__thumb.is-empty {
  background: var(--surface-inset);
}

.slot-card__more {
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  width: 19px;
  height: 28px;
  border-radius: 6px;
  background: var(--surface-inset);
  color: var(--text-strong);
  font-size: 9px;
  font-weight: 600;
  line-height: 1;
}

/* 空占位块 32 × 40、圆角 10、底 #262626 */
.slot-card__placeholder {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 40px;
  border-radius: 10px;
  background: var(--surface-inset);
  color: var(--text-muted);
}

.slot-card__placeholder svg {
  width: 16px;
  height: 16px;
}

.slot-card__body {
  display: flex;
  flex: 1;
  flex-direction: column;
  justify-content: space-between;
  gap: 4px;
  min-width: 0;
  min-height: 48px;
}

.slot-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 4px;
  min-width: 0;
}

.slot-card__head-left {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

/* 类型名 11px（React text-[11px]） */
.slot-card__label {
  flex: none;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.4;
}

/* 已选数量徽标：11px / 600、全圆、深色底 */
.slot-card__count {
  flex: none;
  min-width: 16px;
  padding: 0 5px;
  border-radius: 9999px;
  background: var(--fill-strong);
  color: var(--text-strong);
  font-size: 10px;
  font-weight: 600;
  line-height: 15px;
  text-align: center;
}

/* 名称 12px / 500、最多两行 */
.slot-card__name {
  display: -webkit-box;
  overflow: hidden;
  color: var(--text-strong);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.32;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.slot-card__hint {
  overflow: hidden;
  color: var(--accent-link);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 清除按钮 20 × 20 全圆 */
.slot-card__clear {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  margin: -2px -2px 0 0;
  padding: 0;
  border: 0;
  border-radius: 9999px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition:
    background-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.slot-card__clear:hover {
  background: var(--fill-soft);
  color: var(--text-strong);
}

.slot-card__clear svg {
  width: 12px;
  height: 12px;
}

/* 白模 / 深度分段：10px，与 React 合成台姿势槽一致 */
.depth-toggle {
  display: inline-flex;
  flex: none;
  align-items: center;
  padding: 2px;
  border: 1px solid var(--border-soft);
  border-radius: 6px;
  background: var(--fill-faint);
}

.depth-toggle__btn {
  padding: 2px 6px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 500;
  line-height: 1;
  cursor: pointer;
}

.depth-toggle__btn.is-active {
  background: var(--surface-raised);
  color: var(--text-strong);
}

.depth-toggle__btn.is-active:last-child {
  background: var(--primary);
  color: var(--on-primary);
}

.depth-toggle__btn:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}
</style>