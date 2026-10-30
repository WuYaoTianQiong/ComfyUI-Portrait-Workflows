<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import { apiGet } from '../api/client'
import Modal from './Modal.vue'

/**
 * 磁盘选图：在任意文件夹里挑图，交给换脸这类需要"主图 / 参考图"的场景。
 *
 * 素材来源有两条路：画廊（已出图）与磁盘任意目录（还没进 ComfyUI 的原图）。
 * 磁盘这条只能靠文件系统浏览 —— 后端 `/api/fs/list` 直接列目录内容，
 * 不做目录树递归（深目录会卡），改成"逐级进入"的平铺导航。
 */
const props = defineProps<{
  open: boolean
  title: string
  modelValue: string[]
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
  (e: 'close'): void
}>()

interface FsEntry {
  name: string
  path: string
  size?: number
  mtime?: number
}

interface FsListing {
  path: string
  parent: string
  roots: Array<{ name: string; path: string }>
  dirs: FsEntry[]
  images: FsEntry[]
  truncated: boolean
}

const dir = ref('')

const { data, isFetching } = useQuery<FsListing>({
  queryKey: computed(() => ['fs-list', dir.value]),
  queryFn: () => apiGet('/api/fs/list', { path: dir.value }),
  enabled: computed(() => props.open),
})


/**
 * 打开时自动进入第一个快速入口（ComfyUI/output）。
 *
 * 后端 path 为空时返回的是盘符列表 —— 停在根目录的话用户要先点一次盘符才能看到图，
 * 而换脸最常用的素材就在 ComfyUI/output 里。
 */
watch(
  () => data.value,
  (value) => {
    if (value && !dir.value && value.roots?.length) {
      dir.value = value.roots[0].path
    }
  },
  { immediate: true },
)
const picked = ref<string[]>([...props.modelValue])

/** 双击看原图：缩略图看不清细节（换脸要确认脸和姿势）。 */
const previewPath = ref('')

watch(
  () => props.open,
  (open) => {
    if (open) picked.value = [...props.modelValue]
  },
)

function enter(path: string) {
  dir.value = path
}

function goUp() {
  if (data.value?.parent) dir.value = data.value.parent
}

function toggle(path: string) {
  const next = new Set(picked.value)
  if (next.has(path)) next.delete(path)
  else next.add(path)
  picked.value = Array.from(next)
}

function confirm() {
  emit('update:modelValue', picked.value)
  emit('close')
}

function imageUrl(path: string): string {
  return `/api/fs/image?path=` + encodeURIComponent(path)
}

function thumbUrl(path: string): string {
  return `/api/fs/thumb?path=${encodeURIComponent(path)}&size=240`
}
</script>
<template>
  <Modal
    :open="open"
    :title="title"
    width="min(900px, 94vw)"
    height="min(680px, 88vh)"
    @close="emit('close')"
  >
    <template #head>
        <span class="count">已选 {{ picked.length }} 张</span>
    </template>
    <template #actions>
      <button class="btn btn-sm primary" @click="confirm">确定</button>
    </template>

      <div class="nav">
        <button class="btn btn-sm" :disabled="!data?.parent" title="上一级" @click="goUp">⬆ 上级</button>
        <select class="jump" @change="enter(($event.target as HTMLSelectElement).value)">
          <option value="">快速跳转…</option>
          <option v-for="r in data?.roots ?? []" :key="r.path" :value="r.path">
            {{ r.name }}
          </option>
        </select>
        <span class="cur-path" :title="data?.path">{{ data?.path || '（未选择目录）' }}</span>
        <span v-if="isFetching" class="muted">加载中…</span>
      </div>

      <div class="body">
        <div class="dirs">
          <button
            v-for="d in data?.dirs ?? []"
            :key="d.path"
            class="dir"
            :title="d.path"
            @click="enter(d.path)"
          >
            📁 {{ d.name }}
          </button>
          <div v-if="!(data?.dirs ?? []).length" class="muted small">没有子目录</div>
        </div>

        <div class="grid">
          <button
            v-for="img in data?.images ?? []"
            :key="img.path"
            class="cell"
            :class="{ on: picked.includes(img.path) }"
            :title="img.name"
            @click="toggle(img.path)"
            @dblclick="previewPath = img.path"
          >
            <img :src="thumbUrl(img.path)" :alt="img.name" loading="lazy" />
            <span class="name">{{ img.name }}</span>
          </button>
          <div v-if="!(data?.images ?? []).length && !isFetching" class="muted small">
            这个目录里没有图片
          </div>
        </div>
      </div>

    <template #footer>
        <span class="hint">
          选中的图片会按绝对路径提交，ComfyUI 会把它们拷进 input 目录。
        </span>
    </template>
  </Modal>

    <Modal
      :open="!!previewPath"
      title="预览"
      width="min(880px, 94vw)"
      @close="previewPath = ''"
    >
      <div class="preview-wrap">
        <img :src="imageUrl(previewPath)" alt="预览" />
      </div>
    </Modal>
</template>

<style scoped>




.count {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.spacer {
  flex: 1;
}

.nav {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap-lg);
  border-bottom: 1px solid var(--border);
}

.jump {
  width: 190px;
}

.cur-path {
  flex: 1;
  font-size: var(--fs-xs);
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.body {
  flex: 1;
  min-height: 0;
  display: flex;
}

.dirs {
  width: 210px;
  flex: none;
  border-right: 1px solid var(--border);
  overflow-y: auto;
  padding: var(--gap-sm);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.dir {
  border: none;
  background: transparent;
  text-align: left;
  padding: 3px 6px;
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dir:hover {
  background: var(--panel-2);
}

.grid {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: var(--gap-sm);
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: 6px;
  align-content: start;
}

.cell {
  position: relative;
  border: 2px solid transparent;
  border-radius: var(--radius-sm);
  background: var(--panel-2);
  padding: 0;
  overflow: hidden;
}

.cell img {
  display: block;
  width: 100%;
  aspect-ratio: 1;
  object-fit: contain;
  background: var(--panel-3);
}

.cell.on {
  border-color: var(--primary);
}

.cell .name {
  display: block;
  font-size: 10px;
  padding: 2px 4px;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}


.hint {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.preview-wrap {
  padding: var(--gap);
  display: grid;
  place-items: center;
}

.preview-wrap img {
  max-width: 100%;
  max-height: 74vh;
  object-fit: contain;
}

.muted {
  color: var(--muted);
}

.small {
  font-size: var(--fs-xs);
  padding: var(--gap-sm);
}
</style>
