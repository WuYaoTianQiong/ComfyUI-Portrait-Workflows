<script setup lang="ts">
import { computed } from 'vue'

/**
 * 参考图库统一卡片（阶段 2.1 共享底座）。
 *
 * 视觉数值严格对齐《施工手册》§5 与「§5 补充实测项」：
 * - 卡片：圆角 20px、内边距 8px、底色 #262626；
 * - 缩略图容器：圆角 18px，比例由页面决定（姿势 3:4 / 服装 2:3 / 人像 4:5）；
 * - 标题：12px / 600、行高 16.5px、两行截断、最小高 36px；
 * - 辅助行：11px / 400 #a1a1a1（人像 ID 行 10px）；
 * - 左上编号角标：高 19px、圆角 8px、底 rgba(0,0,0,.7)、白字 10px / 700、内边距 2px 6px、
 *   距缩略图左 / 上各 8px；
 * - 右上角度角标：高 19px、圆角 8px、底 rgba(255,255,255,.9)、字 #18181b 10px / 600；
 * - 「加入配方 / 已选」：未选 80 × 24.5、已选 58 × 24.5、圆角 10px、11px / 600、
 *   内边距 4px 10px，未选底 rgba(0,0,0,.75)、已选底 #009966。
 *
 * 浅色主题：卡片底 / 标题 / 辅助字均走 `styles/tokens.css` 的同名令牌，
 * 浅色下自动变为白卡 + `#111111` 标题 + `#4b5563` 辅助字，无需组件内分支。
 */
const props = withDefaults(
  defineProps<{
    /** 缩略图地址；为 null / 空串时渲染占位，绝不输出空 src */
    src: string | null
    title: string
    alt?: string
    /** 缩略图比例：姿势 3:4、服装 2:3、人像 4:5 */
    aspect?: '3/4' | '2/3' | '4/5'
    /** 缩略图填充方式：姿势 / 人像 object-cover，服装 object-contain */
    fit?: 'cover' | 'contain'
    /** 左上编号角标 */
    badge?: string
    /** 右上角度角标 */
    angle?: string
    /** 辅助行左侧（体系 / 分类等） */
    metaLeft?: string
    /** 辅助行右侧（动作分类等） */
    metaRight?: string
    /** 辅助行是否使用等宽小字号（单张模式的 ID 行） */
    metaMono?: boolean
    /** 是否渲染「加入配方 / 已选」按钮 */
    selectable?: boolean
    /** 已选态（背景切 #009966，文案变「已选」） */
    selected?: boolean
    selectLabel?: string
    selectedLabel?: string
    /** 占位文案 */
    placeholder?: string
  }>(),
  {
    alt: '',
    aspect: '3/4',
    fit: 'cover',
    badge: '',
    angle: '',
    metaLeft: '',
    metaRight: '',
    metaMono: false,
    selectable: false,
    selected: false,
    selectLabel: '加入配方',
    selectedLabel: '已选',
    placeholder: '暂无预览',
  },
)

const emit = defineEmits<{
  (e: 'open'): void
  (e: 'toggle-select'): void
}>()

const thumbStyle = computed(() => ({ aspectRatio: props.aspect.replace('/', ' / ') }))
const hasMeta = computed(() => Boolean(props.metaLeft || props.metaRight))
const imageAlt = computed(() => props.alt || props.title)
</script>

<template>
  <article class="ref-card">
    <div
      class="ref-card__thumb"
      :style="thumbStyle"
      role="button"
      tabindex="0"
      :aria-label="`查看大图：${title}`"
      @click="emit('open')"
      @keydown.enter.prevent="emit('open')"
      @keydown.space.prevent="emit('open')"
    >
      <img
        v-if="src"
        class="ref-card__img"
        :class="`is-${fit}`"
        :src="src"
        :alt="imageAlt"
        loading="lazy"
        draggable="false"
      />
      <div v-else class="ref-card__placeholder" role="img" :aria-label="`${title}：${placeholder}`">
        <span>{{ placeholder }}</span>
      </div>

      <span v-if="badge" class="ref-card__badge">{{ badge }}</span>
      <span v-if="angle" class="ref-card__angle">{{ angle }}</span>

      <button
        v-if="selectable"
        type="button"
        class="ref-card__select"
        :class="{ 'is-selected': selected }"
        :aria-pressed="selected"
        :title="selected ? '点击从角色配方中移除' : '加入角色配方'"
        @click.stop="emit('toggle-select')"
      >
        <svg v-if="selected" class="ref-card__icon" viewBox="0 0 12 12" aria-hidden="true">
          <path
            d="M2.2 6.3 4.8 8.9 9.8 3.4"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        <svg v-else class="ref-card__icon" viewBox="0 0 12 12" aria-hidden="true">
          <path
            d="M6 2v8M2 6h8"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
          />
        </svg>
        {{ selected ? selectedLabel : selectLabel }}
      </button>
    </div>

    <div class="ref-card__body">
      <div class="ref-card__title" :title="title">{{ title }}</div>
      <div v-if="hasMeta" class="ref-card__meta" :class="{ 'is-mono': metaMono }">
        <span class="ref-card__meta-left">{{ metaLeft }}</span>
        <span class="ref-card__meta-right">{{ metaRight }}</span>
      </div>
    </div>

    <!-- 卡片底部扩展区（姿势的 5 角度缩略条等）；`margin-top:auto` 让它贴底 -->
    <div v-if="$slots.default" class="ref-card__extra">
      <slot />
    </div>
  </article>
