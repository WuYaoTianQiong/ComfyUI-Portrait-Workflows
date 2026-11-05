<script setup lang="ts">
/**
 * 合成台（阶段 3 最薄版）。
 *
 * 范围逐条对齐施工手册 §7「合成台」冻结行 + 阶段 3 多选升级：
 * - 三槽位**多选**（人像 / 服装 / 姿势）+ 第 4 张 `extra`（只提交 1 张，仅 uploads）；
 * - 全组合 = 槽位组合 × 画质档 × 比例，常驻显示「当前 N / 上限 100」；
 * - 每组独立 POST、并发上限 2；种子第 i 组 = base_seed + i；
 * - 工作流下拉（`/api/workflows?scope=studio`，自动选中 `default`，展示 input_count）；
 * - M（非空槽数）< N（input_count）时提交前弹降级确认框，不做静默切换；
 * - 尺寸档位 / 比例按 `caps` 渲染；Qwen 系隐藏并显示「跟随参考图」说明；
 * - 画风预设（`none` / `realistic`）+ `prompt_suffix`；
 * - `POST /api/reference/recipes` → 轮询 1500ms / 30min → 结果图 / 任务中心；
 * - 历史只读面板。
 *
 * 明确不迁：配方草稿持久化、旧历史导出、参考图拼合、未决任务恢复、
 * 提示词只读预览。
 *
 * 视觉基线 §5：槽位卡、分区卡、主按钮、工作流下拉与预览区的尺寸/圆角/配色
 * 见各子组件与下方 scoped CSS 的数值注释。
 */

import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { isNsfwCostumeItem, isNsfwPoseItem } from '../../api/reference'
import type { UploadedReference } from '../../api/upload'
import { withReferenceTab } from './referenceDeepLink'
import DropZone from '../../components/DropZone.vue'
import { useReferenceSafeMode } from '../../composables/useReferenceSafeMode'
import { useReferenceRecipeDraft } from '../../composables/useReferenceRecipeDraft'
import type { RecipeSlotKey } from '../../composables/useReferenceRecipeDraft'
import {
  MAX_BATCH_RECIPES,
  useReferenceRecipe,
  workflowDisplayName,
} from '../../composables/useReferenceRecipe'
import { useToast } from '../../composables/useToast'

import ReferenceHistoryPanel from './components/ReferenceHistoryPanel.vue'
import ReferenceSectionCard from './components/reference/ReferenceSectionCard.vue'
import ReferenceSlotCard from './components/reference/ReferenceSlotCard.vue'
import ReferenceWorkflowSelect from './components/reference/ReferenceWorkflowSelect.vue'
import {
  costumeSlotItems,
  poseSlotItems,
  portraitSlotItems,
} from './components/reference/slotView'
import type { SlotSelectedItem } from './components/reference/slotView'
import { useStudioLibraries } from './components/reference/studioLibraries'
import { poseDepthMode, setPoseDepthMode } from './components/poseView'

/** 画风选项：后端只认这两项，其余旧值降级为写实。 */
const STYLE_OPTIONS: ReadonlyArray<{ value: 'none' | 'realistic'; label: string }> = [
  { value: 'none', label: '无预设（跟随参考图）' },
  { value: 'realistic', label: '写实人像写真' },
]

/** 第 4 张只接受 uploads 目录内的文件（前端提前拦一次，最终仍由后端判定）。 */
const UPLOADS_SEGMENT = /(^|[\\/])uploads([\\/]|$)/i

const route = useRoute()
const router = useRouter()

const draft = useReferenceRecipeDraft()
const { safeMode } = useReferenceSafeMode()
const toast = useToast()

const {
  workflows,
  workflowPath,
  workflowsLoading,
  workflowsError,
  caps,
  qualityOptions,
  aspectRatios,
  qualitySelection,
  ratioSelection,
  toggleQuality,
  toggleRatio,
  followsReferenceSize,
  baseSeed,
  setBaseSeed,
  activeSlotCount,
  batchTotal,
  batchOverLimit,
  batchLimitMessage,
  workflowDowngrade,
  style,
  promptSuffix,
  extraPath,
  extraName,

  progress,
  progressPercent,
  jobId,
  jobIds,
  resultUrls,
  primaryResultUrl,
  previousResultUrl,
  errorMessage,
  busy,
  canSubmit,
  loadStudioWorkflows,
  setExtra,
  clearExtra,
  submit,
  confirmWorkflowDowngrade,
  confirmCurrentWorkflowDowngrade,
  cancelWorkflowDowngrade,
  retry,
} = useReferenceRecipe()

const { poses, costumes, portraits, loadAll } = useStudioLibraries()

/** 失败后点「查看上一张结果」时切到上一次成功的图。 */
const showingPrevious = ref(false)

// ---------------------------------------------------------------------------
// 页签跳转（与 ReferenceView.selectTab 同一套 URL 规则）
// ---------------------------------------------------------------------------

function goTab(tab: 'portrait' | 'costume' | 'pose' | 'studio'): void {
  if (route.query.tab === tab) return
  void router.replace({
    path: route.path,
    query: withReferenceTab(route.query, tab),
    hash: route.hash,
  })
}

