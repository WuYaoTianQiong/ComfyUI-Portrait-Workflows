<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import { apiGet, apiPost } from '../api/client'
import { useToast } from '../composables/useToast'
import Modal from './Modal.vue'
import JustifiedGrid from './JustifiedGrid.vue'
import DiskPathList from './DiskPathList.vue'

/**
 * 磁盘选图：在任意文件夹里挑图，交给换脸这类需要"主图 / 参考图"的场景。
 *
 * 素材来源有两条路：画廊（已出图）与磁盘任意目录（还没进 ComfyUI 的原图）。
 * 磁盘这条只能靠文件系统浏览 —— 后端 `/api/browser/list` 直接列目录内容，
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
const toast = useToast()

async function openCurrentDir() {
  const path = data.value?.path
  if (!path) return
  try {
    const result = await apiPost<{ success: boolean; message?: string }>(
      '/api/system/open-folder',
      { path },
    )
    if (!result.success) toast.info(result.message || '无法打开目录')
  } catch (e) {
    toast.error(`打开目录失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

const { data, isFetching } = useQuery<FsListing>({
  queryKey: computed(() => ['fs-list', dir.value]),
  queryFn: () => apiGet('/api/browser/list', { path: dir.value }),
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

/** 筛选/排序只作用于本地已返回的列表，输入时不额外打后端。 */
const query = ref('')
const sortMode = ref<'name' | 'mtime_desc' | 'mtime_asc'>('name')
const typeFilter = ref('')

const currentImages = computed(() => data.value?.images ?? [])

const typeOptions = computed(() => {
  const types = new Set<string>()
  for (const img of currentImages.value) {
    const dot = img.name.lastIndexOf('.')
    if (dot > 0) types.add(img.name.slice(dot).toLowerCase())
  }
  return Array.from(types).sort()
})

const filteredImages = computed(() => {
  let list = currentImages.value
  const keyword = query.value.trim().toLowerCase()
  if (keyword) list = list.filter((img) => img.name.toLowerCase().includes(keyword))
  if (typeFilter.value) {
    list = list.filter((img) => img.name.toLowerCase().endsWith(typeFilter.value))
  }
  if (sortMode.value === 'mtime_desc') {
    list = [...list].sort((a, b) => (b.mtime ?? 0) - (a.mtime ?? 0))
  } else if (sortMode.value === 'mtime_asc') {
    list = [...list].sort((a, b) => (a.mtime ?? 0) - (b.mtime ?? 0))
  }
  return list
})

/** 全选只选「当前筛选后」的图片；跨目录已选不会丢。 */
function selectAll() {
  const next = new Set(picked.value)
  for (const img of filteredImages.value) next.add(img.path)
  picked.value = Array.from(next)
}

function invert() {
  const next = new Set(picked.value)
  for (const img of filteredImages.value) {
    if (next.has(img.path)) next.delete(img.path)
    else next.add(img.path)
  }
  picked.value = Array.from(next)
}

function clearAll() {
  picked.value = []
}

function enter(path: string) {
  dir.value = path
  query.value = ''
  typeFilter.value = ''
}

function goUp() {
  if (!data.value?.parent) return
  dir.value = data.value.parent
  query.value = ''
  typeFilter.value = ''
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
  return `/api/browser/image?path=` + encodeURIComponent(path)
}

function thumbUrl(path: string): string {
  return `/api/browser/thumb?path=${encodeURIComponent(path)}&size=240`
}
/** 磁盘文件没有宽高，图片 onload 后记下真实比例，再重排一次。 */
const ratios = ref<Record<string, number>>({})

function fsRatio(img: FsEntry) {
  return ratios.value[img.path] ?? 3 / 4
}

function fsKey(img: FsEntry) {
  return img.path
}

