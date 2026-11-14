<script setup lang="ts">
import { computed, ref } from 'vue'

import CategoryFilter from './CategoryFilter.vue'
import TagCloud from './TagCloud.vue'
import EmptyState from './EmptyState.vue'
import type { CategoryNode, ImageFacets, TagRow } from '../api/types'

type FacetKey = 'source' | 'date' | 'model' | 'orientation'

/**
 * 画廊左侧筛选栏（含收起态竖条）。
 *
 * 分面分组的折叠状态是纯展示偏好，留在这里；筛选值仍由 GalleryView 持有，
 * 组件只把交互抛上去，避免两处各存一份筛选状态。
 */
const props = defineProps<{
  open: boolean
  filterBadge: number
  total: number
  categories: CategoryNode[] | undefined
  categoryId: number | null
  tags: TagRow[]
  selectedTags: number[]
  tagMatch: 'all' | 'any'
  onlyMissing: boolean
  facets: ImageFacets | undefined
  source: string
  dateFacet: string
  model: string
  orientation: string
}>()

const emit = defineEmits<{
  'toggle-sidebar': []
  'select-category': [id: number | null]
  'toggle-tag': [id: number]
  'update:tag-match': [value: 'all' | 'any']
  'toggle-missing': []
  'clear-tags': []
  'clear-filters': []
  'toggle-facet': [key: FacetKey, value: string]
}>()

/** 每个分面组可折叠，默认展开。 */
const facetCollapsed = ref<Record<string, boolean>>({})
function toggleFacetGroup(key: string) {
  facetCollapsed.value = { ...facetCollapsed.value, [key]: !facetCollapsed.value[key] }
}

/** 分面维度定义（每个维度单选，再点一次取消）。 */
const facetDimDefs: Array<{ key: FacetKey; label: string }> = [
  { key: 'source', label: '来源' },
  { key: 'date', label: '年月' },
  { key: 'model', label: '模型' },
  { key: 'orientation', label: '方向' },
]

const facetValues = computed<Record<FacetKey, string>>(() => ({
  source: props.source,
  date: props.dateFacet,
  model: props.model,
  orientation: props.orientation,
}))

/** 分面值可能很长（模型名是一整个 safetensors 文件名），截断显示但保留完整 title。 */
function facetLabel(name: string): string {
  return name.length > 20 ? name.slice(0, 19) + '…' : name
}

function facetValue(key: FacetKey): string {
  return facetValues.value[key]
}
</script>

<template>
  <aside v-if="open" class="sidebar">
    <div class="side-head">
      <button class="btn btn-sm" title="收起筛选侧栏" @click="emit('toggle-sidebar')">«</button>
      <span class="side-title">筛选</span>
    </div>

    <CategoryFilter
      :categories="categories"
      :model-value="categoryId"
      all-label="全部图片"
      show-count
      @update:model-value="emit('select-category', $event)"
    />

    <section class="group">
      <div class="group-head-row">
        <button
          class="group-head"
          :aria-expanded="!facetCollapsed.tags"
          @click="toggleFacetGroup('tags')"
        >
          <span>{{ facetCollapsed.tags ? '▸' : '▾' }} 标签</span>
        </button>
        <span v-if="facetCollapsed.tags && selectedTags.length" class="facet-on">
          已选 {{ selectedTags.length }}
        </span>
        <button
          v-if="selectedTags.length"
          class="btn btn-sm clear"
          @click="emit('clear-tags')"
        >
          清空 ({{ selectedTags.length }})
        </button>
      </div>

      <TagCloud
        v-show="!facetCollapsed.tags"
        :tags="tags"
        :selected="selectedTags"
        :match="tagMatch"
        empty-text="暂无带图片的标签"
        @toggle="emit('toggle-tag', $event)"
        @update:match="emit('update:tag-match', $event)"
      />
    </section>

    <section v-for="dim in facetDimDefs" :key="dim.key" class="group">
      <button class="group-head" @click="toggleFacetGroup(dim.key)">
        <span>{{ facetCollapsed[dim.key] ? '▸' : '▾' }} {{ dim.label }}</span>
        <span v-if="facetValue(dim.key)" class="facet-on">{{ facetLabel(facetValue(dim.key)) }}</span>
      </button>
      <div v-if="!facetCollapsed[dim.key]" class="chips">
        <button
          v-for="(count, name) in facets?.[dim.key] ?? {}"
          :key="name"
          class="chip" :title="String(name)"
          :class="{ active: facetValue(dim.key) === name }"
          @click="emit('toggle-facet', dim.key, String(name))"
        >
          {{ facetLabel(String(name)) }}<i>{{ count }}</i>
        </button>
        <EmptyState v-if="!Object.keys(facets?.[dim.key] ?? {}).length" text="无" />
      </div>
    </section>

    <section class="group">
      <button
        class="group-head"
        :aria-expanded="!facetCollapsed.status"
        @click="toggleFacetGroup('status')"
      >
        <span>{{ facetCollapsed.status ? '▸' : '▾' }} 状态</span>
      </button>
      <label v-show="!facetCollapsed.status" class="check">
        <input type="checkbox" :checked="onlyMissing" @change="emit('toggle-missing')" />
        <span>只看文件缺失</span>
      </label>
    </section>

    <!-- 清除全部筛选常驻在侧栏底部：收起「状态」组时也必须可见可点 -->
    <button class="btn btn-sm full clear-all" @click="emit('clear-filters')">清除全部筛选</button>
  </aside>

  <aside v-else class="rail">
    <button class="btn btn-sm" title="展开筛选侧栏" @click="emit('toggle-sidebar')">»</button>
    <span v-if="filterBadge" class="rail-badge" :title="`${filterBadge} 项筛选生效`">
      {{ filterBadge }}
    </span>
    <span class="rail-count" :title="`共 ${total} 张`">共 {{ total }} 张</span>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 240px;
  flex: none;
  border-right: 1px solid var(--border);
  background: var(--panel);
  padding: var(--gap);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--gap-lg);
}

