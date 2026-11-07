<script setup lang="ts">
/**
 * 合成台（阶段 3 最薄版）。
 *
 * 范围逐条对齐施工手册 §7「合成台」冻结行 + 阶段 3 多选升级：
 * - 三槽位**多选**（人像 / 服装 / 姿势）+ 第 4 张 `extra`（只提交 1 张，仅 uploads）；
 * - 全组合 = 槽位组合 × 画质档 × 比例，常驻显示「当前 N / 上限 100」；
 * - 每组独立 POST、并发上限 2；种子第 i 组 = base_seed + i；
 * - 工作流下拉（`/api/workflows?scope=studio`，自动选中 `default`，展示 input_count）；
 * - M（非空槽数）< N（input_count）时先问 `/api/reference/trim-check`：
 *   可裁剪 → 直接提交 + toast 说明；不可裁剪 → 才弹降级确认框（不做静默切换）；
 * - 尺寸档位 / 比例按 `caps` 渲染；Qwen21 只显示像素档（resolution），比例仍跟随参考图；
 * - 服装槽为空时自动按素体展示（`bare`）提交并 toast 说明（否则模型会自由发挥出裸体）；
 * - 画风预设（`none` / `realistic`）+ `prompt_suffix`；
 * - `POST /api/reference/recipes` → 轮询 1500ms / 30min → 结果图 / 任务中心；
 * - 提示词只读预览（后端 `dry_run` 组合，只读、不可编辑、与正式提交独立）。
 *
 * 明确不迁：配方草稿持久化、旧历史导出、参考图拼合、未决任务恢复、历史只读面板。
 *
 * 视觉基线 §5：槽位卡、分区卡、主按钮、工作流下拉与预览区的尺寸/圆角/配色
 * 见各子组件与下方 scoped CSS 的数值注释。
 */

import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { isNsfwCostumeItem, isNsfwPoseItem } from '../../api/reference'
import { apiGet } from '../../api/client'
import type { HistoryItem } from '../../api/types'
import { uploadReferenceImages } from '../../api/upload'
import type { UploadedReference } from '../../api/upload'
import { FRAGMENT_TYPES } from '../../constants'
import type { FragmentType } from '../../constants'
import { withReferenceTab } from './referenceDeepLink'
import DropZone from '../../components/DropZone.vue'
import { useReferenceSafeMode } from '../../composables/useReferenceSafeMode'
import { useReferenceRecipeDraft } from '../../composables/useReferenceRecipeDraft'
import type { RecipeSlotKey } from '../../composables/useReferenceRecipeDraft'
import {
  flushReferenceStudioSettings,
  readReferenceStudioSettings,
  writeReferenceStudioSettings,
} from '../../composables/useReferenceStudioSettings'
import {
  MAX_BATCH_RECIPES,
  buildBatchGroups,
  costumeDimensionForBodyMode,

  useReferenceRecipe,
  workflowDisplayName,
} from '../../composables/useReferenceRecipe'
import type { RecipeBatch, RecipeBodyMode } from '../../composables/useReferenceRecipe'
import {
  BARE_COSTUME_TEXT_CONFLICT_HINT,
  MAX_PERSON_B_VARIANTS,
  POSE_TEXT_PAIR_CONFLICT_HINT,
  RECIPE_SLOT_KEYS,
  compileActiveSlotTexts,
  createEmptyRecipeTextFragments,
  hasStyleFragment,
  slotFragmentItems,
} from '../../composables/recipeTextFragments'
import type {

  RecipeSlotMode,
  RecipeSlotTexts,
  RecipeTextFragments,
} from '../../composables/recipeTextFragments'
import { useToast } from '../../composables/useToast'
import Lightbox from '../../components/Lightbox.vue'
import ReferenceSectionCard from './components/reference/ReferenceSectionCard.vue'
import StudioActionBar from './components/reference/StudioActionBar.vue'
import StudioMatrix from './components/reference/StudioMatrix.vue'
import StudioParamsCard from './components/reference/StudioParamsCard.vue'
import StudioPromptEditor from './components/reference/StudioPromptEditor.vue'
import StudioResultBoard from './components/reference/StudioResultBoard.vue'
import StudioSlotPanel from './components/reference/StudioSlotPanel.vue'
import StudioTextSupplementCard from './components/reference/StudioTextSupplementCard.vue'
import StudioPersonBEditor from './components/reference/StudioPersonBEditor.vue'
import HairPickerModal from './components/reference/HairPickerModal.vue'
import type { HairItem } from '../../api/reference'
import {
  desiredPoseFacets,
  pickMatchedPose,
  pickPoseForFacet,
  poseFacetToken,
} from './components/reference/studioPoseMatch'
import {
  slotSelectedItemToHistoryItem,
  slotSelectedItemsToHistoryItems,
} from './components/reference/slotHistoryItem'
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

// ---------------------------------------------------------------------------
// 文本补充（八类碎片）+ 负向（方案 §4.1 / §5.5）
// ---------------------------------------------------------------------------

/**
 * 真源在 `useReferenceRecipeDraft` 单例（跟随 `pb.reference_studio_v1` 持久化），
 * 这里用可写 computed 让卡片走 `v-model`，避免模板直接操作 `.value`。
 */
const textFragments = computed<RecipeTextFragments>({
  get: () => draft.textFragments.value,
  set: (value) => {
    draft.textFragments.value = value
  },
})

/** 用户手填负向；最终负向 = 后端自动抽取 + 这里的内容。 */
const negativePrompt = computed<string>({
  get: () => draft.negativePrompt.value,
  set: (value) => {
    draft.negativePrompt.value = value
  },
})

/** 双人姿势专用：B 变体由草稿单例持有，换 seed / 画质不会清空。 */
const hasPairPose = draft.hasPairPose

/** 新增一条 B 变体；达到上限时只提示，不静默失败。 */
function onAddPersonBVariant(): void {
  if (!draft.addPersonBVariant()) {
    toast.info(`人物 B 变体最多 ${MAX_PERSON_B_VARIANTS} 组，请先删除一组再新增`)
  }
}

/** 删除当前 B 变体（草稿层保证至少保留一组）。 */
function onRemovePersonBVariant(index: number): void {
  draft.removePersonBVariant(index)
}

/**
 * 「画风技术」碎片与画风预设互斥（方案 §5.4）：
 * 选中即强制 `style='none'` 并禁用下拉；buildRecipeRequest 里再兜底一次。
 */
const styleLocked = computed(() => hasStyleFragment(draft.textFragments.value))

/** 三槽模式（真源在草稿单例，与快照的 portraitMode / costumeMode / poseMode 对应）。 */
const slotModes = computed(() => draft.slotModes.value)

/** P4 跨源补充开关（image 模式 + 打开时才发送对应槽文本）。 */
const supplementFlags = computed(() => draft.supplementFlags.value)

/** 三槽「本次真正生效」的文本：矩阵组键 / 组标签与提交体共用同一份。 */
const slotTexts = computed<RecipeSlotTexts>(() =>
  compileActiveSlotTexts(
    draft.textFragments.value,
    draft.slotModes.value,
    draft.supplementFlags.value,
  ),
)

/** 文本模式槽数（素材区摘要展示，避免用户以为选择丢了）。 */
const textSlotCount = computed(
  () => RECIPE_SLOT_KEYS.filter((slot) => slotModes.value[slot] === 'text').length,
)

/** image 模式且打开补充的槽数。 */
const supplementSlotCount = computed(
  () =>
    RECIPE_SLOT_KEYS.filter(
      (slot) => slotModes.value[slot] === 'image' && supplementFlags.value[slot],
    ).length,
)

/** 文本补充卡引用：「去填写」需要展开并滚动到卡片。 */
const textSupplementRef = ref<InstanceType<typeof StudioTextSupplementCard> | null>(null)

const {
  workflows,
  workflowDefaultPath,
  workflowSelection,


  workflowSelectionNotice,
  clearWorkflowSelectionNotice,
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
  filledSlotRoles,
  effectiveWorkflows,
  workflowDimension,

  batchTotal,
  batchOverLimit,
  batchLimitMessage,
  workflowDowngrade,
  workflowTrimNotice,
  clearWorkflowTrimNotice,
  style,
  promptSuffix,
  extraName,
  extraFilled,
  extraLibrary,
  bodyMode,
  setBodyMode,
  bodyModeNotice,
  clearBodyModeNotice,
  supportsExtraSlot,
  previewPrompt,
  previewNegativePrompt,
  previewNegativeEffective,
  previewError,
  previewLoading,
  refreshPreviewPrompt,
  promptOverride,
previewWorkflow,
  primaryResultUrl,
  previousResultUrl,

  batches,
    reuseBatchParams,
    clearFinishedBatches,
    submitting,
  polling,
  formError,
  canSubmit,
  loadStudioWorkflows,
  setExtra,
  setExtraLibrary,
  clearExtra,
  submit,
  confirmWorkflowDowngrade,
  confirmCurrentWorkflowDowngrade,
  cancelWorkflowDowngrade,
  retry,
} = useReferenceRecipe()

