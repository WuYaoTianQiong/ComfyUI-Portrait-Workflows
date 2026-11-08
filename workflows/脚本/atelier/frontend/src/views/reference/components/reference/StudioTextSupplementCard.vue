<script setup lang="ts">
/**
 * 合成台「文本补充」全宽卡（方案 §5.5，2026-11-06 拍板）。
 *
 * 位置：素材区之后、组合清单之前；页面顺序 = 选图 / 选文字 → 看清单 → 调参数。
 *
 * 口径：
 * - 八类分两列：左「与参考槽对应」4 类，右「画面修饰」4 类；
 * - 默认折叠（不选时不占高度），卡头常显「已选 N 条」；
 * - 每类一行：彩色归属标签（放在类型名之前）+ 类型名 + 已选 chips（可删）
 *   + 「选择碎片」按钮 + `n/2 条 · x 字`；
 * - 单类软上限 2 条，达到上限后按钮禁用（弹层内也做同一道拦截）；
 * - 底部负向输入常显，文案说明「最终负向 = 后端自动抽取 + 你填写的内容」。
 *
 * 纯受控组件：不持有任何业务真源，所有变更通过 `update:*` 交回页面；
 * 弹层只加载当前类型（禁止一次拉 8 类）。
 */

import { computed, nextTick, ref } from 'vue'

import type { FragmentType } from '../../../../constants'
import {
  EMPTY_SUPPLEMENT_FLAGS,
  FRAGMENT_HOMES,
  FRAGMENT_HOME_LABELS,
  IMAGE_SLOT_MODES,
  MAX_FRAGMENTS_PER_TYPE,
  MODIFIER_FRAGMENT_TYPES,

  SLOT_FRAGMENT_TYPES,
  SLOT_TEXT_TYPES,
  cloneRecipeTextFragments,
  countFragmentChars,
  countTextFragments,
  fragmentsOf,
} from '../../../../composables/recipeTextFragments'
import type {
  FragmentHome,
  RecipeSlotKey,
  RecipeSlotMode,
  RecipeSlotModes,
  RecipeSupplementFlags,
  RecipeTextFragments,
  SelectedFragment,
} from '../../../../composables/recipeTextFragments'

import StudioFragmentPicker from './StudioFragmentPicker.vue'

/** 每一类在 UI 上的一行。 */
interface FragmentRow {
  type: FragmentType
  home: FragmentHome
  homeLabel: string
  items: SelectedFragment[]
  chars: number
  /** 该行归属的槽位（修饰层为 null）。 */
  slot: RecipeSlotKey | null
  /** 是否是所属槽的「主类型」行（人像槽只在这里放模式开关，避免重复）。 */
  primary: boolean
}

interface FragmentColumn {
  key: 'slot' | 'modifier'
  title: string
  rows: FragmentRow[]
}

const props = defineProps<{
  /** 八类已选碎片（受控真源在页面 / 草稿单例）。 */
  modelValue: RecipeTextFragments
  /** 用户手填负向提示词。 */
  negativePrompt: string
  /** 安全模式开关：透传给碎片弹层做服务端过滤。 */
  safeMode: boolean
  /** 已选「画风技术」碎片 → 画风预设锁定（页面计算后回传）。 */
  styleLocked: boolean
  /** 三槽模式：用于显示「补充 / 替代」并切换（P2 替代态）。 */
  slotModes?: RecipeSlotModes
  /** P4 跨源补充开关：image 模式下按槽控制文本是否发送。 */
  supplementFlags?: RecipeSupplementFlags
  /** P4 同源整套随机的来源名；仅展示。 */
  recipeSourceName?: string
  /** 人物组名（默认人物A；人物B 传「人物B」，避免两卡文案相同）。 */
  personLabel?: string
  /** 人物B 等第二组的 testid 前缀（默认空，保持 A 组契约不变）。 */
  testIdPrefix?: string
}>()

const prefix = computed(() => props.testIdPrefix ?? '')
const personLabel = computed(() => props.personLabel ?? '人物A')

