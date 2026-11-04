/**
 * 参考图上传：`POST /api/reference/uploads`（multipart，字段名 `file`）。
 *
 * 后端只收单张，前端多选时**并发**上传、按选择顺序返回结果：
 * 槽位要按顺序填充，但串行上传会让 3–5 张截图明显变慢。
 */

export interface UploadedReference {
  path: string
  name: string
  width: number
  height: number
  bytes: number
  dedup: boolean
}

export interface UploadFailure {
  index: number
  name: string
  error: string
}

export interface UploadBatchResult {
  items: UploadedReference[]
  failures: UploadFailure[]
}

/** 与后端 `uploads.MAX_UPLOAD_BYTES` 保持一致：前端先拦一次，省一次 25MB 传输。 */
export const UPLOAD_MAX_BYTES = 25 * 1024 * 1024

/** 图片扩展名白名单（与 `paths.IMAGE_EXTENSIONS` 对齐；HEIC 改名也能靠文件头识别）。 */
const IMAGE_EXTENSIONS = [
  '.png',
  '.jpg',
  '.jpeg',
  '.webp',
  '.bmp',
  '.gif',
  '.tif',
  '.tiff',
  '.heic',
  '.heif',
]

export class UploadError extends Error {}

export function isImageFile(file: File | Blob): boolean {
  const type = file.type || ''
  if (type.startsWith('image/')) return true
  if (file instanceof File && file.name) {
    const dot = file.name.lastIndexOf('.')
    if (dot >= 0 && IMAGE_EXTENSIONS.includes(file.name.slice(dot).toLowerCase())) return true
  }
  return false
}

function guessName(file: File | Blob, index: number): string {
  if (file instanceof File && file.name) return file.name
  const type = (file.type || '').toLowerCase()
  const ext = type === 'image/jpeg' ? '.jpg' : type === 'image/webp' ? '.webp' : '.png'
  return `clipboard-${Date.now()}-${index}${ext}`
}

async function readError(resp: Response): Promise<string> {
  const text = await resp.text().catch(() => '')
  if (!text) return `${resp.status} 上传失败`
  try {
    const body = JSON.parse(text) as { detail?: unknown }
    if (body.detail !== undefined && body.detail !== null) {
      return typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    }
  } catch {
    // 非 JSON：截断原始响应，避免把整页 HTML 弹到 toast 里
  }
  return `${resp.status} ${text.slice(0, 200)}`
}

async function postOne(file: File | Blob, name: string): Promise<UploadedReference> {
  const form = new FormData()
  form.append('file', file, name)

  const resp = await fetch('/api/reference/uploads', {
    method: 'POST',
    body: form,
    headers: { Accept: 'application/json' },
  })
  if (!resp.ok) throw new UploadError(await readError(resp))
  const body = (await resp.json()) as UploadedReference
  if (!body || typeof body.path !== 'string') {
    throw new UploadError('上传响应缺少图片路径')
  }
  return body
}

/** 上传单张（拖拽/粘贴/选择最终都走这里）。 */
export function uploadReferenceImage(file: File | Blob, name?: string): Promise<UploadedReference> {
  if (file.size > UPLOAD_MAX_BYTES) {
    return Promise.reject(new UploadError('文件超过 25MB 上限'))
  }
  if (!isImageFile(file)) {
    return Promise.reject(new UploadError('不是支持的图片文件'))
  }
  return postOne(file, name || guessName(file, 0))
}

/**
 * 并发上传多张，返回按**传入顺序**排列的成功项与失败项。
 * 部分失败不影响其余图片进入槽位。
 */
export async function uploadReferenceImages(
  files: Array<File | Blob>,
  names?: string[],
): Promise<UploadBatchResult> {
  const jobs = files.map(async (file, index) => {
    const name = names?.[index] || guessName(file, index)
    try {
      if (file.size > UPLOAD_MAX_BYTES) throw new UploadError('文件超过 25MB 上限')
      if (!isImageFile(file)) throw new UploadError('不是支持的图片文件')
      return { index, item: await postOne(file, name) }
    } catch (e) {
      return {
        index,
        failure: {
          index,
          name,
          error: e instanceof Error ? e.message : String(e),
        },
      }
    }
  })

  const results = await Promise.all(jobs)
  const items: UploadedReference[] = []
  const failures: UploadFailure[] = []
  for (const result of results.sort((a, b) => a.index - b.index)) {
    if ('item' in result && result.item) items.push(result.item)
    else if ('failure' in result && result.failure) failures.push(result.failure)
  }
  return { items, failures }
}