const { poses, costumes, portraits, loadAll } = useStudioLibraries()

// ---------------------------------------------------------------------------
// 工作流多选提示 / 素体开关（C-REF-WF-SLOTS@1 / C-REF-BODY-MODE@1）
// ---------------------------------------------------------------------------

/** 工作流因槽位变化被自动取消时用 toast 明确告知（不静默移除）。 */
watch(workflowSelectionNotice, (message) => {
  if (!message) return
  toast.info(message)
  clearWorkflowSelectionNotice()
})

/** 空槽能被裁剪时直接提交，用 toast 说明「这不是三图全参」的降级（不静默裁剪）。 */
watch(workflowTrimNotice, (message) => {
  if (!message) return
  toast.info(message)
  clearWorkflowTrimNotice()
})

/** 缺服装时自动按素体展示提交（否则 Qwen 系会出裸体），必须让用户知道语义被改了。 */
watch(bodyModeNotice, (message) => {
  if (!message) return
  toast.info(message)
  clearBodyModeNotice()
})

/**
 * 素体开关受安全模式约束：安全模式下禁用；
 * 若用户先打开素体再切回安全模式，则自动关闭并提示（不会在安全模式下自动打开）。
 */
watch(safeMode, (enabled) => {
  if (!enabled || bodyMode.value !== 'bare') return
  setBodyMode('costume')
  toast.info('已切换到安全模式，素体展示（无服装）已关闭')
})

/** 切换素体开关：开启时由 composable 清空服装槽，这里只负责把影响告诉用户。 */
function onToggleBodyMode(enabled: boolean): void {
  if (safeMode.value) {
    toast.info('安全模式下不可用，请先解锁 18+')
    return
  }
  const hadCostume = draft.costumeCount.value > 0
  setBodyMode(enabled ? 'bare' : 'costume')
  if (enabled && hadCostume) {
    toast.info('已清空服装槽：素体展示不提交服装，避免后端拒绝 bare + 服装的组合')
  }
}

/** ParamsCard 的体态 emit（RecipeBodyMode）→ 复用清空服装槽 / toast 逻辑。 */
function onParamsBodyMode(mode: RecipeBodyMode): void {
  onToggleBodyMode(mode === 'bare')
}

/**
 * 槽位模式切换（P2 替代态）。
 *
 * 组件只 emit，真正的双人 / 素体校验统一在这里做：
 * - 素体展示下不能把服装槽改成文本（语义 = 不穿衣服却描述衣服）；
 * - 姿势文本暂不支持双人（后端 C3-3 的防御性限制）。
 *
 * 切到 text 时**不删除**已有图片：改回 image 仍能直接复用（需求 §8 P2）。
 * 对应的碎片为空也允许先切换，提交时由 submit() 统一拦截并提示。
 */
function onSlotModeChange(slot: RecipeSlotKey, mode: RecipeSlotMode): void {
  if (mode === 'text') {
    if (slot === 'costume' && bodyMode.value === 'bare') {
      toast.error(
        `无法改用文本。原因：${BARE_COSTUME_TEXT_CONFLICT_HINT}。下一步：先切回服装模式，或保留服装参考图。`,
      )
      return
    }
    if (slot === 'pose') {
      const poseId =
        draft.pose.value.find((entry) => entry.item.id.startsWith('pair'))?.item.id ??
        draft.pose.value[0]?.item.id ??
        draft.lastPoseId.value
      if (poseId.startsWith('pair')) {
        toast.error(
          `无法改用文本。原因：${POSE_TEXT_PAIR_CONFLICT_HINT}。下一步：换单人姿势，或保留姿势参考图。`,
        )
        return
      }
    }
  }
  draft.setSlotMode(slot, mode)
}

/** 槽位卡「去填写」：展开文本补充卡并滚动到它。 */
function onFillText(): void {
  void textSupplementRef.value?.expand()
}

/**
 * P4 跨源补充开关：只允许 image 模式且该槽已有文本时打开。
 *
 * 这里做父级防御；卡片本身也会在「无图 / 无文本 / text 模式」时禁用开关。
 */
function onSlotSupplementChange(slot: RecipeSlotKey, enabled: boolean): void {
  if (enabled) {
    if (draft.slotModes.value[slot] !== 'image') return
    if (slotFragmentItems(draft.textFragments.value, slot).length === 0) {
      toast.info('该槽还没有文本碎片，先选一条再开启补充')
      return
    }
  }
  draft.setSlotSupplement(slot, enabled)
}

/**
 * 碎片变化时自动把「空槽」升级为文本模式。
 *
 * 复刻旧数据推导口径（无图 + 有对应碎片 = text）：用户直接在文本补充卡里为
 * 空槽选碎片时，槽位卡应同步显示「文本」而不是仍显示「空」。
 * 反向不自动降级：清空碎片后保持 text，提交时统一提示「文本模式需要至少 1 条碎片」。
 */
watch(
  draft.textFragments,
  () => {
    const poseId =
      draft.pose.value.find((entry) => entry.item.id.startsWith('pair'))?.item.id ??
      draft.pose.value[0]?.item.id ??
      draft.lastPoseId.value
    for (const slot of RECIPE_SLOT_KEYS) {
      if (draft.slotModes.value[slot] !== 'empty') continue
      if (slotFragmentItems(draft.textFragments.value, slot).length === 0) continue
      // 自动升级也要遵守与手动切换相同的守卫，不能绕过素体 / 双人限制。
      if (slot === 'costume' && bodyMode.value === 'bare') continue
      if (slot === 'pose' && poseId.startsWith('pair')) continue
      draft.setSlotMode(slot, 'text')
    }
  },
  { deep: true },
)

/** ParamsCard 的画风 emit（string）→ 收敛到后端认可的两种值。 */
function onParamsStyleChange(value: string): void {
  style.value = value === 'realistic' ? 'realistic' : 'none'
}

// ---------------------------------------------------------------------------
// 操作记忆（pb.reference_studio_v1，2026-11-05）
// ---------------------------------------------------------------------------

/**
 * 读一次已存快照并回填「工作流 / 画风 / 基础种子」。
 *
 * 工作流是否仍然可用不在这里判断：`loadStudioWorkflows` 会在目录加载完成后
 * 校验，失效时自动回落后端 default，避免恢复出一个磁盘上已删除的工作流。
 */
const storedSettings = readReferenceStudioSettings()

// 文本补充存的是全文、不依赖库数据：先于三库 hydrate 恢复，
// 避免「库临时加载失败 → 刷新后文本也被清空」。
draft.hydrateTextFragments()

if (storedSettings) {
  if (storedSettings.workflow) workflowPath.value = storedSettings.workflow
  // 已选画风技术碎片时 style 必须为 none（互斥，方案 §5.4），避免恢复出冲突组合。
  style.value = styleLocked.value ? 'none' : storedSettings.style
  baseSeed.value = storedSettings.baseSeed
}

/** 选中 / 保留画风技术碎片时强制 none；删除碎片后不猜测旧值，由用户手动选回。 */
watch(styleLocked, (locked) => {
  if (locked && style.value !== 'none') style.value = 'none'
})

/** 画风 / 工作流 / 种子 / 画质档 / 比例：任何变更都合并写入（300ms 防抖）。 */
watch(
  [workflowPath, style, baseSeed, qualitySelection, ratioSelection],
  () => {
    writeReferenceStudioSettings({
      style: style.value,
      workflow: workflowPath.value,
      baseSeed: baseSeed.value,
      qualities: [...qualitySelection.value],
      ratios: [...ratioSelection.value],
      sizesConfigured: true,
    })
  },
  { deep: true },
)

/**
 * 回填画质档 / 比例。
 *
 * 只恢复当前工作流 caps 仍然支持的项，避免把旧工作流的档位发出去；
 * `sizesConfigured === false` 表示用户从未配置过尺寸，保留 caps reconcile
 * 的工作流默认档，不把默认值误当作用户选择。
 */