const emit = defineEmits<{
  'update:modelValue': [value: RecipeTextFragments]
  'update:negativePrompt': [value: string]
  /** 切换某一槽的图片 / 文本模式（父级负责双人 / 素体校验）。 */
  'update:slotMode': [slot: RecipeSlotKey, mode: RecipeSlotMode]
  /** 打开 / 关闭某一槽的跨源文本补充（仅 image 模式有意义）。 */
  'update:supplement': [slot: RecipeSlotKey, enabled: boolean]
}>()

/** 缺省按全图片模式展示，兼容 P1 调用方。 */
const modes = computed<RecipeSlotModes>(() => props.slotModes ?? { ...IMAGE_SLOT_MODES })

/** 缺省全关，兼容未传该字段的旧调用方。 */
const supplements = computed<RecipeSupplementFlags>(
  () => props.supplementFlags ?? EMPTY_SUPPLEMENT_FLAGS,
)

/** 默认折叠：没选任何碎片时只占一行卡头。 */
const expanded = ref(false)

/** 根节点 ref：`expand()` 需要滚动到卡片位置。 */
const cardRef = ref<HTMLElement | null>(null)

/** 当前打开弹层的类型；null = 未打开。 */
const pickerType = ref<FragmentType | null>(null)

/** 卡头徽标：八类已选总条数。 */
const selectedCount = computed(() => countTextFragments(props.modelValue))

/** 弹层初始选区：当前类已选条目。 */
const pickerSelected = computed<readonly SelectedFragment[]>(() =>
  pickerType.value ? fragmentsOf(props.modelValue, pickerType.value) : [],
)

/** 槽位对应的主类型（人像槽 = 人物面部）。 */
function primaryTypeOf(slot: RecipeSlotKey): FragmentType {
  return SLOT_TEXT_TYPES[slot][0]!
}

/** 归属 → 槽位；修饰层返回 null。 */
function slotOfHome(home: FragmentHome): RecipeSlotKey | null {
  return home === 'modifier' ? null : home
}

function buildRow(type: FragmentType): FragmentRow {
  const items = fragmentsOf(props.modelValue, type)
  const home = FRAGMENT_HOMES[type]
  const slot = slotOfHome(home)
  return {
    type,
    home,
    homeLabel: FRAGMENT_HOME_LABELS[home],
    items,
    chars: countFragmentChars(items),
    slot,
    primary: slot !== null && primaryTypeOf(slot) === type,
  }
}

/** 两列：左与参考槽对应，右画面修饰（顺序与文档一致）。 */
const columns = computed<FragmentColumn[]>(() => [
  {
    key: 'slot',
    title: `${personLabel.value} · 与参考槽对应`,
    rows: SLOT_FRAGMENT_TYPES.map(buildRow),
  },
  {
    key: 'modifier',
    title: '画面修饰',
    rows: MODIFIER_FRAGMENT_TYPES.map(buildRow),
  },
])

/** 某一槽当前模式（修饰层不参与）。 */
function slotModeOf(slot: RecipeSlotKey | null): RecipeSlotMode | null {
  return slot ? modes.value[slot] : null
}

/** 某一槽的全部文本碎片（人像槽 = 面部 + 身材），用于补充开关 / 字数判定。 */
function slotItemsOf(slot: RecipeSlotKey | null): SelectedFragment[] {
  if (!slot) return []
  return SLOT_TEXT_TYPES[slot].flatMap((type) => fragmentsOf(props.modelValue, type))
}

/** 某一槽的文本总字数（人像槽合并面部 + 身材）。 */
function slotCharsOf(slot: RecipeSlotKey | null): number {
  return countFragmentChars(slotItemsOf(slot))
}

/** 某一槽的补充开关是否打开。 */
function supplementOn(slot: RecipeSlotKey | null): boolean {
  return Boolean(slot && supplements.value[slot])
}

/** 是否展示「作为补充」开关：只有 image 模式的主类型行展示。 */
function canShowSupplementToggle(row: FragmentRow): boolean {
  return Boolean(row.slot && row.primary && slotModeOf(row.slot) === 'image')
}

/** 补充开关是否可用：该槽至少有一条文本。 */
function canToggleSupplement(row: FragmentRow): boolean {
  return Boolean(row.slot && slotItemsOf(row.slot).length > 0)
}

