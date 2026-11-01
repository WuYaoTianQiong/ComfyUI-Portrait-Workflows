<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { useEscapeLayer } from '../composables/useEscapeLayer'

/**
 * 统一弹层。
 *
 * 之前 MissingImageRunPanel 与 FilePicker 各写了一份 overlay + panel + head + foot，
 * 结构几乎一样、样式各写一遍。抽出来之后：
 * · 遮罩、圆角、阴影、ESC 关闭只有一处实现
 * · Teleport 到 body，避免被父容器的 overflow / transform 裁掉
 *
 * Esc 走全局弹层栈：嵌套弹窗只有最上面那层响应，关闭后焦点回到打开前的元素。
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
    /**
     * 抬一层：只有「开在灯箱里面的弹窗」需要（如查看器里的临时提示词）。
     * 灯箱本身已经高于普通弹窗，不再抬就会被灯箱盖住。
     */
    raised?: boolean
  }>(),
  { title: '', width: 'min(760px, 92vw)', height: '', headless: false, raised: false },
)

const emit = defineEmits<{ (e: 'close'): void }>()

const panelRef = ref<HTMLElement | null>(null)
let previousFocus: HTMLElement | null = null

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

useEscapeLayer(() => props.open, () => emit('close'))

watch(
  () => props.open,
  async (open) => {
    if (open) {
      previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
      await nextTick()
      const root = panelRef.value
      const first = root?.querySelector<HTMLElement>(FOCUSABLE)
      ;(first ?? root)?.focus()
    } else {
      previousFocus?.focus?.()
      previousFocus = null
    }
  },
)

function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'Tab' || !props.open) return
  const root = panelRef.value
  if (!root) return
  const focusables = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE))
  if (!focusables.length) return
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

onBeforeUnmount(() => {
  previousFocus?.focus?.()
  previousFocus = null
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="modal-overlay"
      :class="{ raised }"
      @click.self="emit('close')"
      @keydown="onKeydown"
    >
      <div
        ref="panelRef"
        class="modal-panel"
        role="dialog"
        aria-modal="true"
        :aria-label="title || '对话框'"
        tabindex="-1"
        :style="{ width, height }"
      >
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
  z-index: var(--z-modal);
  background: rgba(0, 0, 0, 0.55);
  display: grid;
  place-items: center;
}

/* 开在灯箱里面的弹窗：必须比灯箱高，否则被查看器整块盖住 */
.modal-overlay.raised {
  z-index: var(--z-modal-raised);
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
