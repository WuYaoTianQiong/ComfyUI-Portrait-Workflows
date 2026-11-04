import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import ReferenceView from './ReferenceView.vue'

/**
 * 参考页的出图面板契约：
 * - 18+ 开关只认后端的 `allow_nsfw`，不再用 `visible < total` 反推；
 * - 核心槽支持「库条目 / 上传图」二选一，并显示来源徽标；
 * - 提交时按来源传 `*_id` 或 `*_path`。
 */
const fixture = vi.hoisted(() => ({
  allowNsfw: false,
  poseHasDepthThumb: true,
  items: {
    pose: {
      id: 'P001_front',
      library: 'pose',
      name: '正面站姿',
      subtitle: 'P001 · 正面',
      group: '日常',
      facet: '站姿',
      angle: '正面',
      tags: ['站姿'],
      keywords: 'standing',
      thumb_url: '/api/reference/items/pose/P001_front/image?kind=thumb',
      image_url: '/api/reference/items/pose/P001_front/image?kind=image',
      depth_url: '/api/reference/items/pose/P001_front/image?kind=depth',
      depth_thumb_url: '/api/reference/items/pose/P001_front/image?kind=depth_thumb',
      hot: false,
      featured: false,
      nsfw: false,
      remote: false,
    },
    costume: {
      id: 'SPR-0001',
      library: 'costume',
      name: '象牙白针织衫',
      subtitle: '',
      group: '春季穿搭',
      facet: '',
      angle: '',
      tags: [],
      keywords: 'knit',
      thumb_url: '/api/reference/items/costume/SPR-0001/image?kind=thumb',
      image_url: '/api/reference/items/costume/SPR-0001/image?kind=image',
      depth_url: null,
      depth_thumb_url: null,
      hot: false,
      featured: false,
      nsfw: false,
      remote: false,
    },
    upload: {
      path: 'C:/workflows/uploads/abc123.png',
      name: 'me.png',
      width: 600,
      height: 800,
      bytes: 1024,
      dedup: false,
    },
  },
}))

const { apiGet, apiPost, uploadReferenceImages } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  uploadReferenceImages: vi.fn(),
}))

vi.mock('../api/client', () => ({
  apiGet,
  apiPost,
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
  thumbnailUrl: () => '/thumb',
  viewUrl: () => '/view',
}))

vi.mock('../api/upload', () => ({
  uploadReferenceImages,
  isImageFile: () => true,
}))

/** happy-dom 的 localStorage 不完整；参考页的设置读写会静默失败。 */
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

class FakeEventSource {
  addEventListener() {}
  close() {}
}
vi.stubGlobal('EventSource', FakeEventSource)

function libraryRow(library: string, label: string) {
  return {
    library,
    label,
    total: 2,
    local: 2,
    remote: 0,
    // 刻意让 visible == total：若实现仍靠条数差推断，会把总闸误判为开启
    visible: 2,
    available: true,
    allow_nsfw: fixture.allowNsfw,
    groups: [],
    facets: [],
    angles: [],
  }
}

function poseItem() {
  return {
    ...fixture.items.pose,
    depth_thumb_url: fixture.poseHasDepthThumb
      ? '/api/reference/items/pose/P001_front/image?kind=depth_thumb'
      : null,
  }
}

function itemFor(library: unknown) {
  if (library === 'costume') return [fixture.items.costume]

  return [poseItem()]
}

beforeEach(() => {
  fixture.allowNsfw = false
  fixture.poseHasDepthThumb = true
  store.clear()
  apiGet.mockReset()
  apiPost.mockReset()
  uploadReferenceImages.mockReset()
  uploadReferenceImages.mockResolvedValue({ items: [fixture.items.upload], failures: [] })
  apiPost.mockResolvedValue({ success: true, job_id: 0, total: 1, prompt: '图1…' })

  apiGet.mockImplementation(async (path: string, params?: Record<string, unknown>) => {
    if (path === '/api/reference/libraries') {
      return {
        allow_nsfw: fixture.allowNsfw,
        libraries: [
          libraryRow('pose', '姿势库'),
          libraryRow('costume', '服装库'),
          libraryRow('portrait', '人像库'),
          libraryRow('costume-anime', '外链服装'),
        ],
      }
    }
    if (path === '/api/reference/items') {
      const items = itemFor(params?.library)
      return { items, total: items.length, page: 1, page_size: 60 }
    }
    if (path.startsWith('/api/jobs/')) return { id: 0, status: 'done', items: [] }
    return {}
  })
})

async function mountView() {
  const wrapper = mount(ReferenceView, {
    global: {
      plugins: [
        [VueQueryPlugin, { queryClient: new QueryClient() }],
        createRouter({
          history: createMemoryHistory(),
          routes: [
            { path: '/', component: { template: '<div />' } },
            { path: '/reference', component: { template: '<div />' } },
            { path: '/jobs', name: 'jobs', component: { template: '<div />' } },
          ],
        }),
      ],
      stubs: { teleport: true },
    },
  })
  await flushPromises()
  return wrapper
}

function slotByLabel(wrapper: Awaited<ReturnType<typeof mountView>>, label: string) {
  const slot = wrapper
    .findAll('.gen-panel .slot')
    .find((node) => node.find('.slot-label').text().startsWith(label))
  if (!slot) throw new Error(`没找到槽位：${label}`)
  return slot
}


async function pickCurrentLibraryItem(wrapper: Awaited<ReturnType<typeof mountView>>) {
  const pick = wrapper
    .findAll('.pick-actions .mini')
    .find((node) => node.text() === '选')
  if (!pick) throw new Error('当前库没有可选的条目')
  await pick.trigger('click')
}

