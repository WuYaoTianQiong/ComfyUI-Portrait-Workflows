<script setup lang="ts">
import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import { apiGet } from '../api/client'
import EmptyState from '../components/EmptyState.vue'
import QueryState from '../components/QueryState.vue'
import { sourceLabel } from '../utils/format'

/**
 * 统计页：一眼看清库里有什么。
 *
 * 两份数据拼起来：
 * - `/api/system/stats`      —— 总量 + 热门标签
 * - `/api/images/facets` —— 图片的来源/方向/模型分布（复用画廊那套分面统计）
 */
interface StatsResponse {
  prompt_count: number
  history_count: number
  job_count: number
  fragment_count: number
  top_tags: Array<{ name: string; count: number; color: string }>
}

interface Facets {
  source: Record<string, number>
  date: Record<string, number>
  model: Record<string, number>
  orientation: Record<string, number>
}

const {
  data: stats,
  isFetching,
  isError: statsError,
  error: statsErr,
  refetch: refetchStats,
} = useQuery<StatsResponse>({
  queryKey: ['stats'],
  queryFn: () => apiGet('/api/system/stats'),
})

const {
  data: facets,
  isError: facetsError,
  error: facetsErr,
  refetch: refetchFacets,
} = useQuery<Facets>({
  queryKey: ['history', 'facets', 'stats'],
  queryFn: () => apiGet('/api/images/facets'),
})

const loadError = computed(() => {
  if (statsErr.value) return statsErr.value
  if (facetsErr.value) return facetsErr.value
  if (statsError.value) return '统计接口加载失败'
  if (facetsError.value) return '分面统计加载失败'
  return null
})
const initialLoading = computed(
  () => isFetching.value && !stats.value && !facets.value,
)

function retry() {
  refetchStats()
  refetchFacets()
}

/** 分面计数 → 占比条数据；按数量降序。 */
function bars(source: Record<string, number> | undefined) {
  const entries = Object.entries(source ?? {}).sort((a, b) => b[1] - a[1])
  const max = entries.length ? entries[0][1] : 0
  return entries.map(([name, count]) => ({ name, count, percent: max ? (count / max) * 100 : 0 }))
}

const sourceBars = computed(() => bars(facets.value?.source))
const orientationBars = computed(() => bars(facets.value?.orientation))
const modelBars = computed(() => bars(facets.value?.model))

/** 标签色是用户自定的，可能是脏值；给它一个兜底色。 */
function tagColor(color: string | undefined): string {
  return color && /^#[0-9a-fA-F]{3,8}$/.test(color) ? color : 'var(--primary)'
}
</script>
<template>
  <div class="stats">
    <QueryState :loading="initialLoading" :error="loadError" @retry="retry">
    <div class="cards">
      <div class="card">
        <span class="num">{{ stats?.prompt_count ?? '—' }}</span>
        <span class="label">提示词</span>
      </div>
      <div class="card">
        <span class="num">{{ stats?.history_count ?? '—' }}</span>
        <span class="label">图片</span>
      </div>
      <div class="card">
        <span class="num">{{ stats?.job_count ?? '—' }}</span>
        <span class="label">任务</span>
      </div>
      <div class="card">
        <span class="num">{{ stats?.fragment_count ?? '—' }}</span>
        <span class="label">碎片库</span>
      </div>
      <div class="card">
        <span class="num">{{ stats?.top_tags?.length ?? '—' }}</span>
        <span class="label">热门标签</span>
      </div>
    </div>

    <div class="grid">
      <section class="panel">
        <h3>热门标签</h3>
        <div class="tag-list">
          <span
            v-for="tag in stats?.top_tags ?? []"
            :key="tag.name"
            class="tag"
            :style="{ '--c': tagColor(tag.color) }"
          >
            {{ tag.name }}<i>{{ tag.count }}</i>
          </span>
        </div>
        <EmptyState v-if="!(stats?.top_tags ?? []).length && !isFetching" text="还没有标签" />
      </section>

      <section class="panel">
        <h3>图片来源</h3>
        <div v-for="row in sourceBars" :key="row.name" class="bar-row">
          <span class="bar-name">{{ sourceLabel(row.name) }}</span>
          <span class="bar-track"><i :style="{ width: `${row.percent}%` }" /></span>
          <span class="bar-num">{{ row.count }}</span>
        </div>
        <EmptyState v-if="!sourceBars.length" text="还没有图片" />
      </section>

      <section class="panel">
        <h3>图片方向</h3>
        <div v-for="row in orientationBars" :key="row.name" class="bar-row">
          <span class="bar-name">{{ sourceLabel(row.name) }}</span>
          <span class="bar-track"><i :style="{ width: `${row.percent}%` }" /></span>
          <span class="bar-num">{{ row.count }}</span>
        </div>
        <EmptyState v-if="!orientationBars.length" text="还没有图片" />
      </section>

      <section class="panel">
        <h3>使用模型</h3>
        <div v-for="row in modelBars.slice(0, 8)" :key="row.name" class="bar-row">
          <span class="bar-name" :title="row.name">{{ row.name }}</span>
          <span class="bar-track"><i :style="{ width: `${row.percent}%` }" /></span>
          <span class="bar-num">{{ row.count }}</span>
        </div>
        <EmptyState v-if="!modelBars.length" text="还没有图片" />
      </section>
    </div>
    </QueryState>
  </div>
</template>

<style scoped>
.stats {
  height: 100%;
  overflow-y: auto;
  padding: var(--gap-lg);
  display: flex;
  flex-direction: column;
  gap: var(--gap-lg);
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: var(--gap);
}

.card {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel);
  padding: var(--gap);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.card .num {
  font-size: 26px;
  font-weight: 600;
  line-height: 1.2;
}

.card .label {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: var(--gap);
  align-items: start;
}

.panel {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel);
  padding: var(--gap);
}

.panel h3 {
  margin: 0 0 var(--gap-sm);
  font-size: var(--fs-sm);
  color: var(--muted);
  font-weight: 600;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--fs-xs);
  padding: 2px 8px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--c) 18%, transparent);
  border: 1px solid var(--c);
  color: var(--text);
}

.tag i {
  font-style: normal;
  opacity: 0.75;
}

.bar-row {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: 3px 0;
  font-size: var(--fs-sm);
}

.bar-name {
  width: 96px;
  flex: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
}

.bar-track {
  flex: 1;
  min-width: 0;
  height: 8px;
  border-radius: 999px;
  background: var(--panel-3);
  overflow: hidden;
}

.bar-track i {
  display: block;
  height: 100%;
  background: var(--primary);
  border-radius: 999px;
}

.bar-num {
  width: 34px;
  flex: none;
  text-align: right;
  color: var(--muted);
  font-size: var(--fs-xs);
}
</style>