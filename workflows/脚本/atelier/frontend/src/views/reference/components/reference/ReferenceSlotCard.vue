<script setup lang="ts">
/**
 * 合成台槽位卡（人像 / 服装 / 姿势）。
 *
 * 视觉按施工手册 §5「合成台」行：
 * - 空态 224.22 × 68px、已选态 224.22 × 75px，内边距 10px、圆角 14px、底 `#0a0a0a`；
 * - 槽位缩略图 40 × 48px、圆角 10px；
 * - 空槽位占位块 32 × 40px、圆角 10px、底 `#262626`。
 *
 * 宽度由父级三列栅格决定（736.66 内容区 - gap 16 → 224.22），不写死像素，
 * 这样 390px 单列时也不会横向溢出。
 *
 * 明确不出现槽位编号式按钮：只用「类型名 + 缩略图 / 占位块」表达槽位身份。
 */

import { computed } from 'vue'

const props = defineProps<{
  /** 类型名：人像 / 服装 / 姿势 */
  label: string
  /** 已选条目名（空串表示空态） */
  name: string
  /** 缩略图地址；空态传 null */
  thumb: string | null
  /** 空态提示文案（如「+ 选人像」） */
  hint: string
  /** 是否已选 */
  selected: boolean
  /** 姿势槽：是否显示白模 / 深度分段 */
  showDepthToggle?: boolean
  /** 姿势槽：当前是否深度图 */
  useDepth?: boolean
}>()

const emit = defineEmits<{
  /** 点击卡片主体：跳到对应库页签 */
  select: []
  /** 清除当前槽位 */
  clear: []
  /** 姿势槽切换白模 / 深度图 */
  depthChange: [useDepth: boolean]
}>()

const selectedClass = computed(() => (props.selected ? 'is-selected' : 'is-empty'))

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
    :aria-label="selected ? `${label}槽：${name}，点击更换` : `${label}槽未选择，点击前往${label}库`"
    :data-testid="`studio-slot-${label === '人像' ? 'portrait' : label === '服装' ? 'costume' : 'pose'}`"
    @click="emit('select')"
    @keydown="onKeydown"
  >
    <img
      v-if="selected && thumb"
      :src="thumb"
      :alt="name || label"
      class="slot-card__thumb"
      loading="lazy"
    />
    <span v-else-if="selected" class="slot-card__thumb is-empty" aria-hidden="true">
      <svg viewBox="0 0 16 16">
        <rect x="2.6" y="2.6" width="10.8" height="10.8" rx="2" fill="none" stroke="currentColor" stroke-width="1.2" />
      </svg>
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
          :aria-label="`清除${label}参考图`"
          @click.stop="emit('clear')"
        >
          <svg viewBox="0 0 12 12" aria-hidden="true">
            <path d="M3 3l6 6M9 3l-6 6" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
          </svg>
        </button>
      </span>

      <span v-if="selected" class="slot-card__name" :title="name">{{ name }}</span>
      <span v-else class="slot-card__hint">{{ hint }}</span>
    </span>
  </div>
</template>

<style scoped>
/* 空态 68px / 已选态 75px（§5），宽度跟随三列栅格。 */
.slot-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  height: 68px;
  padding: 10px;
  border: 0;
  border-radius: 14px;
  background: #0a0a0a;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    background-color var(--dur-fast) var(--ease),
    height var(--dur-fast) var(--ease);
}

.slot-card.is-selected {
  height: 75px;
  align-items: flex-start;
}

.slot-card:hover {
  background: #141414;
}

.slot-card:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

/* 缩略图 40 × 48、圆角 10 */
.slot-card__thumb {
  display: block;
  flex: none;
  width: 40px;
  height: 48px;
  border-radius: 10px;
  background: #262626;
  object-fit: cover;
}

.slot-card__thumb.is-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #a1a1a1;
}

.slot-card__thumb.is-empty svg {
  width: 18px;
  height: 18px;
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
  background: #262626;
  color: #a1a1a1;
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
  color: #a1a1a1;
  font-size: 11px;
  line-height: 1.4;
}

/* 名称 12px / 500、最多两行 */
.slot-card__name {
  display: -webkit-box;
  overflow: hidden;
  color: #fafafa;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.32;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.slot-card__hint {
  overflow: hidden;
  color: #818cf8;
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
  color: #a1a1a1;
  cursor: pointer;
  transition:
    background-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.slot-card__clear:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #fafafa;
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
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.04);
}

.depth-toggle__btn {
  padding: 2px 6px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: #a1a1a1;
  font-size: 10px;
  font-weight: 500;
  line-height: 1;
  cursor: pointer;
}

.depth-toggle__btn.is-active {
  background: #171717;
  color: #fafafa;
}

.depth-toggle__btn.is-active:last-child {
  background: var(--primary);
  color: #fafafa;
}

.depth-toggle__btn:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}
</style>