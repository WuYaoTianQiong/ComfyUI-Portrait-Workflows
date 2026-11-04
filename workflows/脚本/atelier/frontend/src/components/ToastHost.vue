<script setup lang="ts">
import { useToast } from '../composables/useToast'

const { toasts } = useToast()
</script>

<template>
  <div class="toast-host">
    <div v-for="t in toasts" :key="t.id" class="toast" :class="t.kind">{{ t.text }}</div>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: var(--z-toast);
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  pointer-events: none;
}

.toast {
  max-width: 380px;
  padding: var(--gap-sm) var(--gap);
  border-radius: var(--radius);
  border: 1px solid var(--border-strong);
  background: var(--panel-3);
  color: var(--text);
  font-size: var(--fs-sm);
  box-shadow: var(--shadow);
  animation: toast-in 0.16s ease-out;
}

.toast.success {
  border-color: var(--success);
}

.toast.error {
  border-color: var(--danger);
  color: var(--danger-text);
}

@keyframes toast-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
</style>
