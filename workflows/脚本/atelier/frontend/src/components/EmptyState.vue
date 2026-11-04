<script setup lang="ts">
/**
 * 统一空状态。
 *
 * 散落各页面的 15 处 `.empty` div，样式各写一遍、文案格式也不统一。
 * 这里收口：文字、图标、可选的操作按钮（slot 或 actionText）、以及大/小两种尺寸。
 */
withDefaults(
  defineProps<{
    text: string
    icon?: string
    hint?: string
    size?: 'sm' | 'big'
    /** 行内提示（不是整块空状态）时用，padding 收紧 */
    compact?: boolean
    /** 传了就渲染一个统一的动作按钮，点击时触发 action */
    actionText?: string
  }>(),
  { icon: '', hint: '', size: 'sm', compact: false, actionText: '' },
)

const emit = defineEmits<{ (e: 'action'): void }>()
</script>

<template>
  <div class="empty-state" :class="[size, { compact }]">
    <span v-if="icon" class="icon">{{ icon }}</span>
    <span v-if="text" class="text">{{ text }}</span>
    <span v-if="hint" class="hint">{{ hint }}</span>
    <button v-if="actionText" class="btn btn-sm action" type="button" @click="emit('action')">
      {{ actionText }}
    </button>
    <slot />
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--gap-sm);
  padding: var(--gap-lg);
  color: var(--muted);
  font-size: var(--fs-sm);
  line-height: var(--lh-sm);
  text-align: center;
}

.empty-state.compact {
  padding: var(--gap-xs);
  flex-direction: row;
}

.empty-state.big {
  padding: var(--gap-2xl) var(--gap-xl);
}

.empty-state.big .text {
  font-size: var(--fs-md);
  line-height: var(--lh-md);
}

.empty-state .icon {
  font-size: var(--fs-xl);
  line-height: var(--lh-xl);
  opacity: 0.7;
}

.empty-state .hint {
  font-size: var(--fs-xs);
  line-height: var(--lh-xs);
  opacity: 0.8;
}

.empty-state .action {
  margin-top: var(--gap-xs);
  border-radius: var(--radius-pill);
  transition:
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}

.empty-state .action:hover {
  box-shadow: var(--shadow-1);
}
</style>
