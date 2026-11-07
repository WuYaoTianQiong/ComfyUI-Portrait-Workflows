import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import UpscaleView from './UpscaleView.vue'
import { apiPost } from '../api/client'

// happy-dom 没有 EventSource；提交后会订阅进度，必须给个假的
class FakeEventSource {
  addEventListener() {}
  close() {}
  onerror: (() => void) | null = null
}
vi.stubGlobal('EventSource', FakeEventSource)

const store = new Map<string, string>()
vi.stubGlobal('localStorage', {
  getItem: (key: string) => store.get(key) ?? null,
  setItem: (key: string, value: string) => {
    store.set(key, value)
  },
  removeItem: (key: string) => {
    store.delete(key)
  },
  clear: () => store.clear(),
})

const WF_PATH = 'F:\\wf\\超分.json'

const fixture = vi.hoisted(() => ({
  loadimages: [{ id: '1', title: 'LoadImage' }],
}))

vi.mock('../api/client', () => ({
  newIdempotencyKey: () => 'test-idem',
  apiGet: vi.fn(async (path: string) => {
    if (path.includes('/api/workflows')) {
      return {
        workflows: [
          {
            path: 'F:\\wf\\超分.json',
            name: '超分.json',
            caps: {
              prompt: false,
              negative: false,
              negative_effective: false,
              negative_cfg: null,
              quality: true,
              orientation: false,
            },
            params: {
              quality_mode: 'seedvr',
              orientation_mode: 'none',
              aspect_ratios: [],
              default_ratio: '',
              multiple: 16,
            },
          },
        ],
        default: 'F:\\wf\\超分.json',
      }
    }
    // ImagePicker 读历史图
    return {
      items: [
        {
          id: 1, filename: 'a.png', subfolder: '', img_type: 'output', view_url: '',
          is_favorite: false, missing: false, created_at: '', captured_at: '',
          source: 'local', prompt_name: '', prompt_params: null, categories: [], tags: [],
        },
        {
          id: 2, filename: 'b.png', subfolder: '', img_type: 'output', view_url: '',
          is_favorite: false, missing: false, created_at: '', captured_at: '',
          source: 'local', prompt_name: '', prompt_params: null, categories: [], tags: [],
        },
      ],
      total: 2,
      page: 1,
      page_size: 100,
    }
  }),
  apiPost: vi.fn(async (path: string) => {
    if (path.includes('/api/editor/faceswap/nodes')) {
      return {
        loadimages: fixture.loadimages,
        inputs: fixture.loadimages.map((n, i) => ({
          role: i === 0 ? 'target' : `ref${i}`,
          id: n.id,
        })),
        roles: fixture.loadimages.map((_, i) => (i === 0 ? 'target' : `ref${i}`)),
        target: fixture.loadimages[0]?.id ?? null,
        refs: fixture.loadimages.slice(1).map((n) => n.id),
        mask: false,
        max_combos: 100,
      }
    }
    return { success: true, job_id: 9, total: 2, queued: 2 }
  }),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
  thumbnailUrl: () => '/api/thumb?x.png',
  viewUrl: () => '/api/media/image?x.png',
}))

function mountView() {
  return mount(UpscaleView, {
    global: {
      plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]],
    },
  })
}

async function pickWorkflow(wrapper: ReturnType<typeof mount>) {
  await wrapper.find('aside.panel select').setValue(WF_PATH)
  await flushPromises()
}

async function selectTwoImages(wrapper: ReturnType<typeof mount>) {
  const cells = wrapper.findAll('.picker .cell')
  await cells[0].trigger('click')
  await cells[1].trigger('click')
  await flushPromises()
}

describe('UpscaleView 批量超分', () => {
  beforeEach(() => {
    vi.mocked(apiPost).mockClear()
    store.clear()
    fixture.loadimages = [{ id: '1', title: 'LoadImage' }]
  })

  it('多选后提交带上档位、任务标题与保留源图名标记', async () => {
    const wrapper = mountView()
    await flushPromises()
    await pickWorkflow(wrapper)
    await selectTwoImages(wrapper)

    const submit = wrapper.findAll('button').find((b) => b.text().includes('开始超分'))!
    expect(submit.attributes('disabled')).toBeUndefined()
    await submit.trigger('click')
    await flushPromises()

    const call = vi.mocked(apiPost).mock.calls.find((c) => c[0] === '/api/editor/faceswap/batch')!
    expect(call[1]).toMatchObject({
      main_ids: [1, 2],
      main_paths: [],
      workflow_path: WF_PATH,
      quality: '1.0x',
      job_label: '批量超分',
      clean_source_name: true,
    })
  })

  it('磁盘清单支持单张移除', async () => {
    store.set(
      'pb.session.upscale',
      JSON.stringify({ ids: [], paths: ['F:\\pics\\a.png', 'F:\\pics\\b.png'] }),
    )
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.findAll('.disk-list .path-item').length).toBe(2)

    await wrapper.find('.disk-list .remove').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.disk-list .path-item').length).toBe(1)
    expect(wrapper.text()).toContain('已选 1 张')
  })

  it('多 LoadImage 的工作流会被拦下，不能提交', async () => {
    fixture.loadimages = [
      { id: '1', title: '目标图' },
      { id: '2', title: '参考图' },
    ]
    const wrapper = mountView()
    await flushPromises()
    await pickWorkflow(wrapper)
    await selectTwoImages(wrapper)

    expect(wrapper.text()).toContain('只支持 1 个')
    const submit = wrapper.findAll('button').find((b) => b.text().includes('开始超分'))!
    expect(submit.attributes('disabled')).toBeDefined()
  })
})
