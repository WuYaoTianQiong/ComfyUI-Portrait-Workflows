<script setup lang="ts">
import type { ComponentPublicInstance } from 'vue'

import EmptyState from './EmptyState.vue'
import Icon from './Icon.vue'
import type { CanvasSlot } from '../composables/useComposerCanvas'

interface FragmentItem {
  fragment_id?: number
  prompt_id: number | null
  prompt_name: string
  type: string
  content: string
  tags: string
  source: 'prompt' | 'library' | 'custom'
  dup_count: number
}

/**
 * 组合器的单列滚筒：列头（锁定/定位）、已选摘要、候选卡片与自定义入口。
 *
 * 滚动容器与「加载更多」哨兵通过回调交回父组件：父组件维护
 * 列 → 元素的 Map，用于随机/检索后的滚动定位与 IntersectionObserver。
 */
const props = defineProps<{
  type: string
  /** 当前已加载（已按 limit 截断）的候选碎片。 */
  items: FragmentItem[]
  /** 该类型碎片总数（未截断），用于列头计数与「还有 N 个」。 */
  totalCount: number
  pinned: boolean
  slot: CanvasSlot | undefined
  keyword: string
  registerBody: (el: Element | ComponentPublicInstance | null) => void
  registerMore: (el: Element | ComponentPublicInstance | null) => void
}>()

const emit = defineEmits<{
  'toggle-lock': [type: string]
  locate: [type: string]
  unpick: [type: string]
  pick: [item: FragmentItem]
  'open-custom': [type: string]
  'open-detail': [item: FragmentItem]
  'load-more': [type: string]
}>()

function isHit(content: string): boolean {
  const k = props.keyword.toLowerCase()
  return !!k && content.toLowerCase().includes(k)
}

/** 把正文按关键词切成片段，命中的片段单独着色（不拼 HTML，避免 XSS）。 */
function textParts(text: string): Array<{ text: string; hit: boolean }> {
  const k = props.keyword
  if (!k) return [{ text, hit: false }]
  const parts: Array<{ text: string; hit: boolean }> = []
  const lower = text.toLowerCase()
  const kl = k.toLowerCase()
  let from = 0
  while (from < text.length) {
    const at = lower.indexOf(kl, from)
    if (at < 0) break
    if (at > from) parts.push({ text: text.slice(from, at), hit: false })
    parts.push({ text: text.slice(at, at + k.length), hit: true })
    from = at + k.length
  }
  if (from < text.length) parts.push({ text: text.slice(from), hit: false })
  return parts.length ? parts : [{ text, hit: false }]
}
</script>

<template>
  <section class="reel">
    <header
      class="reel-head"
      :class="{ on: pinned }"
      :title="
        pinned
          ? `已锁定：${type}（随机时保持不变，点击解锁）`
          : `锁定「${type}」：随机时保持不变`
      "
      @click="emit('toggle-lock', type)"
    >
      <span class="pin-ico"><Icon :name="pinned ? 'lock' : 'lock-open'" /></span>
      <button
        class="locate-ico"
        :title="`定位「${type}」已选碎片到列中间`"
        :aria-label="`定位「${type}」已选碎片`"
        @click.stop="emit('locate', type)"
      >
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="8" cy="8" r="3.2" />
          <path d="M8 1v3M8 12v3M1 8h3M12 8h3" />
        </svg>
      </button>
      <span class="reel-type">{{ type }}</span>
      <span class="reel-count">{{ totalCount }}</span>
    </header>

    <div v-if="slot" class="reel-picked" :title="slot.content">
      <span class="picked-label">已选</span>
      <span class="picked-text">{{ slot.content }}</span>
      <button class="picked-x" title="清空这一列" @click="emit('unpick', type)">✕</button>
    </div>

    <div class="reel-body" :ref="(el) => registerBody(el)">
      <button
        v-if="slot?.source === 'custom'"
        class="card on custom"
        @click="emit('open-custom', type)"
      >
        <span class="card-text">{{ slot.content }}</span>
        <span class="card-meta">自定义<span class="tag-self">自</span></span>
      </button>

      <button
        v-for="(item, idx) in items"
        :key="`${type}-${item.fragment_id ?? item.prompt_id}-${idx}`"
        class="card"
        :class="{
          on: slot?.source !== 'custom' && slot?.content === item.content,
          hit: isHit(item.content),
        }"
        :title="`双击查看全文：${item.content}`"
        @click="emit('pick', item)"
        @dblclick.stop="emit('open-detail', item)"
      >
        <span class="card-text">
          <span
            v-for="(part, pi) in textParts(item.content)"
            :key="pi"
            :class="{ mark: part.hit }"
          >{{ part.text }}</span>
        </span>
        <span class="card-meta">
          {{ item.prompt_name || '提示词' }}
          <i v-if="item.dup_count > 1">×{{ item.dup_count }}</i>
        </span>
      </button>

      <!-- 滚到列底会自动加载下一批；这个按钮是兜底，不要求用户先滚到底 -->
      <button
        v-if="totalCount > items.length"
        :ref="(el) => registerMore(el)"
        :data-type="type"
        class="more"
        @click="emit('load-more', type)"
      >
        加载更多 · 还有 {{ totalCount - items.length }} 个
      </button>
      <EmptyState
        v-if="!totalCount && !slot"
        compact
        text="暂无碎片"
        hint="到提示词库为这一栏添加碎片，或点下方「自定义」。"
      />

      <button class="card add" @click="emit('open-custom', type)">✎ 自定义…</button>
    </div>
  </section>
