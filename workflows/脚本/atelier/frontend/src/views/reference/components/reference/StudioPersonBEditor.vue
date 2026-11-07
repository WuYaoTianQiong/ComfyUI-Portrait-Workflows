<script setup lang="ts">
/**
 * 合成台「人物 B 文字设定」（v1.5）。
 *
 * 口径：
 * - 只在双人姿势下显示；B 只有文字，不占图片槽、不参与图片笛卡尔积；
 * - B 的三类人物碎片（面部 / 身材 / 服饰）与 A 完全隔离，独立存储；
 * - 支持多条「B 变体」：批量时按序号与 A 人像 1:1 配对，避免 A×B 爆炸；
 * - 纯受控：碎片与自由文字变更都通过 `update:variants` 交回页面。
 */

import { computed, ref } from 'vue'

import type { FragmentType } from '../../../../constants'
import {
  FRAGMENT_HOMES,
  FRAGMENT_HOME_LABELS,
  MAX_FRAGMENTS_PER_TYPE,
  MAX_PERSON_B_VARIANTS,
  PERSON_FRAGMENT_TYPES,
  cloneRecipeTextFragments,
  countFragmentChars,
  fragmentsOfPerson,
} from '../../../../composables/recipeTextFragments'
import type {
  RecipePersonBVariant,
  SelectedFragment,
} from '../../../../composables/recipeTextFragments'

import StudioFragmentPicker from './StudioFragmentPicker.vue'

const props = defineProps<{
  /** 全部 B 变体（真源在草稿单例）。 */
  variants: RecipePersonBVariant[]
  /** 当前编辑 / 预览的变体下标。 */
  activeIndex: number
  /** 安全模式：透传给碎片弹层。 */
  safeMode: boolean
  /** 手动改写提示词时禁用（B 设定不参与提交）。 */
  disabled?: boolean
  /** 当前 A 人像条目数；用于提示 1:1 配对数量不等。 */
  portraitCount?: number
  /**
   * v2-A：第 4 槽已选人物B身份图。
   *
   * 有身份图时后端只取图里的脸型 / 发型，`人物面部` / `人物身材` 这两类
   * B 碎片会被忽略；页面据此禁用这两类入口并说明原因。
   */
  identityImageSelected?: boolean
  /** 身份图展示名（库条目标题或上传文件名）。 */
  identityImageName?: string
  /** V2-C：双人配对模式下只允许 1 组变体（需「批量展开」才能新增）。 */
  singleMode?: boolean
}>()

const emit = defineEmits<{
  'update:variants': [value: RecipePersonBVariant[]]
  'update:activeIndex': [value: number]
  add: []
  remove: [index: number]
}>()

/** 当前变体；列表为空时为 null。 */
const current = computed<RecipePersonBVariant | null>(
  () => props.variants[props.activeIndex] ?? props.variants[0] ?? null,
)

/** 1:1 配对数量提示：人像与 B 变体数量不等时，批量会复用较少一侧最后一组。 */
const pairingNotice = computed<string>(() => {
  const portraits = props.portraitCount ?? 0
  const variants = props.variants.length
  if (!variants) return ''
  if (portraits <= 0) {
    return `未选人像参考图：${variants} 组 B 变体会各自单独成组（人物 A 走文字槽）。`
  }
  if (portraits === variants) return ''
  return (
    `配对数量不等：人像 ${portraits} 张 / B 变体 ${variants} 组；` +
    '批量时较少一侧复用最后一组，请在生成清单里复核配对。'
  )
})

/** 当前打开弹层的类型；null = 未打开。 */
const pickerType = ref<FragmentType | null>(null)

/** 弹层的初始选区：当前变体该类已有的 B 碎片。 */
const pickerSelected = computed<readonly SelectedFragment[]>(() =>
  pickerType.value && current.value
    ? fragmentsOfPerson(current.value.fragments, pickerType.value, 'B')
    : [],
)

/** 当前变体某一类的 B 碎片。 */
function itemsOf(type: FragmentType): SelectedFragment[] {
  return current.value ? fragmentsOfPerson(current.value.fragments, type, 'B') : []
}

/** 该类 B 碎片是否已被身份图接管（后端忽略这两类）。 */
function isIdentityManaged(type: FragmentType): boolean {
  return (
    props.identityImageSelected === true &&
    (type === '人物面部' || type === '人物身材')
  )
}

/** 某一类的字数合计。 */
function charsOf(type: FragmentType): number {
  return countFragmentChars(itemsOf(type))
}

/** 整体替换当前变体（不可变更新，避免改到 props）。 */
function replaceCurrent(next: RecipePersonBVariant): void {
  emit(
    'update:variants',
    props.variants.map((variant, index) =>
      index === props.activeIndex ? next : variant,
    ),
  )
}

