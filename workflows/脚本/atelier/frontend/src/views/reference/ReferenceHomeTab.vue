<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  isNsfwCostumeItem,
  isNsfwPoseItem,
  referenceImageUrl,
} from '../../api/reference'
import type { CostumeItem, PortraitItem, ReferenceItemDto } from '../../api/reference'
import {
  useReferenceCostumes,
  useReferencePortraits,
  useReferencePoses,
} from '../../composables/useReferenceLibrary'
import { useReferenceRecipeDraft } from '../../composables/useReferenceRecipeDraft'
import { useReferenceSafeMode } from '../../composables/useReferenceSafeMode'
import { useToast } from '../../composables/useToast'

import { poseDepthMode, poseThumbnailUrl } from './components/poseView'
import { withReferenceTab } from './referenceDeepLink'

/**
 * 图库总览（阶段 2.3b 首页）。
 *
 * 迁移 React `gallery-web/src/routes/index.tsx` 的首页四项（§7「首页」行）：
 * 1. 三库入口卡片：数量 Badge + 4 张缩略图（§5 补充实测：416×190、圆角 20px、
 *    内边距 16px；缩略图 91.5×122（3:4）、圆角 10px、4 列 gap 6px；标题 16px/600；
 *    色点 6×6px）；
 * 2. 当前角色配方摘要：三槽缩略图 + 进入合成台 n/3（§5 补充实测：槽 410.66×56、
 *    圆角 14px、内边距 8px、gap 8px；缩略图 40×40、圆角 10px）；
 * 3. 随机捏人：按安全模式过滤 nsfw，三库各随机取一条，可连续触发；
 * 4. 素材来源说明段落（文案与 React 侧逐字一致）。
 *
 * 明确不做：精选 / 热门（§7 阶段 0.3 冻结为「不迁移」，React 首页本就没有渲染）。
 *
 * 数据全部来自阶段 1.2 的 `useReferenceLibrary`，本文件只做展示派生；
 * 图片地址唯一出口是 `referenceImageUrl`（姿势经 `poseThumbnailUrl` 转发），
 * 绝不做字符串前缀拼接（§9 R7 的 `//api/...` 事故）。
 */

/** 本页可以跳转的目标页签（设置页与首页自身不在首页入口范围内）。 */
type HomeTargetTab = 'pose' | 'costume' | 'portrait' | 'studio'

const route = useRoute()
const router = useRouter()

/**
 * 跳转到目标页签。
 *
 * 与 `ReferenceView.selectTab` 保持同一套 URL 规则：只覆盖 `tab`、剔除已废弃的
 * `shell` / `path`、用 `replace` 不堆积历史。首页因此不依赖父组件事件，
 * 单独挂载也能工作。
 */
function goTab(tab: HomeTargetTab): void {
  if (route.query.tab === tab) return
  void router.replace({
    path: route.path,
    query: withReferenceTab(route.query, tab),
    hash: route.hash,
  })
}

const poses = useReferencePoses()
const costumes = useReferenceCostumes()
const portraits = useReferencePortraits()

const { safeMode } = useReferenceSafeMode()
const draft = useReferenceRecipeDraft()
const toast = useToast()

// ---------------------------------------------------------------------------
// DTO 还原（只为取图片地址）
// ---------------------------------------------------------------------------

/**
 * 服装条目 → `ReferenceItemDto` 形状。
 *
 * 数据层把 DTO 映射成中文键后丢掉了原始字段名，但图片地址的唯一出口必须是
 * `referenceImageUrl`（§0 铁律 5 / §9 R7），所以按字段语义原样回填。
 * 本函数只服务 `kind=thumb`，其余字段填占位值即可。
 */
function costumeDto(item: CostumeItem): ReferenceItemDto {
  return {
    id: item.id,
    library: item.library ?? 'costume',
    name: item.服装名称,
    subtitle: item.日文名称 ?? '',
    group: item.分类,
    facet: '',
    angle: '',
    tags: Array.isArray(item.标签) ? item.标签 : [],
    keywords: item.关键词,
    thumb_url: item.缩略图 || null,
    image_url: item.原图 || null,
    depth_url: null,
    depth_thumb_url: null,
    hot: false,
    featured: false,
    nsfw: Boolean(item.nsfw),
    remote: Boolean(item.remote),
    number: '',
    source_url: item.sourceUrl ?? null,
    search_text: item.检索,
  }
}

