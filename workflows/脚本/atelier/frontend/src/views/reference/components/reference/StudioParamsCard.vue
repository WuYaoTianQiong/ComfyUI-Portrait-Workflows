<script setup lang="ts">
/**
 * 合成台参数卡（方案 §5 M4 / M7）。
 *
 * 顺序固定：工作流 chips → 画风预设 → 画质档位 → 输出比例 → 基础种子 → 体态模式。
 *
 * 纯受控组件：不持有业务状态，所有改动都通过 emit 交回页面（`ReferenceStudioTab`）。
 * 因此任何调用方都能复用同一套 UI 与计数口径，避免参数区再抄一遍。
 *
 * 视觉约束：说明文字 ≥ 12px，颜色全部走 `styles/tokens.css` 的语义变量（不写硬编码色值）。
 */

import { computed } from 'vue'

import type {
  RecipeBodyMode,
  StudioWorkflowOption,
  StudioWorkflowSlot,
} from '../../../../composables/useReferenceRecipe'
import { workflowDisplayName } from '../../../../composables/useReferenceRecipe'
import ReferenceWorkflowSelect from './ReferenceWorkflowSelect.vue'

const props = defineProps<{
  /** 已选工作流路径（有序、去重；空数组 = 使用后端默认工作流）。 */
  workflowSelection: string[]
  workflows: readonly StudioWorkflowOption[]
  /** 当前已选**非空**槽位的业务角色；空槽不传。 */
  selectedRoles: readonly StudioWorkflowSlot[]
  /** 后端默认工作流路径（空选择时 UI 明示）。 */
  workflowDefaultPath: string
  workflowsLoading: boolean
  workflowsError: string
  style: string
  styleOptions: readonly { value: string; label: string }[]
  qualityEnabled: boolean
  qualityOptions: readonly { value: string; label: string }[]
  qualitySelection: string[]
  orientationEnabled: boolean
  aspectRatios: readonly string[]
  ratioSelection: string[]
  followsReferenceSize: boolean
  bodyMode: RecipeBodyMode
  safeMode: boolean
  baseSeed: number
}>()

const emit = defineEmits<{
  'update:workflowSelection': [value: string[]]
  'update:style': [value: string]
  toggleQuality: [value: string]
  toggleRatio: [value: string]
  'update:baseSeed': [value: string]
  'update:bodyMode': [mode: RecipeBodyMode]
  reloadWorkflows: []
}>()

/** 后端默认工作流目录项；路径失效时为 null。 */
const defaultWorkflow = computed(
  () => props.workflows.find((item) => item.path === props.workflowDefaultPath) ?? null,
)

/** 未勾选任何工作流 = 使用默认项（计数口径按 1 条默认工作流）。 */
const usesDefaultWorkflow = computed(
  () => props.workflowSelection.length === 0 && defaultWorkflow.value !== null,
)

/** 下拉多选回传；空数组即回落默认工作流。 */
function onWorkflowSelectionChange(value: string[]): void {
  emit('update:workflowSelection', value)
}

function onStyleChange(event: Event): void {
  const target = event.target as HTMLSelectElement | null
  if (!target) return
  emit('update:style', target.value)
}

function onBaseSeedInput(event: Event): void {
  const target = event.target as HTMLInputElement | null
  if (!target) return
  emit('update:baseSeed', target.value)
}

/** 体态开关回传勾选态；安全模式下输入本身 disabled，这里再防御一次。 */
function onBodyModeChange(event: Event): void {
  if (props.safeMode) return
  const target = event.target as HTMLInputElement | null
  if (!target) return
  emit('update:bodyMode', target.checked ? 'bare' : 'costume')
}
</script>

