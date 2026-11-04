<script setup lang="ts">
import { computed, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import { apiGet, thumbnailUrl } from '../api/client'
import { useToast } from '../composables/useToast'
import EmptyState from './EmptyState.vue'
import JustifiedGrid from './JustifiedGrid.vue'
import { imageAspect } from '../utils/image'
import { useImageLocation } from '../composables/useImageLocation'
import type { HistoryItem, HistoryPage } from '../api/types'

/**
 * 从画廊历史里多选图片。
 *
 * 选择**顺序**是有效信息：批量换脸的「1:1 配对」就是按两个列表的选中顺序一一对应，
 * 所以这里给每个已选项标上序号，而不是只画个勾。
 */
const props = defineProps<{
  title: string
  modelValue: number[]
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: number[]): void
}>()

const search = ref('')
const { revealImage } = useImageLocation()
const toast = useToast()
const validating = ref(false)

const { data, isFetching, refetch } = useQuery<HistoryPage>({
  queryKey: computed(() => ['picker', search.value.trim()]),
  queryFn: () =>
    apiGet<HistoryPage>('/api/images', {
      page_size: 100,
      search: search.value.trim(),
      // 缺失的图不能用，直接排除
      missing: 0,
    }),
  staleTime: 30_000,
})

const items = computed<HistoryItem[]>(() => data.value?.items ?? [])

function imageKey(item: HistoryItem) {
  return item.id
}

function orderOf(id: number): number {
  const index = props.modelValue.indexOf(id)
  return index >= 0 ? index + 1 : 0
}

function toggle(id: number) {
  const next = props.modelValue.slice()
  const index = next.indexOf(id)
  if (index >= 0) next.splice(index, 1)
  else next.push(id)
  emit('update:modelValue', next)
}

function clear() {
  emit('update:modelValue', [])
}

/**
 * 清理已选里「记录已删除 / 文件缺失」的图片。
 *
 * 列表接口默认不返回软删记录，`missing` 标记文件是否还在；两者都不可用，
 * 不清理它们会变成计数里有、网格里看不到的“幽灵选择”。
 */
async function pruneMissing() {
  if (!props.modelValue.length || validating.value) return
  validating.value = true
  try {
    const page = await apiGet<HistoryPage>('/api/images', {
      ids: props.modelValue.join(','),
      // ids 精确查询不受默认分页影响：按已选数量取回，避免漏判被截断的 id
      page_size: Math.max(1, props.modelValue.length),
    })
    const valid = new Set(page.items.filter((item) => !item.missing).map((item) => item.id))
    const kept = props.modelValue.filter((id) => valid.has(id))
    const removed = props.modelValue.length - kept.length
    if (!removed) {
      toast.info('没有失效的已选图片')
      return
    }
    emit('update:modelValue', kept)
    toast.success(`已清理 ${removed} 张失效图片`)
  } catch (e) {
    toast.error(`清理失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    validating.value = false
  }
}
</script>

<template>
  <section class="picker">
    <header class="picker-head">
      <span class="title">{{ title }}</span>
      <span class="count">已选 {{ modelValue.length }}<span v-if="isFetching"> · 加载中</span></span>
      <button
        v-if="modelValue.length"
        class="btn btn-sm cleanup"
        :disabled="validating"
        title="移除已删除或文件缺失的已选图片"
        @click="pruneMissing"
      >
        {{ validating ? '校验中…' : '清理失效' }}
      </button>
      <button v-if="modelValue.length" class="btn btn-sm" @click="clear">清空</button>
    </header>

    <input v-model="search" class="search" type="search" placeholder="搜索文件名…" />

        <div class="grid">
      <JustifiedGrid
        v-if="items.length"
        :items="items"
        :ratio="imageAspect"
        :key-of="imageKey"
        :target-row-height="170"
        :gap="6"
      >
        <template #default="{ item, height }">
          <div
            class="cell"
            :class="{ picked: orderOf(item.id) > 0, fav: item.is_favorite }"
            :title="item.filename"
            role="button"
            tabindex="0"
            @click="toggle(item.id)"
            @keydown.enter.prevent="toggle(item.id)"
          >
            <span class="thumb" :style="{ height: `${height}px` }">
              <img :src="thumbnailUrl(item, 240)" :alt="item.filename" loading="lazy" />
              <span v-if="orderOf(item.id)" class="order">{{ orderOf(item.id) }}</span>
              <button class="locate" title="在资源管理器中定位" @click.stop="revealImage(item)">
                定位
              </button>
            </span>
            <span class="name">{{ item.filename }}</span>
          </div>
        </template>
      </JustifiedGrid>
      <EmptyState
        v-if="!items.length && !isFetching"
        text="没有可选图片"
        hint="画廊里还没有可用图片，或当前搜索没有结果。"
        action-text="刷新"
        @action="refetch()"
      />
    </div>
  </section>
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
  min-height: 0;
  gap: var(--gap-sm);
  padding: var(--gap);
  border-right: 1px solid var(--border);
}

.picker-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-sm);
}

.title {
  font-weight: 600;
}

.count {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.picker-head .btn {
  margin-left: auto;
}

.search {
  width: 100%;
}

.grid {
  flex: 1;
  overflow-y: auto;
}

.cell {
  display: block;
  width: 100%;
  padding: 0;
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}

.locate {
  position: absolute;
  right: 2px;
  bottom: 2px;
  padding: 0 5px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--panel) 82%, transparent);
  color: var(--text);
  font-size: var(--fs-xs);
  line-height: var(--lh-xs);
  opacity: 0;
  transition:
    opacity var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease);
}

.cell:hover .locate,
.cell:focus-within .locate {
  opacity: 1;
}

.thumb {
  position: relative;
  display: block;
  width: 100%;
  overflow: hidden;
  border-radius: var(--radius-sm);
  background: var(--panel-3);
  box-shadow: 0 0 0 1px var(--border);
  transition: box-shadow var(--dur-fast) var(--ease);
}

.thumb img {
  display: block;
  width: 100%;
  height: 100%;
  /* 比例由 JustifiedGrid 按原图算好，contain 只保证不裁画面 */
  object-fit: contain;
}

.cell:hover .thumb {
  box-shadow: 0 0 0 1px var(--border-strong);
}

.cell.picked .thumb {
  box-shadow: 0 0 0 2px var(--primary);
}

.name {
  display: block;
  padding: 2px 2px 0;
  font-size: var(--fs-xs);
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.order {
  position: absolute;
  top: 2px;
  right: 2px;
  min-width: 16px;
  height: 16px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--primary);
  color: white;
  font-size: var(--fs-xs);
  line-height: 1;
}

.empty {
  grid-column: 1 / -1;
  font-size: var(--fs-xs);
  color: var(--muted);
  padding: var(--gap);
  text-align: center;
}
</style>