/** 人像条目 → `ReferenceItemDto` 形状（口径同 `costumeDto`）。 */
function portraitDto(item: PortraitItem): ReferenceItemDto {
  return {
    id: item.id,
    library: 'portrait',
    name: item.标题,
    subtitle: item.发型名称,
    group: item.分区,
    facet: item.发长,
    angle: '',
    tags: [],
    keywords: '',
    thumb_url: item.缩略图 || null,
    image_url: item.原图 || null,
    depth_url: null,
    depth_thumb_url: null,
    hot: false,
    featured: false,
    nsfw: Boolean(item.nsfw),
    remote: false,
    number: '',
    source_url: null,
    search_text: item.检索,
  }
}

// ---------------------------------------------------------------------------
// 安全模式过滤（客户端，与 React `randomizeRecipe` 一致）
// ---------------------------------------------------------------------------

/** 安全模式下隐藏的姿势条目（随机池 / 首页缩略图共用）。 */
const visiblePoses = computed(() =>
  safeMode.value ? poses.items.value.filter((item) => !isNsfwPoseItem(item)) : poses.items.value,
)

const visibleCostumes = computed(() =>
  safeMode.value
    ? costumes.items.value.filter((item) => !isNsfwCostumeItem(item))
    : costumes.items.value,
)

/** 人像库在 React `randomizeRecipe` 中不按 nsfw 过滤，这里保持同一口径。 */
const portraitPool = computed(() => portraits.items.value)

/**
 * 首页缩略图的安全过滤。
 *
 * React 首页未做过滤（实测四库 `nsfw` 全为 false，视觉无差异）；Vue 侧在安全
 * 模式下额外隐藏敏感条目，避免首页露出 18+ 缩略图。数量 Badge 仍取全量
 * `items.length`，与后端 `total` 保持同一口径（本任务验收要求）。
 */
const visiblePortraits = computed(() =>
  safeMode.value ? portraits.items.value.filter((item) => !item.nsfw) : portraits.items.value,
)

// ---------------------------------------------------------------------------
// 三库入口卡
// ---------------------------------------------------------------------------

interface ThumbView {
  key: string
  src: string | null
  alt: string
}

interface EntryCardView {
  key: 'pose' | 'costume' | 'portrait'
  title: string
  dot: 'emerald' | 'sky' | 'violet'
  total: number
  loading: boolean
  thumbs: ThumbView[]
}

/** 缩略图栅格固定 4 格：数据不足或首屏加载时补占位，避免卡片高度跳动。 */
function padThumbs(list: ThumbView[]): ThumbView[] {
  const filled = list.slice(0, 4)
  for (let index = filled.length; index < 4; index += 1) {
    filled.push({ key: `empty-${index}`, src: null, alt: '' })
  }
  return filled
}

/** 姿势缩略图取「每体系首角度」，与 React `groups.slice(0,4)` + `order[0]` 一致。 */
const poseThumbs = computed<ThumbView[]>(() => {
  const source = safeMode.value
    ? poses.groups.value.filter((group) => !isNsfwPoseItem(group))
    : poses.groups.value
  const thumbs: ThumbView[] = []
  for (const group of source) {
    if (thumbs.length >= 4) break
    const item = group.order[0] ?? group.items[0]
    if (!item) continue
    thumbs.push({ key: group.key, src: poseThumbnailUrl(item, false), alt: group.name })
  }
  return padThumbs(thumbs)
})

const costumeThumbs = computed<ThumbView[]>(() =>
  padThumbs(
    visibleCostumes.value.slice(0, 4).map((item) => ({
      key: item.id,
      src: referenceImageUrl(costumeDto(item), 'thumb'),
      alt: item.服装名称,
    })),
  ),
)

const portraitThumbs = computed<ThumbView[]>(() =>
  padThumbs(
    visiblePortraits.value.slice(0, 4).map((item) => ({
      key: item.id,
      src: referenceImageUrl(portraitDto(item), 'thumb'),
      alt: item.标题,
    })),
  ),
)

const entryCards = computed<EntryCardView[]>(() => [
  {
    key: 'pose',
    title: '动作姿势库',
    dot: 'emerald',
    total: poses.items.value.length,
    loading: poses.loading.value,
    thumbs: poseThumbs.value,
  },
  {
    key: 'costume',
    title: '服装穿搭库',
    dot: 'sky',
    total: costumes.items.value.length,
    loading: costumes.loading.value,
    thumbs: costumeThumbs.value,
  },
  {
    key: 'portrait',
    title: '人像颜值库',
    dot: 'violet',
    total: portraits.items.value.length,
    loading: portraits.loading.value,
    thumbs: portraitThumbs.value,
  },
])