<template>
  <section class="params-card" data-testid="studio-params-card">
    <!-- 工作流：chips 平铺在触发器下方，下拉只承担「添加」 -->
    <div class="field" data-testid="studio-workflow-field">
      <span class="field__label">工作流（可多选，每项一组任务）</span>
      <ReferenceWorkflowSelect
        variant="chips"
        :model-value="workflowSelection"
        :workflows="workflows"
        :selected-roles="selectedRoles"
        :default-path="workflowDefaultPath"
        :loading="workflowsLoading"
        @update:model-value="onWorkflowSelectionChange"
      />

      <!-- 未勾选时回落默认项，必须在 UI 明示，避免用户误以为没选就不生效 -->
      <p
        v-if="usesDefaultWorkflow && defaultWorkflow"
        class="params-hint"
        data-testid="studio-workflow-default-note"
      >
        当前使用默认工作流：{{ workflowDisplayName(defaultWorkflow.name) }}（未勾选任何工作流时按 1 条默认项计入全组合）
      </p>
      <p
        v-else-if="workflowSelection.length > 1"
        class="params-hint"
        data-testid="studio-workflow-multi-note"
      >
        已选 {{ workflowSelection.length }} 个工作流：全组合按每个工作流各展开一组任务。
      </p>

      <p v-if="workflowsError" class="params-error" role="alert">
        {{ workflowsError }}
        <button
          type="button"
          class="params-btn"
          data-testid="studio-workflow-reload"
          @click="emit('reloadWorkflows')"
        >
          重试
        </button>
      </p>
      <p v-else-if="workflows.length === 0 && !workflowsLoading" class="params-hint">
        本机库目录中没有可用工作流，请先放入出图工作流 JSON 后刷新本页。
      </p>
    </div>

    <!-- 画风预设：与工作流触发器同规格（36px / 圆角 8 / 12px） -->
    <div class="field">
      <label class="field__label" for="studio-style">画风预设</label>
      <select
        id="studio-style"
        class="params-select"
        data-testid="studio-style"
        :value="props.style"
        @change="onStyleChange"
      >
        <option v-for="option in styleOptions" :key="option.value" :value="option.value">
          {{ option.label }}
        </option>
      </select>
    </div>

    <!-- 尺寸能力：按 caps 渲染；不支持时整块隐藏，提交体也不带对应字段 -->
    <div v-if="qualityEnabled && qualityOptions.length" class="field" data-testid="studio-quality-field">
      <span class="field__label">画质档位（可多选，每档一组任务）</span>
      <div class="params-chips" data-testid="studio-quality-options">
        <button
          v-for="option in qualityOptions"
          :key="option.value"
          type="button"
          class="params-chip"
          :class="{ 'is-active': qualitySelection.includes(option.value) }"
          :aria-pressed="qualitySelection.includes(option.value)"
          :data-quality="option.value"
          @click="emit('toggleQuality', option.value)"
        >
          {{ option.label }}
        </button>
      </div>
      <p v-if="qualitySelection.length === 0" class="params-hint">
        未选择画质档位：本轮不发送 quality，沿用工作流原生尺寸。
      </p>
    </div>

    <div v-if="orientationEnabled && aspectRatios.length" class="field" data-testid="studio-ratio-field">
      <span class="field__label">输出比例（可多选，每档一组任务）</span>
      <div class="params-chips" data-testid="studio-ratio-options">
        <button
          v-for="ratio in aspectRatios"
          :key="ratio"
          type="button"
          class="params-chip"
          :class="{ 'is-active': ratioSelection.includes(ratio) }"
          :aria-pressed="ratioSelection.includes(ratio)"
          :data-ratio="ratio"
          @click="emit('toggleRatio', ratio)"
        >
          {{ ratio }}
        </button>
      </div>
      <p v-if="ratioSelection.length === 0" class="params-hint">
        未选择比例：本轮不发送 aspect_ratio / orientation。
      </p>
    </div>

    <p v-if="followsReferenceSize" class="params-note" data-testid="studio-size-follow-note">
      该工作流输出尺寸跟随参考图
    </p>

    <!-- 基础种子：第 i 组 seed = base_seed + i（fixed），便于按固定种子复现 -->
    <div class="field">
      <label class="field__label" for="studio-base-seed">基础种子（第 i 组 = 基础种子 + i）</label>
      <input
        id="studio-base-seed"
        class="params-select params-select--number"
        type="number"
        min="0"
        step="1"
        :value="baseSeed"
        data-testid="studio-base-seed"
        @input="onBaseSeedInput"
      />
      <p class="params-hint" data-testid="studio-seed-hint">
        基础种子 {{ baseSeed }} · 提交时固定为 seed_mode=fixed，第 i 组使用 {{ baseSeed }}+i。
      </p>
    </div>

    <!-- 素体（无服装）开关：受 18+ 安全模式约束，不写 localStorage -->
    <div class="field" data-testid="studio-body-mode-field">
      <span class="field__label">体态模式</span>
      <label class="switch-row" :class="{ 'is-disabled': safeMode }">
        <input
          type="checkbox"
          class="switch-row__input"
          data-testid="studio-body-mode-bare"
          :checked="bodyMode === 'bare'"
          :disabled="safeMode"
          @change="onBodyModeChange"
        />
        <span class="switch-row__text">
          <span class="switch-row__title">素体展示（无服装）</span>
          <span class="switch-row__hint" data-testid="studio-body-mode-hint">
            {{
              safeMode
                ? '安全模式下不可用，请先解锁 18+'
                : '开启后会清空服装槽，提交体带 body_mode=bare'
            }}
          </span>
        </span>
      </label>
    </div>
  </section>
</template>

<style scoped>
.params-card {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}

/* 表单行 */
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.field__label {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.4;
}

/* 画风下拉与工作流触发器同尺寸（336.33 × 36、圆角 8、12px） */
.params-select {
  box-sizing: border-box;
  width: 100%;
  max-width: 336.33px;
  height: 36px;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-code);
  color: var(--text-strong);
  font-family: inherit;
  font-size: 12px;
  line-height: 1;
}

.params-select:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}

.params-select--number {
  font-variant-numeric: tabular-nums;
}

/* 尺寸多选 chip：可换行、选中反色 */
.params-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.params-chip {
  box-sizing: border-box;
  min-height: 28px;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 9999px;
  background: transparent;
  color: var(--text-strong);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
  white-space: nowrap;
  cursor: pointer;
}

.params-chip:hover {
  border-color: var(--primary);
}

.params-chip.is-active {
  border-color: transparent;
  background: var(--btn-inverse-bg);
  color: var(--on-inverse);
  font-weight: 600;
}

.params-chip:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}

.params-hint {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}

.params-error {
  margin: 0;
  color: var(--danger-text-soft);
  font-size: 12px;
  line-height: 1.6;
}

.params-note {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}

.params-btn {
  height: 26px;
  margin-left: 6px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: transparent;
  color: var(--text-strong);
  font-size: 12px;
  font-weight: 500;
  line-height: 1;
  cursor: pointer;
}

.params-btn:hover {
  background: var(--fill-subtle);
}

.params-btn:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

/* 素体开关：用原生 checkbox 保持键盘 / 读屏可访问性，不手搓 switch */
.switch-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-code);
  cursor: pointer;
}

.switch-row.is-disabled {
  cursor: not-allowed;
}

.switch-row__input {
  flex: none;
  width: 14px;
  height: 14px;
  margin: 2px 0 0;
  accent-color: var(--primary);
  cursor: inherit;
}

.switch-row__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.switch-row__title {
  color: var(--text-strong);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
}

.switch-row__hint {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}
</style>