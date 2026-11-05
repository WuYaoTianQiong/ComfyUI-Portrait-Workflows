<script setup lang="ts">
import Modal from '../../../components/Modal.vue'

/**
 * 18+ 年龄确认弹窗（参考图库共用）。
 *
 * 文案与 React `studioStore.tsx` 的 AlertDialog 逐字对齐；弹层骨架复用
 * 主站 `Modal.vue`（Esc 关闭、焦点回收、Teleport 到 body 都由它负责），
 * 这里只放内容与两个决策按钮。
 */
defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  (e: 'confirm'): void
  (e: 'cancel'): void
}>()
</script>

<template>
  <Modal :open="open" headless width="min(460px, 92vw)" @close="emit('cancel')">
    <div class="age-gate" role="document">
      <h2 class="age-gate__title">18+ 内容确认</h2>
      <p class="age-gate__text">
        关闭安全模式后，图库将显示成人向艺术参考，仅供合法的 AI 绘画学习与创作使用。
      </p>
      <p class="age-gate__text">
        须年满 18 周岁；禁止用于真人、未成年人，禁止图片再分发。
      </p>
      <div class="age-gate__actions">
        <button type="button" class="age-gate__btn" @click="emit('cancel')">保持安全模式</button>
        <button
          type="button"
          class="age-gate__btn is-primary"
          data-testid="age-gate-confirm"
          @click="emit('confirm')"
        >
          我已年满 18 周岁
        </button>
      </div>
    </div>
  </Modal>
</template>

<style scoped>
.age-gate {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 24px;
  background: var(--surface-raised);
}

.age-gate__title {
  margin: 0;
  color: var(--text-strong);
  font-size: 16px;
  font-weight: 600;
  line-height: 1.4;
}

.age-gate__text {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
  line-height: 1.65;
}

.age-gate__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}

.age-gate__btn {
  min-height: 32px;
  padding: 0 12px;
  border: 1px solid var(--border-medium);
  border-radius: 8px;
  background: transparent;
  color: var(--text-strong);
  font-size: 12px;
  font-weight: 500;
}

.age-gate__btn.is-primary {
  border-color: transparent;
  background: var(--btn-inverse-bg);
  color: var(--on-inverse);
}
</style>