/** 千分位展示，与 React `toLocaleString('zh-CN')` 一致。 */
function formatCount(value: number): string {
  return value.toLocaleString('zh-CN')
}

// ---------------------------------------------------------------------------
// 当前角色配方摘要
// ---------------------------------------------------------------------------

interface RecipeSlotView {
  key: 'portrait' | 'costume' | 'pose'
  label: string
  hint: string
  tab: 'portrait' | 'costume' | 'pose'
  /** 该槽已选条目数（多选口径）。 */
  count: number
  /** 首条名称；多选时展示为「首条名称 等 N 张」。 */
  name: string | null
  /** 首条缩略图。 */
  thumb: string | null
}

const recipeSlots = computed<RecipeSlotView[]>(() => {
  const portrait = draft.portrait.value
  const costume = draft.costume.value
  const posed = draft.pose.value
  const portraitFirst = portrait[0]
  const costumeFirst = costume[0]
  const poseFirst = posed[0]

  return [
    {
      key: 'portrait',
      label: '人像',
      hint: '选择人像',
      tab: 'portrait',
      count: portrait.length,
      name: portraitFirst ? portraitFirst.发型名称 || portraitFirst.标题 || null : null,
      thumb: portraitFirst ? referenceImageUrl(portraitDto(portraitFirst), 'thumb') : null,
    },
    {
      key: 'costume',
      label: '服装',
      hint: '选择服装',
      tab: 'costume',
      count: costume.length,
      name: costumeFirst ? costumeFirst.服装名称 || null : null,
      thumb: costumeFirst ? referenceImageUrl(costumeDto(costumeFirst), 'thumb') : null,
    },
    {
      key: 'pose',
      label: '姿势',
      hint: '选择姿势',
      tab: 'pose',
      count: posed.length,
      name: poseFirst ? poseFirst.item.姿势名称 || null : null,
      thumb: poseFirst ? poseThumbnailUrl(poseFirst.item, poseFirst.useDepth) : null,
    },
  ]
})

/** 三槽选中的条目总数（多选口径，用于按钮副文案）。 */
const selectedCount = computed(() => draft.totalSelected.value)
const countLabel = computed(() => draft.countLabel.value)
const hasDraft = computed(() => selectedCount.value > 0)

// ---------------------------------------------------------------------------
// 加载状态与随机捏人
// ---------------------------------------------------------------------------

const loading = computed(
  () => poses.loading.value || costumes.loading.value || portraits.loading.value,
)

const loadError = computed(
  () => poses.error.value || costumes.error.value || portraits.error.value,
)

function reload(): void {
  // 三个 load 内部各自捕获异常，不会产生未处理 rejection。
  void Promise.all([poses.load(), costumes.load(), portraits.load()])
}

/** 从池中均匀取一条；空池返回 undefined，调用方据此保留原槽位（React 语义）。 */
function pickRandom<T>(pool: readonly T[]): T | undefined {
  if (pool.length === 0) return undefined
  return pool[Math.floor(Math.random() * pool.length)]
}

/**
 * 随机捏人：三库各随机取一条填入配方。
 *
 * - 安全模式下姿势 / 服装池按 `nsfw` 过滤，人像池不过滤（逐条对齐
 *   React `randomizeRecipe`）；
 * - 某个库为空时保留该槽位原值，不清空用户已有选择；
 * - 姿势槽带上当前全局白模 / 深度图模式（React `poseDepthMode`）；
 * - 可连续触发，每次重新抽样。
 */
function randomize(): void {
  if (loading.value) {
    toast.info('图库仍在加载，请稍候再随机')
    return
  }

  const nextPortrait = pickRandom(portraitPool.value)
  const nextCostume = pickRandom(visibleCostumes.value)
  const nextPose = pickRandom(visiblePoses.value)

  if (nextPortrait) draft.setPortrait(nextPortrait)
  if (nextCostume) draft.setCostume(nextCostume)
  if (nextPose) draft.setPose(nextPose, poseDepthMode.value)

  if (!nextPortrait && !nextCostume && !nextPose) {
    toast.error('图库加载失败或为空，无法随机捏人')
    return
  }

  toast.success(safeMode.value ? '已随机抽取一套角色配方（安全模式）' : '已随机抽取一套角色配方')
}

