<script lang="ts">
/**
 * 模块级「粘贴目标」：同一页面会挂多个 DropZone（目标图 / 参考1 / 参考2），
 * Ctrl+V 只能进一个槽位。用最近点击/拖入/聚焦的那个，未操作时默认第一个。
 * 放在普通 script 里是因为它必须跨组件实例共享，而不是每个实例各有一份。
 */
import { ref } from 'vue'

const activeZoneId = ref<symbol | null>(null)
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'

import {
  isImageFile,
  uploadReferenceImages,
  type UploadFailure,
  type UploadedReference,
} from '../api/upload'

const props = withDefaults(
  defineProps<{
    label?: string
    hint?: string
    multiple?: boolean
    disabled?: boolean
    accept?: string
  }>(),
  {
    label: '拖拽 / 粘贴 / 点击添加图片',
    hint: 'PNG / JPG / WebP / HEIC，单张 ≤ 25MB',
    multiple: true,
    disabled: false,
    accept: 'image/*,.heic,.heif',
  },
)

const emit = defineEmits<{
  uploaded: [items: UploadedReference[]]
  error: [message: string]
}>()

const zoneId = Symbol('drop-zone')
const rootEl = ref<HTMLElement | null>(null)
const inputEl = ref<HTMLInputElement | null>(null)
const busy = ref(false)
const dragging = ref(false)
const localError = ref('')
let dragDepth = 0

const active = computed(() => activeZoneId.value === zoneId)

function activate() {
  if (props.disabled) return
  activeZoneId.value = zoneId
}

function failureText(failures: UploadFailure[]) {
  return failures.map((item) => `${item.name}：${item.error}`).join('；')
}

async function handleFiles(files: Array<File | Blob>) {
  if (props.disabled || busy.value) return
  const list = props.multiple ? files : files.slice(0, 1)
  if (!list.length) {
    localError.value = '没有检测到图片文件'
    return
  }

  busy.value = true
  localError.value = ''
  try {
    const { items, failures } = await uploadReferenceImages(list)
    if (items.length) emit('uploaded', items)
    if (failures.length) {
      const message = failureText(failures)
      localError.value = message
      emit('error', message)
    }
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e)
    localError.value = message
    emit('error', message)
  } finally {
    busy.value = false
  }
}

function pickFiles() {
  if (props.disabled || busy.value) return
  activate()
  inputEl.value?.click()
}

function onInputChange(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  // 清空 value：同一张图删掉后能再次选择
  input.value = ''
  void handleFiles(files)
}

function onDragEnter(event: DragEvent) {
  if (props.disabled) return
  event.preventDefault()
  dragDepth += 1
  dragging.value = true
  activate()
}

function onDragOver(event: DragEvent) {
  if (props.disabled) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
}

function onDragLeave(event: DragEvent) {
  if (props.disabled) return
  event.preventDefault()
  dragDepth = Math.max(0, dragDepth - 1)
  if (dragDepth === 0) dragging.value = false
}

function onDrop(event: DragEvent) {
  if (props.disabled) return
  event.preventDefault()
  dragDepth = 0
  dragging.value = false
  activate()

  const files = Array.from(event.dataTransfer?.files ?? []).filter(isImageFile)
  if (!files.length) {
    localError.value = '没有检测到图片文件（只接受图片）'
    return
  }
  void handleFiles(files)
}

function filesFromClipboard(event: ClipboardEvent): File[] {
  const data = event.clipboardData
  if (!data) return []
  const files: File[] = []
  for (const item of Array.from(data.items ?? [])) {
    if (item.kind !== 'file' || !item.type.startsWith('image/')) continue
    const file = item.getAsFile()
    if (file) files.push(file)
  }
  if (!files.length) {
    files.push(...Array.from(data.files ?? []).filter(isImageFile))
  }
  return files
}

function onWindowPaste(event: ClipboardEvent) {
  if (props.disabled || busy.value) return
  if (activeZoneId.value !== zoneId) return

  const files = filesFromClipboard(event)
  if (!files.length) return
  // 剪贴板里是截图/图片：拦下来交给上传，避免同时把 HTML 粘到页面别处
  event.preventDefault()
  void handleFiles(files)
}

onMounted(() => {
  if (activeZoneId.value === null) activeZoneId.value = zoneId
  window.addEventListener('paste', onWindowPaste)
})

onBeforeUnmount(() => {
  window.removeEventListener('paste', onWindowPaste)
  if (activeZoneId.value === zoneId) activeZoneId.value = null
})
</script>

<template>
  <div
    ref="rootEl"
    class="dropzone"
    :class="{ dragging, busy, active, disabled }"
    role="button"
    tabindex="0"
    :aria-disabled="disabled"
    :aria-label="label"
    @click="pickFiles"
    @keydown.enter.prevent="pickFiles"
    @keydown.space.prevent="pickFiles"
    @focus="activate"
    @pointerdown="activate"
    @dragenter="onDragEnter"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <input
      ref="inputEl"
      class="file-input"
      type="file"
      :accept="accept"
      :multiple="multiple"
      :disabled="disabled"
      @change="onInputChange"
    />
    <div class="dz-text">
      <span class="dz-title">{{ busy ? '上传中…' : label }}</span>
      <span class="dz-hint" :class="{ error: !!localError }">
        {{ localError || hint }}
      </span>
    </div>
    <span v-if="active && !busy" class="dz-paste">Ctrl+V</span>
    <button type="button" class="dz-btn" :disabled="disabled || busy" @click.stop="pickFiles">
      选择文件
    </button>
  </div>
</template>

<style scoped>
.dropzone {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap);
  border: 1px dashed var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
  color: var(--text);
  cursor: pointer;
  user-select: none;
}

.dropzone:hover,
.dropzone:focus-visible,
.dropzone.active {
  border-color: var(--primary);
}

.dropzone:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}

.dropzone.dragging {
  border-color: var(--primary);
  background: var(--panel-3);
}

.dropzone.busy {
  cursor: progress;
}

.dropzone.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.file-input {
  display: none;
}

.dz-text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.dz-title {
  font-size: var(--fs-xs);
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dz-hint {
  font-size: 10px;
  line-height: 1.4;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dz-hint.error {
  color: var(--danger);
  white-space: normal;
}

.dz-paste {
  flex: none;
  padding: 1px 5px;
  border: 1px solid var(--primary);
  border-radius: var(--radius-sm);
  color: var(--primary);
  font-size: 10px;
  font-family: ui-monospace, monospace;
}

.dz-btn {
  flex: none;
  padding: 2px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel);
  color: var(--text);
  font: inherit;
  font-size: var(--fs-xs);
  cursor: pointer;
}

.dz-btn:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}

.dz-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>