/** 状态标签：text = 替代；image = 补充 / 未生效；empty = 空白。 */
function modeBadgeOf(row: FragmentRow): string {
  const mode = slotModeOf(row.slot)
  if (mode === 'text') return '替代'
  if (mode === 'image') return supplementOn(row.slot) ? '补充' : '未生效'
  return ''
}

/** 补充长文本提示：超过 120 字时提醒容易覆盖图片特征。 */
function supplementLong(row: FragmentRow): boolean {
  return Boolean(row.slot && supplementOn(row.slot) && slotCharsOf(row.slot) > 120)
}

function toggleSupplement(row: FragmentRow): void {
  if (!row.slot || !canToggleSupplement(row)) return
  emit('update:supplement', row.slot, !supplementOn(row.slot))
}

/** 切换按钮文案：text → 改回图片；image / empty → 用文本替代。 */
function modeActionLabel(row: FragmentRow): string {
  return slotModeOf(row.slot) === 'text' ? '改回图片' : '用文本替代'
}

function toggleSlotMode(row: FragmentRow): void {
  const slot = row.slot
  if (!slot) return
  const next: RecipeSlotMode = modes.value[slot] === 'text' ? 'image' : 'text'
  emit('update:slotMode', slot, next)
}

/** 统一发整份新表：父级 / 持久化 / 提交体都以「不可变替换」为口径。 */
function emitFragments(next: RecipeTextFragments): void {
  emit('update:modelValue', next)
}

/** 删除某类第 index 条 chip。 */
function removeFragment(type: FragmentType, index: number): void {
  const current = fragmentsOf(props.modelValue, type)
  if (index < 0 || index >= current.length) return
  const next = cloneRecipeTextFragments(props.modelValue)
  next[type] = current.filter((_, position) => position !== index)
  emitFragments(next)
}

/** 打开某一类的选择弹层（已达上限时按钮已禁用，这里再防御一次）。 */
function openPicker(type: FragmentType): void {
  if (fragmentsOf(props.modelValue, type).length >= MAX_FRAGMENTS_PER_TYPE) return
  pickerType.value = type
}

/** 弹层确认：整类替换（弹层内已保证 ≤ 上限，这里再裁一次）。 */
function onPickerConfirm(fragments: SelectedFragment[]): void {
  const type = pickerType.value
  pickerType.value = null
  if (!type) return
  const next = cloneRecipeTextFragments(props.modelValue)
  next[type] = fragments.slice(0, MAX_FRAGMENTS_PER_TYPE)
  emitFragments(next)
}

/** chips 只展示内容前缀，完整内容放 `title`（提示词可能长达 783 字）。 */
function previewContent(content: string): string {
  return content.length > 14 ? `${content.slice(0, 14)}…` : content
}

function onNegativeInput(event: Event): void {
  const target = event.target as HTMLTextAreaElement | null
  emit('update:negativePrompt', target?.value ?? '')
}

/**
 * 展开并滚动到本卡（槽位卡「去填写」调用）。
 *
 * 只负责视图状态，不触碰任何业务真源。
 */
