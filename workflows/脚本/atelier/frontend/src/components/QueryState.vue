<script setup lang="ts">
import { computed } from 'vue'

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

const errorText = computed(() => {
  if (props.error instanceof Error) return props.error.message
  return props.error ? String(props.error) : ''
})
</script>

<template>
  <div v-if="loading" class="query-state loading">
    <span class="spinner" />
    <span>{{ loadingText }}</span>
  </div>
  <div v-else-if="error" class="query-state error" role="alert">
    <div class="title">加载失败</div>
    <div class="detail">{{ errorText }}</div>
    <slot name="action">
      <button class="btn btn-sm" @click="emit('retry')">重试</button>
    </slot>
  </div>
  <div v-else-if="empty" class="query-state empty">
    <slot name="empty">{{ emptyText }}</slot>
  </div>
  <slot v-else />
</template>

<style scoped>
.query-state {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  padding: var(--gap-lg);
  color: var(--muted);
  font-size: var(--fs-sm);
}

.query-state.loading {
  flex-direction: row;
  align-items: center;
}

.query-state.error {
  margin: var(--gap);
  border: 1px solid color-mix(in srgb, var(--danger) 45%, var(--border));
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--danger) 8%, var(--panel));
  color: var(--text);
}

.query-state .title {
  color: var(--danger);
  font-weight: 600;
}

.query-state .detail {
  color: var(--muted);
  word-break: break-all;
}

.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--border);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
