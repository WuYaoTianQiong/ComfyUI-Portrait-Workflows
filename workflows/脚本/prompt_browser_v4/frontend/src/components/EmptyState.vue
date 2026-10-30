<script setup lang="ts">
/**
 * 统一空状态。
 *
 * 散落各页面的 15 处 `.empty` div，样式各写一遍、文案格式也不统一。
 * 这里收口：文字、图标、可选的操作按钮（slot）、以及大/小两种尺寸。
 */
withDefaults(
  defineProps<{
    text: string
    icon?: string
    hint?: string
    size?: 'sm' | 'big'
    /** 行内提示（不是整块空状态）时用，padding 收紧 */
    compact?: boolean
  }>(),
  { icon: '', hint: '', size: 'sm', compact: false },
)
</script>

<template>
  <div class="empty-state" :class="[size, { compact }]">
    <span v-if="icon" class="icon">{{ icon }}</span>
    <span class="text">{{ text }}</span>
    <span v-if="hint" class="hint">{{ hint }}</span>
    <slot />
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--gap-xs);
  padding: var(--gap-lg);
  color: var(--muted);
  font-size: var(--fs-sm);
  text-align: center;
}

.empty-state.compact {
  padding: 2px;
  flex-direction: row;
}

.empty-state.big {
  padding: 60px var(--gap-lg);
}

.empty-state .icon {
  font-size: 22px;
  opacity: 0.7;
}

.empty-state .hint {
  font-size: var(--fs-xs);
  opacity: 0.8;
}
</style>