async function expand(): Promise<void> {
  expanded.value = true
  await nextTick()
  cardRef.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

defineExpose({ expand })

</script>

<template>
  <section ref="cardRef" class="supplement" :data-testid="`${prefix}studio-text-supplement`">
    <header class="supplement__head">
      <button
        type="button"
        class="supplement__toggle"
        :aria-expanded="expanded"
        :data-testid="`${prefix}studio-text-supplement-toggle`"
        @click="expanded = !expanded"
      >
        <span class="supplement__title">文本补充（八类碎片，可选）</span>
        <span class="supplement__badge" :data-testid="`${prefix}studio-text-supplement-count`">
          已选 {{ selectedCount }} 条
        </span>
        <span
          v-if="recipeSourceName"
          class="supplement__source"
          :data-testid="`${prefix}studio-recipe-source`"
          :title="recipeSourceName"
        >
          来源：《{{ recipeSourceName }}》
        </span>
        <span
          v-if="recipeSourceName?.startsWith('跨源实验')"
          class="supplement__experiment"
          :data-testid="`${prefix}studio-atomic-experiment`"
        >
          跨源实验 · 建议人工复核
        </span>
        <span class="supplement__chevron">{{ expanded ? '收起' : '展开' }}</span>
      </button>
    </header>

    <div v-if="expanded" class="supplement__body" :data-testid="`${prefix}studio-text-supplement-body`">
      <p class="supplement__intro">
        图片模式默认不发送前三类文本；需要追加时，在该槽主类型行打开「作为补充」
        （跨源，可能覆盖图片特征）。槽位切到文本模式时，左列对应类碎片作「替代」描述。
        右侧四类始终追加到修饰层。
      </p>

      <div class="supplement__columns">
        <section
          v-for="column in columns"
          :key="column.key"
          class="supplement__column"
          :data-testid="`${prefix}studio-supplement-column-${column.key}`"
        >
          <h3 class="supplement__column-title">{{ column.title }}</h3>

          <div
            v-for="row in column.rows"
            :key="row.type"
            class="supplement__row"
            :class="{ 'is-locked': row.type === '画风技术' && styleLocked }"
            :data-testid="`${prefix}studio-supplement-row-${row.type}`"
          >
            <div class="supplement__row-head">
              <span class="supplement__home" :data-home="row.home">{{ row.homeLabel }}</span>
              <span class="supplement__type">{{ row.type }}</span>
              <span
                v-if="row.slot && modeBadgeOf(row)"
                class="supplement__mode"
                :class="{ 'is-inactive': slotModeOf(row.slot) === 'image' && !supplementOn(row.slot) }"
                :data-mode="slotModeOf(row.slot)"
                :data-supplement="supplementOn(row.slot)"
                :data-testid="`${prefix}studio-supplement-mode-${row.type}`"
              >
                {{ modeBadgeOf(row) }}
              </span>
            </div>

            <div class="supplement__chips">
              <button
                v-for="(item, index) in row.items"
                :key="`${row.type}-${index}`"
                type="button"
                class="supplement__chip"
                :title="item.content"
                :aria-label="`移除${row.type}碎片：${previewContent(item.content)}`"
                :data-testid="`${prefix}studio-supplement-chip-${row.type}-${index}`"
                @click="removeFragment(row.type, index)"
              >
                <span class="supplement__chip-text">{{ previewContent(item.content) }}</span>
                <span class="supplement__chip-remove" aria-hidden="true">移除</span>
              </button>
              <span v-if="!row.items.length" class="supplement__empty">未选</span>
            </div>

            <div class="supplement__row-actions">
              <button
                type="button"
                class="supplement__pick"
                :disabled="row.items.length >= MAX_FRAGMENTS_PER_TYPE"
                :data-testid="`${prefix}studio-supplement-pick-${row.type}`"
                @click="openPicker(row.type)"
              >
                选择碎片
              </button>
              <!-- 槽位模式切换：只放在该槽的主类型行，避免人像两行出现两个同样的开关 -->
              <button
                v-if="row.primary && row.slot"
                type="button"
                class="supplement__mode-toggle"
                :data-testid="`${prefix}studio-supplement-toggle-${row.type}`"
                @click="toggleSlotMode(row)"
              >
                {{ modeActionLabel(row) }}
              </button>
              <!-- P4：跨源补充开关，只在该槽 image 模式的主类型行出现 -->
              <button
                v-if="canShowSupplementToggle(row)"
                type="button"
                class="supplement__supplement-toggle"
                :class="{ 'is-on': supplementOn(row.slot) }"
                :aria-pressed="supplementOn(row.slot)"
                :disabled="!canToggleSupplement(row)"
                :title="
                  canToggleSupplement(row)
                    ? '把该槽文本作为额外特征追加到图片主句'
                    : '该槽还没有文本碎片，先选一条'
                "
                :data-testid="`${prefix}studio-supplement-flag-toggle-${row.type}`"
                @click="toggleSupplement(row)"
              >
                {{ supplementOn(row.slot) ? '补充已开' : '作为补充' }}
              </button>
              <span class="supplement__row-meta">
                {{ row.items.length }}/{{ MAX_FRAGMENTS_PER_TYPE }} 条 · {{ row.chars }} 字
              </span>
              <span
                v-if="row.type === '画风技术' && styleLocked"
                class="supplement__lock"
                :data-testid="`${prefix}studio-supplement-style-lock`"
              >
                已用碎片描述画风
              </span>
            </div>
            <p
              v-if="canShowSupplementToggle(row) && supplementOn(row.slot)"
              class="supplement__supplement-warning"
              :class="{ 'is-long': supplementLong(row) }"
              :data-testid="`${prefix}studio-supplement-warning-${row.type}`"
            >
              跨源补充可能覆盖图片特征{{
                supplementLong(row)
                  ? `；当前 ${slotCharsOf(row.slot)} 字，建议 ≤120 字`
                  : ''
              }}
            </p>
          </div>
        </section>
      </div>

      <div class="supplement__negative">
        <label class="supplement__negative-label" :for="`${prefix}studio-negative-prompt`">
          负向提示词（可选）
        </label>
        <textarea
          :id="`${prefix}studio-negative-prompt`"
          class="supplement__negative-input"
          rows="3"
          :value="negativePrompt"
          placeholder="例如：多余手指、文字水印、塑料质感"
          :data-testid="`${prefix}studio-negative-prompt`"
          @input="onNegativeInput"
        />
        <p class="supplement__negative-hint" :data-testid="`${prefix}studio-negative-hint`">
          最终负向 = 后端自动抽取 + 你填写的内容
        </p>
      </div>
    </div>

    <StudioFragmentPicker
      v-if="pickerType"
      :fragment-type="pickerType"
      :selected="pickerSelected"
      :safe-mode="safeMode"
      @confirm="onPickerConfirm"
      @close="pickerType = null"
    />
  </section>
</template>

<style scoped>
/* 与 ReferenceSectionCard 同规格：24px / 圆角 22 / --surface-raised */
.supplement {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  padding: 24px;
  border-radius: 22px;
  background: var(--surface-raised);
}

.supplement__head {
  display: flex;
  align-items: center;
  min-width: 0;
}

/* 卡头整行可点：标题、计数、展开/收起都在同一个按钮里 */
.supplement__toggle {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-sm);
  box-sizing: border-box;
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text-strong);
  text-align: left;
}