/**
 * 点击槽位：跳到对应库页签继续**多选**。
 *
 * 多选后不再做「选一张就自动跳回合成台」：那会让用户无法连续勾选多张。
 * 用户选完通过页签手动回到合成台即可（草稿是模块级单例，不会丢）。
 */
function openSlot(slot: RecipeSlotKey): void {
  goTab(slot)
}

function clearSlot(slot: RecipeSlotKey): void {
  if (slot === 'portrait') draft.removePortrait()
  else if (slot === 'costume') draft.removeCostume()
  else draft.removePose()
}

// ---------------------------------------------------------------------------
// 槽位视图
// ---------------------------------------------------------------------------

interface SlotCardView {
  key: RecipeSlotKey
  label: string
  items: SlotSelectedItem[]
  hint: string
  showDepthToggle: boolean
  useDepth: boolean
}

const slotCards = computed<SlotCardView[]>(() => {
  const useDepth = draft.pose.value[0]?.useDepth ?? poseDepthMode.value

  return [
    {
      key: 'portrait',
      label: '人像',
      items: portraitSlotItems(draft.portrait.value),
      hint: '+ 选人像（可多选）',
      showDepthToggle: false,
      useDepth: false,
    },
    {
      key: 'costume',
      label: '服装',
      items: costumeSlotItems(draft.costume.value),
      hint: '+ 选服装（可多选）',
      showDepthToggle: false,
      useDepth: false,
    },
    {
      key: 'pose',
      label: '姿势',
      items: poseSlotItems(draft.pose.value),
      hint: '+ 选姿势（可多选）',
      showDepthToggle: true,
      useDepth,
    },
  ]
})

const countLabel = computed(() => draft.countLabel.value)
const totalSelected = computed(() => draft.totalSelected.value)

/** 姿势槽切换白模 / 深度图：同步全局模式与槽内全部姿势。 */
function changePoseDepth(useDepth: boolean): void {
  setPoseDepthMode(useDepth)
  draft.setPoseMode(useDepth)
}

// ---------------------------------------------------------------------------
// 随机捏人（语义与首页一致）
// ---------------------------------------------------------------------------

const libraryLoading = computed(
  () => poses.loading.value || costumes.loading.value || portraits.loading.value,
)

/** 安全模式下姿势 / 服装按 nsfw 过滤；人像不过滤（React `randomizeRecipe` 同口径）。 */
const posePool = computed(() =>
  safeMode.value
    ? poses.items.value.filter((item) => !isNsfwPoseItem(item))
    : poses.items.value,
)

const costumePool = computed(() =>
  safeMode.value
    ? costumes.items.value.filter((item) => !isNsfwCostumeItem(item))
    : costumes.items.value,
)

const portraitPool = computed(() => portraits.items.value)

function pickRandom<T>(pool: readonly T[]): T | undefined {
  if (pool.length === 0) return undefined
  return pool[Math.floor(Math.random() * pool.length)]
}

/**
 * 随机捏人：三库各随机取一条。
 *
 * - 某个库为空时保留该槽位原值，不清空用户已有选择；
 * - 姿势槽带上当前全局白模 / 深度图模式；
 * - 可连续触发。
 */
function randomize(): void {
  if (libraryLoading.value) {
    toast.info('图库仍在加载，请稍候再随机')
    return
  }

  const nextPortrait = pickRandom(portraitPool.value)
  const nextCostume = pickRandom(costumePool.value)
  const nextPose = pickRandom(posePool.value)

  if (nextPortrait) draft.setPortrait(nextPortrait)
  if (nextCostume) draft.setCostume(nextCostume)
  if (nextPose) draft.setPose(nextPose, poseDepthMode.value)

  if (!nextPortrait && !nextCostume && !nextPose) {
    toast.error('图库加载失败或为空，无法随机捏人')
    return
  }

  toast.success(safeMode.value ? '已随机抽取一套角色配方（安全模式）' : '已随机抽取一套角色配方')
}

// ---------------------------------------------------------------------------
// 第 4 张（extra）：只保留 1 张，仅 uploads
// ---------------------------------------------------------------------------

function onExtraUploaded(items: UploadedReference[]): void {
  const first = items[0]
  if (!first) return
  if (!UPLOADS_SEGMENT.test(first.path)) {
    toast.error(
      '第 4 张参考图被拒绝。原因：上传结果不在 uploads 上传目录内。下一步：用本页的上传入口重新选择图片。',
    )
    return
  }
  setExtra(first.path, first.name)
  toast.success('已添加第 4 张参考图（只提交这 1 张）')
}

function onExtraError(message: string): void {
  toast.error(`第 4 张参考图上传失败。原因：${message}。下一步：换一张图片，或确认文件不超过 25MB 后重试。`)
}

// ---------------------------------------------------------------------------
// 提交 / 结果
// ---------------------------------------------------------------------------

