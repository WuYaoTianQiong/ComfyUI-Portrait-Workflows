<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import { apiGet, apiPost } from '../api/client'
import { useSettings } from '../composables/useSettings'
import { useToast } from '../composables/useToast'
import OutputFolderPicker from './OutputFolderPicker.vue'

/**
 * 出图归档位置（全局设置）。
 *
 * 留空 = 沿用旧的 output 根目录平铺；填了才在 ComfyUI output 下建相对子目录。
 * 变量由后端展开，前端只负责收集模板，避免把路径校验复制一份。
 */
const { outputSubfolder } = useSettings()
const toast = useToast()
const open = ref(false)
const root = ref<HTMLElement | null>(null)
const opening = ref(false)
const pickerOpen = ref(false)

const { data: sysConfig } = useQuery<{ output_dir: string }>({
  queryKey: ['system-config'],
  queryFn: () => apiGet('/api/system/config'),
  staleTime: 60_000,
})

function onFolderPicked(path: string) {
  outputSubfolder.value = path
  pickerOpen.value = false
}

const presets = [
  { label: '按日期', value: '{date}' },
  { label: '日期/工作流', value: '{date}/{workflow}' },
  { label: '按月/工作流', value: '{month}/{workflow}' },
]

function onDocClick(event: MouseEvent) {
  if (open.value && root.value && !root.value.contains(event.target as Node)) {
    open.value = false
  }
}

onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))

async function openOutputDir() {
  opening.value = true
  try {
    const result = await apiPost<{ success: boolean; path?: string; message?: string }>(
      '/api/system/open-output',
    )
    if (result.success) toast.success(`已打开：${result.path}`)
    else toast.info(result.message || '无法打开出图目录')
  } catch (e) {
    const reason = e instanceof Error ? e.message : String(e)
    toast.error(`现象：无法打开出图目录。原因：${reason}。下一步：确认 ComfyUI output 目录存在后重试。`)
  } finally {
    opening.value = false
  }
}
</script>

<template>
  <div ref="root" class="output-location">
    <button
      class="btn btn-sm trigger"
      :class="{ on: !!outputSubfolder }"
      :title="outputSubfolder ? `出图到 output/${outputSubfolder}` : '出图到 output 根目录'"
      aria-haspopup="dialog"
      :aria-expanded="open"
      @click="open = !open"
    >
      出图：<span class="value">{{ outputSubfolder || '根目录' }}</span>
    </button>

    <div v-if="open" class="popover" role="dialog" aria-label="出图归档位置">
      <div class="root-line">
        <span>根目录</span>
        <code :title="sysConfig?.output_dir">{{ sysConfig?.output_dir ?? '读取中…' }}</code>
      </div>
      <p class="root-hint">根目录由 ComfyUI 决定；这里选的是它下面的相对子目录。</p>
      <label class="field">
        <span>output 下的相对子目录</span>
        <div class="input-row">
          <input
            v-model="outputSubfolder"
            spellcheck="false"
            placeholder="留空=根目录，如 {date}/{workflow}"
          />
          <button class="btn btn-xs" @click="pickerOpen = true">浏览…</button>
        </div>
      </label>
      <div class="presets">
        <button
          v-for="preset in presets"
          :key="preset.value"
          class="btn btn-xs"
          @click="outputSubfolder = preset.value"
        >
          {{ preset.label }}
        </button>
        <button class="btn btn-xs" @click="outputSubfolder = ''">清空</button>
      </div>
      <p class="hint">
        可用变量：{date} {month} {year} {workflow} {job_id} {quality} {orientation}
      </p>
      <div class="foot">
        <button class="btn btn-sm" :disabled="opening" @click="openOutputDir">
          {{ opening ? '打开中…' : '打开出图目录' }}
        </button>
        <button class="btn btn-sm primary" @click="open = false">完成</button>
      </div>
    </div>

    <OutputFolderPicker
      :open="pickerOpen"
      :model-value="outputSubfolder"
      @close="pickerOpen = false"
      @update:model-value="onFolderPicked"
    />
  </div>
</template>

<style scoped>
.btn {
  transition:
    color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}

.output-location {
  position: relative;
  display: inline-flex;
  flex: 0 1 auto;
  min-width: 0;
}

.trigger {
  max-width: 220px;
  min-width: 0;
}

.trigger .value {
  max-width: 130px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trigger.on {
  border-color: var(--primary);
  color: var(--accent-link);
}

.popover {
  position: absolute;
  top: calc(100% + var(--gap-sm));
  right: 0;
  z-index: 1200;
  width: min(360px, 86vw);
  padding: var(--gap);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel);
  box-shadow: var(--shadow-3);
}

.field {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.root-line {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-sm);
  min-width: 0;
}

.root-line span {
  color: var(--muted);
  flex: none;
}

.root-line code {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text);
  background: var(--panel-2);
  border-radius: var(--radius-sm);
  padding: 2px 6px;
}

.root-hint {
  margin: var(--gap-sm) 0 0;
  color: var(--muted);
  font-size: var(--fs-sm);
  line-height: var(--lh-sm);
}

.input-row {
  display: flex;
  gap: var(--gap-sm);
  min-width: 0;
}

.input-row input {
  flex: 1;
  min-width: 0;
}

.field span {
  color: var(--muted);
  font-size: var(--fs-sm);
}

.field input {
  font: inherit;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-sm);
}

.presets {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-sm);
  margin-top: var(--gap-sm);
}

.hint {
  margin: var(--gap-sm) 0;
  color: var(--muted);
  font-size: var(--fs-sm);
  line-height: var(--lh-sm);
}

.foot {
  display: flex;
  justify-content: flex-end;
  gap: var(--gap-sm);
}
</style>
