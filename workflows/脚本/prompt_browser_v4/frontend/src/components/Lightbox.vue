<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'

import { viewUrl } from '../api/client'
import type { HistoryItem } from '../api/types'
import { formatSize, resolution, shotTime, sourceLabel } from '../utils/format'

const props = defineProps<{ items: HistoryItem[]; index: number }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'update:index', value: number): void
}>()

const item = computed<HistoryItem | undefined>(() => props.items[props.index])
const hasPrev = computed(() => props.index > 0)
const hasNext = computed(() => props.index < props.items.length - 1)

function go(delta: number) {
  const next = props.index + delta
  if (next < 0 || next >= props.items.length) return
  emit('update:index', next)
}

/**
 * 键盘：← → 翻页，Esc 关闭。
 * 旧版把这套逻辑散在 imageViewer.js（956 行）里，还依赖多个 window 全局；
 * 这里只负责"当前是哪一张"，由父组件持有 index。
 */
function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
  else if (event.key === 'ArrowLeft') go(-1)
  else if (event.key === 'ArrowRight') go(1)
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div v-if="item" class="lightbox" @click.self="emit('close')">
    <button class="nav prev" :disabled="!hasPrev" title="上一张 (←)" @click="go(-1)">‹</button>

    <figure class="stage">
      <img :src="viewUrl(item)" :alt="item.filename" />
    </figure>

    <button class="nav next" :disabled="!hasNext" title="下一张 (→)" @click="go(1)">›</button>

    <aside class="info">
      <header class="info-head">
        <span class="pos">{{ index + 1 }} / {{ items.length }}</span>
        <button class="close" title="关闭 (Esc)" @click="emit('close')">✕</button>
      </header>

      <div class="filename" :title="item.filename">{{ item.filename }}</div>

      <dl class="facts">
        <div v-if="resolution(item)"><dt>分辨率</dt><dd>{{ resolution(item) }}</dd></div>
        <div v-if="item.file_size"><dt>体积</dt><dd>{{ formatSize(item.file_size) }}</dd></div>
        <div><dt>来源</dt><dd>{{ sourceLabel(item.source) }}</dd></div>
        <div><dt>出图时间</dt><dd>{{ shotTime(item) }}</dd></div>
        <div v-if="item.prompt_name"><dt>提示词</dt><dd>{{ item.prompt_name }}</dd></div>
      </dl>

      <div v-if="item.tags.length" class="tags">
        <span
          v-for="tag in item.tags"
          :key="tag.id"
          class="tag"
          :style="{ '--c': tag.color }"
        >
          {{ tag.name }}
        </span>
      </div>

      <p v-if="item.missing" class="missing-tip">
        🚫 磁盘上已找不到这个文件，记录与标签仍保留
      </p>
    </aside>
  </div>
</template>

<style scoped>
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.88);
  backdrop-filter: blur(2px);
}

.stage {
  margin: 0;
  max-width: calc(100% - 360px);
  max-height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--gap-lg);
}

.stage img {
  max-width: 100%;
  max-height: calc(100vh - 80px);
  object-fit: contain;
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow);
}

.nav {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 44px;
  height: 68px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: rgba(22, 27, 34, 0.8);
  color: var(--text);
  font-size: 26px;
  line-height: 1;
}

.nav:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}

.nav:disabled {
  opacity: 0.25;
  cursor: default;
}

.prev {
  left: 16px;
}

.next {
  right: 336px;
}

.info {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 320px;
  padding: var(--gap-lg);
  overflow-y: auto;
  background: var(--panel);
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}

.info-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.pos {
  font-size: var(--fs-sm);
  color: var(--muted);
}

.close {
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: var(--fs-lg);
}

.close:hover {
  color: var(--danger);
}

.filename {
  font-size: var(--fs-sm);
  word-break: break-all;
  color: var(--text);
}

.facts {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.facts div {
  display: flex;
  gap: var(--gap);
  font-size: var(--fs-sm);
}

.facts dt {
  flex: none;
  width: 62px;
  color: var(--muted);
}

.facts dd {
  margin: 0;
  word-break: break-all;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag {
  font-size: var(--fs-xs);
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--c);
  color: var(--c);
}

.missing-tip {
  margin: 0;
  font-size: var(--fs-sm);
  padding: var(--gap-sm);
  border-radius: var(--radius-sm);
  background: var(--danger-soft);
  color: #fecaca;
}
</style>
