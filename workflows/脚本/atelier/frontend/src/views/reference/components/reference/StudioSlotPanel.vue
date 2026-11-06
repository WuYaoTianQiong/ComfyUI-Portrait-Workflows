<script setup lang="ts">
/**
 * 合成台槽位卡（人像 / 服装 / 姿势，竖向图墙版）。
 *
 * 与旧 `ReferenceSlotCard.vue` 的差异（2026-11-06 拍板）：
 * - 取消 4 张展示上限：`items` 全量渲染，数量徽标显示真实总数；
 * - 图墙改为竖向自适应列（auto-fill + 3/4 画幅），容器内部纵向滚动，
 *   卡片不再随已选数量无限长高；
 * - 每格右上角独立 `×` 删除单条（`remove`），缩略图主体点击开灯箱（`preview`）；
 * - 空态整卡是**一个真实 button**；已选态根是 `<section>`，不再声明按钮角色，
 *   因此不存在「按钮角色里套 button」的嵌套可交互语义问题；
 * - 卡片级点击只保留在空态，已选态所有跳库入口都是独立按钮。
 *
 * 宽度由父级三列栅格决定（不写死像素），390px 单列时也不会横向溢出。
 */

import { computed } from 'vue'

import type { SlotSelectedItem } from './slotView'

const props = defineProps<{
  /** 类型名：人像 / 服装 / 姿势 */
  label: string
  /** 槽位键，同时用于 data-testid 后缀 */
  slotKey: 'portrait' | 'costume' | 'pose'
  /** 已选条目（顺序即加入顺序）；空数组表示空态 */
  items: readonly SlotSelectedItem[]
  /** 空态主文案（如「＋ 选人像」） */
  hint: string
  /** 姿势槽：是否显示白模 / 深度分段 */
  showDepthToggle?: boolean
  /** 姿势槽：当前是否深度图 */
  useDepth?: boolean
}>()

const emit = defineEmits<{
  /** 点「更换」/ 空态整卡 / 底部「继续选」：跳对应库页 */
  select: []
  /** 清空当前槽位全部条目 */
  clear: []
  /** 姿势槽切换白模 / 深度图 */
  depthChange: [useDepth: boolean]
  /** 点缩略图：在灯箱打开该下标的大图 */
  preview: [index: number]
  /** 单项删除；key 即 `SlotSelectedItem.key`（= 条目 id） */
  remove: [key: string]
}>()

const selected = computed(() => props.items.length > 0)

/** 灯箱地址：优先原图，无原图回退缩略图；两者皆无时返回 null 走占位。 */
function mediaUrl(entry: SlotSelectedItem): string | null {
  return entry.image ?? entry.thumb
}
</script>