/** 删除某一类第 index 条 chip。 */
function removeFragment(type: FragmentType, index: number): void {
  if (!current.value) return
  const fragments = cloneRecipeTextFragments(current.value.fragments)
  fragments[type] = fragmentsOfPerson(fragments, type, 'B').filter(
    (_, position) => position !== index,
  )
  replaceCurrent({ ...current.value, fragments })
}

/** 打开某一类的碎片弹层（已达上限 / 身份图接管时按钮已禁用，这里再防御一次）。 */
function openPicker(type: FragmentType): void {
  if (props.disabled || isIdentityManaged(type)) return
  if (itemsOf(type).length >= MAX_FRAGMENTS_PER_TYPE) return
  pickerType.value = type
}

/** 弹层确认：整类替换，强制 person='B'。 */
function onPickerConfirm(fragments: SelectedFragment[]): void {
  const type = pickerType.value
  pickerType.value = null
  if (!type || !current.value) return
  const next = cloneRecipeTextFragments(current.value.fragments)
  next[type] = fragments
    .slice(0, MAX_FRAGMENTS_PER_TYPE)
    .map((item) => ({ ...item, person: 'B' as const }))
  replaceCurrent({ ...current.value, fragments: next })
}

/** 自由文字输入。 */
function onFreeText(event: Event): void {
  if (!current.value || props.disabled) return
  const target = event.target as HTMLTextAreaElement | null
  replaceCurrent({ ...current.value, freeText: target?.value ?? '' })
}

/** chips 只展示内容前缀，完整内容放 `title`。 */
function previewContent(content: string): string {
  return content.length > 14 ? `${content.slice(0, 14)}…` : content
}
</script>

<template>
  <section class="person-b" data-testid="studio-person-b">
    <header class="person-b__head">
      <span class="person-b__title">人物 B · 文字设定</span>
      <span class="person-b__badge">双人姿势</span>
      <span class="person-b__count" data-testid="studio-person-b-count">
        {{ variants.length }} 组变体
      </span>
    </header>

    <p class="person-b__hint">
      <template v-if="identityImageSelected">
        人物 B 的脸型/发型由第 4 槽身份图
        <strong v-if="identityImageName">「{{ identityImageName }}」</strong>
        控制：人物面部/人物身材碎片会被忽略，只保留人物服饰与自由文字。
        人物 A 仍沿用图2的脸型/发型与图3的衣装。
      </template>
      <template v-else>
        人物 A 沿用图2的脸型/发型与图3的衣装；人物 B 只按这里的文字生成，脸会与 A 区分。
      </template>
      批量时按序号与人物 A 的人像参考图 1:1 配对；数量不等时较少一侧复用最后一组。
      <template v-if="disabled">
        当前已手动改写提示词，B 设定不参与提交，请直接改下方提示词。
      </template>
    </p>

    <p
      v-if="pairingNotice"
      class="person-b__notice"
      data-testid="studio-person-b-pairing-notice"
    >
      {{ pairingNotice }}
    </p>

    <div class="person-b__tabs" role="tablist" aria-label="人物B变体">
      <button
        v-for="(variant, index) in variants"
        :key="variant.id"
        type="button"
        class="person-b__tab"
        :class="{ 'is-active': index === activeIndex }"
        :aria-selected="index === activeIndex"
        :data-testid="`studio-person-b-tab-${index}`"
        @click="emit('update:activeIndex', index)"
      >
        变体 {{ index + 1 }}
      </button>
      <button
        type="button"
        class="person-b__action"
        :disabled="disabled || singleMode || variants.length >= MAX_PERSON_B_VARIANTS"
        :title="singleMode ? '双人配对模式下只保留 1 组；如需多组请打开「批量展开」' : ''"
        data-testid="studio-person-b-add"
        @click="emit('add')"
      >
        ＋ 新增变体
      </button>
      <button
        type="button"
        class="person-b__action"
        :disabled="disabled || variants.length <= 1"
        data-testid="studio-person-b-remove"
        @click="emit('remove', activeIndex)"
      >
        删除当前
      </button>
    </div>

    <template v-if="current">
      <div class="person-b__rows">
        <div
          v-for="type in PERSON_FRAGMENT_TYPES"
          :key="type"
          class="person-b__row"
          :class="{ 'is-identity-managed': isIdentityManaged(type) }"
          :data-testid="`studio-person-b-row-${type}`"
        >
          <span class="person-b__home" :data-home="FRAGMENT_HOMES[type]">
            {{ FRAGMENT_HOME_LABELS[FRAGMENT_HOMES[type]] }}
          </span>
          <span class="person-b__type">{{ type }}</span>

          <div class="person-b__chips">
            <button
              v-for="(item, index) in itemsOf(type)"
              :key="`${type}-${index}`"
              type="button"
              class="person-b__chip"
              :title="item.content"
              :aria-label="`移除${type}碎片：${previewContent(item.content)}`"
              :data-testid="`studio-person-b-chip-${type}-${index}`"
              @click="removeFragment(type, index)"
            >
              <span class="person-b__chip-text">{{ previewContent(item.content) }}</span>
              <span class="person-b__chip-remove" aria-hidden="true">移除</span>
            </button>
            <span v-if="!itemsOf(type).length" class="person-b__empty">未选</span>
          </div>

          <div class="person-b__row-actions">
            <button
              type="button"
              class="person-b__pick"
              :disabled="disabled || isIdentityManaged(type) || itemsOf(type).length >= MAX_FRAGMENTS_PER_TYPE"
              :data-testid="`studio-person-b-pick-${type}`"
              @click="openPicker(type)"
            >
              {{ isIdentityManaged(type) ? '由身份图控制' : '选择碎片' }}
            </button>
            <span v-if="isIdentityManaged(type)" class="person-b__meta">
              已选身份图，该类碎片不参与提交
            </span>
            <span v-else class="person-b__meta">
              {{ itemsOf(type).length }}/{{ MAX_FRAGMENTS_PER_TYPE }} 条 ·
              {{ charsOf(type) }} 字
            </span>
          </div>
        </div>
      </div>

      <label class="person-b__label" :for="`studio-person-b-text`">
        自由补充（可选）
      </label>
      <textarea
        id="studio-person-b-text"
        class="person-b__text"
        rows="3"
        :value="current.freeText"
        :disabled="disabled"
        data-testid="studio-pair-b-text"
        placeholder="例如：成年女性，金色齐肩短发，酒红色西装外套，黑色阔腿长裤；五官与人物 A 明显不同。"
        @input="onFreeText"
      ></textarea>
    </template>

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
.person-b {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  padding: 20px 24px;
  border-radius: 22px;
  background: var(--surface-raised);
}