const previewUrl = computed(() => {
  if (showingPrevious.value) return previousResultUrl.value
  // 批量 / 部分失败时只要拿到图片就展示第一张，错误区仍会显示失败原因。
  return primaryResultUrl.value
})

/** 提交结束后统一处理提示；降级确认框打开时不弹错误 toast。 */
function afterSubmit(ok: boolean): void {
  if (ok) {
    const count = resultUrls.value.length
    toast.success(
      jobIds.value.length > 1
        ? `已完成 ${jobIds.value.length} 个任务，共 ${count} 张`
        : `角色图已完成（任务 #${jobId.value}）`,
    )
    return
  }
  if (workflowDowngrade.value) return
  if (errorMessage.value) toast.error(errorMessage.value)
}

async function onGenerate(): Promise<void> {
  showingPrevious.value = false
  if (activeSlotCount.value === 0) {
    toast.error(
      '无法提交。原因：请至少选择一个参考图或上传一张参考图。下一步：从人像 / 服装 / 姿势任一库选择参考图，或上传第 4 张后再提交。',
    )
    return
  }
  if (batchOverLimit.value) {
    toast.error(`无法提交。原因：${batchLimitMessage.value}。下一步：减少素材或尺寸档位后重试。`)
    return
  }
  afterSubmit(await submit())
}

/** 降级确认框：切到候选工作流并继续提交。 */
async function onConfirmDowngrade(path: string): Promise<void> {
  showingPrevious.value = false
  afterSubmit(await confirmWorkflowDowngrade(path))
}

/** 降级确认框：不切换，仍用当前工作流提交（后端会尝试裁剪空槽）。 */
async function onConfirmCurrentWorkflow(): Promise<void> {
  showingPrevious.value = false
  afterSubmit(await confirmCurrentWorkflowDowngrade())
}

/** 降级确认框：取消，不提交。 */
function onCancelDowngrade(): void {
  cancelWorkflowDowngrade()
  toast.info('已取消提交：当前工作流输入数与所选参考图不匹配')
}

/** 基础种子输入：非负整数；非法值由 composable 回落默认种子。 */
function onBaseSeedInput(event: Event): void {
  setBaseSeed((event.target as HTMLInputElement).value)
}

async function onRetry(): Promise<void> {
  showingPrevious.value = false
  afterSubmit(await retry())
}

function showPreviousResult(): void {
  if (!previousResultUrl.value) return
  showingPrevious.value = true
}

function goJobCenter(): void {
  void router.push({ name: 'jobs' })
}

function reloadWorkflows(): void {
  void loadStudioWorkflows()
}

onMounted(() => {

  void loadStudioWorkflows()
  void loadAll()
})
</script>