function restoreSizeSelections(): void {
  const stored = readReferenceStudioSettings()
  if (!stored?.sizesConfigured) return

  const qualityAvailable = new Set(qualityOptions.value.map((option) => option.value))
  qualitySelection.value = caps.value.quality
    ? stored.qualities.filter((value) => qualityAvailable.has(value))
    : []

  const ratioAvailable = new Set(aspectRatios.value)
  ratioSelection.value = caps.value.orientation
    ? stored.ratios.filter((value) => ratioAvailable.has(value))
    : []
}

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
// 三槽本地上传图（与库条目同数组，一起参与笛卡尔积）
// ---------------------------------------------------------------------------

/** 隐藏的 file input：三个槽共用一个，点击时记住目标槽。 */
const slotUploadInput = ref<HTMLInputElement | null>(null)
const slotUploadTarget = ref<RecipeSlotKey>('portrait')
const slotUploading = ref(false)

/** 点「上传本地图」：记住目标槽并触发文件选择。 */
function pickSlotUpload(slot: RecipeSlotKey): void {
  slotUploadTarget.value = slot
  slotUploadInput.value?.click()
}

/** 文件选择完成：并发上传，成功后按目标槽加入对应数组。 */
async function onSlotUploadChange(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  const slot = slotUploadTarget.value
  input.value = ''
  if (!files.length) return

  slotUploading.value = true
  try {
    const result = await uploadReferenceImages(files)
    for (const item of result.items) {
      const payload = {
        path: item.path,
        name: item.name,
        width: item.width,
        height: item.height,
      }
      if (slot === 'portrait') draft.addPortraitUpload(payload)
      else if (slot === 'costume') draft.addCostumeUpload(payload)
      else draft.addPoseUpload(payload)
    }
    if (result.items.length) {
      toast.success(`已加入 ${result.items.length} 张本地图到${SLOT_LABELS[slot]}槽`)
    }
    if (result.failures.length) {
      toast.error(
        `${result.failures.length} 张上传失败。原因：${result.failures[0].error}。下一步：换一张图片后重试。`,
      )
    }
  } catch (cause) {
    toast.error(
      `上传失败。原因：${cause instanceof Error ? cause.message : String(cause)}。下一步：确认文件是图片且不超过 25MB。`,
    )
  } finally {
    slotUploading.value = false
  }
}

/** 槽位名（删除 toast 用）。 */
const SLOT_LABELS: Readonly<Record<RecipeSlotKey, string>> = {
  portrait: '人像',
  costume: '服装',
  pose: '姿势',
}

/**
 * 单项删除：`key` 即 `SlotSelectedItem.key`（= 条目 id）。
 *
 * 不传 id 才是清空整槽，所以这里必须把 id 传下去；删完用 toast 明确剩余数量，
 * 避免用户连点 × 时不知道删到了哪一张。
 */