onMounted(() => {
  // 三个库并行拉取；load 内部自带 in-flight 复用与错误捕获。
  void Promise.all([poses.load(), costumes.load(), portraits.load()])
})
</script>

<template>
  <div class="ref-home" data-testid="reference-home">
    <header class="ref-home__head">
      <!--
        `tab-placeholder__title` 是 ReferenceView 骨架期冻结的「页签面板标题」契约，
        真实页签沿用同一 class（与姿势库一致），使页签直达断言稳定。
      -->
      <h1 class="ref-home__title tab-placeholder__title" data-testid="reference-home-title">
        图库总览
      </h1>
      <p class="ref-home__desc">三大图库入口、当前角色配方与随机捏人；挑选人像 / 服装 / 姿势后进入合成台。</p>
    </header>

    <!-- 三库入口卡片：数量 Badge + 4 张缩略图 -->
    <div class="ref-home__entries" data-testid="reference-home-entries">
      <button
        v-for="card in entryCards"
        :key="card.key"
        type="button"
        class="home-card"
        :data-testid="`home-entry-${card.key}`"
        @click="goTab(card.key)"
      >
        <div class="home-card__head">
          <h2 class="home-card__title">
            <span class="home-card__dot" :class="`is-${card.dot}`" aria-hidden="true" />
            <span class="home-card__title-text">{{ card.title }}</span>
          </h2>
          <span class="home-card__count" :data-testid="`home-entry-count-${card.key}`">
            {{ card.loading && card.total === 0 ? '…' : formatCount(card.total) }}
          </span>
        </div>

        <div class="home-card__thumbs">
          <template v-for="thumb in card.thumbs" :key="thumb.key">
          <img
            v-if="thumb.src"
            :src="thumb.src"
            :alt="thumb.alt"
            loading="lazy"
            class="home-card__thumb"
          />
        </template>
          <span
            v-for="thumb in card.thumbs.filter((entry) => !entry.src)"
            :key="`placeholder-${thumb.key}`"
            class="home-card__thumb is-empty"
            aria-hidden="true"
          />
        </div>
      </button>
    </div>

    <p v-if="loadError" class="ref-home__error" role="alert">
      图库加载失败：{{ loadError }}
      <button type="button" class="ref-home__retry" @click="reload">重试</button>
    </p>

    <!-- 当前角色配方摘要：三槽 + 进入合成台 n/3 -->
    <section class="home-recipe" data-testid="reference-home-recipe">
      <div class="home-recipe__head">
        <div class="home-recipe__title-group">
          <h2 class="home-recipe__title">当前角色配方</h2>
          <span class="home-recipe__total" data-testid="reference-home-recipe-total">
            共 {{ selectedCount }} 张
          </span>
        </div>
        <div class="home-recipe__actions">
          <button
            type="button"
            class="home-btn home-btn--ghost"
            data-testid="reference-home-random"
            :disabled="loading"
            :title="loading ? '图库加载中，请稍候' : '从三个库中各随机抽取一条'"
            @click="randomize"
          >
            <svg class="home-btn__icon" viewBox="0 0 16 16" aria-hidden="true">
              <rect x="2.2" y="2.2" width="11.6" height="11.6" rx="2.4" fill="none" stroke="currentColor" stroke-width="1.3" />
              <circle cx="5.8" cy="5.8" r="0.9" fill="currentColor" />
              <circle cx="10.2" cy="10.2" r="0.9" fill="currentColor" />
              <circle cx="10.2" cy="5.8" r="0.9" fill="currentColor" />
              <circle cx="5.8" cy="10.2" r="0.9" fill="currentColor" />
            </svg>
            随机捏人
          </button>
          <button
            type="button"
            class="home-btn home-btn--primary"
            data-testid="reference-home-studio"
            @click="goTab('studio')"
          >
            <svg class="home-btn__icon" viewBox="0 0 16 16" aria-hidden="true">
              <path
                d="M8 2.2 9.3 6 13 7.3 9.3 8.6 8 12.4 6.7 8.6 3 7.3 6.7 6Z"
                fill="none"
                stroke="currentColor"
                stroke-width="1.2"
                stroke-linejoin="round"
              />
            </svg>
            进入合成台 ({{ countLabel }})
          </button>
        </div>
      </div>

      <div class="home-recipe__slots">
        <button
          v-for="slot in recipeSlots"
          :key="slot.key"
          type="button"
          class="home-slot"
          :data-testid="`home-slot-${slot.key}`"
          :title="slot.count ? `已选 ${slot.count} 张${slot.name ? `：${slot.name}` : ''}` : slot.hint"
          @click="goTab(slot.tab)"
        >
          <img
            v-if="slot.thumb"
            :src="slot.thumb"
            :alt="slot.name ?? slot.label"
            loading="lazy"
            class="home-slot__thumb"
          />
          <span v-else class="home-slot__thumb is-empty" aria-hidden="true">
            <svg viewBox="0 0 16 16">
              <path
                d="M8 8.4a2.6 2.6 0 1 0 0-5.2 2.6 2.6 0 0 0 0 5.2Z"
                fill="none"
                stroke="currentColor"
                stroke-width="1.3"
              />
              <path
                d="M3.2 13.2c.5-2.4 2.4-3.8 4.8-3.8s4.3 1.4 4.8 3.8"
                fill="none"
                stroke="currentColor"
                stroke-width="1.3"
                stroke-linecap="round"
              />
            </svg>
          </span>

          <span class="home-slot__body">
            <span class="home-slot__label-row">
              <span class="home-slot__label">{{ slot.label }}</span>
              <span
                v-if="slot.count"
                class="home-slot__count"
                :data-testid="`home-slot-count-${slot.key}`"
              >×{{ slot.count }}</span>
            </span>
            <span v-if="slot.name" class="home-slot__name" :title="slot.name">{{ slot.name }}</span>
            <span v-else class="home-slot__hint">{{ slot.hint }}</span>
          </span>
        </button>
      </div>

      <p v-if="!hasDraft" class="home-recipe__note">
        配方为空，可先随机捏人，或从上方三个图库中各挑一项。
      </p>

      <!-- 供自动化断言：配方槽 n/3（不渲染可见文案） -->
      <span class="home-sr-only" data-testid="reference-home-recipe-count">{{ countLabel }}</span>
    </section>

    <!-- 素材来源：文案与 React `routes/index.tsx` 222-225 行逐字一致 -->
    <p class="ref-home__source">
      素材来源：姿势与现实服装参考图源自 ギア（@giaaibusi）公开分享；二次元服装来自 たき AI · CharaDB，仅收录元数据、图片从来源站点读取，禁止再分发原图；人像库遵循 CC0 1.0 协议。部分姿势含 18+ 内容，默认由安全模式隐藏。
    </p>
  </div>
