<script setup lang="ts">
/**
 * 合成台 · 生成历史（只读）。
 *
 * 数据源：`GET /api/images`（atelier 画廊历史）。按施工手册 §7 冻结口径：
 * - 图片地址直接用后端下发的 `view_url`，不做任何前缀拼接；
 * - `view_url` 为空时渲染「图片不可用」占位，并禁用下载；
 * - **无清空、无单条删除**（本面板只读）。
 *
 * 明确不做：「复用词」按钮 —— React 侧的复用词来自本地 IndexedDB 历史记录里的
 * `prompt` 文本，而 `/api/images` 只下发 `prompt_name` / `prompt_params`，没有
 * 可复原的提示词正文；硬接会得到一段空提示词，故不实现。
 */

import { computed, onMounted, ref } from 'vue'

import type { HistoryItem } from '../../../api/types'

/** 历史接口；`sort=newest` 与画廊默认一致。 */
const HISTORY_ENDPOINT = '/api/images?page=1&page_size=12&sort=newest'

const items = ref<HistoryItem[]>([])
const loading = ref(false)
const error = ref('')
const total = ref(0)

const isEmpty = computed(() => !loading.value && !error.value && items.value.length === 0)

function errorText(message: string): string {
  return `读取生成历史失败。原因：${message}。下一步：点击「重试」重新读取；若仍失败，请确认后端服务在线。`
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const response = await fetch(HISTORY_ENDPOINT)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const body = (await response.json()) as { items?: unknown; total?: unknown }
    if (!body || !Array.isArray(body.items)) throw new Error('响应结构异常')
    items.value = body.items as HistoryItem[]
    total.value = Number(body.total) || items.value.length
  } catch (cause) {
    items.value = []
    error.value = errorText(cause instanceof Error ? cause.message : String(cause))
  } finally {
    loading.value = false
  }
}

/** 展示标题：提示词名优先，缺失回退文件名。 */
function titleOf(item: HistoryItem): string {
  return item.prompt_name || item.filename
}

/** 展示摘要：来源 + 出图时间（只读信息，不做操作）。 */
function metaOf(item: HistoryItem): string {
  const source = item.source || '未知来源'
  const date = item.captured_at || item.created_at
  return date ? `${source} · ${date}` : source
}

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="history-panel" data-testid="reference-history-panel">
    <header class="history-panel__head">
      <h2 class="history-panel__title">
        生成历史
        <span v-if="total > 0" class="history-panel__count">{{ total }}</span>
      </h2>
      <div class="history-panel__head-right">
        <span class="history-panel__readonly">只读</span>
        <button
          type="button"
          class="history-panel__retry"
          :disabled="loading"
          @click="load"
        >
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
      </div>
    </header>

    <p v-if="error" class="history-panel__error" role="alert">
      {{ error }}
      <button type="button" class="history-panel__retry" @click="load">重试</button>
    </p>

    <p v-if="isEmpty" class="history-panel__empty">还没有生成记录，出图完成后会在这里展示。</p>

    <div v-if="items.length" class="history-panel__grid">
      <article
        v-for="item in items"
        :key="item.id"
        class="history-card"
        :data-testid="`reference-history-${item.id}`"
      >
        <div class="history-card__thumb">
          <img
            v-if="item.view_url"
            :src="item.view_url"
            :alt="titleOf(item)"
            loading="lazy"
            class="history-card__img"
          />
          <span v-else class="history-card__unavailable">图片不可用</span>
        </div>

        <div class="history-card__body">
          <p class="history-card__title" :title="titleOf(item)">{{ titleOf(item) }}</p>
          <p class="history-card__meta" :title="metaOf(item)">{{ metaOf(item) }}</p>

          <a
            v-if="item.view_url"
            class="history-card__download"
            :href="item.view_url"
            :download="`character-${item.id}.png`"
          >
            下载
          </a>
          <span v-else class="history-card__download is-disabled" aria-disabled="true">
            下载
          </span>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.history-panel {
  box-sizing: border-box;
  width: 100%;
  padding: 24px;
  border-radius: 22px;
  background: #171717;
}

.history-panel__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}

.history-panel__title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  color: #fafafa;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
}

.history-panel__count {
  padding: 1px 8px;
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.08);
  color: #fafafa;
  font-size: 11px;
  font-weight: 500;
}

.history-panel__head-right {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.history-panel__readonly {
  color: #a1a1a1;
  font-size: 11px;
}

.history-panel__retry {
  height: 26px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: transparent;
  color: #fafafa;
  font-size: 11px;
  cursor: pointer;
}

.history-panel__retry:hover:not(:disabled) {
  border-color: var(--primary);
}

.history-panel__retry:disabled {
  opacity: 0.5;
  cursor: progress;
}

.history-panel__error {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 0 0 12px;
  padding: 10px 12px;
  border: 1px solid rgba(239, 68, 68, 0.4);
  border-radius: 10px;
  background: rgba(239, 68, 68, 0.08);
  color: #fecaca;
  font-size: 12px;
  line-height: 1.6;
}

.history-panel__empty {
  margin: 0;
  color: #a1a1a1;
  font-size: 12px;
  line-height: 1.6;
}

/* 4 列 → 390px 2 列 */
.history-panel__grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.history-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 8px;
  border-radius: 16px;
  background: #0a0a0a;
}

/* 缩略图 3:4 */
.history-card__thumb {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  width: 100%;
  aspect-ratio: 3 / 4;
  border-radius: 12px;
  background: #262626;
}

.history-card__img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.history-card__unavailable {
  padding: 0 8px;
  color: #a1a1a1;
  font-size: 11px;
  text-align: center;
}

.history-card__body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 8px 2px 2px;
}

.history-card__title {
  margin: 0;
  overflow: hidden;
  color: #fafafa;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-card__meta {
  margin: 0;
  overflow: hidden;
  color: #a1a1a1;
  font-size: 10px;
  line-height: 1.5;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-card__download {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 24px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.08);
  color: #fafafa;
  font-size: 11px;
  font-weight: 500;
  text-decoration: none;
}

.history-card__download:hover {
  background: rgba(255, 255, 255, 0.14);
}

/* 无图时禁用下载：占位灰、不可点 */
.history-card__download.is-disabled {
  background: #262626;
  color: #6b6b6b;
  cursor: not-allowed;
}

@media (max-width: 639px) {
  .history-panel {
    padding: 16px;
    border-radius: 18px;
  }

  .history-panel__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>