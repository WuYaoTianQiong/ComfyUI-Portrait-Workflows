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

import {
  SLOT_TEXT_TYPE_HINTS,
} from '../../../../composables/recipeTextFragments'
import type { RecipeSlotMode } from '../../../../composables/recipeTextFragments'
import type { SlotSelectedItem } from './slotView'

const props = defineProps<{
  /** 类型名：人像 / 服装 / 姿势 */
  label: string
  /** 槽位键，同时用于 data-testid 后缀 */
  slotKey: 'portrait' | 'costume' | 'pose'
  /** 人物B 等第二组的 testid 前缀（默认空，保持 A 组契约不变）。 */
  testIdPrefix?: string
  /** 已选条目（顺序即加入顺序）；空数组表示空态 */
  items: readonly SlotSelectedItem[]
  /** 空态主文案（如「＋ 选人像」） */
  hint: string
  /**
   * 槽位模式（P2 替代态）：
   * - image：显示图墙与图片入口；
   * - text：隐藏图墙，引导到下方「文本补充」卡填写对应类碎片；
   * - empty：无图无文本（空态）。
   */
  mode?: RecipeSlotMode
  /** 姿势槽：是否显示白模 / 深度分段 */
  showDepthToggle?: boolean
  /** 姿势槽：当前是否深度图 */
  useDepth?: boolean
  /**
   * 本槽对应的工作流图号（提示词里的「图N」）。
   *
   * 0 / undefined = 该工作流没有这个图位或后端未返回映射 → 不显示徽标。
   * 空槽也显示：用户才能看懂为什么提示词里跳过了图3 直接出现图4。
   */
  figureNo?: number
}>()

const emit = defineEmits<{
  /** 点「更换」/ 空态主按钮 / 底部「继续选」：跳对应库页 */
  select: []
  /** 清空当前槽位全部条目 */
  clear: []
  /** 姿势槽切换白模 / 深度图 */
  depthChange: [useDepth: boolean]
  /** 点缩略图：在灯箱打开该下标的大图 */
  preview: [index: number]
  /** 单项删除；key 即 `SlotSelectedItem.key`（= 条目 id） */
  remove: [key: string]
  /** 切换图片 / 文本模式（父级负责双人 / 素体校验） */
  'update:mode': [mode: RecipeSlotMode]
  /** 文本模式「去填写」：展开并定位到文本补充卡 */
  fillText: []
}>()

const prefix = computed(() => props.testIdPrefix ?? '')
const selected = computed(() => props.items.length > 0)
/** 缺省按图片模式渲染，兼容旧调用方。 */
const mode = computed<RecipeSlotMode>(() => props.mode ?? 'image')
/** text 模式的安全网：即使还有残留图片也不再展示图墙 / 图片入口。 */
const textMode = computed(() => mode.value === 'text')
const textTypeHint = computed(() => SLOT_TEXT_TYPE_HINTS[props.slotKey])

/** 灯箱地址：优先原图，无原图回退缩略图；两者皆无时返回 null 走占位。 */
function mediaUrl(entry: SlotSelectedItem): string | null {
  return entry.image ?? entry.thumb
}

/** 卡头分段控件：只在已选图 / 已选文本时出现，避免空态多出两个入口。 */
const showModeToggle = computed(() => selected.value || textMode.value)

function setMode(next: RecipeSlotMode): void {
  if (mode.value === next) return
  emit('update:mode', next)
}
</script>