async function uploadInto(wrapper: Awaited<ReturnType<typeof mountView>>, label: string) {
  const slot = slotByLabel(wrapper, label)
  const input = slot.find('input[type="file"]')
  const file = new File(['fake-image'], 'me.png', { type: 'image/png' })
  Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
  await input.trigger('change')
  await flushPromises()
}

describe('ReferenceView · 18+ 开关', () => {
  it('allow_nsfw=false 时置灰，即使 visible 等于 total 也不推断为开启', async () => {
    fixture.allowNsfw = false
    const wrapper = await mountView()

    const toggle = wrapper.find('.nsfw-toggle')
    expect(toggle.classes()).toContain('disabled')
    expect(toggle.find('input').attributes('disabled')).toBeDefined()
    expect(toggle.attributes('title')).toContain('后端未开启')
  })

  it('allow_nsfw=true 时可用', async () => {
    fixture.allowNsfw = true
    const wrapper = await mountView()

    const toggle = wrapper.find('.nsfw-toggle')
    expect(toggle.classes()).not.toContain('disabled')
    expect(toggle.find('input').attributes('disabled')).toBeUndefined()
  })
})

describe('ReferenceView · 槽位来源', () => {
  it('从图库选中显示「图库」徽标', async () => {
    const wrapper = await mountView()
    await pickCurrentLibraryItem(wrapper)

    const pose = slotByLabel(wrapper, '姿势')
    expect(pose.find('.source-badge.library').text()).toBe('图库')
    expect(pose.find('.slot-name').text()).toBe('正面站姿')
    expect(pose.find('input[type="file"]').exists()).toBe(false)
  })

  it('上传后显示「上传」徽标，可一键退回图库', async () => {
    const wrapper = await mountView()
    await uploadInto(wrapper, '人像')

    let portrait = slotByLabel(wrapper, '人像')
    expect(portrait.find('.source-badge.upload').text()).toBe('上传')
    expect(portrait.find('.slot-name').text()).toBe('me.png')
    expect(portrait.find('.slot-meta').text()).toContain('600×800')

    const back = portrait.findAll('button').find((node) => node.text() === '退回图库')
    expect(back).toBeTruthy()
    await back!.trigger('click')
    await flushPromises()

    portrait = slotByLabel(wrapper, '人像')
    expect(portrait.find('.source-badge').exists()).toBe(false)
    expect(portrait.find('input[type="file"]').exists()).toBe(true)
  })

  it('同槽位从上传再选图库条目会清掉上传来源', async () => {
    const wrapper = await mountView()
    await uploadInto(wrapper, '姿势')

    expect(slotByLabel(wrapper, '姿势').find('.source-badge.upload').exists()).toBe(true)
    await pickCurrentLibraryItem(wrapper)

    const pose = slotByLabel(wrapper, '姿势')
    expect(pose.find('.source-badge.library').exists()).toBe(true)
    expect(pose.find('.source-badge.upload').exists()).toBe(false)
  })
})

describe('ReferenceView · 提交与深度卡片', () => {
  it('混合来源提交时按槽位分别传 *_id / *_path', async () => {
    const wrapper = await mountView()

    // 人像走上传
    await uploadInto(wrapper, '人像')
    // 姿势走图库
    await pickCurrentLibraryItem(wrapper)
    // 服装切到服装库后从图库选
    const costumeTab = wrapper
      .findAll('.tab-row .tab')
      .find((node) => node.text().includes('服装库'))
    expect(costumeTab).toBeTruthy()
    await costumeTab!.trigger('click')
    await flushPromises()
    await pickCurrentLibraryItem(wrapper)
    await flushPromises()

    const start = wrapper
      .findAll('.panel-actions button')
      .find((node) => node.text().includes('开始出图'))
    expect(start).toBeTruthy()
    expect(start!.attributes('disabled')).toBeUndefined()
    await start!.trigger('click')
    await flushPromises()

    const call = apiPost.mock.calls.find((args) => args[0] === '/api/reference/recipes')
    expect(call).toBeTruthy()
    const body = call![1] as Record<string, unknown>
    expect(body.portrait_id).toBe('')
    expect(body.portrait_path).toBe(fixture.items.upload.path)
    expect(body.costume_id).toBe(fixture.items.costume.id)
    expect(body.costume_path).toBe('')
    expect(body.pose_id).toBe(fixture.items.pose.id)
    expect(body.pose_path).toBe('')
    expect(body.extra_id).toBe('')
    expect(body.extra_path).toBe('')
  })

  it('深度卡片使用 depth_thumb_url，缺失缩略图时按钮禁用', async () => {
    const wrapper = await mountView()

    const depth = wrapper
      .findAll('.thumb-mode .mini')
      .find((node) => node.text() === '深度')
    expect(depth).toBeTruthy()
    expect(depth!.attributes('disabled')).toBeUndefined()
    await depth!.trigger('click')

    const cardImg = wrapper.find('.thumb img')
    expect(cardImg.attributes('src')).toBe(fixture.items.pose.depth_thumb_url)
    expect(cardImg.attributes('src')).not.toBe(fixture.items.pose.depth_url)

    fixture.poseHasDepthThumb = false
    const second = await mountView()
    const disabled = second
      .findAll('.thumb-mode .mini')
      .find((node) => node.text() === '深度')
    expect(disabled?.attributes('disabled')).toBeDefined()
  })
})