function rememberRatio(img: FsEntry, event: Event) {
  const el = event.target as HTMLImageElement
  if (el.naturalWidth && el.naturalHeight) {
    ratios.value[img.path] = el.naturalWidth / el.naturalHeight
  }
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
        <button class="btn btn-sm" :disabled="!data?.path" title="在资源管理器中打开当前目录" @click="openCurrentDir">
          打开目录
        </button>
        <span v-if="isFetching" class="muted">加载中…</span>
      </div>

      <div class="filters">
        <input v-model="query" class="search" type="search" placeholder="按文件名搜索…" />
        <select v-model="sortMode" class="sort" title="排序方式">
          <option value="name">按名称</option>
          <option value="mtime_desc">时间 新→旧</option>
          <option value="mtime_asc">时间 旧→新</option>
        </select>
        <select v-if="typeOptions.length > 1" v-model="typeFilter" class="type" title="按格式筛选">
          <option value="">全部格式</option>
          <option v-for="t in typeOptions" :key="t" :value="t">{{ t }}</option>
        </select>
        <span class="muted small">本目录 {{ filteredImages.length }} / {{ currentImages.length }} 张</span>
        <span v-if="data?.truncated" class="warn small" title="后端单目录上限 800 张">
          超过 800 张，仅显示前 800
        </span>
        <span class="spacer" />
        <button class="btn btn-sm" :disabled="!filteredImages.length" @click="selectAll">
          全选（{{ filteredImages.length }}）
        </button>
        <button class="btn btn-sm" :disabled="!filteredImages.length" @click="invert">反选</button>
        <button class="btn btn-sm" :disabled="!picked.length" @click="clearAll">清空已选</button>
      </div>

      <div v-if="picked.length" class="picked-bar">
        <span class="picked-title">已选清单</span>
        <DiskPathList v-model="picked" />
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
          <JustifiedGrid
            v-if="filteredImages.length"
            :items="filteredImages"
            :ratio="fsRatio"
            :key-of="fsKey"
            :target-row-height="150"
            :gap="6"
          >
            <template #default="{ item, height }">
              <button
                class="cell"
                :class="{ on: picked.includes(item.path) }"
                :title="item.name"
                @click="toggle(item.path)"
                @dblclick="previewPath = item.path"
              >
                <span class="thumb" :style="{ height: `${height}px` }">
                  <img
                    :src="thumbUrl(item.path)"
                    :alt="item.name"
                    loading="lazy"
                    @load="rememberRatio(item, $event)"
                  />
                </span>
                <span class="name">{{ item.name }}</span>
              </button>
            </template>
          </JustifiedGrid>
          <div v-if="!filteredImages.length && !isFetching" class="muted small">
            {{ currentImages.length ? '没有匹配的图片' : '这个目录里没有图片' }}
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

.filters {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap-lg);
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}

.filters .search {
  width: 180px;
}

.filters .sort {
  width: 130px;
}

.filters .type {
  width: 100px;
}

/* 筛选行里的辅助文案不沿用 .small 的块级内边距 */
.filters .small {
  padding: 0;
  white-space: nowrap;
}

.filters .warn {
  color: var(--warn);
}

/* 跨目录选中的图集中在这里，避免切目录后“已选 N 张”但找不到是哪几张 */
.picked-bar {
  display: flex;
  align-items: flex-start;
  gap: var(--gap-sm);
  max-height: 110px;
  padding: var(--gap-sm) var(--gap-lg);
  border-bottom: 1px solid var(--border);
}

.picked-title {
  flex: none;
  padding-top: 3px;
  color: var(--muted);
  font-size: var(--fs-xs);
}

.picked-bar :deep(.path-list) {
  max-height: 82px;
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
}

.cell {
  display: block;
  width: 100%;
  padding: 0;
  border: none;
  background: transparent;
  text-align: left;
}

.thumb {
  display: block;
  width: 100%;
  overflow: hidden;
  border-radius: var(--radius-sm);
  background: var(--panel-3);
  box-shadow: 0 0 0 1px var(--border);
}

.thumb img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.cell:hover .thumb {
  box-shadow: 0 0 0 1px var(--border-strong);
}

.cell.on .thumb {
  box-shadow: 0 0 0 2px var(--primary);
}

.cell .name {
  display: block;
  font-size: 10px;
  padding: 2px 2px 0;
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
