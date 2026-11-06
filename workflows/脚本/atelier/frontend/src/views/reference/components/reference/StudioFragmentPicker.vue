<script setup lang="ts">
/**
 * 单类碎片选择弹层（方案 §5.5）。
 *
 * 硬约束（§9「前端性能」）：**只拉当前类型**，绝不一次拉 8 类 2175 条。
 * 请求参数：
 *   GET /api/composer/fragments?fragment_type=<type>&safe_mode=<bool>
 * 返回 `{ grouped: { [type]: entries[] }, fragment_count }`，这里只读当前类型分组。
 *
 * 交互口径：
 * - 前缀搜索在**本地**对 `content` 过滤，不重新请求后端；
 * - 多选，单类软上限 {@link MAX_FRAGMENTS_PER_TYPE} 条；
 * - 展示每条碎片的来源（`source_names` / `prompt_name`）与重复次数（`dup_count`）；
 * - 「确认」回填整类选区（含打开前已选、但当前搜索结果里看不见的条目）。
 *
 * 纯受控：不改父级状态，只在确认时 emit 整类数组。
 */

import { computed, ref, watch } from 'vue'

import { apiGet } from '../../../../api/client'
import Modal from '../../../../components/Modal.vue'
import type { FragmentType } from '../../../../constants'
import {
  FRAGMENT_HOME_LABELS,
  FRAGMENT_HOMES,
  MAX_FRAGMENTS_PER_TYPE,
} from '../../../../composables/recipeTextFragments'
import type { SelectedFragment } from '../../../../composables/recipeTextFragments'

/** 碎片池端点（Composer 与本弹层共用；只按 `fragment_type` 分类拉取）。 */
const COMPOSER_FRAGMENTS_ENDPOINT = '/api/composer/fragments'

/** 后端条目字段（只声明本弹层用到的部分）。 */
interface ComposerFragmentEntry {
  fragment_id?: number
  prompt_id?: number | null
  prompt_name?: string
  type?: string
  content: string
  tags?: string
  source?: string
  dup_count?: number
  source_names?: string[]
  /** P4：来自「多图/双人/参考图专用」提示词的警告；为空表示无警告。 */
  warning?: string
}

interface ComposerFragmentsResponse {
  grouped?: Record<string, ComposerFragmentEntry[] | undefined>
  fragment_count?: number
}

const props = defineProps<{
  /** 本次只加载并回填这一类。 */
  fragmentType: FragmentType
  /** 该类当前已选（打开弹层时的初始选区）。 */
  selected: readonly SelectedFragment[]
  /** 安全模式开启时后端做 NSFW 启发式过滤。 */
  safeMode: boolean
}>()

const emit = defineEmits<{
  confirm: [fragments: SelectedFragment[]]
  close: []
}>()

/** 归属标签（彩色标签放在类型名之前，不用 emoji）。 */
const homeLabel = computed(() => FRAGMENT_HOME_LABELS[FRAGMENT_HOMES[props.fragmentType]])

/** 当前类全部条目（后端已按 fragment_type 分组）。 */
const entries = ref<ComposerFragmentEntry[]>([])
/** 全池条数（后端 `fragment_count`，仅作说明，不参与过滤）。 */
const poolCount = ref(0)
const loading = ref(false)
const loadError = ref('')
/** 请求序号：快速切换类型 / 重试时丢弃过期响应。 */
let requestSeq = 0

const query = ref('')
/** 选区只存 `content`（同类以内容唯一定位，与后端 type||content 去重口径一致）。 */
const draftContents = ref<string[]>(props.selected.map((item) => item.content))
/** 超上限提示（不弹 toast，避免打断连续点选）。 */
const limitNotice = ref('')

const selectedSet = computed(() => new Set(draftContents.value))

/**
 * 前缀搜索：本地对 `content` 过滤。
 *
 * 去首尾空白、忽略大小写；空查询返回全部。中文内容以「一位…」等短语开头，
 * 前缀匹配比全模糊更可预期，也避免短词把整池都命中。
 */
const filteredEntries = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  if (!keyword) return entries.value
  return entries.value.filter((entry) =>
    entry.content.trim().toLowerCase().startsWith(keyword),
  )
})

/** 已选 n/2。 */
const selectedCountLabel = computed(
  () => `${draftContents.value.length}/${MAX_FRAGMENTS_PER_TYPE}`,
)

