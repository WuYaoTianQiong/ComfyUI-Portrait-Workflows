<script setup lang="ts">
import { computed, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import { apiGet, thumbnailUrl } from '../api/client'
import EmptyState from './EmptyState.vue'
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

const { data, isFetching } = useQuery<HistoryPage>({
  queryKey: computed(() => ['picker', search.value.trim()]),
  queryFn: () =>
    apiGet<HistoryPage>('/api/history', {
      page_size: 100,
      search: search.value.trim(),
      // 缺失的图不能用，直接排除
      missing: 0,
    }),
  staleTime: 30_000,
})

const items = computed<HistoryItem[]>(() => data.value?.items ?? [])

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
</script>

<template>
  <section class="picker">
    <header class="picker-head">
      <span class="title">{{ title }}</span>
      <span class="count">已选 {{ modelValue.length }}<span v-if="isFetching"> · 加载中</span></span>
      <button v-if="modelValue.length" class="btn btn-sm" @click="clear">清空</button>
    </header>

    <input v-model="search" class="search" type="search" placeholder="搜索文件名…" />

    <div class="grid">
      <button
        v-for="item in items"
        :key="item.id"
        class="cell"
        :class="{ picked: orderOf(item.id) > 0, fav: item.favorite }"
        :title="item.filename"
        @click="toggle(item.id)"
      >
        <img :src="thumbnailUrl(item, 240)" :alt="item.filename" loading="lazy" />
        <span v-if="orderOf(item.id)" class="order">{{ orderOf(item.id) }}</span>
      </button>
      <EmptyState v-if="!items.length && !isFetching" text="没有可选图片" />
    </div>
  </section>
</template>

<style scoped>
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
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: 6px;
  align-content: start;
}

.cell {
  position: relative;
  padding: 0;
  border: 2px solid transparent;
  border-radius: var(--radius-sm);
  background: var(--panel-2);
  overflow: hidden;
  transition: 0.12s;
}

.cell img {
  display: block;
  width: 100%;
  aspect-ratio: 1;
  /* contain：选素材要看清整张图（换脸尤其要确认脸和姿势），裁掉头部就没法选了 */
  object-fit: contain;
  background: var(--panel-3);
}

.cell:hover {
  border-color: var(--border-strong);
}

.cell.picked {
  border-color: var(--primary);
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
  color: #fff;
  font-size: 10px;
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
