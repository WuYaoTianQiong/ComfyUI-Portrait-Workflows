<script setup lang="ts">
import { computed } from 'vue'

import type { PoseItem } from '../../../../api/reference'

/**
 * 姿势卡片管理条（管理态）：逐条标记 18+ / 安全 与 可用 / 不可用。
 *
 * 只发 `patch` 事件，不自己发请求也不改 props —— 落库与状态回写统一交给
 * 页面处理，避免分组视图与单张视图各存一份状态（同一条目会漂移）。
 */
const props = withDefaults(
  defineProps<{
    /** 允许为空：分组视图在没图的角度上是空卡，管理条直接不渲染 */
    item?: PoseItem | null
    /** 该条目正在保存：禁用按钮，避免连点互相覆盖 */
    saving?: boolean
  }>(),
  { item: null, saving: false },
)

const emit = defineEmits<{
  (e: 'patch', patch: { rating?: 'nsfw' | 'safe'; usable?: boolean }): void
}>()

const isNsfw = computed(() => props.item?.rating === 'nsfw')
const unavailable = computed(() => props.item?.usable === false)
const ratingTitle = computed(() =>
  isNsfw.value
    ? '当前 18+：点击改为安全（安全模式可见）'
    : '当前安全：点击标为 18+（安全模式隐藏）',
)
const usableTitle = computed(() => {
  if (unavailable.value) {
    const note = props.item?.usableNote
    return note ? `不可用：${note}（点击恢复可用）` : '当前不可用：点击恢复可用'
  }
  return '当前可用：点击标为不可用（不进出图候选）'
})
</script>

<template>
  <div v-if="item" class="pose-manage" data-testid="pose-manage" @click.stop>
    <button
      type="button"
      class="pose-manage__btn"
      :class="{ 'is-nsfw': isNsfw }"
      :disabled="saving"
      :title="ratingTitle"
      data-testid="pose-manage-rating"
      @click="emit('patch', { rating: isNsfw ? 'safe' : 'nsfw' })"
    >
      {{ isNsfw ? '18+' : '安全' }}
    </button>
    <button
      type="button"
      class="pose-manage__btn"
      :class="{ 'is-off': unavailable }"
      :disabled="saving"
      :title="usableTitle"
      data-testid="pose-manage-usable"
      @click="emit('patch', { usable: unavailable })"
    >
      {{ unavailable ? '不可用' : '可用' }}
    </button>
  </div>
</template>

<style scoped>
/* 卡片底部管理条：22px 高、10.5px 字，尽量不挤占缩略图 */
.pose-manage {
  display: flex;
  gap: 4px;
  padding-top: 4px;
}

.pose-manage__btn {
  flex: 1 1 0;
  min-width: 0;
  box-sizing: border-box;
  height: 22px;
  padding: 0 4px;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-sm);
  background: var(--surface-inset);
  color: var(--text-body-soft);
  font-size: 10.5px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
  transition:
    background-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease);
}

.pose-manage__btn:hover:not(:disabled) {
  background: var(--surface-inset-hover);
  color: var(--text-strong);
}

.pose-manage__btn:disabled {
  opacity: 0.5;
  cursor: default;
}

/* 18+：红系，和安全态一眼可分 */
.pose-manage__btn.is-nsfw {
  border-color: var(--accent-red-border);
  background: var(--accent-red-soft);
  color: var(--accent-red-text);
}

/* 不可用：降饱和，和「18+」区分开（不是敏感，是实测跑不动） */
.pose-manage__btn.is-off {
  border-style: dashed;
  color: var(--text-muted);
}
</style>