</template>

<style scoped>
/*
 * 深色主题数值按施工手册 §5 与「§5 补充实测项」：
 * - 入口卡 416 × 190、圆角 20px、内边距 16px；缩略图 91.5 × 122（3:4）、
 *   圆角 10px、4 列 gap 6px；标题 16px / 600；色点 6 × 6px；
 * - 配方槽 410.66 × 56、圆角 14px、内边距 8px、gap 8px；缩略图 40 × 40、圆角 10px。
 * 浅色主题：Vue 主站目前只有深色令牌（同 ReferenceCard 的 TODO）。
 */
.ref-home {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.ref-home__head {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
}

.ref-home__title {
  margin: 0;
  color: var(--text-strong);
  font-size: 20px;
  font-weight: 600;
  line-height: 1.3;
}

.ref-home__desc {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}

/* 三库入口卡：1280 内容区三列、gap 16px → 单卡 416px。 */
.ref-home__entries {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.home-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  box-sizing: border-box;
  min-width: 0;
  height: 190px;
  padding: 16px;
  border: 0;
  border-radius: 20px;
  background: var(--surface-card);
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    background-color var(--dur-fast) var(--ease),
    transform var(--dur-fast) var(--ease);
}

.home-card:hover {
  background: var(--surface-card-hover);
}

.home-card:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

.home-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.home-card__title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  margin: 0;
  color: var(--text-strong);
  font-size: 16px;
  font-weight: 600;
  line-height: 1.3;
}

.home-card__title-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 色点 6 × 6px */
.home-card__dot {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 9999px;
}

.home-card__dot.is-emerald {
  background: #10b981;
}

.home-card__dot.is-sky {
  background: #0ea5e9;
}

.home-card__dot.is-violet {
  background: #8b5cf6;
}