.supplement__toggle:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 3px;
}

.supplement__title {
  color: var(--text-strong);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
}

.supplement__badge {
  padding: 1px 8px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill);
  color: var(--text-body);
  font-size: 12px;
  line-height: 1.5;
  font-variant-numeric: tabular-nums;
}

.supplement__chevron {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.supplement__body {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  margin-top: var(--gap-md);
}

.supplement__intro {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}

/* 宽屏两列并列；窄屏单列（方案 §5.5） */
.supplement__columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--gap-md) var(--gap-lg);
}

.supplement__column {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: var(--gap) var(--gap-md);
  border: 1px solid var(--border-faint);
  border-radius: var(--radius-lg);
  background: var(--surface-panel);
}

.supplement__column-title {
  margin: 0 0 var(--gap-sm);
  color: var(--text-strong);
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
}

.supplement__row {
  display: grid;
  grid-template-columns: minmax(104px, auto) minmax(0, 1fr) minmax(132px, auto);
  gap: var(--gap-sm) var(--gap);
  align-items: start;
  padding: var(--gap-sm) 0;
  border-bottom: 1px solid var(--border-faint);
}

.supplement__row:last-child {
  border-bottom: 0;
}

.supplement__row.is-locked {
  /* 锁定态只提亮边框，不压暗文字（避免灰淡看不清） */
  border-bottom-color: var(--border-medium);
}

.supplement__row-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

/* 彩色归属标签：放在类型名之前，不用 emoji */
.supplement__home {
  padding: 1px 7px;
  border: 1px solid currentColor;
  border-radius: var(--radius-pill);
  font-size: 12px;
  line-height: 1.5;
}

.supplement__home[data-home='portrait'] {
  color: var(--accent-link);
}

.supplement__home[data-home='costume'] {
  color: var(--accent-green-text);
}

.supplement__home[data-home='pose'] {
  color: var(--accent-red-text);
}

.supplement__home[data-home='modifier'] {
  color: var(--text-muted);
}

