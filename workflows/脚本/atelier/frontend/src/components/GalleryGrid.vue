<script setup lang="ts">
import EmptyState from './EmptyState.vue'
import Skeleton from './Skeleton.vue'
import { thumbnailUrl } from '../api/client'
import { formatSize, resolution } from '../utils/format'
import type { HistoryItem } from '../api/types'

/**
 * 画廊网格：真实卡片、首屏骨架与空状态。
 *
 * 外层滚动容器（`.grid`）仍留在 GalleryView —— 会话恢复要直接操作它的
 * scrollTop；这里只负责卡片呈现并把操作抛给父组件。
 */
defineProps<{
  items: HistoryItem[]
  isFetching: boolean
  density: 'standard' | 'compact'
  skeletonCount: number
  selected: Set<number>
}>()

const emit = defineEmits<{
  open: [index: number]
  'toggle-select': [id: number]
  favorite: [id: number]
  locate: [item: HistoryItem]
  'copy-filename': [name: string]
}>()

/** 替换碎片出图的图片不挂原提示词，卡片上给一个轻量标记。 */
function isBatchReplace(item: HistoryItem): boolean {
  const pp = item.prompt_params as Record<string, unknown> | null | undefined
  return pp?.source === 'batch_replace'
}
</script>

<template>
  <div
    v-if="!items.length && isFetching"
    class="cards skeleton-cards"
    :class="density"
    aria-hidden="true"
  >
    <article v-for="n in skeletonCount" :key="`skeleton-${n}`" class="card skeleton-card">
      <div class="thumb">
        <Skeleton variant="block" width="100%" height="100%" radius="var(--radius)" />
      </div>
      <div class="caption">
        <Skeleton width="72%" />
        <Skeleton width="46%" />
      </div>
      <div class="actions">
        <Skeleton width="64px" height="24px" radius="var(--radius-sm)" />
      </div>
    </article>
  </div>

  <div v-else-if="items.length" class="cards" :class="density">
    <article
      v-for="(item, index) in items"
      :key="item.id"
      class="card"
      :class="{ missing: item.missing, picked: selected.has(item.id) }"
      :title="item.missing ? '磁盘上找不到这个文件（勾选「只看文件缺失」可批量清理记录）' : item.filename"
      @click="emit('open', index)"
    >
      <div class="thumb">
        <img :src="thumbnailUrl(item)" :alt="item.filename" loading="lazy" />

        <span v-if="item.missing" class="badge-missing">文件缺失</span>
        <span v-else-if="isBatchReplace(item)" class="badge-replace" title="由替换碎片出图生成，提示词以临时记录保存">
          替换
        </span>
        <span v-if="selected.has(item.id)" class="check-mark" aria-hidden="true">✓</span>
      </div>

      <div class="caption">
        <span
          class="filename"
          title="点击复制文件名"
          @click.stop="emit('copy-filename', item.filename)"
        >
          {{ item.filename }}
        </span>
        <span class="dim">{{ resolution(item) }} · {{ formatSize(item.file_size) }}</span>
      </div>

      <div class="actions">
        <button
          class="btn btn-sm pick"
          :class="{ on: selected.has(item.id) }"
          :title="selected.has(item.id) ? '取消选择' : '选择'"
          @click.stop="emit('toggle-select', item.id)"
        >
          {{ selected.has(item.id) ? '✓ 已选' : '选择' }}
        </button>

        <button
          class="btn btn-sm fav"
          :class="{ on: item.is_favorite }"
          title="收藏"
          @click.stop="emit('favorite', item.id)"
        >
          {{ item.is_favorite ? '★ 已收藏' : '☆ 收藏' }}
        </button>

        <button
          class="btn btn-sm locate"
          title="在资源管理器中定位原图"
          @click.stop="emit('locate', item)"
        >
          定位
        </button>
      </div>
    </article>
  </div>

  <EmptyState v-else size="big" text="没有符合条件的图片" />
</template>

<style scoped>
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--gap);
}

.cards.compact {
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: var(--gap-sm);
}

.card {
  width: 100%;
  cursor: pointer;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel);
  overflow: hidden;
  transition: border-color var(--dur-fast) var(--ease), box-shadow var(--dur-fast) var(--ease);
}

.card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-2);
}

.card.picked {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

.thumb {
  position: relative;
  width: 100%;
  /* 固定比例容器：图片加载前后网格高度一致，首屏不再重排 */
  aspect-ratio: 4 / 5;
  overflow: hidden;
  background: var(--panel-3);
}

.thumb img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.card.missing .thumb img {
  opacity: 0.35;
  filter: grayscale(1);
}

.check-mark {
  position: absolute;
  top: var(--gap-sm);
  right: var(--gap-sm);
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--primary);
  /* 主色实底：浅色下 --text 是近黑，必须换成垫在主色上的专用前景色 */
  color: var(--on-primary-soft);
  font-size: var(--fs-sm);
  font-weight: 700;
  box-shadow: var(--shadow-1);
}

.skeleton-card {
  cursor: default;
}

.skeleton-card .caption {
  padding: var(--gap-sm) var(--gap-sm) 0;
}

.skeleton-card .actions {
  padding: 0 var(--gap-sm) var(--gap-sm);
}

.skeleton-card:hover {
  border-color: var(--border);
  box-shadow: none;
}

.skeleton-card:hover .thumb img {
  transform: none;
}

.pick,
.fav,
.locate {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: color var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease),
    background var(--dur-fast) var(--ease);
}

.pick.on {
  background: var(--primary);
  border-color: var(--primary);
  color: var(--on-primary-soft);
}

.fav.on {
  border-color: var(--warn);
  color: var(--warn);
}

.badge-missing {
  position: absolute;
  top: var(--gap-sm);
  left: 50%;
  transform: translateX(-50%);
  padding: 2px var(--gap-sm);
  border-radius: var(--radius-pill);
  background: var(--danger-soft);
  color: var(--text);
  font-size: var(--fs-xs);
  font-weight: 600;
  white-space: nowrap;
}

.badge-replace {
  position: absolute;
  top: var(--gap-sm);
  left: 50%;
  transform: translateX(-50%);
  padding: 1px var(--gap-sm);
  border-radius: var(--radius-pill);
  background: var(--primary-soft);
  color: var(--accent-link);
  font-size: var(--fs-xs);
  font-weight: 600;
  white-space: nowrap;
}

.caption {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: var(--gap-sm) var(--gap-sm) 0;
}

.filename {
  font-size: var(--fs-xs);
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: copy;
}

.filename:hover {
  color: var(--accent-link);
}

.dim {
  font-size: var(--fs-xs);
  color: var(--muted);
  opacity: 0.8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
  padding: 0 var(--gap-sm) var(--gap-sm);
}
</style>