<template>
  <div class="ref-studio" data-testid="reference-studio">
    <header class="ref-studio__head">
      <h1 class="ref-studio__title tab-placeholder__title" data-testid="reference-studio-title">
        合成台
      </h1>
      <p class="ref-studio__desc">
        AI 角色合成台：人像 / 服装 / 姿势三个库均可多选，按「槽位组合 × 画质档 × 比例」逐组提交；第 4 张为可选的上传附加图。
      </p>
    </header>

    <div class="studio-grid">
      <!-- 左栏：参考图组合、工作流与画风、补充要求、生成按钮 -->
      <div class="studio-column studio-column--left">
        <ReferenceSectionCard title="参考图组合" :subtitle="`已选 ${countLabel}`" :min-height="226.5">
          <template #actions>
            <span class="studio-count" data-testid="studio-recipe-count">{{ countLabel }}</span>
            <button
              type="button"
              class="studio-btn studio-btn--ghost"
              data-testid="studio-random"
              :disabled="libraryLoading"
              :title="libraryLoading ? '图库加载中，请稍候' : '从三个库中各随机抽取一条'"
              @click="randomize"
            >
              <svg class="studio-btn__icon" viewBox="0 0 16 16" aria-hidden="true">
                <rect x="2.2" y="2.2" width="11.6" height="11.6" rx="2.4" fill="none" stroke="currentColor" stroke-width="1.3" />
                <circle cx="5.8" cy="5.8" r="0.9" fill="currentColor" />
                <circle cx="10.2" cy="10.2" r="0.9" fill="currentColor" />
                <circle cx="10.2" cy="5.8" r="0.9" fill="currentColor" />
                <circle cx="5.8" cy="10.2" r="0.9" fill="currentColor" />
              </svg>
              随机捏人
            </button>
          </template>

          <!-- 三槽位：多选；展示已选数量与前 3 张缩略图 -->
          <div class="slot-grid">
            <ReferenceSlotCard
              v-for="slot in slotCards"
              :key="slot.key"
              :label="slot.label"
              :items="slot.items"
              :hint="slot.hint"
              :show-depth-toggle="slot.showDepthToggle"
              :use-depth="slot.useDepth"
              @select="openSlot(slot.key)"
              @clear="clearSlot(slot.key)"
              @depth-change="changePoseDepth"
            />
          </div>

          <!-- 批量预览：常驻显示「当前 N / 上限 100」与基础种子 -->
          <div class="batch-summary" data-testid="studio-batch-summary">
            <div class="batch-summary__row">
              <span class="batch-summary__label">全组合预览</span>
              <span class="batch-summary__total" data-testid="studio-batch-total">
                当前 {{ batchTotal }} / 上限 {{ MAX_BATCH_RECIPES }}
              </span>
              <span class="batch-summary__selected" data-testid="studio-selected-total">
                已选 {{ totalSelected }} 张 · 非空槽 {{ activeSlotCount }}
              </span>
            </div>
            <p v-if="batchOverLimit" class="batch-summary__limit" role="alert" data-testid="studio-batch-limit">
              {{ batchLimitMessage }}
            </p>
            <p v-else class="batch-summary__hint">
              {{ activeSlotCount === 0 ? '三槽与第 4 张都为空：请至少选择一张参考图。' : `共 ${batchTotal} 个独立任务，每组一个 job。` }}
            </p>
          </div>

          <!-- 第 4 张：只提交 1 张，仅 uploads；说明并入上传框 label/hint 以对齐 §5 卡高 -->
          <div class="extra-block">
            <div v-if="extraPath" class="extra-item" data-testid="studio-extra-selected">
              <span class="extra-item__mark" aria-hidden="true">
                <svg viewBox="0 0 16 16">
                  <path d="M2.6 12.4V5.2h3l1-1.6h3.8l1 1.6h2v7.2Z" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" />
                  <circle cx="8" cy="8.8" r="1.8" fill="none" stroke="currentColor" stroke-width="1.2" />
                </svg>
              </span>
              <span class="extra-item__body">
                <span class="extra-item__name" :title="extraName">{{ extraName }}</span>
                <span class="extra-item__meta">来自 uploads · 提交时作为第 4 张</span>
              </span>
              <button type="button" class="extra-item__remove" @click="clearExtra">移除</button>
            </div>

            <DropZone
              v-else
              :multiple="false"
              label="第 4 张（可选）：点击上传 / 拖拽 / 粘贴"
              hint="仅 uploads 内图片，只提交 1 张；PNG/JPG/WebP/HEIC ≤ 25MB"
              @uploaded="onExtraUploaded"
              @error="onExtraError"
            />
          </div>
        </ReferenceSectionCard>

        <ReferenceSectionCard title="工作流与画风">
          <div class="field">
            <label class="field__label" for="studio-workflow">工作流（本机工作流目录）</label>
            <ReferenceWorkflowSelect
              id="studio-workflow"
              v-model="workflowPath"
              :workflows="workflows"
              :loading="workflowsLoading"
            />
          </div>

          <p v-if="workflowsError" class="studio-error" role="alert">
            {{ workflowsError }}
            <button type="button" class="studio-btn studio-btn--ghost studio-btn--sm" @click="reloadWorkflows">
              重试
            </button>
          </p>

          <div v-if="workflows.length === 0 && !workflowsLoading && !workflowsError" class="studio-hint">
            本机库目录中没有可用工作流，请先放入出图工作流 JSON 后刷新本页。
          </div>

          <!-- 尺寸能力：按 caps 渲染；不支持时整块隐藏，提交体也不带对应字段 -->
          <div v-if="caps.quality && qualityOptions.length" class="field" data-testid="studio-quality-field">
            <span class="field__label">画质档位（可多选，每档一组任务）</span>
            <div class="chip-group" data-testid="studio-quality-options">
              <button
                v-for="option in qualityOptions"
                :key="option.value"
                type="button"
                class="chip"
                :class="{ 'is-active': qualitySelection.includes(option.value) }"
                :aria-pressed="qualitySelection.includes(option.value)"
                :data-quality="option.value"
                @click="toggleQuality(option.value)"
              >
                {{ option.label }}
              </button>
            </div>
            <p v-if="qualitySelection.length === 0" class="studio-hint">
              未选择画质档位：本轮不发送 quality，沿用工作流原生尺寸。
            </p>
          </div>

          <div v-if="caps.orientation && aspectRatios.length" class="field" data-testid="studio-ratio-field">
            <span class="field__label">输出比例（可多选，每档一组任务）</span>
            <div class="chip-group" data-testid="studio-ratio-options">
              <button
                v-for="ratio in aspectRatios"
                :key="ratio"
                type="button"
                class="chip"
                :class="{ 'is-active': ratioSelection.includes(ratio) }"
                :aria-pressed="ratioSelection.includes(ratio)"
                :data-ratio="ratio"
                @click="toggleRatio(ratio)"
              >
                {{ ratio }}
              </button>
            </div>
            <p v-if="ratioSelection.length === 0" class="studio-hint">
              未选择比例：本轮不发送 aspect_ratio / orientation。
            </p>
          </div>

          <p v-if="followsReferenceSize" class="studio-note" data-testid="studio-size-follow-note">
            输出尺寸跟随参考图（当前实际尺寸未知时不显示数值）
          </p>

          <div class="field">
            <label class="field__label" for="studio-style">画风预设</label>
            <select id="studio-style" v-model="style" class="studio-select" data-testid="studio-style">
              <option v-for="option in STYLE_OPTIONS" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </div>

          <!-- 常驻说明（D4 冻结） -->
          <p class="studio-note" data-testid="studio-node-note">
            节点映射由后端固定，参数面板不改变出图节点与工作流。
          </p>
        </ReferenceSectionCard>

        <ReferenceSectionCard title="补充要求">
          <label class="field__label" for="studio-prompt-suffix">补充要求（可选）</label>
          <textarea
            id="studio-prompt-suffix"
            v-model="promptSuffix"
            class="studio-textarea"
            rows="3"
            placeholder="例如：暖色灯光、浅景深；作为 prompt_suffix 提交"
            data-testid="studio-prompt-suffix"
          />
          <p class="studio-hint">
            补充要求是唯一进入提交的自由文本；提示词由后端按三槽自动生成，前端不预览、不改写。
          </p>

          <!-- 基础种子：第 i 组 seed = base_seed + i（fixed），便于按固定种子复现 -->
          <div class="field">
            <label class="field__label" for="studio-base-seed">基础种子（第 i 组 = 基础种子 + i）</label>
            <input
              id="studio-base-seed"
              class="studio-select studio-select--number"
              type="number"
              min="0"
              step="1"
              :value="baseSeed"
              data-testid="studio-base-seed"
              @input="onBaseSeedInput"
            />
            <p class="studio-hint" data-testid="studio-seed-hint">
              基础种子 {{ baseSeed }} · 提交时固定为 seed_mode=fixed，第 i 组使用 {{ baseSeed }}+i。
            </p>
          </div>

          <!-- 主按钮 44px 高、圆角 8、14px / 600、深色底 #e5e5e5 / 字 #171717 -->
          <button
            type="button"
            class="generate-btn"
            data-testid="studio-generate"
            :disabled="!canSubmit"
            @click="onGenerate"
          >
            <span v-if="busy" class="generate-btn__spinner" aria-hidden="true" />
            {{ busy ? '生成中…' : '生成角色图' }}
          </button>
          <p v-if="batchOverLimit" class="studio-error studio-error--inline" data-testid="studio-generate-blocked">
            {{ batchLimitMessage }}
          </p>
        </ReferenceSectionCard>
      </div>

      <!-- 右栏：生成结果 -->
      <div class="studio-column studio-column--right">
        <ReferenceSectionCard title="生成结果">
          <template #actions>
            <a
              v-if="previewUrl"
              class="studio-btn studio-btn--ghost studio-btn--sm"
              :href="previewUrl"
              download="image.png"
            >
              下载图片
            </a>
          </template>

          <!-- 预览区：471.33 × 511.97（min-height 460）、内边距 16、圆角 18 -->
          <div class="preview-box" data-testid="studio-preview">
            <div v-if="busy" class="preview-state">
              <span class="preview-state__spinner" aria-hidden="true" />
              <p class="preview-state__title">正在生成角色图…</p>
              <p class="preview-state__message">{{ progress.message || '正在提交任务…' }}</p>

              <div v-if="progressPercent !== null" class="progress">
                <div
                  class="progress__track"
                  role="progressbar"
                  aria-label="生成进度"
                  aria-valuemin="0"
                  aria-valuemax="100"
                  :aria-valuenow="progressPercent"
                >
                  <div class="progress__fill" :style="{ width: `${progressPercent}%` }" />
                </div>
                <span class="progress__pct">{{ progressPercent }}%</span>
              </div>

              <p v-if="jobId" class="preview-state__job">任务 #{{ jobId }}</p>
              <p class="preview-state__tip">切换页签不会中断后端任务</p>
            </div>

            <div v-else-if="errorMessage && !showingPrevious && resultUrls.length === 0" class="preview-error" role="alert">
              <span class="preview-error__mark" aria-hidden="true">!</span>
              <p class="preview-error__title">生成失败</p>
              <p class="preview-error__text">{{ errorMessage }}</p>
              <div class="preview-error__actions">
                <button type="button" class="studio-btn studio-btn--ghost studio-btn--sm" @click="onRetry">
                  重试
                </button>
                <button
                  v-if="previousResultUrl"
                  type="button"
                  class="studio-btn studio-btn--ghost studio-btn--sm"
                  @click="showPreviousResult"
                >
                  查看上一张结果
                </button>
              </div>
            </div>

            <!-- 批量结果：多张时网格展示，单张保持大图 -->
            <div v-else-if="resultUrls.length > 1 && !showingPrevious" class="preview-grid" data-testid="studio-result-grid">
              <a
                v-for="(url, index) in resultUrls"
                :key="url"
                class="preview-grid__cell"
                :href="url"
                download="image.png"
              >
                <img
                  :src="url"
                  :alt="`生成结果 ${index + 1}`"
                  class="preview-grid__image"
                  loading="lazy"
                  :data-testid="index === 0 ? 'studio-result-image' : undefined"
                />
              </a>
            </div>

            <img
              v-else-if="previewUrl"
              :src="previewUrl"
              alt="生成结果"
              class="preview-image"
              data-testid="studio-result-image"
            />

            <div v-else class="preview-state">
              <span class="preview-state__mark" aria-hidden="true">
                <svg viewBox="0 0 20 20">
                  <path
                    d="M10 2.6 11.7 7.4 16.5 9.1 11.7 10.8 10 15.6 8.3 10.8 3.5 9.1 8.3 7.4Z"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.3"
                    stroke-linejoin="round"
                  />
                </svg>
              </span>
              <p class="preview-state__message">点击「生成角色图」后在此处展示生成结果</p>
            </div>
          </div>

          <!-- 部分任务失败但有结果图：结果照常展示，错误集中在下方说明 -->
          <p v-if="errorMessage && resultUrls.length" class="studio-error studio-error--inline" role="alert">
            {{ errorMessage }}
          </p>

          <div class="result-footer">
            <span>
              {{ jobIds.length > 1 ? `共 ${jobIds.length} 个任务（首个 #${jobIds[0]}）` : jobId ? `当前任务 #${jobId}` : '任务由 atelier 后端排队执行' }}
            </span>
            <button type="button" class="result-footer__link" data-testid="studio-job-center" @click="goJobCenter">
              任务中心
            </button>
          </div>
        </ReferenceSectionCard>
      </div>
    </div>

    <!-- 工作流降级确认框：M（非空槽数）< N（input_count）时出现，取消则不提交 -->
    <div
      v-if="workflowDowngrade"
      class="studio-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="studio-downgrade-title"
      data-testid="studio-workflow-downgrade"
    >
      <div class="studio-modal__panel">
        <h2 id="studio-downgrade-title" class="studio-modal__title">当前工作流输入数不匹配</h2>
        <p class="studio-modal__message" data-testid="studio-downgrade-message">
          {{ workflowDowngrade.message }}
        </p>

        <p class="studio-modal__meta">
          非空槽 {{ workflowDowngrade.slotCount }} 个 · 当前工作流需要 {{ workflowDowngrade.inputCount }} 个输入
        </p>

        <div v-if="workflowDowngrade.candidates.length" class="downgrade-list">
          <p class="downgrade-list__head">可切换的候选工作流（input_count ≤ {{ workflowDowngrade.slotCount }}）</p>
          <button
            v-for="candidate in workflowDowngrade.candidates"
            :key="candidate.path"
            type="button"
            class="downgrade-list__item"
            :title="candidate.path"
            @click="onConfirmDowngrade(candidate.path)"
          >
            <span class="downgrade-list__name">{{ workflowDisplayName(candidate.name) }}</span>
            <span class="downgrade-list__count">{{ candidate.inputCount }} 图</span>
          </button>
        </div>
        <p v-else class="studio-modal__message">
          当前没有 input_count ≤ {{ workflowDowngrade.slotCount }} 的候选工作流。可取消后补齐参考图再提交，或仍用当前工作流尝试（后端会裁掉空槽，无法裁剪时返回 400）。
        </p>

        <div class="studio-modal__actions">
          <button
            type="button"
            class="studio-btn studio-btn--ghost"
            data-testid="studio-downgrade-current"
            @click="onConfirmCurrentWorkflow"
          >
            仍用当前工作流提交
          </button>
          <button
            type="button"
            class="studio-btn studio-btn--ghost"
            data-testid="studio-downgrade-cancel"
            @click="onCancelDowngrade"
          >
            取消，不提交
          </button>
        </div>
      </div>
    </div>

    <!-- 历史：只读，来自 /api/images -->
    <ReferenceHistoryPanel class="studio-history" />
  </div>