.person-b__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-sm);
}

.person-b__title {
  color: var(--text-strong);
  font-size: 14px;
  font-weight: 600;
}

.person-b__badge,
.person-b__count {
  padding: 1px 8px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill);
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.person-b__hint {
  margin: 6px 0 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}

.person-b__notice {
  margin: 6px 0 0;
  color: var(--warn);
  font-size: 12px;
  line-height: 1.6;
}

.person-b__tabs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: var(--gap-sm);
}

.person-b__tab,
.person-b__action,
.person-b__pick {
  padding: 3px 10px;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-body);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.5;
}

.person-b__tab.is-active {
  border-color: var(--primary);
  color: var(--primary);
  font-weight: 600;
}

.person-b__action:disabled,
.person-b__pick:disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
}

.person-b__rows {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: var(--gap-sm);
}

.person-b__row {
  display: grid;
  grid-template-columns: minmax(104px, auto) minmax(0, 1fr) minmax(132px, auto);
  gap: var(--gap-sm) var(--gap);
  align-items: start;
  padding: var(--gap-sm) 0;
  border-bottom: 1px solid var(--border-faint);
}

.person-b__row:last-child {
  border-bottom: 0;
}

/* 身份图接管脸/发型后：这两类仍展示已有碎片，但明确弱化（后端不采用）。 */
.person-b__row.is-identity-managed .person-b__chips,
.person-b__row.is-identity-managed .person-b__type {
  opacity: 0.6;
}

.person-b__home {
  padding: 1px 7px;
  border: 1px solid currentColor;
  border-radius: var(--radius-pill);
  font-size: 12px;
  line-height: 1.5;
}

.person-b__home[data-home='portrait'] {
  color: var(--accent-link);
}

.person-b__home[data-home='costume'] {
  color: var(--accent-green-text);
}

.person-b__type {
  color: var(--text-body);
  font-size: 12px;
  font-weight: 500;
}

.person-b__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.person-b__chip {
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

.person-b__chip-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.person-b__chip-remove {
  flex: none;
  color: var(--danger-text-soft);
  font-size: 12px;
}

.person-b__empty {
  color: var(--text-muted);
  font-size: 12px;
}

.person-b__row-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  justify-content: flex-end;
}

.person-b__meta {
  color: var(--text-muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.person-b__label {
  display: block;
  margin-top: var(--gap-sm);
  color: var(--text-body);
  font-size: 12px;
  font-weight: 500;
}

.person-b__text {
  box-sizing: border-box;
  width: 100%;
  min-height: 66px;
  margin-top: 4px;
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

.person-b__text:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}

@media (max-width: 639px) {
  .person-b {
    padding: 16px;
    border-radius: 18px;
  }

  .person-b__row {
    grid-template-columns: minmax(0, 1fr);
  }

  .person-b__row-actions {
    justify-content: flex-start;
  }
}
</style>