/* 展开态栏头：与 PromptView 的 .side-head 同款（贴边栏头 + 底部分隔线）。 */
.side-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  /* 抵消 .sidebar 的内边距，让栏头横贯整栏 */
  margin: calc(var(--gap) * -1) calc(var(--gap) * -1) 0;
  padding: var(--gap-sm) var(--gap);
  border-bottom: 1px solid var(--border);
}

.side-title {
  font-size: var(--fs-sm);
  color: var(--text);
}

/* 收起态竖条：与 PromptView 的 .rail 保持一致。 */
.rail {
  flex: none;
  width: 44px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) 0;
  border-right: 1px solid var(--border);
  background: var(--panel);
}

.rail-count {
  font-size: var(--fs-xs);
  color: var(--muted);
  writing-mode: vertical-rl;
  letter-spacing: 1px;
}

/* 收起期间仍有筛选生效时的数量角标 */
.rail-badge {
  display: grid;
  place-items: center;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  border-radius: var(--radius-pill);
  background: var(--primary);
  color: var(--on-primary);
  font-size: var(--fs-xs);
  line-height: 1;
}

.group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  border: none;
  background: transparent;
  padding: 0;
  cursor: pointer;
  text-align: left;
  font-size: var(--fs-sm);
  color: var(--muted);
  margin-bottom: var(--gap-sm);
}

.group-head:hover {
  color: var(--text);
}

.facet-on {
  max-width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--primary);
  font-size: var(--fs-xs);
}

/* 标签组头与「清空」并列：两个独立按钮，避免 button 嵌套导致的误触折叠。 */
.group-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-xs);
  margin-bottom: var(--gap-sm);
}

/* 横排里的组头只占文字宽度，避免把右侧「清空」挤出去。 */
.group-head-row .group-head {
  width: auto;
  flex: none;
  margin-bottom: 0;
}

.group-head-row .facet-on {
  margin-left: auto;
}

/* 「清除全部筛选」常驻侧栏底部，不随「状态」组折叠。 */
.clear-all {
  margin-top: auto;
}

.clear {
  font-size: var(--fs-xs);
  padding: 1px 6px;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.chip {
  font-size: var(--fs-xs);
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--muted);
  transition: color var(--dur-fast) var(--ease), background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease);
}

.chip:hover {
  border-color: var(--border-strong);
  color: var(--text);
}

.chip.active {
  background: var(--primary-soft);
  border-color: var(--primary);
  color: var(--primary);
}

.chip i {
  font-style: normal;
  opacity: 0.7;
  margin-left: 3px;
}

.check {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-sm);
  margin-bottom: var(--gap-sm);
  cursor: pointer;
}

.full {
  width: 100%;
}
</style>