<template>
  <!-- 空态：整卡就是一个真实 button，点击前往对应库页 -->
  <button
    v-if="!selected"
    type="button"
    class="slot-panel slot-panel--empty"
    :aria-label="`${label}槽未选择，点击前往${label}库多选`"
    :data-testid="`studio-slot-${slotKey}`"
    @click="emit('select')"
  >
    <span
      class="slot-panel__empty-media"
      :data-testid="`studio-slot-media-${slotKey}`"
      aria-hidden="true"
    >
      <svg viewBox="0 0 16 16">
        <path
          d="M8 2.6v10.8M2.6 8h10.8"
          fill="none"
          stroke="currentColor"
          stroke-width="1.2"
          stroke-linecap="round"
        />
      </svg>
    </span>
    <span class="slot-panel__empty-hint">{{ hint }}</span>
    <span class="slot-panel__empty-note">可多选，选完手动切回合成台</span>
  </button>

  <!-- 已选态：section 仅作分组容器，不带按钮角色、不整卡点击 -->
  <section
    v-else
    class="slot-panel"
    :aria-label="`${label}槽，已选 ${items.length} 张`"
    :data-testid="`studio-slot-${slotKey}`"
  >
    <header class="slot-panel__head">
      <div class="slot-panel__head-main">
        <span class="slot-panel__label">{{ label }}</span>
        <span
          class="slot-panel__count"
          :data-testid="`studio-slot-count-${slotKey}`"
        >
          {{ items.length }}
        </span>
      </div>

      <!--
        姿势槽：整槽白模 / 深度切换。
        它是**整槽设置**（`depthChange` → `setPoseMode` 全量），因此放在头部
        与「更换 / 清空」同一行，而不是贴在图墙上方冒充单图开关。
        该开关只影响槽位 / 清单 / 灯箱显示哪张图，不影响出图 —— 卡片底部有常驻说明。
      -->
      <div
        v-if="showDepthToggle && items.length > 0"
        class="depth-toggle"
        role="group"
        aria-label="切换本槽显示白模或深度图（仅预览，不影响出图）"
        title="仅切换本槽显示白模 / 深度图，不影响出图"
      >
        <button
          type="button"
          class="depth-toggle__btn"
          :class="{ 'is-active': !useDepth }"
          :aria-pressed="!useDepth"
          data-testid="studio-pose-depth-white"
          @click="emit('depthChange', false)"
        >
          白模
        </button>
        <button
          type="button"
          class="depth-toggle__btn"
          :class="{ 'is-active': useDepth }"
          :aria-pressed="useDepth"
          data-testid="studio-pose-depth-depth"
          @click="emit('depthChange', true)"
        >
          深度
        </button>
      </div>

      <div class="slot-panel__head-actions">
        <button
          type="button"
          class="slot-panel__change"
          :aria-label="`前往${label}库更换或追加参考图`"
          :data-testid="`studio-slot-change-${slotKey}`"
          @click="emit('select')"
        >
          更换
        </button>
        <button
          type="button"
          class="slot-panel__clear"
          :aria-label="`清空${label}槽全部参考图`"
          :data-testid="`studio-slot-clear-${slotKey}`"
          @click="emit('clear')"
        >
          清空
        </button>
      </div>
    </header>

    <!-- 竖向图墙：全量渲染 + 内部纵向滚动，约 3 行高度 -->
    <div
      class="slot-panel__media"
      :data-testid="`studio-slot-media-${slotKey}`"
    >
      <div v-for="(entry, index) in items" :key="entry.key" class="tile">
        <!-- 缩略图主体：与 × 是同级 sibling，不互相嵌套 -->
        <button
          type="button"
          class="tile__open"
          :aria-label="`查看第 ${index + 1} 张：${entry.name}`"
          :data-testid="`studio-slot-thumb-${slotKey}`"
          :data-index="index"
          @click="emit('preview', index)"
        >
          <img
            v-if="mediaUrl(entry)"
            :src="mediaUrl(entry)!"
            :alt="entry.name"
            class="tile__img"
            loading="lazy"
          />
          <span v-else class="tile__empty">无图</span>
        </button>

        <!-- 单项删除：hover / focus 才显形，触屏常显 -->
        <button
          type="button"
          class="tile__remove"
          :aria-label="`从${label}槽移除 ${entry.name}`"
          :data-testid="`studio-slot-remove-${slotKey}`"
          :data-key="entry.key"
          @click.stop="emit('remove', entry.key)"
        >
          <svg viewBox="0 0 12 12" aria-hidden="true">
            <path
              d="M3 3l6 6M9 3l-6 6"
              fill="none"
              stroke="currentColor"
              stroke-width="1.4"
              stroke-linecap="round"
            />
          </svg>
        </button>

        <!-- 白模 / 深度角标：整槽统一，仅提示当前显示的是哪张图 -->
        <span v-if="showDepthToggle" class="tile__mode" aria-hidden="true">
          {{ useDepth ? '深' : '白' }}
        </span>
      </div>
    </div>

    <!-- 常驻说明：把「仅预览」写在界面上，避免误以为切换会影响出图 -->
    <p v-if="showDepthToggle" class="slot-panel__note" data-testid="studio-pose-depth-note">
      白模 / 深度仅影响预览，不影响出图
    </p>

    <button
      type="button"
      class="slot-panel__more"
      :aria-label="`继续选择${label}参考图`"
      @click="emit('select')"
    >
      ＋ 继续选{{ label }}
    </button>
  </section>
</template>

<style scoped>
/*
 * 已选态与空态共用的外框：14px 圆角 + 深底。
 * 宽度 100% / min-width 0，交给父级三列栅格控制。
 */
.slot-panel {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  min-width: 0;
  min-height: 120px;
  padding: 10px;
  border: 1px solid var(--border-faint);
  border-radius: 14px;
  background: var(--surface-deep);
  color: inherit;
}

/* 空态：虚线边框 + 居中图标 / 主文案 / 副文案，整卡可点 */
.slot-panel--empty {
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 20px 12px;
  border: 1px dashed var(--border-stronger);
  text-align: center;
  cursor: pointer;
  transition:
    border-color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease);
}

.slot-panel--empty:hover {
  border-color: var(--primary);
  background: var(--fill-faint);
}

.slot-panel--empty:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: -2px;
}

/* 空态占位块 36 × 44、圆角 10（与旧卡同语义，仅放大到可点击卡尺度） */
.slot-panel__empty-media {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 44px;
  border-radius: 10px;
  background: var(--surface-inset);
  color: var(--text-muted);
}

.slot-panel__empty-media svg {
  width: 16px;
  height: 16px;
}

/* 主文案 13px / 500 */
.slot-panel__empty-hint {
  color: var(--accent-link);
  font-size: 13px;
  font-weight: 500;
  line-height: 1.4;
}

/* 副文案 12px，弱于主文案但保持可读 */
.slot-panel__empty-note {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.4;
}

/* 头部：类型名 + 数量 | 白模/深度 | 更换 + 清空（窄卡时自动换行） */
.slot-panel__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  min-width: 0;
  row-gap: 6px;
}

