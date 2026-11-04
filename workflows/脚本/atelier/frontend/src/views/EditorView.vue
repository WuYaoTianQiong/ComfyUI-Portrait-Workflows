<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import ImagePicker from '../components/ImagePicker.vue'
import DiskPathList from '../components/DiskPathList.vue'
import DropZone from '../components/DropZone.vue'
import FilePicker from '../components/FilePicker.vue'
import MaskEditorModal from '../components/MaskEditorModal.vue'
import ReferenceSheetButton from '../components/ReferenceSheetButton.vue'
import { apiGet, apiPost, thumbnailUrl, viewUrl } from '../api/client'
import type { UploadedReference } from '../api/upload'
import { useGenerate } from '../composables/useGenerate'
import { useSettings } from '../composables/useSettings'
import { useImageLocation } from '../composables/useImageLocation'
import { useWorkflows, customWorkflowContent } from '../composables/useWorkflows'
import { statusLabel } from '../utils/format'
import { confirmDialog } from '../utils/naive'
import { CONFIRM_PROMPTS } from '../utils/confirmKeys'
import { useToast } from '../composables/useToast'
import { readSession, writeSession } from '../composables/useSessionState'
import type { HistoryItem, HistoryPage } from '../api/types'

/** 与后端 `editor.DEFAULT_PROMPT` 保持一致；留空提交时后端也会用这句。 */
const DEFAULT_PROMPT =
  '只修改提示词中描述的部分，其余人物相貌、姿势、构图、服装、背景与光线保持与目标图一致，自然真实，高清细节'

/** 常用编辑场景的参考提示词：点一下填入，省得用户从零手写。 */
const PROMPT_PRESETS: Array<{ label: string; text: string }> = [
  { label: '通用编辑', text: DEFAULT_PROMPT },
  {
    label: '换脸',
    text:
      '保持人物的姿势、构图、服装、背景与光线完全不变，只把面部替换成参考图中人物的脸，' +
      '脸型与五官保持一致，自然真实，高清细节',
  },
  {
    label: '换衣',
    text:
      '保持人物姿势、面部、背景与光线不变，把服装换成参考图中的款式、材质与颜色，' +
      '版型自然贴合身体，高清细节',
  },
  {
    label: '换背景',
    text:
      '保持人物的姿势、面部与服装不变，把背景替换成参考图中的场景，' +
      '光照方向与人物自然融合，高清细节',
  },
  {
    label: '三图参考',
    text:
      '人物相貌参考参考图1，服装参考参考图2，保持目标图的姿势、构图与背景，' +
      '自然融合，高清细节',
  },
  {
    label: '局部重绘',
    text:
      '只修改遮罩标记的区域，其余区域保持不变，' +
      '修改结果与周围光照、材质自然过渡，高清细节',
  },
]

// 换脸必须用「双 LoadImage」的换脸工作流，单独一份，不能被文生图工作流覆盖
const { faceswapWorkflowPath: workflowPath } = useSettings()
const { workflows } = useWorkflows()
const { busy: generating, job: activeJob, error: generateError, submitAndTrack } = useGenerate()
const { revealImage } = useImageLocation()
const toast = useToast()

/** 会话状态：三组素材、组合方式、种子、提示词。 */
interface EditGroup {
  ids: number[]
  paths: string[]
  pickerOpen: boolean
}

interface EditSession {
  targetIds: number[]
  targetPaths: string[]
  refIds: number[]
  refPaths: string[]
  ref2Ids: number[]
  ref2Paths: string[]
  ref3Ids: number[]
  ref3Paths: string[]
  /** 目标图 → 遮罩文件绝对路径；key 形如 id:12 / file:<路径>。 */
  masks: Record<string, string>
  pairMode: 'cross' | 'zip'
  seedMode: 'fixed' | 'random' | 'increment'
  seed: number
  promptText: string
}

const SESSION_KEY = 'pb.session.faceswap'
/** 旧会话只有主图/参考图两组，读取时做一次兼容映射。 */
const savedSession = readSession<
  Partial<EditSession> & { mainIds?: number[]; mainPaths?: string[] }
>(SESSION_KEY, {
  masks: {},
  pairMode: 'cross',
  seedMode: 'fixed',
  seed: 100000,
  promptText: '',
})