</template>

<style scoped>
.ref-studio {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.ref-studio__head {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
}

.ref-studio__title {
  margin: 0;
  color: #fafafa;
  font-size: 20px;
  font-weight: 600;
  line-height: 1.3;
}

.ref-studio__desc {
  margin: 0;
  color: #a1a1a1;
  font-size: 12px;
  line-height: 1.6;
}

/*
 * 12 栏布局：左 7 列 / 右 5 列、gap 24px（对齐 React lg:grid-cols-12 lg:gap-6）。
 * 用 12 列而不是 `7fr / 5fr`：12 列的 gap 也参与列宽换算，1920 视口下
 * 左栏 = 736.67、右栏 = 519.33，与 §5 的槽位卡 224.22 / 预览区 471.33 对得上。
 */
.studio-grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 24px;
  align-items: start;
}

.studio-column {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.studio-column--left {
  grid-column: span 7;
}

.studio-column--right {
  grid-column: span 5;
}

.studio-history {
  margin-top: 16px;
}

/* 三槽：736.66 内容区 - gap 16 → 单卡 224.22px */
.slot-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.studio-count {
  padding: 1px 8px;
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.08);
  color: #a1a1a1;
  font-size: 11px;
  font-weight: 500;
  line-height: 16px;
}

/* 小按钮：32px 高、圆角 8、12px / 500 */
.studio-btn {
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
  text-decoration: none;
}

