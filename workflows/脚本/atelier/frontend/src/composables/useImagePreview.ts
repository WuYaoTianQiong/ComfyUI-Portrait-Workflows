import { computed, ref } from 'vue'

import { apiGet } from '../api/client'
import type { HistoryItem, HistoryPage } from '../api/types'

/**
 * 「点缩略图看大图」的统一入口。
 *
 * 任务快照里的图片只有 filename / subfolder / type，而画廊那套查看器
 * （`Lightbox.vue`：缩放、平移、旋转、下载、收藏、投喂工作流、信息卡）
 * 吃的是完整的 `HistoryItem`。所以这里做两件事：
 *   1. 按文件名把那条历史记录取回来 → 直接喂给 Lightbox，不另写一个查看器；
 *   2. 取不到（图还没入库）时退化成一份只读占位记录，至少还能看原图。
 *
 * 画廊的深链（`/gallery?image=<文件名>`）与结果中心 / 任务页共用这一份查找，
 * 避免三处各写一遍"按名查图"的请求与匹配规则。
 */
export interface ImageRef {
  filename: string
  subfolder?: string | null
  type?: string | null
}

/** 按文件名精确取一条历史记录；同名的优先认子目录一致的。 */
export async function findHistoryItem(image: ImageRef): Promise<HistoryItem | null> {
  const page = await apiGet<HistoryPage>('/api/images', {
    search: image.filename,
    page_size: 20,
  })
  const rows = page.items ?? []
  const subfolder = image.subfolder ?? ''
  return (
    rows.find((it) => it.filename === image.filename && (it.subfolder ?? '') === subfolder) ??
    rows.find((it) => it.filename === image.filename) ??
    null
  )
}

/** 未入库图片的占位记录：只够 Lightbox 渲染，写操作会被 readonly 挡掉。 */
function placeholderItem(image: ImageRef): HistoryItem {
  return {
    id: 0,
    filename: image.filename,
    subfolder: image.subfolder ?? '',
    img_type: image.type ?? 'output',
    view_url: null,
    is_favorite: false,
    missing: false,
    created_at: '',
    captured_at: '',
    source: 'local',
    prompt_id: null,
    job_id: null,
    prompt_name: '',
    prompt_params: null,
    comfyui_prompt_id: null,
    file_size: null,
    width: null,
    height: null,
    categories: [],
    tags: [],
  }
}

export function useImagePreview() {
  /** 单张图也走 Lightbox 的 items/index 协议，和画廊保持一致。 */
  const items = ref<HistoryItem[]>([])
  /** 图没入库（或查询失败）时不允许收藏/删除/重出图。 */
  const readonly = ref(false)
  const open = computed(() => items.value.length > 0)

  async function preview(image: ImageRef) {
    try {
      const hit = await findHistoryItem(image)
      readonly.value = !hit
      items.value = [hit ?? placeholderItem(image)]
    } catch {
      readonly.value = true
      items.value = [placeholderItem(image)]
    }
  }

  function close() {
    items.value = []
    readonly.value = false
  }

  return { items, readonly, open, preview, close }
}
