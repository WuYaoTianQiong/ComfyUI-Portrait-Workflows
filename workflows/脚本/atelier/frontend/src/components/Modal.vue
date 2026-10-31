<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'

/**
 * 统一弹层。
 *
 * 之前 MissingImageRunPanel 与 FilePicker 各写了一份 overlay + panel + head + foot，
 * 结构几乎一样、样式各写一遍。抽出来之后：
 * · 遮罩、圆角、阴影、ESC 关闭只有一处实现
 * · Teleport 到 body，避免被父容器的 overflow / transform 裁掉
 */
const props = withDefaults(
  defineProps<{
    open: boolean
    title?: string
    /** 面板宽度；高度由内容自适应（body 内部自行滚动） */
    width?: string
    /** 固定高度（图片网格这类需要大片区域的面板用） */
    height?: string
    /** 不要顶部标题栏（由内容自己在右侧放标题/关闭时用） */
    headless?: boolean
  }>(),
  { title: '', width: 'min(760px, 92vw)', height: '', headless: false },
)

const emit = defineEmits<{ (e: 'close'): void }>()

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape' && props.open) {
    // 标记已处理：叠在弹层下面的查看器（如 Lightbox）不应再被同一次 Esc 关掉
    event.preventDefault()
    emit('close')
  }
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-overlay" @click.self="emit('close')">
      <div class="modal-panel" :style="{ width, height }">
        <header v-if="!headless" class="modal-head">
          <span v-if="title" class="title">{{ title }}</span>
          <slot name="head" />
          <span class="spacer" />
          <slot name="actions" />
          <button class="btn btn-sm" title="关闭（Esc）" @click="emit('close')">关闭</button>
        </header>
        <div class="modal-body">
          <slot />
        </div>
        <footer v-if="$slots.footer" class="modal-foot">
          <slot name="footer" />
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 150;
  background: rgba(0, 0, 0, 0.55);
  display: grid;
  place-items: center;
}

.modal-panel {
  max-height: 88vh;
  display: flex;
  flex-direction: column;
  background: var(--panel);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}

.modal-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap) var(--gap-lg);
  border-bottom: 1px solid var(--border);
}

.title {
  font-weight: 600;
}

.spacer {
  flex: 1;
}

.modal-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.modal-foot {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap-lg);
  border-top: 1px solid var(--border);
}
</style>