/* 数量 Badge：次要徽标，12px / 500、全圆 */
.home-card__count {
  flex: none;
  min-width: 32px;
  padding: 2px 8px;
  border-radius: 9999px;
  background: var(--fill-soft);
  color: var(--text-strong);
  font-size: 12px;
  font-weight: 500;
  line-height: 16px;
  text-align: center;
  white-space: nowrap;
}

/* 缩略图 4 列 gap 6px；单格随卡片宽度自适应，比例固定 3:4。 */
.home-card__thumbs {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
  margin-top: 12px;
}

.home-card__thumb {
  display: block;
  width: 100%;
  aspect-ratio: 3 / 4;
  border-radius: 10px;
  background: var(--surface-thumb);
  object-fit: cover;
}

.home-card__thumb.is-empty {
  background: var(--surface-inset);
}

.ref-home__error {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 12px 0 0;
  padding: 10px 12px;
  border: 1px solid var(--danger-border);
  border-radius: 10px;
  background: var(--danger-surface-mid);
  color: var(--danger-text);
  font-size: 12px;
  line-height: 1.6;
}

.ref-home__retry {
  height: 26px;
  padding: 0 10px;
  border: 1px solid var(--danger-border-strong);
  border-radius: 8px;
  background: transparent;
  color: var(--danger-text);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}

/* 配方摘要：圆角 20px、内边距 16px、底 #262626 */
.home-recipe {
  margin-top: 16px;
  padding: 16px;
  border-radius: 20px;
  background: var(--surface-panel);
}

.home-recipe__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.home-recipe__title {
  margin: 0;
  color: var(--text-strong);
  font-size: 16px;
  font-weight: 600;
  line-height: 1.3;
}

/* 标题 + 总选中数（多选口径） */
.home-recipe__title-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.home-recipe__total {
  flex: none;
  padding: 1px 8px;
  border-radius: 9999px;
  background: var(--fill-medium);
  color: var(--text-strong);
  font-size: 11px;
  font-weight: 500;
  line-height: 17px;
}

.home-recipe__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

/* 按钮：32px 高、圆角 8px、12px / 500（对齐 React Button size=sm）。 */
.home-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  box-sizing: border-box;
  height: 32px;
  padding: 0 12px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
  transition:
    background-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.home-btn__icon {
  width: 14px;
  height: 14px;
  flex: none;
}

.home-btn--ghost {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-strong);
}

.home-btn--ghost:hover:not(:disabled) {
  background: var(--fill-subtle);
}

.home-btn--primary {
  border: 0;
  background: var(--btn-inverse-bg);
  color: var(--on-inverse);
  font-weight: 600;
}

.home-btn--primary:hover {
  background: var(--btn-inverse-bg-hover-strong);
}

.home-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.home-btn:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

/* 三槽：410.66 × 56、圆角 14px、内边距 8px、gap 8px。 */
.home-recipe__slots {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.home-slot {
  display: flex;
  align-items: center;
  gap: 8px;
  box-sizing: border-box;
  min-width: 0;
  height: 56px;
  padding: 8px;
  border: 0;
  border-radius: 14px;
  background: var(--surface-deep);
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.home-slot:hover {
  background: var(--surface-card-hover);
}

.home-slot:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

/* 缩略图 40 × 40、圆角 10px */
.home-slot__thumb {
  display: block;
  flex: none;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: var(--surface-thumb);
  object-fit: cover;
}

.home-slot__thumb.is-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
}

.home-slot__thumb.is-empty svg {
  width: 18px;
  height: 18px;
}

.home-slot__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

/* 槽位标签行：名称 + 多选数量 */
.home-slot__label-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.home-slot__count {
  flex: none;
  color: var(--text-strong);
  font-size: 10px;
  font-weight: 600;
  line-height: 1.4;
}

/* 槽位标签 10px，名称 12px / 500（React text-[10px] / text-xs） */
.home-slot__label {
  color: var(--text-muted);
  font-size: 10px;
  line-height: 1.4;
}

.home-slot__name {
  overflow: hidden;
  color: var(--text-strong);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-slot__hint {
  overflow: hidden;
  color: var(--accent-link);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-recipe__note {
  margin: 8px 0 0;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.6;
}

/* 素材来源段落：11px、行高 relaxed */
.ref-home__source {
  margin: 16px 0 8px;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.6;
}

/* 仅供自动化读取的状态值 */
.home-sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}

/* React `sm:grid-cols-3` 的等价断点：<640px 单列，避免 390px 横向溢出。 */
@media (max-width: 639px) {
  .ref-home__entries,
  .home-recipe__slots {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>