function removeSlotItem(slot: RecipeSlotKey, key: string): void {
  if (slot === 'portrait') draft.removePortrait(key)
  else if (slot === 'costume') draft.removeCostume(key)
  else draft.removePose(key)

  const remaining =
    slot === 'portrait'
      ? draft.portraitCount.value
      : slot === 'costume'
        ? draft.costumeCount.value
        : draft.poseCount.value
  toast.success(`已从${SLOT_LABELS[slot]}槽移除 1 张（剩 ${remaining} 张）`)
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

/** 已选姿势里是否含「实测不可用」条目（v1.5 D046 降权提示）。 */
const unusablePoseMessage = computed(() => {
  const entry = draft.pose.value.find((item) => item.item.usable === false)
  if (!entry) return ''
  const reason = entry.item.usableNote || '实测姿势不跟随参考图'
  return `姿势「${entry.item.姿势名称}」标记为不可用：${reason}。下一步：换一张姿势，或仅在确认可接受时继续提交。`
})
const unusablePoseSelected = computed(() => unusablePoseMessage.value !== '')

/** 三槽当前是否按深度图取姿势缩略图（图墙与清单共用同一模式）。 */
const poseUseDepth = computed(() => draft.pose.value[0]?.useDepth ?? poseDepthMode.value)

/** 清单 / 操作条用的三槽条目数。 */
const slotCounts = computed(() => ({
  portrait: draft.portraitCount.value,
  costume: draft.costumeCount.value,
  pose: draft.poseCount.value,
}))

/** 操作条 / 清单用的尺寸维数：能力不支持或未选择时按 1 计（与 countBatchTotal 同口径）。 */
const qualityCountForBar = computed(() =>
  Math.max(1, caps.value.quality ? qualitySelection.value.length : 0),
)
const ratioCountForBar = computed(() =>
  Math.max(1, caps.value.orientation ? ratioSelection.value.length : 0),
)

/**
 * 生成清单：前端纯函数展开，与提交口径逐字一致（素体模式裁掉服装维度）。
 *
 * 不请求后端；上限由 `batchTotal` 判定，清单只负责「把每一张要生成的图列出来」。
 */
const previewGroups = computed(() =>
  buildBatchGroups({
    portrait: draft.portrait.value,
    costume: costumeDimensionForBodyMode(draft.costume.value, bodyMode.value),
    pose: draft.pose.value.map((entry) => entry.item),
    workflows: effectiveWorkflows.value.map((item) => item.path),
    qualities: qualitySelection.value,
    ratios: ratioSelection.value,
    qualityEnabled: caps.value.quality,
    orientationEnabled: caps.value.orientation,
    baseSeed: baseSeed.value,
    // P2：清单与提交共用模式 / 文本，避免「清单显示图片、提交却发文本」。
    slotModes: slotModes.value,
    slotTexts: slotTexts.value,
    // v1.5：双人姿势下 A 人像与 B 变体 1:1 配对，清单与计数器同口径。
    personBVariants: draft.hasPairPose.value ? draft.personBVariants.value : [],
  }),
)

const countLabel = computed(() => draft.countLabel.value)
const totalSelected = computed(() => draft.totalSelected.value)

/** 姿势槽切换白模 / 深度图：同步全局模式与槽内全部姿势。 */
function changePoseDepth(useDepth: boolean): void {
  setPoseDepthMode(useDepth)
  draft.setPoseMode(useDepth)
}

// ---------------------------------------------------------------------------
// 槽位灯箱：直接复用画廊 `components/Lightbox.vue`（只读）
// ---------------------------------------------------------------------------

interface SlotPreviewState {
  slot: RecipeSlotKey
  index: number
}

const slotPreview = ref<SlotPreviewState | null>(null)

const previewCard = computed<SlotCardView | null>(() => {
  const state = slotPreview.value
  if (!state) return null
  return slotCards.value.find((card) => card.key === state.slot) ?? null
})

const previewItems = computed<SlotSelectedItem[]>(() => previewCard.value?.items ?? [])

/**
 * 参考条目 → 画廊灯箱契约（`HistoryItem[]`）。
 *
 * 只做只读投影：收藏 / 删除 / 重出图 / 投喂等写操作由灯箱的 `readonly`
 * 统一关掉；不传 `workflows`，参考条目本来也没有工作流。
 */
const previewHistoryItems = computed<HistoryItem[]>(() =>
  slotSelectedItemsToHistoryItems(previewItems.value),
)

/** Lightbox 的 `index` 是必填 number；由模板 `v-if` 保证只在打开时求值。 */
const previewIndex = computed<number>(() => slotPreview.value?.index ?? 0)

function openSlotPreview(slot: RecipeSlotKey, index: number): void {
  const card = slotCards.value.find((entry) => entry.key === slot)
  if (!card || card.items.length === 0) return
  slotPreview.value = {
    slot,
    index: Math.min(Math.max(index, 0), card.items.length - 1),
  }
}

function closeSlotPreview(): void {
  slotPreview.value = null
}

/**
 * 灯箱内 ← / → 或左右按钮翻页：只更新传给 Lightbox 的 `index`。
 *
 * 翻页范围始终限制在当前槽位的已选条目内（顺序即加入顺序），不跨槽、
 * 不触发增删；单张时灯箱自身会把左右按钮置灰，不会走到这里。
 */
function onPreviewIndexChange(index: number): void {
  const state = slotPreview.value
  const length = previewItems.value.length
  if (!state || length === 0) return
  slotPreview.value = {
    ...state,
    index: Math.min(Math.max(index, 0), length - 1),
  }
}

// ---------------------------------------------------------------------------
// 结果灯箱（A1）：结果图点击开只读灯箱，翻页范围限于该批次
// ---------------------------------------------------------------------------

interface ResultPreviewState {
  urls: string[]
  index: number
}

const resultPreview = ref<ResultPreviewState | null>(null)

/**
 * 结果 URL → 画廊灯箱契约（`HistoryItem[]`）。
 *
 * 与槽位灯箱共用同一投影：`key` 用 URL 保证同批次翻页时 id 稳定；
 * 结果图没有真实历史记录字段，宽高 / 时间 / 体积按 0 / 空串 / null 回落。
 */
const resultPreviewHistoryItems = computed<HistoryItem[]>(() => {
  const state = resultPreview.value
  if (!state) return []
  return state.urls.map((url) =>
    slotSelectedItemToHistoryItem({
      key: url,
      name: '生成结果',
      thumb: url,
      image: url,
    }),
  )
})

const resultPreviewIndex = computed<number>(() => resultPreview.value?.index ?? 0)

function openResultPreview(urls: readonly string[], index: number): void {
  if (!urls.length) return
  resultPreview.value = {
    urls: [...urls],
    index: Math.min(Math.max(index, 0), urls.length - 1),
  }
}

function closeResultPreview(): void {
  resultPreview.value = null
}

function onResultPreviewIndexChange(index: number): void {
  const state = resultPreview.value
  if (!state) return
  resultPreview.value = {
    ...state,
    index: Math.min(Math.max(index, 0), state.urls.length - 1),
  }
}

// ---------------------------------------------------------------------------
// 随机捏人（语义与首页一致）
// ---------------------------------------------------------------------------

const libraryLoading = computed(
  () => poses.loading.value || costumes.loading.value || portraits.loading.value,
)

/**
 * 安全模式下姿势 / 服装按 nsfw 过滤；人像不过滤（React `randomizeRecipe` 同口径）。
 * v1.5：实测不可用的姿势不进入随机候选（仍可在库页手动选择）。
 */
const posePool = computed(() => {
  const usable = poses.items.value.filter((item) => item.usable !== false)
  return safeMode.value ? usable.filter((item) => !isNsfwPoseItem(item)) : usable
})

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

/** `GET /api/composer/recipes/random` 的响应（P4）。 */
interface RandomRecipeResponse {
  prompt_id: number
  name: string
  fragments: Array<{ type: FragmentType; content: string }>
  tags?: string
  source?: string
  recipe_count: number
}

interface AtomicRecipeResponse {
  bank_version: number
  combo_id: string
  fragments: Array<{ type: FragmentType; content: string }>
  pose_facet: string
  labels?: Record<string, string>
  warning?: string
}

const recipeRandomLoading = ref(false)
const atomicRandomLoading = ref(false)
const recipeSourceName = computed(() => draft.recipeSourceName.value)

/**
 * 同源整套随机（P4）：抽一套完整 8 类配方，用姿势图作唯一图片锚点。
 *
 * - 人像 / 服装槽切文本模式，由配方文本驱动；
 * - 姿势槽保持 image 模式，从姿势库随机取一张；
 * - 姿势文本默认不生效；用户可手动打开「作为补充」把它作为第 8 条发送。
 */
async function randomizeRecipe(): Promise<void> {
  if (recipeRandomLoading.value) return
  if (libraryLoading.value) {
    toast.info('图库仍在加载，请稍候再整套随机')
    return
  }
  if (!posePool.value.some((item) => !item.id.startsWith('pair'))) {
    toast.error('无法整套随机。原因：姿势库没有单人姿势。下一步：先加载单人姿势库，或手动选择一张姿势图。')
    return
  }

  recipeRandomLoading.value = true
  try {
    const response = await apiGet<RandomRecipeResponse>('/api/composer/recipes/random', {
      exclude_id: draft.recipeSourceId.value ?? undefined,
      safe_mode: safeMode.value,
    })

    const next = createEmptyRecipeTextFragments()
    for (const fragment of response.fragments ?? []) {
      if (!FRAGMENT_TYPES.includes(fragment.type)) continue
      next[fragment.type] = [{ type: fragment.type, content: fragment.content }]
    }

    // 姿势文本默认不生效，但用它匹配姿势库 facet，避免「配方说坐、图是站」。
    const poseText = next.姿态动作[0]?.content ?? ''
    const poseFacets = desiredPoseFacets(poseText)
    const nextPose = pickMatchedPose(posePool.value, poseText)
    if (!nextPose) {
      toast.error('无法整套随机。原因：姿势库没有可用的单人姿势。下一步：稍后重试，或手动选择一张姿势图。')
      return
    }
    const poseMatched = poseFacets.some((facet) =>
      (nextPose.分类 || '').includes(facet),
    )

    draft.textFragments.value = next
    draft.setPose(nextPose, poseDepthMode.value)
    // 姿势锚点：人像 / 服装用文本替代，姿势保留图片。
    draft.setSlotMode('portrait', 'text')
    draft.setSlotMode('costume', 'text')
    draft.setSlotMode('pose', 'image')
    draft.setSlotSupplement('portrait', false)
    draft.setSlotSupplement('costume', false)
    draft.setSlotSupplement('pose', false)
    draft.setRecipeSource(response.prompt_id, response.name)

    toast.success(`已套用《${response.name}》：${poseMatched ? '姿势图按配方姿态匹配' : '使用安全姿势图'}，7 类文本生效；姿势文本可手动开启补充`)
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    toast.error(
      `整套随机失败。原因：${message}。下一步：重试；仍失败请检查后端服务。`,
    )
  } finally {
    recipeRandomLoading.value = false
  }
}

/**
 * 跨源实验：从原子碎片库抽一套兼容组合。
 *
 * 与同源整套随机的区别只是文本来源；姿势仍用姿势图锚点，姿势文本默认不发。
 * 实验入口不写数据库，来源标签以「跨源实验 ·」开头，提示需人工复核。
 */
async function randomizeAtomic(): Promise<void> {
  if (atomicRandomLoading.value) return
  if (libraryLoading.value) {
    toast.info('图库仍在加载，请稍候再跨源实验')
    return
  }
  if (!posePool.value.some((item) => !item.id.startsWith('pair'))) {
    toast.error('无法跨源实验。原因：姿势库没有单人姿势。下一步：先加载单人姿势库，或手动选择一张姿势图。')
    return
  }

  atomicRandomLoading.value = true
  try {
    const response = await apiGet<AtomicRecipeResponse>('/api/composer/recipes/atomic')
    const next = createEmptyRecipeTextFragments()
    for (const fragment of response.fragments ?? []) {
      if (!FRAGMENT_TYPES.includes(fragment.type)) continue
      next[fragment.type] = [{ type: fragment.type, content: fragment.content }]
    }

    const nextPose = pickPoseForFacet(posePool.value, response.pose_facet)
    if (!nextPose) {
      toast.error('无法跨源实验。原因：姿势库没有可用的单人姿势。下一步：稍后重试，或手动选择一张姿势图。')
      return
    }
    const facetToken = poseFacetToken(response.pose_facet)
    const poseMatched = Boolean(facetToken) && (nextPose.分类 || '').includes(facetToken)

    draft.textFragments.value = next
    draft.setPose(nextPose, poseDepthMode.value)
    draft.setSlotMode('portrait', 'text')
    draft.setSlotMode('costume', 'text')
    draft.setSlotMode('pose', 'image')
    draft.setSlotSupplement('portrait', false)
    draft.setSlotSupplement('costume', false)
    draft.setSlotSupplement('pose', false)
    draft.setRecipeSource(null, `跨源实验 · ${response.combo_id}`)

    toast.info(
      `已套用跨源实验组合：${poseMatched ? '姿势图按配方姿态匹配' : '使用安全姿势图'}；建议人工复核`,
    )
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    toast.error(
      `跨源实验失败。原因：${message}。下一步：重试；仍失败请检查后端服务。`,
    )
  } finally {
    atomicRandomLoading.value = false
  }
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

/**
 * 第 4 槽文案由「当前来源」决定，不再按工作流文件名猜：
 * 从发型库选中即显示「发型」，上传图则保持通用「第 4 张」。
 * 是否显示该槽位仍由工作流 `slots.includes('extra')` 决定。
 */
const extraSlotLabel = computed(() => (extraLibrary.value ? '发型' : '第 4 张'))
const extraSlotHint = computed(() =>
  extraSlotLabel.value === '发型'
    ? '可从发型库选背面无脸图，或上传本地图；PNG/JPG/WebP/HEIC ≤ 25MB'
    : 'PNG/JPG/WebP/HEIC ≤ 25MB',
)

/** 第 4 槽文字补充（v-model）；真源在 `useReferenceRecipeDraft` 单例。 */
const extraText = computed<string>({
  get: () => draft.extra.value.text,
  set: (value) => {
    draft.setExtraText(value)
  },
})

const hairPickerOpen = ref(false)

function onHairPick(item: HairItem): void {
  setExtraLibrary('hair', item.id, item.标题)
  hairPickerOpen.value = false
  toast.success(`已选发型「${item.标题}」，提交时使用背面无脸图`)
}

function onExtraUploaded(items: UploadedReference[]): void {
  const first = items[0]
  if (!first) return
  if (!UPLOADS_SEGMENT.test(first.path)) {
    toast.error(
      `${extraSlotLabel.value}参考图被拒绝。原因：上传结果不在 uploads 上传目录内。下一步：用本页的上传入口重新选择图片。`,
    )
    return
  }
  setExtra(first.path, first.name)
  toast.success(`已添加${extraSlotLabel.value}参考图（只提交这 1 张）`)
}

function onExtraError(message: string): void {
  toast.error(
    `${extraSlotLabel.value}参考图上传失败。原因：${message}。下一步：换一张图片，或确认文件不超过 25MB 后重试。`,
  )
}

/**
 * 工作流都不支持第 4 张时，入口直接隐藏：
 * 会话恢复的草稿里若还留着 extra，必须清掉，否则它会算进非空槽位、把所有工作流判成不适用。
 */
watch(supportsExtraSlot, (enabled) => {
  if (enabled || !extraFilled.value) return
  clearExtra()
  toast.info('当前工作流都不支持第 4 张参考图，已清空该槽位')
})

// ---------------------------------------------------------------------------
// 提交 / 结果
// ---------------------------------------------------------------------------

const previewUrl = computed(() => {
  if (showingPrevious.value) return previousResultUrl.value
  // 批量 / 部分失败时只要拿到图片就展示第一张，错误区仍会显示失败原因。
  return primaryResultUrl.value
})

// ---------------------------------------------------------------------------
// 多批次结果：按批分组展示（各批结果互不串批）
// ---------------------------------------------------------------------------

/** 展示顺序：最新批次在最上方；批号由 StudioResultBoard 按创建顺序计算。 */
const displayedBatches = computed<RecipeBatch[]>(() => [...batches.value].reverse())

/**
 * 提交结束后统一处理提示。
 *
 * 以**本次提交返回的批次**为准（不读“最近一批”兼容视图），
 * 这样并发批次各自的完成 toast 不会互相串。
 */
function afterSubmit(batch: RecipeBatch | null): void {
  if (batch) {
    if (batch.status === 'success') {
      toast.success(
        batch.jobIds.length > 1
          ? `已完成 ${batch.jobIds.length} 个任务，共 ${batch.results.length} 张`
          : `角色图已完成（任务 #${batch.jobIds[0]}）`,
      )
    } else if (batch.errorMessage) {
      toast.error(batch.errorMessage)
    }
    return
  }
  if (workflowDowngrade.value) return
  if (formError.value) toast.error(formError.value)
}

async function onGenerate(): Promise<void> {
  showingPrevious.value = false
  // P2：至少 1 图 / 文本碎片 / 素体 + 服装文本 / 双人姿势等校验统一在 submit() 内完成，
  // 这里只保留超限预检（与可提交性无关，避免把批次打爆）。
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


/**
 * 是否处于手动改写模式（`prompt_override` 非空）。
 *
 * 手动模式下后端不再自动抽取负向，也不再二次编译正向：
 * 负向块必须如实显示用户填写内容，而不是 dry-run 的旧值。
 */
const manualPromptActive = computed(() => promptOverride.value !== null)

/** 负向块要展示的文本：手动模式 = 用户手填；自动模式 = 后端编译后的最终负向。 */
const displayedNegativePrompt = computed(() =>
  manualPromptActive.value ? draft.negativePrompt.value.trim() : previewNegativePrompt.value,
)

/** 复制当前实际会提交的正向：手动改写优先，否则复制自动预览。 */
async function copyPromptPreview(): Promise<void> {
  const text = promptOverride.value ?? previewPrompt.value
  if (!text.trim()) return
  try {
    if (!navigator.clipboard?.writeText) throw new Error('当前浏览器不支持剪贴板 API')
    await navigator.clipboard.writeText(text)
    toast.success('提示词已复制到剪贴板')
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : String(cause)
    toast.error(`复制失败。原因：${message}。下一步：手动选中预览文本后按 Ctrl+C 复制。`)
  }
}

async function onRetry(): Promise<void> {
  showingPrevious.value = false
  afterSubmit(await retry())
}

/** 是否存在失败批次（决定结果区是否显示重试入口）。 */
const hasFailedBatch = computed(() => batches.value.some((batch) => batch.status === 'failed'))

/** 结果区「复用参数」：全量回填该批槽位 + 工作流 / 尺寸，清单应还原到提交前组数。 */
function onReuseBatch(batch: RecipeBatch): void {
  if (!reuseBatchParams(batch)) return
  const number = batches.value.findIndex((item) => item.id === batch.id) + 1
  toast.success(`已回填批次 ${number} 的配方`)
}

/** 结果区「清理已结束」：只保留运行中批次。 */
function onClearFinishedBatches(): void {
  const removed = clearFinishedBatches()
  if (removed > 0) toast.success(`已清理 ${removed} 个已结束批次`)
}

function showPreviousResult(): void {
  if (!previousResultUrl.value) return
  showingPrevious.value = true
}

/** 从「上一张结果」回到最新批次结果。 */
function returnToLatestResult(): void {
  showingPrevious.value = false
}

function goJobCenter(): void {
  void router.push({ name: 'jobs' })
}

function reloadWorkflows(): void {
  void loadStudioWorkflows()
}

onMounted(async () => {
  // 先加载工作流：caps 决定画质档 / 比例，恢复尺寸前必须先知道当前工作流支持什么。
  await loadStudioWorkflows()

  const workflowsReady = !workflowsError.value && workflows.value.length > 0
  if (workflowsReady) restoreSizeSelections()

  await loadAll()

  // 三库全部成功才 hydrate：任一库加载失败时「没数据」不等于「条目已删除」，
  // 此时恢复会清空三槽并覆盖存储，等下次进入重试更安全。
  const librariesReady =
    !poses.error.value && !costumes.error.value && !portraits.error.value
  if (librariesReady) {
    draft.hydrate({
      portrait: portraits.items.value,
      costume: costumes.items.value,
      pose: poses.items.value,
    })
  }

  // 首次进入也落一份完整快照：把 reconcile 得到的工作流默认档一并记住，
  // 之后用户显式清空（空数组）才能与「从未配置」区分开。
  // 工作流目录读取失败时不写，避免用空列表覆盖已有记忆。
  if (workflowsReady) {
    writeReferenceStudioSettings({
      style: style.value,
      workflow: workflowPath.value,
      baseSeed: baseSeed.value,
      qualities: [...qualitySelection.value],
      ratios: [...ratioSelection.value],
      sizesConfigured: true,
    })
    flushReferenceStudioSettings()
  }
})
</script>

<template>
  <div class="ref-studio" data-testid="reference-studio">
    <header class="ref-studio__head">
      <h1 class="ref-studio__title tab-placeholder__title" data-testid="reference-studio-title">
        合成台
      </h1>
      <p class="ref-studio__desc">
        AI 角色合成台：人像 / 服装 / 姿势三个库与工作流均可多选，按「槽位组合 × 工作流 × 画质档 × 比例」逐组提交<template v-if="supportsExtraSlot">；第 4 张为可选发型参考图（可加文字补充，不参与批次组合）</template>。
      </p>
    </header>

    <!-- 素材区 + 生成清单：全宽（P1 重排，4 列每列约 280px） -->
    <ReferenceSectionCard title="参考图组合">
      <template #actions>
        <span class="studio-count" data-testid="studio-recipe-count">{{ countLabel }}</span>
      </template>

      <!-- 素材区：三槽（图墙版）+ 第 4 张上传块；没有工作流支持 extra 时只留三槽 -->
      <div class="slot-grid" :class="{ 'slot-grid--compact': !supportsExtraSlot }">
        <div v-for="slot in slotCards" :key="slot.key" class="slot-column">
          <StudioSlotPanel
            :label="slot.label"
            :slot-key="slot.key"
            :items="slot.items"
            :hint="slot.hint"
            :mode="slotModes[slot.key]"
            :show-depth-toggle="slot.showDepthToggle"
            :use-depth="slot.useDepth"
            @select="openSlot(slot.key)"
            @clear="clearSlot(slot.key)"
            @depth-change="changePoseDepth"
            @preview="openSlotPreview(slot.key, $event)"
            @remove="removeSlotItem(slot.key, $event)"
            @update:mode="onSlotModeChange(slot.key, $event)"
            @fill-text="onFillText"
          >
            <!-- 与「继续选」同一行（studio-slot-footer）；text 模式不提交图片，不提供入口 -->
            <template #footer>
              <button
                v-if="slotModes[slot.key] !== 'text'"
                type="button"
                class="slot-upload"
                :data-testid="`studio-slot-upload-${slot.key}`"
                :disabled="slotUploading"
                @click="pickSlotUpload(slot.key)"
              >
                {{ slotUploading ? '上传中…' : '＋ 上传本地图' }}
              </button>
            </template>
          </StudioSlotPanel>
        </div>

        <input
          ref="slotUploadInput"
          class="slot-upload-input"
          type="file"
          accept="image/*"
          multiple
          data-testid="studio-slot-upload-input"
          @change="onSlotUploadChange"
        />

        <!-- 第 4 张：与三槽同级，只提交 1 张，仅 uploads；没有工作流接 extra 时整块不渲染 -->
        <div v-if="supportsExtraSlot" class="extra-block">
          <div v-if="extraFilled" class="extra-item" data-testid="studio-extra-selected">
            <div class="extra-item__row">
              <span class="extra-item__mark" aria-hidden="true">
                <svg viewBox="0 0 16 16">
                  <path d="M2.6 12.4V5.2h3l1-1.6h3.8l1 1.6h2v7.2Z" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" />
                  <circle cx="8" cy="8.8" r="1.8" fill="none" stroke="currentColor" stroke-width="1.2" />
                </svg>
              </span>
              <span class="extra-item__body">
                <span class="extra-item__name" :title="extraName">{{ extraName }}</span>
                <span class="extra-item__meta">
                  {{ extraLibrary ? '来自发型库 · 提交背面无脸裁切图' : '来自 uploads' }} · 作为{{ extraSlotLabel }}
                </span>
              </span>
              <button type="button" class="extra-item__remove" @click="clearExtra">移除</button>
            </div>
            <!-- 图为主 + 文本补充：有图时文字作为「此外需体现」，不做纯文字第 4 槽 -->
            <p v-if="manualPromptActive" class="extra-item__hint" data-testid="studio-extra-text-manual">
              当前已手动改写提示词，第 4 槽文字补充不参与提交，请直接改下方提示词。
            </p>
            <textarea
              v-else
              v-model="extraText"
              class="extra-item__text"
              rows="2"
              data-testid="studio-extra-text"
              placeholder="此外需体现：发色、发饰、发尾弧度…（没有图片时不提交文字）"
            ></textarea>
          </div>

          <div v-else class="extra-actions">
            <DropZone
              variant="tile"
              :multiple="false"
              :label="`＋ 上传${extraSlotLabel}`"
              :hint="extraSlotHint"
              @uploaded="onExtraUploaded"
              @error="onExtraError"
            />
            <button
              v-if="extraSlotLabel === '发型'"
              type="button"
              class="extra-library"
              data-testid="studio-extra-hair-library"
              @click="hairPickerOpen = true"
            >
              从发型库选择
            </button>
          </div>

          <HairPickerModal
            :open="hairPickerOpen"
            @close="hairPickerOpen = false"
            @select="onHairPick"
          />
        </div>
      </div>

      <StudioPersonBEditor
        v-if="hasPairPose"
        :variants="draft.personBVariants.value"
        :active-index="draft.activePersonBVariantIndex.value"
        :safe-mode="safeMode"
        :disabled="manualPromptActive"
        @update:variants="draft.personBVariants.value = $event"
        @update:active-index="draft.setActivePersonBVariant($event)"
        @add="onAddPersonBVariant"
        @remove="onRemovePersonBVariant"
      />

      <p
        v-if="unusablePoseSelected"
        class="studio-error studio-error--inline"
        role="alert"
        data-testid="studio-pose-unusable"
      >
        {{ unusablePoseMessage }}
      </p>

    </ReferenceSectionCard>

    <!-- 文本补充（八类碎片）+ 负向：素材区之后、组合清单之前（方案 §5.5） -->
    <StudioTextSupplementCard
      ref="textSupplementRef"
      v-model="textFragments"
      v-model:negative-prompt="negativePrompt"
      :safe-mode="safeMode"
      :style-locked="styleLocked"
      :slot-modes="slotModes"
      :supplement-flags="supplementFlags"
      :recipe-source-name="recipeSourceName"
      @update:slot-mode="onSlotModeChange"
      @update:supplement="onSlotSupplementChange"
    />

    <div class="studio-grid">
      <!--
        行 B 左（8/12）：生成清单。
        矩阵自带「生成清单 + N / 上限 100」标题，这里只保留一行槽位摘要，
        batch-* testid 仍挂在原位置，兼容既有 e2e。
      -->
      <section class="studio-cell studio-cell--8 matrix-cell">
        <div class="matrix-head" data-testid="studio-batch-summary">
          <span data-testid="studio-selected-total">已选 {{ totalSelected }} 张 · 图片槽 {{ activeSlotCount }} · 文本槽 {{ textSlotCount }} · 补充 {{ supplementSlotCount }}</span>
          <span class="matrix-head__sep" aria-hidden="true">·</span>
          <span data-testid="studio-batch-total">共 {{ batchTotal }} 组</span>
        </div>
        <p v-if="batchOverLimit" class="studio-error studio-error--inline" role="alert" data-testid="studio-batch-limit">
          {{ batchLimitMessage }}
        </p>
        <StudioMatrix
          :groups="previewGroups"
          :total="batchTotal"
          :limit="MAX_BATCH_RECIPES"
          :over-limit="batchOverLimit"
          :limit-message="batchLimitMessage"
          :slot-counts="slotCounts"
          :workflow-count="workflowDimension"
          :quality-count="qualityCountForBar"
          :ratio-count="ratioCountForBar"
          :workflows="workflows"
          :pose-use-depth="poseUseDepth"
          :active-slot-count="activeSlotCount"
          :slot-modes="slotModes"
          :slot-texts="slotTexts"
          :supplement-flags="supplementFlags"
        />
      </section>

      <!-- 行 B 右（4/12）：参数（用分区卡包一层，和左侧清单同底色） -->
      <ReferenceSectionCard class="studio-cell studio-cell--4" title="参数">
        <StudioParamsCard
          :workflow-selection="workflowSelection"
          :workflows="workflows"
          :selected-roles="filledSlotRoles"
          :workflow-default-path="workflowDefaultPath"
          :workflows-loading="workflowsLoading"
          :workflows-error="workflowsError"
          :style="style"
          :style-options="STYLE_OPTIONS"
          :style-locked="styleLocked"
          :quality-enabled="caps.quality"
          :quality-options="qualityOptions"
          :quality-selection="qualitySelection"
          :orientation-enabled="caps.orientation"
          :aspect-ratios="aspectRatios"
          :ratio-selection="ratioSelection"
          :follows-reference-size="followsReferenceSize"
          :body-mode="bodyMode"
          :safe-mode="safeMode"
          :base-seed="baseSeed"
          @update:workflow-selection="workflowSelection = $event"
          @update:style="onParamsStyleChange"
          @toggle-quality="toggleQuality"
          @toggle-ratio="toggleRatio"
          @update:base-seed="setBaseSeed"
          @update:body-mode="onParamsBodyMode"
          @reload-workflows="reloadWorkflows"
        />
      </ReferenceSectionCard>

      <!-- 行 C 左（7/12）：提示词分段直接编辑（P3，方案 §14） -->
      <ReferenceSectionCard class="studio-cell studio-cell--7" title="提示词预览">
          <template #actions>
            <button
              type="button"
              class="studio-btn studio-btn--ghost studio-btn--sm"
              data-testid="studio-prompt-copy"
              :disabled="(!previewPrompt && !promptOverride) || previewLoading"
              @click="copyPromptPreview"
            >
              复制提示词
            </button>
          </template>

          <p class="studio-hint">
            提示词由碎片生成；每段都可直接编辑，改后按原文提交。
            <template v-if="totalSelected > 1">多选时按每槽第一张生成代表组合。</template>
            <template v-if="workflowSelection.length > 1 && previewWorkflow">
              多工作流时按第一条工作流预览：{{ workflowDisplayName(previewWorkflow.name) }}。
            </template>
          </p>

          <div class="prompt-preview" data-testid="studio-prompt-preview">
            <span v-if="previewLoading" class="prompt-preview__state">
              正在生成提示词预览…
            </span>
            <span v-else-if="previewError" class="prompt-preview__error" role="alert">
              {{ previewError }}
            </span>
            <StudioPromptEditor
              v-else-if="previewPrompt || promptOverride"
              :prompt="previewPrompt"
              v-model="promptOverride"
              :slot-modes="slotModes"
              :supplement-flags="supplementFlags"
              :loading="previewLoading"
              :error="previewError"
              @retry="refreshPreviewPrompt"
            />
            <span v-else class="prompt-preview__state">
              三槽均未选择：选择任一参考图后将在此显示后端组合出的提示词。
            </span>
          </div>

          <!--
            最终负向（实际提交）：§11.3 要求预览与真实提交同源。
            自动模式随后端 dry-run 的 negative_prompt / negative_effective；
            手动改写时后端不再自动抽取，只显示用户填写的内容（方案 §14.2）。
          -->
          <div
            v-if="previewPrompt || manualPromptActive"
            class="prompt-preview__negative"
            data-testid="studio-prompt-negative"
          >
            <span class="prompt-preview__negative-label">
              {{ manualPromptActive ? '负向（已手动修改）' : '最终负向（实际提交）' }}
            </span>
            <pre
              v-if="displayedNegativePrompt"
              class="prompt-preview__negative-text"
              data-testid="studio-prompt-negative-text"
            >{{ displayedNegativePrompt }}</pre>
            <span
              v-else
              class="prompt-preview__negative-empty"
              data-testid="studio-prompt-negative-empty"
            >
              （空）
            </span>
            <p
              v-if="manualPromptActive"
              class="prompt-preview__negative-note"
              data-testid="studio-prompt-negative-manual-note"
            >
              已手动修改：负向只包含你填写的内容，不再自动抽取
            </p>
            <p
              v-else-if="previewNegativeEffective === false"
              class="prompt-preview__negative-note"
              data-testid="studio-prompt-negative-inactive"
            >
              当前工作流负向不生效，实际提交为空
            </p>
          </div>

          <button
            v-if="previewError"
            type="button"
            class="studio-btn studio-btn--ghost studio-btn--sm"
            data-testid="studio-prompt-retry"
            :disabled="previewLoading"
            @click="refreshPreviewPrompt"
          >
            重试
          </button>
      </ReferenceSectionCard>

      <!-- 行 C 右（5/12）：补充要求（与提示词预览并排，避免两块各占整行） -->
      <ReferenceSectionCard class="studio-cell studio-cell--5" title="补充要求">
        <label class="field__label" for="studio-prompt-suffix">补充要求（可选）</label>
        <textarea
          id="studio-prompt-suffix"
          v-model="promptSuffix"
          class="studio-textarea"
          rows="4"
          placeholder="例如：暖色灯光、浅景深；作为 prompt_suffix 提交"
          data-testid="studio-prompt-suffix"
        />
        <p class="studio-hint">
          每段可直接编辑；改后按原文提交，补充要求不再参与。
        </p>
      </ReferenceSectionCard>

      <!-- 行 D（12/12）：生成结果 -->
      <ReferenceSectionCard class="studio-cell studio-cell--12" title="生成结果">
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

          <!-- 常驻说明：ComfyUI 队列串行执行，新任务立即入队 -->
          <p
            class="studio-queue-note"
            data-testid="studio-queue-note"
            :data-polling="polling ? 'true' : 'false'"
          >
            GPU 串行执行：新任务会立即入队，无需等上一批出图
          </p>

          <!-- 提交前校验错误（尚未创建批次） -->
          <p
            v-if="formError"
            class="studio-error studio-error--inline"
            role="alert"
            data-testid="studio-form-error"
          >
            {{ formError }}
          </p>

          <!-- 上一张结果（失败区手动查看） -->
          <div v-if="showingPrevious && previousResultUrl" class="preview-box preview-box--previous">
            <img
              :src="previousResultUrl"
              alt="上一张生成结果"
              class="preview-image"
              data-testid="studio-previous-image"
            />
            <button
              type="button"
              class="studio-btn studio-btn--ghost studio-btn--sm"
              @click="returnToLatestResult"
            >
              返回最新结果
            </button>
          </div>

          <StudioResultBoard
            :batches="displayedBatches"
            :pose-use-depth="poseUseDepth"
            :workflows="workflows"
            @preview="openResultPreview"
            @reuse="onReuseBatch"
            @clear-finished="onClearFinishedBatches"
            @job-center="goJobCenter"
          />

          <!-- 失败批次操作：沿用既有重试 / 查看上一张 -->
          <div v-if="hasFailedBatch" class="result-actions">
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
      </ReferenceSectionCard>
    </div>

    <!-- 操作条（M6）：fixed 吸底，确认弹窗在组件内，取消不发 submit -->
    <StudioActionBar
      :total="batchTotal"
      :portrait-count="slotCounts.portrait"
      :costume-count="slotCounts.costume"
      :pose-count="slotCounts.pose"
      :workflow-count="workflowDimension"
      :quality-count="qualityCountForBar"
      :ratio-count="ratioCountForBar"
      :over-limit="batchOverLimit"
      :limit-message="batchLimitMessage"
      :can-submit="canSubmit"
      :submitting="submitting"
      :library-loading="libraryLoading"
      :recipe-loading="recipeRandomLoading"
      :atomic-loading="atomicRandomLoading"
      :slot-modes="slotModes"
      :person-b-variant-count="hasPairPose ? draft.personBVariants.value.length : 0"
      @randomize="randomize"
      @randomize-recipe="randomizeRecipe"
      @randomize-atomic="randomizeAtomic"
      @submit="onGenerate"
    />

    <!--
      槽位灯箱：直接复用画廊 `components/Lightbox.vue`，只读打开。
      - `readonly` 关掉收藏 / 删除 / 重出图 / 投喂等写操作；
      - `can-open-gallery=false` 不显示「到画廊定位」；
      - `file-actions=false` 隐藏下载 / 打开目录 / 出片档案 / 存储位置
        （这些入口依赖 ComfyUI 媒体三目录里的 filename）；
      - 不传 `workflows`：参考图条目没有工作流；
      - 翻页只更新 `index`，范围由 `onPreviewIndexChange` 限制在当前槽位内。
    -->
    <Lightbox
      v-if="slotPreview && previewHistoryItems.length"
      :items="previewHistoryItems"
      :index="previewIndex"
      readonly
      :can-open-gallery="false"
      :file-actions="false"
      @update:index="onPreviewIndexChange"
      @close="closeSlotPreview"
    />

    <!--
      结果灯箱：只读打开，翻页范围限于当前批次。
      与槽位灯箱的唯一差异是**不传 `file-actions=false`** —— 灯箱里的「下载原图」
      受 `showFileActions` 控制，关掉它等于连下载一起关掉；用户 2026-11-06 已拍板
      「下载只留在灯箱内」，因此保留 fileActions 默认值。
    -->
    <Lightbox
      v-if="resultPreview && resultPreviewHistoryItems.length"
      :items="resultPreviewHistoryItems"
      :index="resultPreviewIndex"
      readonly
      :can-open-gallery="false"
      @update:index="onResultPreviewIndexChange"
      @close="closeResultPreview"
    />

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

        <!-- 后端已确认裁不掉（blockedReason 非空）时不再提供「仍用当前工作流提交」：必然 400 -->
        <p
          v-if="workflowDowngrade.blockedReason"
          class="studio-modal__message studio-modal__message--blocked"
          data-testid="studio-downgrade-blocked"
        >
          后端确认空槽无法裁剪：{{ workflowDowngrade.blockedReason }}
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
          <template v-if="workflowDowngrade.blockedReason">
            当前没有 input_count ≤ {{ workflowDowngrade.slotCount }} 的候选工作流。可取消后补齐参考图再提交。
          </template>
          <template v-else>
            当前没有 input_count ≤ {{ workflowDowngrade.slotCount }} 的候选工作流。可取消后补齐参考图再提交，或仍用当前工作流尝试（后端会裁掉空槽，无法裁剪时返回 400）。
          </template>
        </p>

        <div class="studio-modal__actions">
          <button
            v-if="!workflowDowngrade.blockedReason"
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

    </div>
</template>

<style scoped>
.ref-studio {
  display: flex;
  flex-direction: column;
  min-width: 0;
  /* fixed 操作条常驻：页面末尾留出条高，避免遮住结果区最后一行 */
  padding-bottom: 80px;
}

@media (max-width: 1023px) {
  .ref-studio {
    padding-bottom: 96px;
  }
}

.ref-studio__head {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
}

.ref-studio__title {
  margin: 0;
  color: var(--text-strong);
  font-size: 20px;
  font-weight: 600;
  line-height: 1.3;
}

.ref-studio__desc {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}

/*
 * 12 栏布局：左 7 列 / 右 5 列、gap 24px（对齐 React lg:grid-cols-12 lg:gap-6）。
 * 用 12 列而不是 `7fr / 5fr`：12 列的 gap 也参与列宽换算，1920 视口下
 * 左栏 = 736.67、右栏 = 519.33，与 §5 的槽位卡 224.22 / 预览区 471.33 对得上。
 */
/*
 * 12 栏网格：每个区块直接是 grid 子项，用 `.studio-cell--N` 指定跨栏。
 *
 * 2026-11-06 空间利用率优化（此前所有区块都是 `1 / -1` 全宽单列）：
 *   行 A：素材 12
 *   行 B：清单 8 + 参数 4
 *   行 C：提示词预览 7 + 补充要求 5
 *   行 D：结果 12
 * <1200 全部回落整行（参数卡在 4 栏时只剩 300 出头，两列网格会挤）。
 */
.studio-grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 16px;
  align-items: start;
  /* 全宽素材卡与下方两栏之间留 16px（header 自带 margin-bottom，不再叠加） */
  margin-top: 16px;
}

.studio-cell {
  min-width: 0;
}

.studio-cell--8 {
  grid-column: span 8;
}

.studio-cell--7 {
  grid-column: span 7;
}

.studio-cell--5 {
  grid-column: span 5;
}

.studio-cell--4 {
  grid-column: span 4;
}

.studio-cell--12 {
  grid-column: 1 / -1;
}

/* 清单列：摘要行 + 矩阵，两者都由矩阵自身提供卡片外观 */
.matrix-cell {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

@media (max-width: 1199px) {
  .studio-cell--8,
  .studio-cell--7,
  .studio-cell--5,
  .studio-cell--4 {
    grid-column: 1 / -1;
  }
}


/* 素材区 4 列：三槽 + 第 4 张；全宽下每列约 280px，窄屏回落 2 列 / 1 列 */
.slot-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  align-items: stretch;
}

/* 没有工作流接第 4 张时收成 3 列，避免右侧留一个空洞 */
.slot-grid--compact {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

/* 槽位列：面板 + 「上传本地图」按钮（上传图与库条目同数组，一起参与组合） */
.slot-column {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.slot-upload {
  width: 100%;
  padding: 6px 10px;
  border: 1px dashed var(--border);
  border-radius: 8px;
  background: transparent;
  color: var(--text-body-soft);
  font-size: 12px;
  line-height: 1.4;
  cursor: pointer;
}

.slot-upload:hover:not(:disabled) {
  border-color: var(--border-hover);
  color: var(--text-strong);
}

.slot-upload:disabled {
  cursor: progress;
  opacity: 0.6;
}

.slot-upload-input {
  display: none;
}

/*
 * 断点收紧：780px 左右若还保持 4 列，单卡只有约 170px，图墙会退化成
 * 1 列大图（3 张就把卡片撑到 500px 高）。这里按可用宽度逐级减列。
 */
@media (max-width: 1023px) {
  .slot-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 899px) {
  .slot-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 479px) {
  .slot-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

/* 生成清单头部：标题 + 计数（batch-* testid 兼容层） */
.matrix-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.4;
}

.matrix-head__sep {
  color: var(--text-faint);
}

.studio-count {
  padding: 1px 8px;
  border-radius: 9999px;
  background: var(--fill-soft);
  color: var(--text-muted);
  font-size: 12px;
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
  font-size: 12px;
}

.studio-btn--ghost {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-strong);
}

.studio-btn--ghost:hover:not(:disabled) {
  background: var(--fill-subtle);
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

.extra-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.extra-library {
  height: 40px;
  border: 1px dashed var(--border-subtle);
  border-radius: 12px;
  background: transparent;
  color: var(--text-muted);
  font-size: 14px;
  cursor: pointer;
}

.extra-library:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.extra-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
  box-sizing: border-box;
  min-width: 0;
  padding: 8px 10px;
  border-radius: 12px;
  background: var(--surface-code);
}

/* 首行：图标 + 名称 / 来源 + 移除，保持与三槽卡片同高的横排 */
.extra-item__row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

/* 文字补充：只在有图时出现（图为主 + 文本补充） */
.extra-item__text {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-sunken);
  color: var(--text-strong);
  font-size: 12px;
  line-height: 1.5;
  resize: vertical;
}

.extra-item__hint {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.extra-item__mark {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 40px;
  border-radius: 10px;
  background: var(--surface-inset);
  color: var(--text-muted);
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
  color: var(--text-strong);
  font-size: 12px;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.extra-item__meta {
  color: var(--text-muted);
  font-size: 12px;
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
  color: var(--text-strong);
  font-size: 12px;
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
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.4;
}

/* 工作流 / 画风并排：2fr / 1fr；<768px 回落单列 */
.field-row {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 16px;
  align-items: start;
  min-width: 0;
}

/* 子组件下拉原本 max-width 336.33；并排时让它撑满所在列 */
.field-row :deep(.wf-select) {
  max-width: none;
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
  background: var(--surface-code);
  color: var(--text-strong);
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
  background: var(--surface-code);
  color: var(--text-strong);
  font-family: inherit;
  font-size: 12px;
  line-height: 1.6;
  resize: vertical;
}

.studio-textarea:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
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

.studio-note {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}

.studio-hint {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}

.studio-error {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--danger-border);
  border-radius: 10px;
  background: var(--danger-surface-mid);
  color: var(--danger-text);
  font-size: 12px;
  line-height: 1.6;
}


/* 提示词预览：分段卡片自适应高度，交给页面滚动，不再嵌套滚动条 */
.prompt-preview {
  box-sizing: border-box;
  width: 100%;
  padding: 10px 12px;
  border-radius: 12px;
  background: var(--surface-code);
}

.prompt-preview__text {
  margin: 0;
  color: var(--text-strong);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.prompt-preview__state {
  display: block;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}

/* 最终负向（实际提交）：与正向预览分块展示，避免两段文本混在一起 */
.prompt-preview__negative {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  box-sizing: border-box;
  padding: 10px 12px;
  border: 1px solid var(--border-faint);
  border-radius: 12px;
  background: var(--surface-result);
}

.prompt-preview__negative-label {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.prompt-preview__negative-text {
  margin: 0;
  color: var(--text-body);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.prompt-preview__negative-empty {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.prompt-preview__negative-note {
  margin: 0;
  color: var(--warn);
  font-size: 12px;
  line-height: 1.6;
}

.prompt-preview__error {
  display: block;
  color: var(--danger-text-soft);
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}


/* 结果预览区：min-height 460、内边距 16、圆角 18；浅色下补 1px 边框避免与卡片同色 */
.preview-box {
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  width: 100%;
  min-height: 460px;
  padding: 16px;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 18px;
  background: var(--surface-result);
}

/* 进度条 / 预览态骨架已迁入 StudioResultBoard，这里不再保留 */

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
  background: var(--danger-surface-strong);
  color: var(--danger-text-strong);
  font-size: 16px;
  font-weight: 700;
}

.preview-error__title {
  margin: 0;
  color: var(--danger-text-strong);
  font-size: 14px;
  font-weight: 600;
}

.preview-error__text {
  margin: 0;
  color: var(--text-body-soft);
  font-size: 12px;
  line-height: 1.7;
  text-align: left;
  word-break: break-word;
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


/* 1024px 以下整行堆叠（栅格子项已在 1200 断点统一回落 1 / -1） */
@media (max-width: 1023px) {
  .studio-grid {
    grid-template-columns: minmax(0, 1fr);
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
  color: var(--text-strong);
  font-size: 12px;
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
  background: var(--btn-inverse-bg);
  color: var(--on-inverse);
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
  color: var(--danger-text-soft);
  font-size: 12px;
  line-height: 1.6;
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
  background: var(--scrim-strong);
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
  background: var(--surface-raised);
  box-shadow: var(--shadow-overlay);
}

.studio-modal__title {
  margin: 0;
  color: var(--text-strong);
  font-size: 15px;
  font-weight: 600;
  line-height: 1.4;
}

.studio-modal__message {
  margin: 0;
  color: var(--text-body-soft);
  font-size: 12px;
  line-height: 1.7;
  word-break: break-word;
}

/* 后端确认裁不掉：用错误色与前两段说明区分开，避免用户误以为是可尝试项 */
.studio-modal__message--blocked {
  color: var(--danger-text-soft);
}

.studio-modal__meta {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
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
  color: var(--text-muted);
  font-size: 12px;
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
  background: var(--surface-code);
  color: var(--text-strong);
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}

.downgrade-list__item:hover {
  border-color: var(--primary);
  background: var(--fill-faint);
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
  color: var(--text-muted);
  font-size: 12px;
}

/* 结果区（多批次分组 / 网格 / 空态）已迁入 StudioResultBoard.vue */

/* 常驻说明：新任务入队即可，不必等上一批出图 */
.studio-queue-note {
  margin: 0 0 10px;
  color: var(--text-body-soft);
  font-size: 12px;
  line-height: 1.6;
}

/* 「上一张结果」块不占 460 基础高度 */
.preview-box--previous {
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  margin-bottom: 10px;
}


</style>