const groups = ref<EditGroup[]>([
  {
    ids: savedSession.targetIds ?? savedSession.mainIds ?? [],
    paths: savedSession.targetPaths ?? savedSession.mainPaths ?? [],
    pickerOpen: false,
  },
  { ids: savedSession.refIds ?? [], paths: savedSession.refPaths ?? [], pickerOpen: false },
  { ids: savedSession.ref2Ids ?? [], paths: savedSession.ref2Paths ?? [], pickerOpen: false },
  { ids: savedSession.ref3Ids ?? [], paths: savedSession.ref3Paths ?? [], pickerOpen: false },
])

const pairMode = ref<'cross' | 'zip'>(savedSession.pairMode ?? 'cross')
const seedMode = ref<'fixed' | 'random' | 'increment'>(savedSession.seedMode ?? 'fixed')
const seed = ref(savedSession.seed ?? 100000)
const promptText = ref(savedSession.promptText ?? '')
const maskEntries = ref<Record<string, string>>({ ...(savedSession.masks ?? {}) })

watch(
  [groups, maskEntries, pairMode, seedMode, seed, promptText],
  () => {
    const [target, ref1, ref2, ref3] = groups.value
    writeSession(SESSION_KEY, {
      targetIds: target.ids,
      targetPaths: target.paths,
      refIds: ref1.ids,
      refPaths: ref1.paths,
      ref2Ids: ref2.ids,
      ref2Paths: ref2.paths,
      ref3Ids: ref3.ids,
      ref3Paths: ref3.paths,
      masks: maskEntries.value,
      pairMode: pairMode.value,
      seedMode: seedMode.value,
      seed: seed.value,
      promptText: promptText.value,
    })
  },
  { deep: true },
)

interface NodeInfo {
  loadimages: Array<{ id: string; title: string }>
  inputs: Array<{ role: 'target' | 'ref1' | 'ref2' | 'ref3'; id: string }>
  roles: string[]
  target: string | null
  refs: string[]
  /** 工作流是否带遮罩链路（VAEEncodeForInpaint）。 */
  mask: boolean
  max_combos: number
}

/** 探测工作流的 LoadImage 节点，按数量决定页面显示 1/2/3/4 列。 */
const {
  data: nodeInfo,
  error: nodeError,
  isFetching: probing,
} = useQuery<NodeInfo>({
  queryKey: computed(() => ['fs-nodes', workflowPath.value]),
  queryFn: () => apiPost<NodeInfo>('/api/editor/faceswap/nodes', { workflow_path: workflowPath.value }),
  enabled: computed(() => !!workflowPath.value),
  retry: false,
})

/** 目标图的文件名/缩略图：遮罩按图配，行里得让用户认得出是哪张。 */
const { data: targetBriefs } = useQuery<HistoryPage>({
  queryKey: computed(() => ['fs-target-briefs', groups.value[0].ids.join(',')]),
  queryFn: () =>
    apiGet<HistoryPage>('/api/images', {
      ids: groups.value[0].ids.join(','),
      page_size: 200,
    }),
  enabled: computed(() => groups.value[0].ids.length > 0),
  staleTime: 30_000,
})

const briefMap = computed<Record<number, HistoryItem>>(() => {
  const map: Record<number, HistoryItem> = {}
  for (const item of targetBriefs.value?.items ?? []) map[item.id] = item
  return map
})

function fileName(path: string) {
  return path.split(/[/\\]/).pop() || path
}

interface TargetRow {
  key: string
  label: string
  thumb: string
  /** 原图地址：涂抹遮罩时铺到 canvas 上。 */
  imageUrl: string
}

/** 与后端 _collect_sources 的顺序一致：先画廊 id，再磁盘路径。 */
const targetRows = computed<TargetRow[]>(() => {
  const [target] = groups.value
  const rows: TargetRow[] = target.ids.map((id) => {
    const item = briefMap.value[id]
    return {
      key: `id:${id}`,
      label: item?.filename ?? `#${id}`,
      thumb: item ? thumbnailUrl(item, 120) : '',
      imageUrl: item ? viewUrl(item) : '',
    }
  })
  for (const path of target.paths) {
    rows.push({
      key: `file:${path}`,
      label: fileName(path),
      thumb: `/api/browser/thumb?path=${encodeURIComponent(path)}&size=120`,
      imageUrl: `/api/browser/image?path=${encodeURIComponent(path)}`,
    })
  }
  return rows
})

const targetKeys = computed(() => targetRows.value.map((row) => row.key))