/** 加载当前类的碎片（只拉这一类，不拉全池）。 */
async function loadFragments(): Promise<void> {
  const seq = ++requestSeq
  loading.value = true
  loadError.value = ''
  try {
    const response = await apiGet<ComposerFragmentsResponse>(COMPOSER_FRAGMENTS_ENDPOINT, {
      fragment_type: props.fragmentType,
      safe_mode: props.safeMode,
    })
    if (seq !== requestSeq) return
    const grouped = response?.grouped ?? {}
    const list = grouped[props.fragmentType]
    entries.value = Array.isArray(list) ? list : []
    poolCount.value =
      typeof response?.fragment_count === 'number' ? response.fragment_count : entries.value.length
  } catch (cause) {
    if (seq !== requestSeq) return
    entries.value = []
    const message = cause instanceof Error ? cause.message : String(cause)
    loadError.value = `碎片加载失败。原因：${message}。下一步：点击「重试」再次请求；仍失败请检查后端服务。`
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

watch(
  () => [props.fragmentType, props.safeMode],
  () => {
    query.value = ''
    limitNotice.value = ''
    void loadFragments()
  },
  { immediate: true },
)

/** 选中 / 取消一条；超上限只给内联提示，不加入。 */
function toggleEntry(entry: ComposerFragmentEntry): void {
  const content = entry.content
  if (!content) return
  if (selectedSet.value.has(content)) {
    draftContents.value = draftContents.value.filter((item) => item !== content)
    limitNotice.value = ''
    return
  }
  if (draftContents.value.length >= MAX_FRAGMENTS_PER_TYPE) {
    limitNotice.value = `单类最多 ${MAX_FRAGMENTS_PER_TYPE} 条，请先取消一条再选`
    return
  }
  draftContents.value = [...draftContents.value, content]
  limitNotice.value = ''
}

/** 来源文案：优先 source_names，回落提示词名，再回落「碎片库」。 */
function entrySource(entry: ComposerFragmentEntry): string {
  const names = (entry.source_names ?? []).filter(
    (name): name is string => typeof name === 'string' && name.trim().length > 0,
  )
  if (names.length) {
    return names.length > 2 ? `${names.slice(0, 2).join('、')} 等 ${names.length} 处` : names.join('、')
  }
  return entry.prompt_name?.trim() || '碎片库'
}

/** 重复次数；<= 1 不显示。 */
function entryDupCount(entry: ComposerFragmentEntry): number {
  return typeof entry.dup_count === 'number' && entry.dup_count > 1 ? entry.dup_count : 0
}

/** 确认：按选区顺序回填整类（type 一律用当前类型）。 */
function confirmSelection(): void {
  emit(
    'confirm',
    draftContents.value.map((content) => ({ type: props.fragmentType, content })),
  )
}
</script>

<template>
  <Modal
    :open="true"
    :title="`选择碎片 · ${fragmentType}`"
    width="min(720px, 92vw)"
    @close="emit('close')"
  >
    <template #head>
      <span class="fragment-picker__tag" :data-home="FRAGMENT_HOMES[fragmentType]">
        {{ homeLabel }}
      </span>
      <span class="fragment-picker__head-count">已选 {{ selectedCountLabel }}</span>
    </template>

    <div class="fragment-picker" data-testid="studio-fragment-picker">
      <div class="fragment-picker__toolbar">
        <input
          v-model="query"
          type="search"
          class="fragment-picker__search"
          placeholder="按内容前缀搜索（本地过滤）"
          aria-label="按内容前缀搜索碎片"
          data-testid="studio-fragment-picker-search"
        />
        <span class="fragment-picker__count" data-testid="studio-fragment-picker-count">
          当前类 {{ entries.length }} 条 · 全池 {{ poolCount }} 条
        </span>
      </div>

      <p class="fragment-picker__hint">
        安全模式{{ safeMode ? '已开启：敏感碎片不下发' : '已关闭：内容未过滤' }}；单类最多
        {{ MAX_FRAGMENTS_PER_TYPE }} 条。
      </p>

      <p v-if="limitNotice" class="fragment-picker__notice" role="status" data-testid="studio-fragment-picker-limit">
        {{ limitNotice }}
      </p>

      <p v-if="loading" class="fragment-picker__state">正在加载当前类碎片…</p>
      <div v-else-if="loadError" class="fragment-picker__state fragment-picker__state--error" role="alert">
        {{ loadError }}
        <button type="button" class="btn btn-sm" @click="loadFragments">重试</button>
      </div>
      <p v-else-if="!filteredEntries.length" class="fragment-picker__state">
        {{ query.trim() ? '没有以该前缀开头的内容，请换个前缀。' : '当前分类没有可用碎片。' }}
      </p>

      <ul v-else class="fragment-picker__list">
        <li v-for="(entry, index) in filteredEntries" :key="`${entry.fragment_id ?? entry.prompt_id ?? 'x'}-${index}`">
          <button
            type="button"
            class="fragment-entry"
            :class="{
              'is-selected': selectedSet.has(entry.content),
              'has-warning': Boolean(entry.warning),
            }"
            :aria-pressed="selectedSet.has(entry.content)"
            :data-testid="`studio-fragment-entry-${index}`"
            @click="toggleEntry(entry)"
          >
            <span class="fragment-entry__mark" aria-hidden="true">
              {{ selectedSet.has(entry.content) ? '已选' : '选择' }}
            </span>
            <span class="fragment-entry__body">
              <span class="fragment-entry__content" :title="entry.content">{{ entry.content }}</span>
              <span
                v-if="entry.warning"
                class="fragment-entry__warning"
                data-testid="studio-fragment-warning"
              >
                {{ entry.warning }}
              </span>
              <span class="fragment-entry__meta">
                <span>来源：{{ entrySource(entry) }}</span>
                <span v-if="entryDupCount(entry)">重复 ×{{ entryDupCount(entry) }}</span>
                <span v-if="entry.tags">{{ entry.tags }}</span>
              </span>
            </span>
          </button>
        </li>
      </ul>
    </div>

    <template #footer>
      <span class="fragment-picker__foot-count">已选 {{ selectedCountLabel }} 条</span>
      <span class="fragment-picker__spacer" />
      <button type="button" class="btn btn-sm" @click="emit('close')">取消</button>
      <button
        type="button"
        class="btn btn-sm fragment-picker__confirm"
        data-testid="studio-fragment-picker-confirm"
        :disabled="loading"
        @click="confirmSelection"
      >
        确认回填
      </button>
    </template>
  </Modal>
</template>

<style scoped>
.fragment-picker__tag {
  padding: 1px 7px;
  border: 1px solid currentColor;
  border-radius: var(--radius-pill);
  font-size: 12px;
  line-height: 1.5;
}

.fragment-picker__tag[data-home='portrait'] {
  color: var(--accent-link);
}

.fragment-picker__tag[data-home='costume'] {
  color: var(--accent-green-text);
}

.fragment-picker__tag[data-home='pose'] {
  color: var(--accent-red-text);
}

.fragment-picker__tag[data-home='modifier'] {
  color: var(--text-muted);
}

.fragment-picker__head-count {
  color: var(--text-muted);
  font-size: 12px;
}

.fragment-picker {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  padding: var(--gap-md) var(--gap-lg);
  min-height: 0;
}

.fragment-picker__toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-sm);
}