.supplement__type {
  color: var(--text-body);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.5;
}

.supplement__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.supplement__chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  padding: 3px 8px;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-pill);
  background: var(--surface-inset);
  color: var(--text-body);
  font-size: 12px;
  line-height: 1.5;
}

.supplement__chip:hover {
  border-color: var(--border-hover);
}

.supplement__chip-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.supplement__chip-remove {
  flex: none;
  color: var(--danger-text-soft);
  font-size: 12px;
}

.supplement__empty {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.supplement__row-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  justify-content: flex-end;
}

.supplement__pick {
  padding: 3px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-strong);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.5;
}

.supplement__pick:hover:not(:disabled) {
  border-color: var(--primary);
}

/* 当前槽的「补充 / 替代」状态标签：彩色描边放在类型名之后 */
.supplement__mode {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border: 1px solid var(--border-medium);
  border-radius: var(--radius-pill);
  color: var(--text-body);
  font-size: 12px;
  line-height: 1.5;
}

.supplement__mode[data-mode='text'] {
  border-color: var(--accent-link);
  color: var(--accent-link);
  font-weight: 600;
}

.supplement__mode[data-mode='image'] {
  border-color: var(--accent-green-text);
  color: var(--accent-green-text);
}

/* image 模式但补充开关关闭：文本本次不发送 */
.supplement__mode.is-inactive {
  border-color: var(--border-faint);
  color: var(--text-muted);
  font-weight: 400;
}

/* 同源整套随机的来源名：单行省略，不挤占卡头 */
.supplement__source {
  max-width: 280px;
  overflow: hidden;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 跨源实验：与普通来源区分，提示需要人工复核 */
.supplement__experiment {
  padding: 1px 7px;
  border: 1px solid var(--accent-link);
  border-radius: var(--radius-pill);
  color: var(--accent-link);
  font-size: 12px;
  line-height: 1.5;
  white-space: nowrap;
}

/* 替代 / 改回图片：次要按钮，与「选择碎片」同高 */
.supplement__mode-toggle {
  padding: 3px 10px;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-body);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.5;
}

.supplement__mode-toggle:hover {
  border-color: var(--primary);
  color: var(--text-strong);
}

.supplement__mode-toggle:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}

/* P4 跨源补充开关：默认关闭；打开后显示为强调色 */
.supplement__supplement-toggle {
  padding: 3px 10px;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-body);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.5;
}

.supplement__supplement-toggle:hover:not(:disabled) {
  border-color: var(--accent-green-text);
}

.supplement__supplement-toggle.is-on {
  border-color: var(--accent-green-text);
  color: var(--accent-green-text);
  font-weight: 600;
}

.supplement__supplement-toggle:disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
}

.supplement__supplement-toggle:focus-visible {
  outline: 1px solid var(--accent-green-text);
  outline-offset: 1px;
}

/* 跨源补充提示：独占整行，长度超 120 字转危险色 */
.supplement__supplement-warning {
  grid-column: 1 / -1;
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.supplement__supplement-warning.is-long {
  color: var(--danger-text-soft);
}

.supplement__pick:disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
}

.supplement__row-meta {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
  font-variant-numeric: tabular-nums;
}

.supplement__lock {
  color: var(--text-body);
  font-size: 12px;
  line-height: 1.5;
}

.supplement__negative {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--gap) var(--gap-md);
  border: 1px solid var(--border-faint);
  border-radius: var(--radius-lg);
  background: var(--surface-panel);
}

.supplement__negative-label {
  color: var(--text-body);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.5;
}

.supplement__negative-input {
  box-sizing: border-box;
  width: 100%;
  min-height: 66px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-code);
  color: var(--text-body);
  font-family: inherit;
  font-size: 12px;
  line-height: 1.6;
  resize: vertical;
}

.supplement__negative-input:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}

.supplement__negative-hint {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}

@media (max-width: 1023px) {
  .supplement__columns {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 639px) {
  .supplement {
    padding: 16px;
    border-radius: 18px;
  }

  .supplement__row {
    grid-template-columns: minmax(0, 1fr);
  }

  .supplement__row-actions {
    justify-content: flex-start;
  }
}
</style>