<template>
  <!-- 统一用 section 作根：空态内部需要「选图 / 改用文本」两个独立按钮，不能再整卡套 button -->
  <section
    class="slot-panel"
    :class="{ 'slot-panel--empty': !selected && !textMode }"
    :aria-label="
      textMode
        ? `${label}槽使用文本替代，请在文本补充卡填写${textTypeHint}`
        : selected
          ? `${label}槽，已选 ${items.length} 张`
          : `${label}槽未选择，可选择参考图或改用文本`
    "
    :data-testid="`${prefix}studio-slot-${slotKey}`"
  >
    <header class="slot-panel__head">
      <div class="slot-panel__head-main">
        <span class="slot-panel__label">{{ label }}</span>
        <span
          v-if="figureNo"
          class="slot-panel__figure"
          :title="`提示词里的「图${figureNo}」就是本槽`"
          :data-testid="`${prefix}studio-slot-figure-${slotKey}`"
        >
          图{{ figureNo }}
        </span>
        <span
          v-if="selected"
          class="slot-panel__count"
          :data-testid="`${prefix}studio-slot-count-${slotKey}`"
        >
          {{ items.length }}
        </span>
      </div>

      <!--
        图片 / 文本分段控件（方案 §8 P2）：
        只在「已选图」或「已切文本」时出现，空态由下方两个入口承担，
        避免同一张窄卡里出现四个并列按钮。
      -->
      <div
        v-if="showModeToggle"
        class="mode-toggle"
        role="group"
        :aria-label="`切换${label}槽用参考图还是用文本`"
      >
        <button
          type="button"
          class="mode-toggle__btn"
          :class="{ 'is-active': mode === 'image' }"
          :aria-pressed="mode === 'image'"
          :data-testid="`${prefix}studio-slot-mode-${slotKey}-image`"
          @click="setMode('image')"
        >
          图片
        </button>
        <button
          type="button"
          class="mode-toggle__btn"
          :class="{ 'is-active': mode === 'text' }"
          :aria-pressed="mode === 'text'"
          :data-testid="`${prefix}studio-slot-mode-${slotKey}-text`"
          @click="setMode('text')"
        >
          文本
        </button>
      </div>

      <!--
        姿势槽：整槽白模 / 深度切换。
        它是**整槽设置**（`depthChange` → `setPoseMode` 全量），因此放在头部
        与「更换 / 清空」同一行，而不是贴在图墙上方冒充单图开关。
        该开关只影响槽位 / 清单 / 灯箱显示哪张图，不影响出图 —— 卡片底部有常驻说明。
      -->
      <div
        v-if="showDepthToggle && items.length > 0 && !textMode"
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
          :data-testid="`${prefix}studio-pose-depth-white`"
          @click="emit('depthChange', false)"
        >
          白模
        </button>
        <button
          type="button"
          class="depth-toggle__btn"
          :class="{ 'is-active': useDepth }"
          :aria-pressed="useDepth"
          :data-testid="`${prefix}studio-pose-depth-depth`"
          @click="emit('depthChange', true)"
        >
          深度
        </button>
      </div>

      <!-- text 模式不提供任何图片选择入口（方案 §8 P2） -->
      <div v-if="!textMode && selected" class="slot-panel__head-actions">
        <button
          type="button"
          class="slot-panel__change"
          :aria-label="`前往${label}库更换或追加参考图`"
          :data-testid="`${prefix}studio-slot-change-${slotKey}`"
          @click="emit('select')"
        >
          更换
        </button>
        <button
          type="button"
          class="slot-panel__clear"
          :aria-label="`清空${label}槽全部参考图`"
          :data-testid="`${prefix}studio-slot-clear-${slotKey}`"
          @click="emit('clear')"
        >
          清空
        </button>
      </div>

      <!-- text 模式仍允许清空残留图片（只删图，不改模式） -->
      <div v-else-if="textMode" class="slot-panel__head-actions">
        <button
          type="button"
          class="slot-panel__clear"
          :aria-label="`清空${label}槽残留参考图`"
          :data-testid="`${prefix}studio-slot-clear-${slotKey}`"
          @click="emit('clear')"
        >
          清空
        </button>
      </div>
    </header>

    <!-- text 模式：只给说明与「去填写」，不显示图墙 / 选图入口 -->
    <div v-if="textMode" class="slot-panel__text" :data-testid="`${prefix}studio-slot-text-${slotKey}`">
      <p class="slot-panel__text-hint">
        文本模式：请在下方「文本补充」卡填写 {{ textTypeHint }} 类（当前图片不参与提交）
      </p>
      <button
        type="button"
        class="slot-panel__fill"
        :data-testid="`${prefix}studio-slot-fill-text-${slotKey}`"
        @click="emit('fillText')"
      >
        去填写
      </button>
    </div>

    <!-- image 模式且有图：竖向图墙（全量渲染 + 内部滚动） -->
    <div
      v-else-if="selected"
      class="slot-panel__media"
      :data-testid="`${prefix}studio-slot-media-${slotKey}`"
    >
      <div v-for="(entry, index) in items" :key="entry.key" class="tile">
        <!-- 缩略图主体：与 × 是同级 sibling，不互相嵌套 -->
        <button
          type="button"
          class="tile__open"
          :aria-label="`查看第 ${index + 1} 张：${entry.name}`"
          :data-testid="`${prefix}studio-slot-thumb-${slotKey}`"
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
          :data-testid="`${prefix}studio-slot-remove-${slotKey}`"
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

    <p
      v-if="showDepthToggle && !textMode && selected"
      class="slot-panel__note"
      :data-testid="`${prefix}studio-pose-depth-note`"
    >
      白模 / 深度仅影响预览，不影响出图
    </p>

    <div v-if="!textMode && selected" class="slot-panel__footer">
      <button
        type="button"
        class="slot-panel__more"
        :aria-label="`继续选择${label}参考图`"
        @click="emit('select')"
      >
        ＋ 继续选{{ label }}
      </button>
      <slot name="footer" />
    </div>

    <!-- 空态：保留原选图入口，并增加「改用文本 / 上传本地图」（方案 §8 P2） -->
    <div v-if="!selected && !textMode" class="slot-panel__empty" :data-testid="`${prefix}studio-slot-media-${slotKey}`">
      <button
        type="button"
        class="slot-panel__empty-main"
        :aria-label="`前往${label}库选择参考图`"
        :data-testid="`${prefix}studio-slot-select-${slotKey}`"
        @click="emit('select')"
      >
        <span class="slot-panel__empty-media" aria-hidden="true">
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
        <span class="slot-panel__empty-note">选完手动切回合成台</span>
      </button>
      <div class="slot-panel__footer slot-panel__footer--empty">
        <button
          type="button"
          class="slot-panel__empty-switch"
          :data-testid="`${prefix}studio-slot-use-text-${slotKey}`"
          @click="emit('update:mode', 'text')"
        >
          改用文本
        </button>
        <slot name="footer" />
      </div>
    </div>
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