.fragment-picker__search {
  flex: 1 1 260px;
  min-width: 0;
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-code);
  color: var(--text-body);
  font-size: 12px;
}

.fragment-picker__search:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}

.fragment-picker__count {
  color: var(--text-muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.fragment-picker__hint,
.fragment-picker__state {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}

.fragment-picker__state--error {
  color: var(--danger-text-soft);
}

.fragment-picker__notice {
  margin: 0;
  color: var(--warn);
  font-size: 12px;
  line-height: 1.6;
}

.fragment-picker__list {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  max-height: 48vh;
  margin: 0;
  padding: 0;
  overflow: auto;
  list-style: none;
}

.fragment-entry {
  display: flex;
  gap: var(--gap-sm);
  box-sizing: border-box;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--border-faint);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-body);
  text-align: left;
}

.fragment-entry:hover {
  border-color: var(--border-hover);
  background: var(--surface-card-hover);
}

.fragment-entry.is-selected {
  border-color: var(--primary);
  background: var(--primary-soft);
}

.fragment-entry__mark {
  flex: none;
  align-self: flex-start;
  padding: 1px 7px;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-pill);
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.fragment-entry.is-selected .fragment-entry__mark {
  border-color: var(--primary);
  color: var(--primary);
}

.fragment-entry__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.fragment-entry__content {
  display: -webkit-box;
  overflow: hidden;
  color: var(--text-body);
  font-size: 12px;
  line-height: 1.6;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

/* P4：不适合单图合成的来源只标警告，不阻止选择 */
.fragment-entry.has-warning {
  border-color: var(--border-strong);
}

.fragment-entry__warning {
  color: var(--danger-text-soft);
  font-size: 12px;
  line-height: 1.5;
}

.fragment-entry__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-sm);
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.fragment-picker__foot-count {
  color: var(--text-muted);
  font-size: 12px;
}

.fragment-picker__spacer {
  flex: 1;
}

.fragment-picker__confirm {
  border-color: var(--primary);
  color: var(--primary);
}
</style>