</template>

<style scoped>
/* 深色主题数值来自 §5；浅色由 tokens 覆盖。 */
.ref-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  padding: 8px;
  border-radius: 20px;
  background: var(--surface-card);
  transition:
    transform var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}

.ref-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-2);
}

.ref-card__thumb {
  position: relative;
  width: 100%;
  overflow: hidden;
  border-radius: 18px;
  background: var(--surface-thumb);
  cursor: zoom-in;
}

.ref-card__thumb:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

.ref-card__img {
  display: block;
  width: 100%;
  height: 100%;
  transition: transform 0.3s var(--ease);
}

.ref-card__img.is-cover {
  object-fit: cover;
}

.ref-card__img.is-contain {
  object-fit: contain;
}

.ref-card:hover .ref-card__img {
  transform: scale(1.05);
}

.ref-card__placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.5;
  background: var(--surface-raised);
}

/* 左上编号角标：高 19px / 圆角 8px / 内边距 2px 6px / 10px 700 */
.ref-card__badge {
  position: absolute;
  top: 8px;
  left: 8px;
  box-sizing: border-box;
  min-height: 19px;
  padding: 2px 6px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.7);
  color: #ffffff;
  font-size: 10px;
  font-weight: 700;
  line-height: 15px;
  white-space: nowrap;
}

/* 右上角度角标：高 19px / 圆角 8px / 白底深字 */
.ref-card__angle {
  position: absolute;
  top: 8px;
  right: 8px;
  box-sizing: border-box;
  min-height: 19px;
  padding: 2px 6px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.9);
  color: #18181b;
  font-size: 10px;
  font-weight: 600;
  line-height: 15px;
  white-space: nowrap;
  box-shadow: var(--shadow-1);
}

/* 加入配方 / 已选：24.5px 高、圆角 10px、11px 600、内边距 4px 10px */
.ref-card__select {
  position: absolute;
  bottom: 8px;
  left: 8px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  box-sizing: border-box;
  height: 24.5px;
  padding: 4px 10px;
  border: 0;
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.75);
  color: #ffffff;
  font-size: 11px;
  font-weight: 600;
  line-height: 16.5px;
  white-space: nowrap;
  transition: background-color var(--dur-fast) var(--ease);
}

.ref-card__select:hover {
  background: var(--btn-inverse-bg);
  color: var(--on-inverse);
}

.ref-card__select.is-selected {
  background: var(--accent-green);
  color: var(--on-primary);
}

.ref-card__select.is-selected:hover {
  background: var(--accent-green-strong);
}

.ref-card__icon {
  width: 12px;
  height: 12px;
  flex: none;
}

.ref-card__body {
  padding: 10px 6px 6px;
}

/* 标题：12px / 600 / 行高 16.5px / 两行截断 / 最小高 36px */
.ref-card__title {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 36px;
  color: var(--text-strong);
  font-size: 12px;
  font-weight: 600;
  line-height: 16.5px;
}

/* 辅助行：11px / 400 / #a1a1a1 */
.ref-card__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 4px;
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 400;
  line-height: 1.5;
}

.ref-card__meta.is-mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10px;
}

.ref-card__meta-left {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ref-card__meta-right {
  flex: none;
  font-weight: 500;
  color: var(--text-muted);
}

.ref-card__extra {
  margin-top: auto;
  padding-top: 4px;
}
</style>