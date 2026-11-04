<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    width?: string
    height?: string
    radius?: string
    count?: number
    variant?: 'line' | 'block'
  }>(),
  { width: '100%', count: 1, variant: 'line' },
)

const barStyle = computed(() => ({
  width: props.width,
  height: props.height ?? (props.variant === 'block' ? '120px' : '12px'),
  borderRadius:
    props.radius ?? (props.variant === 'block' ? 'var(--radius)' : 'var(--radius-sm)'),
}))
</script>

<template>
  <div class="skeleton" :class="variant" aria-hidden="true">
    <span v-for="n in count" :key="n" class="skeleton-bar" :style="barStyle" />
  </div>
</template>

<style scoped>
.skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  width: 100%;
}

.skeleton.block {
  gap: var(--gap-sm);
}

.skeleton-bar {
  display: block;
  flex: 0 0 auto;
  background: linear-gradient(90deg, var(--panel-2), var(--panel-3), var(--panel-2));
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.4s var(--ease) infinite;
}

@keyframes skeleton-shimmer {
  from {
    background-position: 200% 0;
  }
  to {
    background-position: -200% 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .skeleton-bar {
    animation: none;
  }
}
</style>