.studio-btn--sm {
  height: 26px;
  padding: 0 10px;
  font-size: 11px;
}

.studio-btn--ghost {
  border: 1px solid var(--border);
  background: transparent;
  color: #fafafa;
}

.studio-btn--ghost:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.06);
}

.studio-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.studio-btn:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

.studio-btn__icon {
  width: 14px;
  height: 14px;
  flex: none;
}

/* 第 4 张 */
.extra-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.extra-item {
  display: flex;
  align-items: center;
  gap: 10px;
  box-sizing: border-box;
  min-width: 0;
  padding: 8px 10px;
  border-radius: 12px;
  background: #0a0a0a;
}

.extra-item__mark {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 40px;
  border-radius: 10px;
  background: #262626;
  color: #a1a1a1;
}

.extra-item__mark svg {
  width: 16px;
  height: 16px;
}

.extra-item__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.extra-item__name {
  overflow: hidden;
  color: #fafafa;
  font-size: 12px;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.extra-item__meta {
  color: #a1a1a1;
  font-size: 10px;
  line-height: 1.4;
}

.extra-item__remove {
  flex: none;
  height: 24px;
  margin-left: auto;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: transparent;
  color: #fafafa;
  font-size: 11px;
  cursor: pointer;
}

.extra-item__remove:hover {
  border-color: var(--primary);
}

/* 表单行 */
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.field__label {
  color: #a1a1a1;
  font-size: 11px;
  line-height: 1.4;
}

/* 画风下拉与工作流下拉同尺寸（336.33 × 36、圆角 8、12px） */
.studio-select {
  box-sizing: border-box;
  width: 100%;
  max-width: 336.33px;
  height: 36px;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #0a0a0a;
  color: #fafafa;
  font-size: 12px;
  line-height: 1;
}

.studio-select:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}