.slot-panel__head-main {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.slot-panel__head-actions {
  display: flex;
  flex: none;
  align-items: center;
  gap: 4px;
}

/* 类型名 12px / 600 */
.slot-panel__label {
  flex: none;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.4;
}

/* 数量徽标：显示真实总数（4 / 12 / 30），11px 全圆 */
.slot-panel__count {
  flex: none;
  min-width: 18px;
  padding: 0 6px;
  border-radius: var(--radius-pill);
  background: var(--fill-strong);
  color: var(--text-body);
  font-size: 11px;
  font-weight: 600;
  line-height: 17px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

/* 更换：24px 高次要按钮 */
.slot-panel__change {
  flex: none;
  height: 24px;
  padding: 0 8px;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 500;
  line-height: 1;
  transition:
    border-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.slot-panel__change:hover {
  border-color: var(--primary);
  color: var(--text-strong);
}

.slot-panel__change:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}

/* 清空：同尺寸文字按钮，hover 才提示危险语义 */
.slot-panel__clear {
  flex: none;
  height: 24px;
  padding: 0 8px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 500;
  line-height: 1;
  transition:
    border-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.slot-panel__clear:hover {
  border-color: var(--danger-border-soft);
  color: var(--danger-text-strong);
}

.slot-panel__clear:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}

/*
 * 白模 / 深度分段：位于头部「数量」与「更换 / 清空」之间，靠右排列。
 * 尺寸压到 22px 高，保证 250px 窄卡也不换行（换行时由 head 的 flex-wrap 兜底）。
 */
.depth-toggle {
  display: inline-flex;
  flex: none;
  align-items: center;
  margin-left: auto;
  padding: 1px;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-sm);
  background: var(--fill-faint);
}

.depth-toggle__btn {
  padding: 2px 6px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 500;
  line-height: 1.2;
}

/* 两段同色：预览开关是次要控件，不用主色抢「更换 / 清空」的注意力 */
.depth-toggle__btn.is-active {
  background: var(--surface-card);
  color: var(--text-strong);
}

.depth-toggle__btn:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}

/*
 * 图墙：auto-fill 自适应列（最小 72px），每格 3/4 画幅；
 * 容器限高约 3 行（300px）后内部纵向滚动，滚动条走 thin。
 */
.slot-panel__media {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));
  align-content: start;
  gap: 6px;
  max-height: 300px;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: var(--fill-heavy) transparent;
}

.slot-panel__media::-webkit-scrollbar {
  width: 6px;
}

.slot-panel__media::-webkit-scrollbar-track {
  background: transparent;
}

.slot-panel__media::-webkit-scrollbar-thumb {
  border-radius: var(--radius-pill);
  background: var(--fill-heavy);
}

/* 单个格子：竖版 3/4，两张 button 同级叠放 */
.tile {
  position: relative;
  width: 100%;
  min-width: 0;
  aspect-ratio: 3 / 4;
  overflow: hidden;
  border-radius: var(--radius-sm);
  background: var(--surface-thumb);
}

.tile__open {
  display: block;
  width: 100%;
  height: 100%;
  padding: 0;
  border: 0;
  background: transparent;
}

.tile__img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: opacity var(--dur-fast) var(--ease);
}

.tile__open:hover .tile__img {
  opacity: 0.88;
}

.tile__open:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: -2px;
}

/* 无图占位：保持同尺寸，避免图墙抖动 */
.tile__empty {
  display: grid;
  place-items: center;
  width: 100%;
  height: 100%;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1;
}

/* 单项删除：默认不可见，hover / 焦点内显形 */
.tile__remove {
  position: absolute;
  top: 3px;
  right: 3px;
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-pill);
  background: var(--btn-inverse-bg);
  color: var(--on-inverse);
  opacity: 0;
  transition:
    opacity var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease);
}

.tile__remove svg {
  width: 12px;
  height: 12px;
}

.tile:hover .tile__remove,
.tile:focus-within .tile__remove,
.tile__remove:focus-visible {
  opacity: 1;
}

.tile__remove:hover {
  background: var(--btn-inverse-bg-hover);
}

.tile__remove:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}

/* 触屏没有 hover：删除按钮常显，避免无法删除 */
@media (hover: none) {
  .tile__remove {
    opacity: 1;
  }
}

/* 白 / 深角标：左下角，12px 以内，避免与右上角删除按钮抢位置 */
.tile__mode {
  position: absolute;
  bottom: 3px;
  left: 3px;
  padding: 0 3px;
  border-radius: 3px;
  background: var(--surface-overlay);
  color: var(--text-body-soft);
  font-size: 9px;
  font-weight: 600;
  line-height: 13px;
  pointer-events: none;
}

/* 姿势槽常驻说明：把「仅预览」明确写给用户 */
.slot-panel__note {
  margin: 0;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.4;
}

/* 底部整宽「继续选」：虚线按钮，与空态边框同语义 */
.slot-panel__more {
  width: 100%;
  min-height: 28px;
  padding: 4px 8px;
  border: 1px dashed var(--border-stronger);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
  transition:
    border-color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.slot-panel__more:hover {
  border-color: var(--primary);
  background: var(--fill-faint);
  color: var(--text-strong);
}

.slot-panel__more:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}
</style>