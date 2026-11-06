<script setup lang="ts">
/**
 * 合成台槽位卡（人像 / 服装 / 姿势，多选版）。
 *
 * 交互分工（2026-11-05 拍板）：
 * - 点媒体面板里的缩略图 = 打开参考图库灯箱看大图（在多选条目内左右翻看）；
 * - 点右上「更换」按钮 = 跳到对应库页继续多选；
 * - 空槽整卡点击 = 跳对应库页；已选槽整卡点击同样跳库页（去换图），
 *   但媒体区与各按钮内部一律 `.stop`，避免点图误跳。
 *
 * 视觉：
 * - 卡片 padding 0，内部为「左侧通栏媒体面板 + 右侧信息区」；
 * - 媒体面板 100px 宽，贴住卡片左 / 上 / 下三边，随卡片 14px 圆角裁切；
 * - 已选态 min-height 120px、空态 68px（空态面板 `align-self: start`，
 *   避免被同行已选卡拉高）；单张填满面板，多张 2 列平铺（每格约 46 × 56）。
 *
 * 宽度由父级三列栅格决定（736.66 内容区 - gap 16 → 224.22），不写死像素，
 * 这样 390px 单列时也不会横向溢出。
 *
 * 明确不出现槽位编号式按钮：只用「类型名 + 已选数量 + 图片」表达槽位身份。
 */

import { computed } from 'vue'

import type { SlotSelectedItem } from './slotView'

/** 媒体面板内最多平铺展示的缩略图数量；超出部分用 `+N` 表示。 */
const MEDIA_PREVIEW_LIMIT = 4

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
  /** 点击卡片主体 /「更换」按钮：跳到对应库页签 */
  select: []
  /** 清除当前槽位全部条目 */
  clear: []
  /** 姿势槽切换白模 / 深度图 */
  depthChange: [useDepth: boolean]
  /** 点击媒体面板里的图片：在灯箱中打开该下标的大图 */
  preview: [index: number]
}>()

const selected = computed(() => props.items.length > 0)
const selectedClass = computed(() => (selected.value ? 'is-selected' : 'is-empty'))

/** 单张时填满面板，多张时走 2 列网格。 */
const singleItem = computed(() => (props.items.length === 1 ? props.items[0]! : null))
const previewItems = computed(() => props.items.slice(0, MEDIA_PREVIEW_LIMIT))
const overflowCount = computed(() => Math.max(0, props.items.length - MEDIA_PREVIEW_LIMIT))
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

const ariaLabel = computed(() =>
  selected.value
    ? `${props.label}槽已选 ${props.items.length} 张，点缩略图查看大图，点更换前往${props.label}库`
    : `${props.label}槽未选择，点击前往${props.label}库`,
)

/**
 * 媒体面板图片地址：优先原图（面板已放大到 100px，缩略图会糊），
 * 无原图时用缩略图兜底；两者都没有时返回 null，模板渲染占位块。
 */
function mediaUrl(entry: SlotSelectedItem): string | null {
  return entry.image ?? entry.thumb
}

function onKeydown(event: KeyboardEvent): void {
  // 只响应整卡自身的键盘事件：内部按钮的 Enter / Space 不应再触发「跳库页」。
  if (event.target !== event.currentTarget) return
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
    :aria-label="ariaLabel"
    :data-testid="`studio-slot-${testKey}`"
    @click="emit('select')"
    @keydown="onKeydown"
  >
    <!-- 左侧通栏媒体面板：贴住卡片左 / 上 / 下三边，随卡片圆角裁切 -->
    <div
      class="slot-card__media"
      :class="{ 'is-empty': !selected }"
      :data-testid="`studio-slot-media-${testKey}`"
    >
      <!-- 单张：填满面板；真实 button 保证 Enter / Space 可触发 -->
      <button
        v-if="singleItem"
        type="button"
        class="slot-card__media-single"
        :aria-label="`查看${singleItem.name}大图`"
        @click.stop="emit('preview', 0)"
      >
        <img
          v-if="mediaUrl(singleItem)"
          :src="mediaUrl(singleItem)!"
          :alt="singleItem.name"
          class="slot-card__media-img"
          loading="lazy"
        />
        <span v-else class="slot-card__media-empty" aria-hidden="true">无图</span>
      </button>

      <!-- 多张：2 列平铺，最多 4 张；第 4 格右下角叠加剩余数量 -->
      <div v-else-if="selected" class="slot-card__media-grid">
        <button
          v-for="(entry, index) in previewItems"
          :key="entry.key"
          type="button"
          class="slot-card__media-cell"
          :aria-label="`查看第 ${index + 1} 张：${entry.name}`"
          @click.stop="emit('preview', index)"
        >
          <img
            v-if="mediaUrl(entry)"
            :src="mediaUrl(entry)!"
            :alt="entry.name"
            class="slot-card__media-img"
            loading="lazy"
          />
          <span v-else class="slot-card__media-empty" aria-hidden="true">无图</span>
          <span
            v-if="index === MEDIA_PREVIEW_LIMIT - 1 && overflowCount > 0"
            class="slot-card__media-more"
          >
            +{{ overflowCount }}
          </span>
        </button>
      </div>

      <!-- 空态占位块：32 × 40、底 #262626（走令牌） -->
      <span v-else class="slot-card__placeholder" aria-hidden="true">
        <svg viewBox="0 0 16 16">
          <path d="M8 2.4v11.2M2.4 8h11.2" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
        </svg>
      </span>
    </div>

    <span class="slot-card__body">
      <span class="slot-card__head">
        <span class="slot-card__head-left">
          <span class="slot-card__label">{{ label }}</span>
          <span v-if="selected" class="slot-card__count" :data-testid="`studio-slot-count-${testKey}`">
            {{ items.length }}
          </span>
        </span>

        <span class="slot-card__head-right">
          <!-- 更换：跳对应库页继续多选；小号次要按钮，不与清除抢视觉 -->
          <button
            v-if="selected"
            type="button"
            class="slot-card__change"
            :data-testid="`studio-slot-change-${testKey}`"
            :aria-label="`前往${label}库更换参考图`"
            @click.stop="emit('select')"
          >
            更换
          </button>

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

      <span v-if="selected" class="slot-card__name" :title="nameText">{{ nameText }}</span>
      <span v-else class="slot-card__hint">{{ hint }}</span>
    </span>
  </div>
</template>

<style scoped>
/*
 * 已选态 120px / 空态 68px；宽度跟随三列栅格。
 * `overflow: hidden` 让左侧媒体面板随卡片 14px 圆角裁切（面板本身不给圆角，
 * 否则内圆角与外圆角之间会露出卡片底色缝隙）。
 */
.slot-card {
  --slot-media-width: 100px;

  display: flex;
  align-items: stretch;
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  min-height: 68px;
  padding: 0;
  overflow: hidden;
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
  min-height: 120px;
}

/* 空态不被同一 grid 行的已选卡拉高（行内自身只占 68px）。 */
.slot-card.is-empty {
  align-self: start;
}

.slot-card:hover {
  background: var(--surface-inset-hover);
}

/* 自身裁切导致外部 outline 可能被切，焦点环改画在内侧。 */
.slot-card:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: -2px;
}

