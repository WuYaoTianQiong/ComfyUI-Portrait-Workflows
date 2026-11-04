<script setup lang="ts">
import { computed, useSlots } from 'vue'

import EmptyState from './EmptyState.vue'
import Skeleton from './Skeleton.vue'

/**
 * 查询三态：loading / error / empty。
 *
 * 以前的页面把请求错误当成空列表渲染，后端 500 时用户只看到“没有数据”。
 * 这里统一给出可见的错误信息与重试入口；默认插槽只在数据可用时渲染。
 */
const props = withDefaults(
  defineProps<{
    loading?: boolean
    error?: unknown
    empty?: boolean
    loadingText?: string
    emptyText?: string
  }>(),
  {
    loading: false,
    empty: false,
    loadingText: '加载中…',
    emptyText: '暂无数据',
  },
)

const emit = defineEmits<{ (e: 'retry'): void }>()

const slots = useSlots()
const hasEmptySlot = computed(() => Boolean(slots.empty))

const errorText = computed(() => {
  if (props.error instanceof Error) return props.error.message
  return props.error ? String(props.error) : ''
})
</script>

<template>
  <div v-if="loading" class="query-state loading" aria-busy="true">
    <Skeleton :count="3" height="12px" />
    <span class="loading-text">{{ loadingText }}</span>
  </div>
  <div v-else-if="error" class="query-state error" role="alert">
    <div class="title">加载失败</div>
    <div class="detail">{{ errorText }}</div>
    <div class="next">请检查网络连接或后端服务，然后重试。</div>
    <slot name="action">
      <button class="btn btn-sm" @click="emit('retry')">重试</button>
    </slot>
  </div>
  <EmptyState v-else-if="empty" :text="hasEmptySlot ? '' : emptyText">
    <slot name="empty" />
  </EmptyState>
  <slot v-else />
</template>

<style scoped>
.query-state {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--gap-sm);
  padding: var(--gap-md) var(--gap-lg);
  color: var(--muted);
  font-size: var(--fs-sm);
  line-height: var(--lh-sm);
}

.query-state.loading {
  align-items: stretch;
}

.query-state.loading .loading-text {
  font-size: var(--fs-sm);
  line-height: var(--lh-sm);
}

.query-state.error {
  margin: var(--gap);
  border: 1px solid color-mix(in srgb, var(--danger) 45%, var(--border));
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--danger) 8%, var(--panel));
  color: var(--text);
  box-shadow: var(--shadow-1);
}

.query-state .title {
  color: var(--danger);
  font-size: var(--fs-md);
  line-height: var(--lh-md);
  font-weight: 600;
}

.query-state .detail {
  color: var(--muted);
  word-break: break-all;
}

.query-state .next {
  color: var(--muted);
  font-size: var(--fs-xs);
  line-height: var(--lh-xs);
}
</style>