/** 提交时按目标图顺序摊平成数组；空串 = 这张不配遮罩（整图重绘）。 */
const maskPaths = computed(() => targetKeys.value.map((key) => maskEntries.value[key] ?? ''))

// 目标图被移除后，对应遮罩也清掉，避免换图时错配
watch(targetKeys, (keys) => {
  const next = { ...maskEntries.value }
  let changed = false
  for (const key of Object.keys(next)) {
    if (!keys.includes(key)) {
      delete next[key]
      changed = true
    }
  }
  if (changed) maskEntries.value = next
})

const maskPickerOpen = ref(false)
const maskPickTarget = ref('')
const maskPickPaths = ref<string[]>([])

function pickMask(key: string) {
  maskPickTarget.value = key
  maskPickPaths.value = []
  maskPickerOpen.value = true
}

function onMaskPickerClose() {
  const picked = maskPickPaths.value[0]
  if (picked && maskPickTarget.value) {
    maskEntries.value = { ...maskEntries.value, [maskPickTarget.value]: picked }
  }
  maskPickerOpen.value = false
}

function clearMask(key: string) {
  const next = { ...maskEntries.value }
  delete next[key]
  maskEntries.value = next
}

/** 从目标图里移除一张（画廊 id 或磁盘路径）；对应遮罩随 targetKeys 变化自动清掉。 */
function removeTarget(key: string) {
  const [target] = groups.value
  if (key.startsWith('id:')) {
    const id = Number(key.slice(3))
    target.ids = target.ids.filter((x) => x !== id)
  } else if (key.startsWith('file:')) {
    const path = key.slice(5)
    target.paths = target.paths.filter((x) => x !== path)
  }
}

/** 上传成功：按返回顺序追加到对应槽位（同一张图重复拖入时只留一份）。 */
function onUploaded(index: number, items: UploadedReference[]) {
  const group = groups.value[index]
  if (!group || !items.length) return

  const known = new Set(group.paths)
  const fresh = items
    .map((item) => item.path)
    .filter((path) => !known.has(path))
  if (fresh.length) group.paths = [...group.paths, ...fresh]

  const duplicated = items.length - fresh.length
  if (!fresh.length) {
    toast.info(`${roleMeta(index).label}里已有这 ${items.length} 张图片`)
    return
  }
  toast.success(
    duplicated > 0
      ? `已加入 ${fresh.length} 张，${duplicated} 张已在槽位中`
      : `已加入 ${fresh.length} 张图片`,
  )
}

// ---------------- 涂抹遮罩 ----------------

const maskEditorOpen = ref(false)
const maskEditorKey = ref('')
const maskEditorImage = ref('')
const maskEditorInitial = ref('')
const maskSaving = ref(false)

function openMaskEditor(row: TargetRow) {
  if (!row.imageUrl) return
  maskEditorKey.value = row.key
  maskEditorImage.value = row.imageUrl
  const existing = maskEntries.value[row.key]
  maskEditorInitial.value = existing
    ? `/api/browser/image?path=${encodeURIComponent(existing)}`
    : ''
  maskEditorOpen.value = true
}