/* 媒体面板：左侧通栏，贴上 / 下 / 左三边；宽度用局部变量便于一处调整。 */
.slot-card__media {
  display: flex;
  flex: none;
  align-self: stretch;
  width: var(--slot-media-width);
  overflow: hidden;
  background: var(--surface-thumb);
}

/* 空态不被同行已选卡拉高：只占自身 68px 高度。 */
.slot-card__media.is-empty {
  display: grid;
  align-self: flex-start;
  height: 68px;
  background: var(--surface-inset);
  color: var(--text-muted);
  place-items: center;
}

/* 单张按钮铺满面板。 */
.slot-card__media-single {
  display: block;
  width: 100%;
  height: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
}

.slot-card__media-img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.slot-card__media-single .slot-card__media-img {
  transition: opacity var(--dur-fast) var(--ease);
}

.slot-card__media-single:hover .slot-card__media-img {
  opacity: 0.88;
}

.slot-card__media-single:focus-visible,
.slot-card__media-cell:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: -2px;
}

/* 多张：2 列网格、每格约 46 × 56；2px 内边距 + 2px 间距，贴合 100 × 120 面板。 */
.slot-card__media-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-auto-rows: minmax(0, 1fr);
  gap: 2px;
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  padding: 2px;
}

.slot-card__media-cell {
  position: relative;
  display: block;
  min-width: 0;
  min-height: 0;
  padding: 0;
  overflow: hidden;
  border: 0;
  border-radius: 5px;
  background: var(--surface-inset);
  cursor: pointer;
}

.slot-card__media-cell .slot-card__media-img {
  transition: opacity var(--dur-fast) var(--ease);
}

.slot-card__media-cell:hover .slot-card__media-img {
  opacity: 0.88;
}

/* 无图占位：图片位保持同尺寸，避免面板抖动。 */
.slot-card__media-empty {
  display: grid;
  place-items: center;
  width: 100%;
  height: 100%;
  color: var(--text-faint);
  font-size: 10px;
  line-height: 1;
}

/* 超出 4 张：第 4 格右下角叠加剩余数量。 */
.slot-card__media-more {
  position: absolute;
  right: 2px;
  bottom: 2px;
  padding: 0 4px;
  border-radius: 9999px;
  background: var(--btn-inverse-bg);
  color: var(--on-inverse);
  font-size: 9px;
  font-weight: 600;
  line-height: 14px;
  font-variant-numeric: tabular-nums;
  pointer-events: none;
}

/* 空态占位块 32 × 40、圆角 10。 */
.slot-card__placeholder {
  display: flex;
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

/* 右侧信息区：约 124px 可用宽（224 - 100 面板），内容自适应不撑破卡片。 */
.slot-card__body {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  justify-content: space-between;
  gap: 4px;
  min-width: 0;
  padding: 8px;
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

.slot-card__head-right {
  display: flex;
  flex: none;
  align-items: center;
  gap: 4px;
  margin-left: auto;
}

/* 类型名 11px */
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

/* 更换按钮：20px 高次要按钮，描边弱于主按钮、弱于清除按钮的悬停强调。 */
.slot-card__change {
  flex: none;
  height: 20px;
  padding: 0 6px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 500;
  line-height: 1;
  cursor: pointer;
  transition:
    border-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease);
}

.slot-card__change:hover {
  border-color: var(--primary);
  color: var(--text-strong);
}

.slot-card__change:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}

/* 清除按钮 20 × 20 全圆 */
.slot-card__clear {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
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

.slot-card__clear:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}

.slot-card__clear svg {
  width: 12px;
  height: 12px;
}

/* 白模 / 深度分段：10px，与 React 合成台姿势槽一致 */
.depth-toggle {
  display: inline-flex;
  align-self: flex-start;
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