import { beforeEach, describe, expect, it, vi } from 'vitest'

import { findHistoryItem, useImagePreview } from './useImagePreview'
import { apiGet } from '../api/client'

vi.mock('../api/client', () => ({
  apiGet: vi.fn(async () => ({ items: [], total: 0, page: 1, page_size: 20 })),
}))

/** 只需要 filename / subfolder 两个字段参与匹配，其余按最小可渲染补齐。 */
function row(id: number, filename: string, subfolder = '') {
  return {
    id,
    filename,
    subfolder,
    img_type: 'output',
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

describe('useImagePreview', () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockReset()
  })

  it('优先命中子目录一致的那条，其次同名', async () => {
    vi.mocked(apiGet).mockResolvedValue({
      items: [row(1, 'a.png', 'sub'), row(2, 'a.png', '') as never],
      total: 2,
      page: 1,
      page_size: 20,
    } as never)

    const hit = await findHistoryItem({ filename: 'a.png', subfolder: 'sub' })
    expect(hit?.id).toBe(1)

    vi.mocked(apiGet).mockResolvedValue({
      items: [row(2, 'a.png') as never],
      total: 1,
      page: 1,
      page_size: 20,
    } as never)
    // 子目录对不上时退化成"同名即可"，任务快照里 subfolder 常常是 null
    expect((await findHistoryItem({ filename: 'a.png', subfolder: 'nope' }))?.id).toBe(2)
  })

  it('查不到时返回 null', async () => {
    vi.mocked(apiGet).mockResolvedValue({
      items: [row(3, 'other.png') as never],
      total: 1,
      page: 1,
      page_size: 20,
    } as never)
    expect(await findHistoryItem({ filename: 'a.png' })).toBeNull()
  })

  it('命中时进灯箱且不是只读', async () => {
    vi.mocked(apiGet).mockResolvedValue({
      items: [row(7, 'a.png') as never],
      total: 1,
      page: 1,
      page_size: 20,
    } as never)

    const preview = useImagePreview()
    await preview.preview({ filename: 'a.png', type: 'output' })

    expect(preview.open.value).toBe(true)
    expect(preview.readonly.value).toBe(false)
    expect(preview.items.value).toHaveLength(1)
    expect(preview.items.value[0].id).toBe(7)
  })

  it('图还没入库时给只读占位，仍能看原图', async () => {
    vi.mocked(apiGet).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 } as never)

    const preview = useImagePreview()
    await preview.preview({ filename: 'new.png', subfolder: 'tmp', type: 'temp' })

    expect(preview.open.value).toBe(true)
    expect(preview.readonly.value).toBe(true)
    expect(preview.items.value[0]).toMatchObject({
      id: 0,
      filename: 'new.png',
      subfolder: 'tmp',
      img_type: 'temp',
    })
  })

  it('查询失败也退回只读占位，不挡住看图', async () => {
    vi.mocked(apiGet).mockRejectedValue(new Error('boom'))

    const preview = useImagePreview()
    await preview.preview({ filename: 'a.png' })

    expect(preview.open.value).toBe(true)
    expect(preview.readonly.value).toBe(true)
  })
})