async function onMaskSaved(payload: { dataUrl: string | null }) {
  const key = maskEditorKey.value
  maskEditorOpen.value = false
  if (!payload.dataUrl) {
    clearMask(key)
    return
  }
  maskSaving.value = true
  try {
    const result = await apiPost<{ path: string }>('/api/editor/faceswap/mask', {
      data_url: payload.dataUrl,
    })
    maskEntries.value = { ...maskEntries.value, [key]: result.path }
  } catch (e) {
    toast.error(`遮罩保存失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    maskSaving.value = false
  }
}

/** 文案与角色：工作流有几个 LoadImage，就显示几列，顺序固定为目标图 → 参考1 → 参考2 → 参考3。 */
const ROLE_META = {
  target: { label: '目标图', hint: '保留姿势/服装/背景，决定输出尺寸' },
  ref1: { label: '参考图1', hint: '提供要参考/替换的内容' },
  ref2: { label: '参考图2', hint: '第二张参考' },
  ref3: { label: '参考图3', hint: '只补鞋包/配饰/场景' },
} as const
const ROLE_KEYS = ['target', 'ref1', 'ref2', 'ref3'] as const

function roleMeta(index: number) {
  return ROLE_META[ROLE_KEYS[index] ?? 'ref3']
}

/** 未选工作流时按旧版双图布局兜底；选中后按实际 LoadImage 数量显示。 */
const columnCount = computed(() => {
  const n = nodeInfo.value?.loadimages.length
  if (!n) return 2
  return Math.min(4, n)
})

const tooManyInputs = computed(() => (nodeInfo.value?.loadimages.length ?? 0) > 4)
const visibleGroups = computed(() => groups.value.slice(0, columnCount.value))
const groupCounts = computed(() => groups.value.map((g) => g.ids.length + g.paths.length))
const activeCounts = computed(() => groupCounts.value.slice(0, columnCount.value))


const UPLOADS_SEGMENT = /(^|[/\\])uploads[/\\]/i

const ref3UploadPath = computed<string | null>(() => {
  const ref3 = groups.value[3]
  if (!ref3) return null
  return ref3.paths.find((path) => UPLOADS_SEGMENT.test(path)) ?? null
})

const comboCount = computed(() => {
  if (activeCounts.value.some((c) => c === 0)) return 0
  if (columnCount.value === 1) return activeCounts.value[0]
  if (pairMode.value === 'zip') {
    return activeCounts.value.every((c) => c === activeCounts.value[0])
      ? activeCounts.value[0]
      : 0
  }
  return activeCounts.value.reduce((a, b) => a * b, 1)
})

const zipMismatch = computed(
  () =>
    columnCount.value >= 2 &&
    pairMode.value === 'zip' &&
    activeCounts.value.some((c) => c !== activeCounts.value[0]),
)

const maxCombos = computed(() => nodeInfo.value?.max_combos ?? 100)
/**
 * 组合上限只约束「多角色 × 全组合」。
 *
 * 单图工作流（1 个 LoadImage）其实是批量处理多张目标图，后端按单组直接提交、
 * 没有 10 张上限；这里沿用旧逻辑一刀切会导致 16 张被静默禁用（按钮点不动，
 * 又因为组合方式分区只在多列时显示，用户看不到任何原因）。
 * 1:1 配对的组数相等，同样不受全组合上限约束。
 */
const comboOverLimit = computed(
  () =>
    columnCount.value > 1 &&
    pairMode.value === 'cross' &&
    comboCount.value > maxCombos.value,
)

const summaryText = computed(() =>
  activeCounts.value.map((c, i) => `${roleMeta(i).label} ${c}`).join(' × '),
)

/**
 * 工作流的 LoadImage 数量必须和页面列数一致：
 * 1 个 = 单图编辑，2 个 = 双图参考，3 个 = 三图参考。
 * 多于 3 个后端注入不了，0 个则不是图像编辑工作流。
 */
const nodeReady = computed(() => {
  const info = nodeInfo.value
  if (!info || tooManyInputs.value || !info.target) return false
  return (info.inputs?.length ?? 0) === columnCount.value
})

const canSubmit = computed(
  () =>
    !generating.value &&
    !!workflowPath.value &&
    nodeReady.value &&
    activeCounts.value.every((c) => c > 0) &&
    !zipMismatch.value &&
    !comboOverLimit.value,
)

async function submit() {
  if (!canSubmit.value) return
  const ok = await confirmDialog({
    title: '图像编辑',
    content: `将提交 ${comboCount.value} 张（${summaryText.value}），确认继续？`,
    positiveText: '提交',
    negativeText: '取消',
    rememberKey: CONFIRM_PROMPTS.editorSubmit.key,
  })
  if (!ok) return
  const [target, ref1, ref2, ref3] = groups.value
  try {
    const result = await submitAndTrack<{
      success: boolean
      job_id: number
      total: number
      submitted: number
      async?: boolean
      queued?: number
    }>('/api/editor/faceswap/batch', {
      main_ids: target.ids,
      main_paths: target.paths,
      ref_ids: columnCount.value >= 2 ? ref1.ids : [],
      ref_paths: columnCount.value >= 2 ? ref1.paths : [],
      ref2_ids: columnCount.value >= 3 ? ref2.ids : [],
      ref2_paths: columnCount.value >= 3 ? ref2.paths : [],
      ref3_ids: columnCount.value >= 4 ? ref3.ids : [],
      ref3_paths: columnCount.value >= 4 ? ref3.paths : [],
      // 工作流没有遮罩链路时不提交，避免后端报错
      mask_paths: nodeInfo.value?.mask ? maskPaths.value : [],
      workflow_path: workflowPath.value,
      // 自定义工作流不在后端磁盘上，内容必须一起带过去
      workflow_content: customWorkflowContent(workflowPath.value),
      prompt: promptText.value,
      seed_mode: seedMode.value,
      seed: seed.value,
      pair_mode: pairMode.value,
    })
    if (!result.success) toast.error('提交失败')
    else if (result.async) toast.success(`已加入提交队列（${result.queued ?? result.total} 组）`)
  } catch (e) {
    toast.error(`提交失败：${e instanceof Error ? e.message : String(e)}`)
  }
}
</script>

<template>
  <div class="faceswap">
    <div v-for="(group, i) in visibleGroups" :key="ROLE_KEYS[i]" class="picker-col">
      <div class="picker-head">
        <span>{{ roleMeta(i).label }}（{{ roleMeta(i).hint }}）</span>
        <button class="btn btn-sm" title="从磁盘任意目录选图" @click="group.pickerOpen = true">
          📁 磁盘<template v-if="group.paths.length"> {{ group.paths.length }}</template>
        </button>
      </div>
      <p v-if="i === 3" class="pick-hint">
        第 4 张只补鞋包/配饰/场景，不要放第二套完整服装或第二张人像
      </p>
      <DropZone
        :label="`拖拽 / 粘贴 / 点击添加到${roleMeta(i).label}`"
        @uploaded="onUploaded(i, $event)"
        @error="toast.error($event)"
      />
      <ImagePicker v-model="group.ids" title="" />
      <div v-if="group.paths.length" class="disk-picked">
        <div class="disk-picked-head">
          <span>磁盘已选 {{ group.paths.length }} 张</span>
          <button class="btn btn-sm" @click="group.paths = []">清空</button>
        </div>
        <DiskPathList v-model="group.paths" show-thumbs :thumb-size="96" />
      </div>
    </div>

    <aside class="panel">
      <div class="section">
        <span class="label">工作流</span>
        <select v-model="workflowPath">
          <option value="">选择图像编辑工作流…</option>
          <option v-for="wf in workflows" :key="wf.path" :value="wf.path">{{ wf.name }}</option>
        </select>
      </div>

      <div class="section nodes">
        <span class="label">节点映射</span>
        <template v-if="probing">探测中…</template>
        <div v-else-if="nodeError" class="err-text">{{ nodeError.message }}</div>
        <template v-else-if="nodeInfo">
          <div v-if="nodeReady" class="node-row">
            <template v-for="(item, i) in nodeInfo.inputs" :key="item.role">
              <span class="node-role">{{ roleMeta(i).label }}</span>
              <span class="node-id">{{ item.id }}</span>
            </template>
          </div>
          <div v-else class="err-text">
            <template v-if="tooManyInputs">
              这个工作流有 {{ nodeInfo.loadimages.length }} 个 LoadImage，当前最多支持 4 个输入
            </template>
            <template v-else>
              这个工作流没有可注入的 LoadImage，请换一个图像编辑工作流
            </template>
          </div>
          <div class="node-list">
            LoadImage 节点 {{ nodeInfo.loadimages.length }} 个：
            {{ nodeInfo.loadimages.map((n) => n.id).join(' / ') || '无' }}
          </div>
        </template>
      </div>

      <div class="section masks">
        <span class="label">遮罩（可选，按目标图单独配）</span>
        <div v-if="!workflowPath" class="hint">
          先选择支持遮罩的单图 / 双图工作流，选好目标图后这里会出现「涂抹」按钮
        </div>
        <div v-else-if="probing" class="hint">探测工作流中…</div>
        <div v-else-if="nodeError" class="err-text">{{ nodeError.message }}</div>
        <div v-else-if="nodeInfo && !nodeInfo.mask" class="hint">
          该工作流没有遮罩链路（参考类工作流不支持遮罩）
        </div>
        <template v-else-if="nodeInfo">
          <div class="hint">白/不透明 = 要改；黑/透明 = 保留；不配 = 整图重绘</div>
          <div v-if="!targetRows.length" class="hint">先在左侧选目标图，再点「涂抹」画遮罩</div>
          <div v-else class="mask-list">
            <div v-for="row in targetRows" :key="row.key" class="mask-row">
              <img
                v-if="row.thumb"
                class="mask-thumb"
                :src="row.thumb"
                :alt="row.label"
                loading="lazy"
              />
              <span v-else class="mask-thumb placeholder">?</span>
              <div class="mask-info">
                <span class="mask-target" :title="row.label">{{ row.label }}</span>
                <span class="mask-file" :title="maskEntries[row.key] || ''">
                  {{ maskEntries[row.key] ? fileName(maskEntries[row.key]) : '未配（全图重绘）' }}
                </span>
              </div>
              <button class="btn btn-sm" :disabled="!row.imageUrl || maskSaving" title="在目标图上涂抹遮罩" @click="openMaskEditor(row)">
                涂抹
              </button>
              <button
                v-if="row.key.startsWith('id:')"
                class="btn btn-sm"
                title="在资源管理器中定位原图"
                @click="revealImage({ id: Number(row.key.slice(3)) })"
              >
                定位
              </button>
              <button class="btn btn-sm" @click="pickMask(row.key)">
                {{ maskEntries[row.key] ? '换' : '导入' }}
              </button>
              <button
                v-if="maskEntries[row.key]"
                class="btn btn-sm"
                title="清除这张目标图的遮罩"
                @click="clearMask(row.key)"
              >
                ×
              </button>
              <button
                class="btn btn-sm"
                title="从目标图中移除这张"
                @click="removeTarget(row.key)"
              >
                移除
              </button>
            </div>
          </div>
        </template>
      </div>

      <div v-if="columnCount >= 2" class="section">
        <span class="label">组合方式</span>
        <div class="seg">
          <button class="btn btn-sm" :class="{ active: pairMode === 'cross' }" @click="pairMode = 'cross'">
            全组合
          </button>
          <button class="btn btn-sm" :class="{ active: pairMode === 'zip' }" @click="pairMode = 'zip'">
            1:1 配对
          </button>
        </div>
        <div class="hint">
          全组合 = 各组素材的笛卡尔积；1:1 = 各组按选中顺序一一对应
        </div>
        <div v-if="zipMismatch" class="err-text">
          1:1 配对要求各组数量相同（当前 {{ activeCounts.join(' vs ') }}）
        </div>
        <div v-if="comboOverLimit" class="err-text">
          共 {{ comboCount }} 张，超过上限 {{ maxCombos }} 张，请减少素材
        </div>
      </div>

      <div class="section">
        <span class="label">种子</span>
        <div class="seg">
          <button class="btn btn-sm" :class="{ active: seedMode === 'fixed' }" @click="seedMode = 'fixed'">
            固定
          </button>
          <button class="btn btn-sm" :class="{ active: seedMode === 'increment' }" @click="seedMode = 'increment'">
            递增
          </button>
          <button class="btn btn-sm" :class="{ active: seedMode === 'random' }" @click="seedMode = 'random'">
            随机
          </button>
        </div>
        <input v-if="seedMode !== 'random'" v-model.number="seed" type="number" class="seed-input" />
      </div>

      <div class="section">
        <span class="label">提示词（留空使用内置默认提示）</span>
        <div class="presets">
          <button
            v-for="p in PROMPT_PRESETS"
            :key="p.label"
            class="btn btn-sm"
            :class="{ on: promptText === p.text }"
            @click="promptText = p.text"
          >
            {{ p.label }}
          </button>
          <button class="btn btn-sm" :disabled="!promptText" @click="promptText = ''">
            清空
          </button>
        </div>
        <textarea v-model="promptText" spellcheck="false" :placeholder="DEFAULT_PROMPT" />
      </div>

      <div v-if="columnCount >= 4" class="section sheet">
        <span class="label">参考板</span>
        <ReferenceSheetButton
          :extra="ref3UploadPath"
          :disabled="!ref3UploadPath"
          label="导出第 4 槽上传图"
        />
        <div class="hint">
          把参考图3槽里的上传图作为附加图导出为 1800×1200；核心三图请在参考图库页导出
        </div>
      </div>

      <div class="summary">
        <span>将生成</span>
        <b>{{ comboCount }}</b>
        <span>张（{{ summaryText }}）</span>
      </div>

      <div class="actions">
        <span v-if="generateError" class="err-text">{{ generateError }}</span>
        <span v-else-if="activeJob" class="job-state" :class="activeJob.status">
          {{ statusLabel(activeJob.status) }} {{ activeJob.done_count ?? 0 }}/{{ activeJob.total ?? 1 }}
        </span>
        <span class="spacer" />
        <button
          class="btn btn-sm primary"
          :class="{ loading: generating }"
          :disabled="!canSubmit"
          @click="submit"
        >
          {{ generating ? '生成中…' : '🚀 开始编辑' }}
        </button>
      </div>
    </aside>

    <FilePicker
      v-for="(group, i) in visibleGroups"
      :key="'fs-picker-' + i"
      v-model="group.paths"
      :open="group.pickerOpen"
      :title="`从磁盘选${roleMeta(i).label}`"
      @close="group.pickerOpen = false"
    />
    <FilePicker
      v-model="maskPickPaths"
      :open="maskPickerOpen"
      title="从磁盘选遮罩图（取第一张）"
      @close="onMaskPickerClose"
    />
    <MaskEditorModal
      :open="maskEditorOpen"
      :image-url="maskEditorImage"
      :initial-mask-url="maskEditorInitial"
      @close="maskEditorOpen = false"
      @save="onMaskSaved"
    />
  </div>
</template>

<style scoped>
.faceswap {
  display: flex;
  height: 100%;
  min-height: 0;
}

.faceswap > :deep(.picker) {
  flex: 1;
  min-width: 0;
}

.picker-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* 画廊选择器占据剩余高度；磁盘缩略图区固定在下方并自行滚动 */
.picker-col :deep(.picker) {
  flex: 1 1 auto;
  min-height: 0;
}

/* 上传区与标题、画廊选择器之间留出左右/下方间距 */
.picker-col :deep(.dropzone) {
  margin: 0 var(--gap) var(--gap-sm);
  flex: none;
}

.disk-picked {
  flex: 0 0 auto;
  max-height: 250px;
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  padding: var(--gap-sm) var(--gap);
  border-top: 1px solid var(--border);
}

.disk-picked-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--muted);
  font-size: var(--fs-xs);
}

.disk-picked :deep(.path-list) {
  max-height: 190px;
}

.picker-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap);
  font-size: var(--fs-sm);
  border-bottom: 1px solid var(--border);
}

.picker-head .btn {
  margin-left: auto;
}

.pick-hint {
  margin: 0;
  padding: 4px var(--gap);
  border-bottom: 1px solid var(--border);
  color: var(--warn);
  font-size: var(--fs-xs);
  line-height: 1.5;
}

.panel {
  width: 340px;
  flex: none;
  background: var(--panel);
  padding: var(--gap);
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  overflow-y: auto;
}

.section {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  font-size: var(--fs-sm);
}

.label {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.seg {
  display: flex;
  gap: var(--gap-xs);
}

.seg .btn {
  flex: 1;
}

.presets {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.presets .btn.on {
  border-color: var(--primary);
  color: var(--primary);
}

.mask-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 190px;
  overflow-y: auto;
}

.mask-row {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--fs-xs);
}

.mask-thumb {
  width: 28px;
  height: 28px;
  flex: none;
  object-fit: cover;
  border-radius: var(--radius-sm);
  background: var(--panel-3);
  display: grid;
  place-items: center;
  color: var(--muted);
}

.mask-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.mask-target,
.mask-file {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mask-file {
  color: var(--muted);
}

.nodes {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-sm);
  font-size: var(--fs-xs);
}

.node-row {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
}

.node-role {
  color: var(--muted);
}

.node-id {
  font-family: ui-monospace, monospace;
  color: var(--primary);
  margin-right: var(--gap-sm);
}

.node-list {
  color: var(--muted);
  margin-top: 2px;
}

.hint {
  font-size: 10px;
  color: var(--muted);
  line-height: 1.5;
}

.err-text {
  font-size: var(--fs-xs);
  color: var(--danger);
}

.seed-input {
  width: 130px;
}

textarea {
  min-height: 84px;
  resize: vertical;
  font: inherit;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-sm);
  outline: none;
}

.summary {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: var(--fs-sm);
  color: var(--muted);
  border-top: 1px solid var(--border);
  padding-top: var(--gap-sm);
}

.summary b {
  font-size: var(--fs-xl);
  color: var(--primary);
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-xs);
}

.spacer {
  flex: 1;
}

.job-state {
  color: var(--muted);
}

.job-state.running,
.job-state.pending {
  color: var(--primary);
}

.job-state.done {
  color: var(--success);
}

.job-state.error {
  color: var(--danger);
}

.btn.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}

.btn.primary:disabled {
  opacity: 0.4;
  cursor: default;
}
</style>