</template>

<style scoped>
.reel {
  flex: 1 1 0;
  min-width: 148px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel);
  overflow: hidden;
}

.reel-head {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
  padding: 5px 8px;
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-sm);
  cursor: pointer;
  user-select: none;
  transition: background-color var(--dur-fast) var(--ease);
}

/* 整行表头都能切锁定，不必去点小图标 */
.reel-head:hover {
  background: var(--panel-2);
}

.reel-type {
  font-weight: 600;
}

.reel-count {
  color: var(--muted);
  font-size: var(--fs-xs);
  margin-left: auto;
}

.pin-ico {
  flex: none;
  color: var(--muted);
  font-size: var(--fs-sm);
  line-height: 1;
}

.reel-head.on .pin-ico {
  color: var(--warn);
}

/* 列头定位：把已选碎片滚回可视区中间 */
.locate-ico {
  flex: none;
  display: inline-flex;
  align-items: center;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  line-height: 1;
  transition: color var(--dur-fast) var(--ease);
}

.locate-ico svg {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.4;
  stroke-linecap: round;
}

.locate-ico:hover {
  color: var(--accent-link);
}

/* 列头下方：当前选中的碎片，替代旧版底部 8/8 的信息 */
.reel-picked {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
  padding: 2px 6px;
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-xs);
  color: var(--muted);
}

.picked-label {
  flex: none;
  color: var(--accent-link);
}

.picked-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.picked-x {
  flex: none;
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: var(--fs-xs);
  transition: color var(--dur-fast) var(--ease);
}

.picked-x:hover {
  color: var(--danger);
}

.reel-body {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  padding: var(--gap-xs);
}

/* 列尾留白：最后一张卡片也要能滚到列中间。
   没有这段空白时 scrollIntoView({block:'center'}) 会被容器末端卡住，
   选中列表末尾那条永远贴在最下面。 */
.reel-body::after {
  content: '';
  flex: 0 0 45%;
}

.card {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  text-align: left;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
  padding: 5px 7px;
  transition:
    color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}

.card:hover {
  border-color: var(--primary);
  background: var(--panel-3);
}

.card.on {
  border-color: var(--primary);
  background: var(--primary-soft);
}

/* 检索命中：整卡描边 + 关键词着色，便于定位 */
.card.hit {
  border-color: var(--warn);
}

.card-text .mark {
  color: var(--warn);
  font-weight: 600;
}

.card.custom {
  border-color: var(--warn);
}

.card-text {
  font-size: var(--fs-xs);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-meta {
  font-size: var(--fs-xs);
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-self {
  color: var(--accent-link);
  border: 1px solid currentColor;
  border-radius: var(--radius-sm);
  padding: 0 2px;
  margin-left: var(--gap-xs);
}

.more {
  border: 1px dashed var(--border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--muted);
  font-size: var(--fs-xs);
  padding: var(--gap-xs);
  transition:
    color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease);
}

.more:hover {
  border-color: var(--primary);
  color: var(--accent-link);
}

.card.add {
  color: var(--muted);
  border-style: dashed;
}

/* 1366 / 1024 收一档：窄屏时控制条自动换行，滚筒再窄一点 */
@media (max-width: 1280px) {
  .reel {
    min-width: 132px;
  }
}
</style>