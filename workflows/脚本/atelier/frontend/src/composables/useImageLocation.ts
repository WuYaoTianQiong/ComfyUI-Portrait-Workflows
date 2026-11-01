import { apiPost } from '../api/client'
import { useToast } from './useToast'

export interface ImageLocationRef {
  id?: number | null
  filename?: string | null
  subfolder?: string | null
  img_type?: string | null
  type?: string | null
}

/**
 * 在资源管理器中定位一张图。
 *
 * 有 DB id 时按 id 查（最稳）；任务/结果中心里还没入库的图只有文件名，
 * 就按 (filename, subfolder, type) 定位。后端统一做路径校验。
 */
export function useImageLocation() {
  const toast = useToast()

  async function revealImage(ref: ImageLocationRef) {
    const body = ref.id
      ? { id: ref.id }
      : {
          filename: ref.filename ?? '',
          subfolder: ref.subfolder ?? '',
          img_type: ref.img_type ?? ref.type ?? 'output',
        }
    try {
      const result = await apiPost<{ success: boolean; path?: string; message?: string }>(
        '/api/images/reveal',
        body,
      )
      if (result.success) toast.success(`已定位：${result.path}`)
      else toast.info(result.message || '无法打开所在目录')
    } catch (e) {
      toast.error(`打开目录失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  return { revealImage }
}
