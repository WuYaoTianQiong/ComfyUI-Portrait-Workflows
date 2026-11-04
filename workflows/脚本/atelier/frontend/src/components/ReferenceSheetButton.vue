<script setup lang="ts">
import { computed, ref } from 'vue'

import {
  downloadReferenceSheet,
  SHEET_FILENAME,
  SHEET_HEIGHT,
  SHEET_WIDTH,
} from '../api/sheet'
import { useToast } from '../composables/useToast'

/**
 * 「生成参考板」按钮（M5）。
 *
 * 只负责导出与下载：选中的 3–4 张参考图由父组件通过 props 传入。
 * 目前唯一入口是 `EditorView.vue`（旧参考库页 `ReferenceView.vue`
 * 已于 2026-11-04 验收收尾删除，参考图库改由 `/ref-web` 托管）。
 */
const props = withDefaults(
  defineProps<{
    pose?: string | null
    costume?: string | null
    portrait?: string | null
    extra?: string | null
    /** false = 纯图拼接（可喂给拼图工作流） */
    labels?: boolean
    disabled?: boolean
    label?: string
    filename?: string
  }>(),
  {
    pose: null,
    costume: null,
    portrait: null,
    extra: null,
    labels: true,
    disabled: false,
    label: '生成参考板',
    filename: SHEET_FILENAME,
  },
)

const emit = defineEmits<{
  error: [message: string]
}>()

const toast = useToast()
const busy = ref(false)

const hasAny = computed(() => !!(props.pose || props.costume || props.portrait || props.extra))
const hint = computed(() =>
  hasAny.value ? `导出 ${SHEET_WIDTH}×${SHEET_HEIGHT} PNG` : '先选择参考图',
)

async function generate() {
  if (busy.value || props.disabled || !hasAny.value) return
  busy.value = true
  try {
    await downloadReferenceSheet(
      {
        pose: props.pose,
        costume: props.costume,
        portrait: props.portrait,
        extra: props.extra,
        labels: props.labels,
      },
      props.filename,
    )
    toast.success('参考板已下载')
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e)
    toast.error(message)
    emit('error', message)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <button
    type="button"
    class="btn btn-sm sheet-btn"
    :class="{ loading: busy }"
    :disabled="disabled || !hasAny || busy"
    :title="hint"
    @click="generate"
  >
    {{ busy ? '生成中…' : label }}
  </button>
</template>

<style scoped>
.sheet-btn {
  white-space: nowrap;
}
</style>