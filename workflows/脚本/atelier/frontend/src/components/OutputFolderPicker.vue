<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  NButton,
  NConfigProvider,
  NEmpty,
  NInput,
  NModal,
  NScrollbar,
  NSpin,
  darkTheme,
} from 'naive-ui'

import { apiGet, apiPost } from '../api/client'
import { useToast } from '../composables/useToast'

interface OutputFolder {
  name: string
  path: string
}

interface OutputFolderListing {
  root: string
  path: string
  parent: string
  dirs: OutputFolder[]
}

const props = defineProps<{
  open: boolean
  modelValue: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'update:modelValue', value: string): void
}>()

const toast = useToast()
const queryClient = useQueryClient()
const current = ref(props.modelValue)
const newName = ref('')
const creating = ref(false)

const themeOverrides = {
  common: {
    primaryColor: 'rgb(99 102 241)',
    primaryColorHover: 'rgb(124 127 245)',
    primaryColorPressed: 'rgb(85 88 230)',
    borderRadius: 'var(--radius-sm)',
  },
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      current.value = props.modelValue
      newName.value = ''
    }
  },
)

const { data, isFetching, refetch } = useQuery<OutputFolderListing>({
  queryKey: computed(() => ['output-folders', current.value]),
  queryFn: () => apiGet('/api/system/output-folders', { path: current.value }),
  enabled: computed(() => props.open),
})

const label = computed(() => `output/${current.value}`.replace(/\/$/, ''))

function enter(dir: OutputFolder) {
  current.value = dir.path
}

function goUp() {
  if (data.value) current.value = data.value.parent
}

function choose() {
  emit('update:modelValue', current.value)
  emit('close')
}

async function createFolder() {
  const name = newName.value.trim()
  if (!name) return
  creating.value = true
  try {
    const result = await apiPost<{ success: boolean; path: string }>(
      '/api/system/output-folders',
      { parent: current.value, name },
    )
    current.value = result.path
    newName.value = ''
    await refetch()
    await queryClient.invalidateQueries({ queryKey: ['output-folders'] })
    toast.success(`已创建：${result.path}`)
  } catch (e) {
    const reason = e instanceof Error ? e.message : String(e)
    toast.error(`现象：新建出图子目录失败。原因：${reason}。下一步：换一个名称或确认目录权限后重试。`)
  } finally {
    creating.value = false
  }
}
</script>

<template>
  <n-config-provider :theme="darkTheme" :theme-overrides="themeOverrides">
    <n-modal
      :show="open"
      preset="card"
      title="选择出图子目录"
      :style="{ width: 'min(560px, 94vw)' }"
      :mask-closable="true"
      @update:show="(value: boolean) => { if (!value) emit('close') }"
    >
      <div class="picker">
        <div class="root">
          <span class="muted">根目录</span>
          <code>{{ data?.root ?? '…' }}</code>
        </div>

        <div class="nav">
          <n-button size="small" :disabled="!data?.parent" @click="goUp">上级</n-button>
          <n-button size="small" :disabled="!current" @click="current = ''">根目录</n-button>
          <span class="cur" :title="label">{{ label }}</span>
          <n-spin v-if="isFetching" size="small" />
        </div>

        <n-scrollbar class="list" style="max-height: 280px">
          <button
            v-for="dir in data?.dirs ?? []"
            :key="dir.path"
            class="row"
            @click="enter(dir)"
          >
            <span class="icon">▸</span>
            <span class="name">{{ dir.name }}</span>
          </button>
          <n-empty
            v-if="data && !data.dirs.length"
            description="这个目录下还没有子目录"
            style="padding: 28px 0"
          />
        </n-scrollbar>

        <div class="new-row">
          <n-input
            v-model:value="newName"
            size="small"
            placeholder="在当前目录下新建文件夹…"
            @keydown.enter.prevent="createFolder"
          />
          <n-button size="small" :loading="creating" :disabled="!newName.trim()" @click="createFolder">
            新建
          </n-button>
        </div>

        <p class="hint">
          这里只能选择 ComfyUI output 内的目录。出图根目录由 ComfyUI 的 output 决定；
          需要换盘/换根时请用 <code>ATELIER_COMFYUI_OUTPUT_DIR</code> 并让 ComfyUI 使用同一目录。
        </p>
      </div>

      <template #footer>
        <div class="foot">
          <n-button size="small" @click="emit('close')">取消</n-button>
          <n-button size="small" type="primary" @click="choose">使用 {{ label }}</n-button>
        </div>
      </template>
    </n-modal>
  </n-config-provider>
</template>

<style scoped>
.btn {
  transition:
    color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}

.picker {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}

.root {
  display: flex;
  gap: var(--gap-sm);
  align-items: center;
  font-size: var(--fs-sm);
  min-width: 0;
}

.muted {
  color: var(--muted);
  flex: none;
}

.root code,
.hint code {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text);
  background: var(--panel-2);
  border-radius: var(--radius-sm);
  padding: 1px 5px;
}

.nav {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  min-width: 0;
}

.nav .cur {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
  font-size: var(--fs-sm);
}

.list {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
}

.row {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  width: 100%;
  padding: var(--gap-sm) var(--gap);
  border: 0;
  border-bottom: 1px solid var(--border);
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease);
}

.row:hover {
  background: var(--panel-3);
}

.icon {
  color: var(--primary);
}

.new-row {
  display: flex;
  gap: var(--gap-sm);
}

.hint {
  margin: 0;
  color: var(--muted);
  font-size: var(--fs-xs);
  line-height: var(--lh-md);
}

.foot {
  display: flex;
  justify-content: flex-end;
  gap: var(--gap-sm);
}
</style>