/* 空态：虚线边框；内部「选图」按钮与「改用文本」按钮各自独立 */
.slot-panel--empty {
  gap: 0;
  padding: 10px;
  border: 1px dashed var(--border-stronger);
  transition:
    border-color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease);
}

.slot-panel--empty:hover {
  border-color: var(--primary);
  background: var(--fill-faint);
}

/* 空态容器：主入口在上，改用文本在下 */
.slot-panel__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

/* 空态主入口：整块可点，视觉上仍是原来的虚线卡 */
.slot-panel__empty-main {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  box-sizing: border-box;
  width: 100%;
  padding: 20px 12px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: inherit;
  text-align: center;
  cursor: pointer;
}

.slot-panel__empty-main:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: -2px;
}

/* 空态次级入口：改用文本（与主入口同一张卡，但视觉更轻） */
.slot-panel__empty-switch {
  min-height: 24px;
  padding: 0 10px;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-body);
  font-size: 12px;
  font-weight: 500;
  line-height: 1;
  transition:
    border-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.slot-panel__empty-switch:hover {
  border-color: var(--primary);
  color: var(--text-strong);
}

.slot-panel__empty-switch:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
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

/* 图号徽标：把提示词里的「图N」标到本槽，空槽也显示 */
.slot-panel__figure {
  flex: none;
  padding: 0 6px;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-pill);
  background: var(--fill-subtle);
  color: var(--text-muted);
  font-size: 11px;
  line-height: 17px;
  font-variant-numeric: tabular-nums;
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
/* 图片 / 文本分段：与白模 / 深度同尺寸，放在头部右侧 */
.mode-toggle {
  display: inline-flex;
  flex: none;
  align-items: center;
  margin-left: auto;
  padding: 1px;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-sm);
  background: var(--fill-faint);
}

.mode-toggle__btn {
  padding: 2px 8px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-body);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.3;
}

/* 当前模式用卡片底色 + 强文本；非当前段保持可读（不用灰淡色） */
.mode-toggle__btn.is-active {
  background: var(--surface-card);
  color: var(--text-strong);
  font-weight: 600;
}

.mode-toggle__btn:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}

/* 文本模式：说明 + 去填写，不渲染图墙 */
.slot-panel__text {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  padding: var(--gap-sm) 0;
}

.slot-panel__text-hint {
  margin: 0;
  color: var(--text-body);
  font-size: 12px;
  line-height: 1.6;
}

.slot-panel__fill {
  align-self: flex-start;
  min-height: 28px;
  padding: 0 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-strong);
  font-size: 12px;
  font-weight: 500;
  line-height: 1;
}

.slot-panel__fill:hover {
  border-color: var(--primary);
}

.slot-panel__fill:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}

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

/* 「继续选」与「上传本地图」同一行：flex 等分，避免上下堆叠 */
.slot-panel__footer {
  display: flex;
  align-items: stretch;
  gap: 8px;
  min-width: 0;
}

.slot-panel__footer .slot-panel__more {
  width: auto;
  flex: 1 1 0;
  min-width: 0;
}

/* slotted 内容属于父组件作用域，用 :slotted 覆盖父级的 width:100% */
.slot-panel__footer :slotted(.slot-upload) {
  width: auto;
  flex: 1 1 0;
  min-width: 0;
  margin-top: 0;
}

/* 空态：改用文本 + 上传本地图同排，与已选态的 footer 保持一致 */
.slot-panel__footer--empty {
  width: 100%;
}

.slot-panel__footer--empty .slot-panel__empty-switch {
  flex: 1 1 0;
  min-height: 28px;
  padding: 0 8px;
}
</style>