.studio-textarea {
  box-sizing: border-box;
  width: 100%;
  min-height: 76px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #0a0a0a;
  color: #fafafa;
  font-family: inherit;
  font-size: 12px;
  line-height: 1.6;
  resize: vertical;
}

.studio-textarea:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}

.studio-note {
  margin: 0;
  color: #a1a1a1;
  font-size: 11px;
  line-height: 1.6;
}

.studio-hint {
  margin: 0;
  color: #a1a1a1;
  font-size: 11px;
  line-height: 1.6;
}

.studio-error {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 10px 12px;
  border: 1px solid rgba(239, 68, 68, 0.4);
  border-radius: 10px;
  background: rgba(239, 68, 68, 0.08);
  color: #fecaca;
  font-size: 12px;
  line-height: 1.6;
}

/* 主按钮：44px 高、圆角 8px、14px / 600、底 #e5e5e5 / 字 #171717 */
.generate-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  box-sizing: border-box;
  width: 100%;
  height: 44px;
  padding: 0 10px;
  border: 0;
  border-radius: 8px;
  background: #e5e5e5;
  color: #171717;
  font-size: 14px;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
}

.generate-btn:hover:not(:disabled) {
  background: #f5f5f5;
}

.generate-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.generate-btn:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

.generate-btn__spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(23, 23, 23, 0.25);
  border-top-color: #171717;
  border-radius: 50%;
  animation: studio-spin 0.8s linear infinite;
}

/* 结果预览区：min-height 460、内边距 16、圆角 18、底 #0a0a0a */
.preview-box {
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  width: 100%;
  min-height: 460px;
  padding: 16px;
  overflow: hidden;
  border-radius: 18px;
  background: #0a0a0a;
}

.preview-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  width: 100%;
  max-width: 320px;
  text-align: center;
}

.preview-state__mark {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.06);
  color: #a1a1a1;
}

.preview-state__mark svg {
  width: 22px;
  height: 22px;
}

.preview-state__spinner {
  width: 48px;
  height: 48px;
  border: 3px solid rgba(255, 255, 255, 0.12);
  border-top-color: #e5e5e5;
  border-radius: 16px;
  animation: studio-spin 1s linear infinite;
}

@keyframes studio-spin {
  to {
    transform: rotate(360deg);
  }
}

.preview-state__title {
  margin: 0;
  color: #fafafa;
  font-size: 14px;
  font-weight: 600;
}

.preview-state__message {
  margin: 0;
  color: #a1a1a1;
  font-size: 12px;
  line-height: 1.6;
}

.preview-state__job {
  margin: 0;
  color: #a1a1a1;
  font-size: 11px;
}

.preview-state__tip {
  margin: 0;
  color: #a1a1a1;
  font-size: 11px;
  line-height: 1.5;
}

/* 进度条：1.5px 高、全圆角 */
.progress {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  max-width: 240px;
}

.progress__track {
  flex: 1;
  height: 1.5px;
  overflow: hidden;
  border-radius: 9999px;
  background: #262626;
}

.progress__fill {
  height: 100%;
  border-radius: 9999px;
  background: #e5e5e5;
  transition: width 0.2s var(--ease);
}

.progress__pct {
  flex: none;
  color: #a1a1a1;
  font-size: 11px;
  line-height: 1;
}

.preview-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  width: 100%;
  max-width: 420px;
  text-align: center;
}

.preview-error__mark {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
  font-size: 16px;
  font-weight: 700;
}

