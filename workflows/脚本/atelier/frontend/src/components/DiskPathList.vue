<script setup lang="ts">
/**
 * 已选磁盘图清单：文件名 + 单张移除。
 *
 * 页面里用 `showThumbs` 展示缩略图；弹窗里用默认的紧凑 chips。
 * 横向/纵向由父容器决定，这里只负责内容与滚动。
 */
const props = withDefaults(
  defineProps<{
    modelValue: string[]
    showThumbs?: boolean
    thumbSize?: number
  }>(),
  { showThumbs: false, thumbSize: 120 },
)

const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()

function fileName(path: string) {
  return path.split(/[/\\]/).pop() || path
}

function thumbUrl(path: string, size: number) {
  return `/api/browser/thumb?path=${encodeURIComponent(path)}&size=${size}`
}

function remove(index: number) {
  const next = props.modelValue.slice()
  next.splice(index, 1)
  emit('update:modelValue', next)
}
</script>

<template>
  <div class="path-list" :class="{ thumbs: showThumbs }">
    <div v-for="(path, i) in modelValue" :key="path" class="path-item" :title="path">
      <img
        v-if="showThumbs"
        class="thumb"
        :src="thumbUrl(path, thumbSize)"
        :alt="fileName(path)"
        loading="lazy"
      />
      <span class="name">{{ fileName(path) }}</span>
      <button type="button" class="remove" title="移除这张" @click="remove(i)">×</button>
    </div>
  </div>
</template>

<style scoped>
.path-list {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-wrap: wrap;
  align-content: flex-start;
  gap: var(--gap-xs);
  overflow-y: auto;
}

.path-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  min-width: 0;
  padding: 2px 6px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
  font-size: var(--fs-xs);
}

.path-item .name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.remove {
  flex: none;
  padding: 0 2px;
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: var(--fs-sm);
  line-height: 1;
  cursor: pointer;
}

.remove:hover {
  color: var(--danger);
}

/* 缩略图模式：页面里每列下方的磁盘图 */
.path-list.thumbs {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(84px, 1fr));
  align-content: start;
}

.thumbs .path-item {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  padding: 0;
  border: none;
  background: transparent;
}

.thumbs .thumb {
  width: 100%;
  height: 84px;
  object-fit: contain;
  border-radius: var(--radius-sm);
  background: var(--panel-3);
  box-shadow: 0 0 0 1px var(--border);
}

.thumbs .path-item .name {
  display: block;
  width: 100%;
  padding: 2px 2px 0;
  color: var(--muted);
  font-size: 10px;
}

.thumbs .remove {
  position: absolute;
  top: 3px;
  right: 3px;
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: rgb(22 27 34 / 82%);
  color: var(--text);
  opacity: 0.9;
}
</style>