.preview-error__title {
  margin: 0;
  color: #f87171;
  font-size: 14px;
  font-weight: 600;
}

.preview-error__text {
  margin: 0;
  color: #d4d4d4;
  font-size: 12px;
  line-height: 1.7;
  text-align: left;
  word-break: break-word;
}

.preview-error__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  padding-top: 4px;
}

.preview-image {
  display: block;
  max-width: 100%;
  max-height: 480px;
  width: auto;
  height: auto;
  border-radius: 12px;
  object-fit: contain;
}

.result-footer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
  color: #a1a1a1;
  font-size: 11px;
}

.result-footer__link {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--primary);
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
}

.result-footer__link:hover {
  text-decoration: underline;
}

.result-footer__link:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

/* 1024px 以下单列（React lg 断点） */
@media (max-width: 1023px) {
  .studio-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .studio-column--left,
  .studio-column--right {
    grid-column: auto;
  }
}

/* 390px：三槽改单列，避免压缩到不可读 */
@media (max-width: 639px) {
  .slot-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .preview-box {
    min-height: 340px;
  }
}

/* ---------------------------------------------------------------------------
 * 批量预览 / 尺寸多选 / 降级确认框（多选升级新增）
 * ------------------------------------------------------------------------- */

/* 批量摘要：常驻 N/100，放在槽位卡下方 */
.batch-summary {
  display: flex;
  flex-direction: column;
  gap: 4px;
  box-sizing: border-box;
  padding: 10px 12px;
  border-radius: 12px;
  background: #0a0a0a;
}

.batch-summary__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.batch-summary__label {
  flex: none;
  color: #a1a1a1;
  font-size: 11px;
  line-height: 1.4;
}

.batch-summary__total {
  flex: none;
  padding: 1px 8px;
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.1);
  color: #fafafa;
  font-size: 12px;
  font-weight: 600;
  line-height: 18px;
}

.batch-summary__selected {
  min-width: 0;
  color: #a1a1a1;
  font-size: 11px;
  line-height: 1.4;
}

.batch-summary__hint {
  margin: 0;
  color: #a1a1a1;
  font-size: 11px;
  line-height: 1.6;
}

.batch-summary__limit {
  margin: 0;
  color: #fca5a5;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.6;
}

/* 尺寸多选 chip：可换行、选中深色底 */
.chip-group {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.chip {
  box-sizing: border-box;
  min-height: 28px;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 9999px;
  background: transparent;
  color: #fafafa;
  font-size: 11px;
  font-weight: 500;
  line-height: 1.4;
  white-space: nowrap;
  cursor: pointer;
}

.chip:hover {
  border-color: var(--primary);
}

.chip.is-active {
  border-color: transparent;
  background: #e5e5e5;
  color: #171717;
  font-weight: 600;
}

.chip:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}

/* 数字输入沿用下拉尺寸 */
.studio-select--number {
  font-variant-numeric: tabular-nums;
}

/* 主按钮下方的超限说明：不再重复整块错误卡的内边距 */
.studio-error--inline {
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: #fca5a5;
  font-size: 11px;
  line-height: 1.6;
}

/* 批量结果网格：两列，单格保持 3:4 */
.preview-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  width: 100%;
  max-height: 560px;
  overflow-y: auto;
}

.preview-grid__cell {
  display: block;
  overflow: hidden;
  border-radius: 10px;
  background: #171717;
}

.preview-grid__image {
  display: block;
  width: 100%;
  aspect-ratio: 3 / 4;
  object-fit: cover;
}

/* 降级确认框：全屏遮罩 + 居中面板 */
.studio-modal {
  position: fixed;
  inset: 0;
  z-index: 220;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(0, 0, 0, 0.62);
}

.studio-modal__panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  box-sizing: border-box;
  width: min(480px, 100%);
  max-height: calc(100vh - 48px);
  overflow-y: auto;
  padding: 18px 18px 16px;
  border-radius: 16px;
  background: #171717;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.55);
}

.studio-modal__title {
  margin: 0;
  color: #fafafa;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.4;
}

.studio-modal__message {
  margin: 0;
  color: #d4d4d4;
  font-size: 12px;
  line-height: 1.7;
  word-break: break-word;
}

.studio-modal__meta {
  margin: 0;
  color: #a1a1a1;
  font-size: 11px;
  line-height: 1.5;
}

.studio-modal__actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 4px;
}

.downgrade-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 260px;
  overflow-y: auto;
}

.downgrade-list__head {
  margin: 0;
  color: #a1a1a1;
  font-size: 11px;
  line-height: 1.5;
}

.downgrade-list__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  box-sizing: border-box;
  width: 100%;
  min-height: 34px;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #0a0a0a;
  color: #fafafa;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}

.downgrade-list__item:hover {
  border-color: var(--primary);
  background: rgba(255, 255, 255, 0.05);
}

.downgrade-list__item:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}

.downgrade-list__name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.downgrade-list__count {
  flex: none;
  color: #a1a1a1;
  font-size: 11px;
}

@media (max-width: 639px) {
  .preview-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>