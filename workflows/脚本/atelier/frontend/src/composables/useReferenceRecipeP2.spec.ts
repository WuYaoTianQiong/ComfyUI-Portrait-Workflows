/**
 * P2 替代态提交校验单测（方案 §4.4 / §8 P2）。
 *
 * 覆盖：
 * 1. `text` 模式对应类碎片为空 → 阻止，文案「文本模式需要至少选择 1 条碎片」；
 * 2. 三槽都没有 image 模式图片 → 阻止（文本不计入参考图）；
 * 3. `bare` + 服装文本 → 阻止；
 * 4. 姿势 `text` + 当前 / 上次是 `pair*` 双人姿势 → 阻止；
 * 5. 正面：人像图 + 服装文本 → 提交体只发 `portrait_id` 与 `costume_text`，
 *    `body_mode` 仍为 `costume`。
 *
 * fetch 用最小 stub：工作流目录 / POST recipes / GET jobs 三条通路。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'
import type { EffectScope } from 'vue'

import type { PoseItem, PortraitItem } from '@/api/reference'

import { createEmptyRecipeTextFragments } from './recipeTextFragments'
import { RECIPE_POLL_INTERVAL_MS, useReferenceRecipe } from './useReferenceRecipe'
import type { RecipeSubmitRequest } from './useReferenceRecipe'
import { useReferenceRecipeDraft } from './useReferenceRecipeDraft'

function portrait(id = 'pt1'): PortraitItem {
  return {
    id,
    分区: '分区',
    发长: '',
    发型名称: '发型',
    标题: '人像',
    宽: 0,
    高: 0,
    字节数: 0,
    精选: false,
    热门: false,
    缩略图: '',
    原图: '',
    检索: '',
  }
}

function pose(id = 'single-01'): PoseItem {
  return {
    id,
    体系: '体系',
    姿势编号: id,
    分类: '分类',
    姿势名称: '姿势',
    角度: '正面',
    缩略图: '',
    原图: '',
    检索: '',
    nsfw: false,
  }
}

function jsonResponse(data: unknown): { ok: boolean; status: number; json: () => Promise<unknown> } {
  return { ok: true, status: 200, json: async () => data }
}

describe('P2 替代态提交校验', () => {
  const draft = useReferenceRecipeDraft()
  let scopes: EffectScope[] = []
  let submittedBodies: RecipeSubmitRequest[] = []

  function installFetchMock(): void {
    submittedBodies = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown, init?: { method?: string; body?: unknown }) => {
        const url =
          typeof input === 'string'
            ? input
            : input instanceof URL
              ? input.toString()
              : String((input as { url?: string } | null)?.url ?? '')

        if (url.startsWith('/api/workflows')) {
          return jsonResponse({
            workflows: [
              {
                path: '/wf.api.json',
                name: 'wf.api.json',
                source: '图库专用',
                rel_path: '/wf.api.json',
                image_slots: 1,
                input_count: 1,
                recommended: false,
              },
            ],
            default: '/wf.api.json',
          })
        }

        if (url === '/api/reference/recipes' && (init?.method ?? 'GET') === 'POST') {
          const body = JSON.parse(String(init?.body ?? '{}')) as RecipeSubmitRequest
          if ((body as { dry_run?: boolean }).dry_run) {
            return jsonResponse({ success: true, dry_run: true, prompt: '预览' })
          }
          submittedBodies.push(body)
          return jsonResponse({
            success: true,
            job_id: 1,
            total: 1,
            submitted: 1,
            queued: 1,
            errors: [],
          })
        }

        if (url === '/api/jobs/1') {
          return jsonResponse({
            id: 1,
            status: 'done',
            total: 1,
            done_count: 1,
            items: [{ images: [{ filename: 'p2.png', subfolder: '', type: 'output' }] }],
          })
        }

        throw new Error(`未预期的请求：${url}`)
      }),
    )
  }

  async function flushMicrotasks(rounds = 20): Promise<void> {
    for (let round = 0; round < rounds; round += 1) await Promise.resolve()
  }

  async function prepareRecipe() {
    const scope = effectScope()
    const recipe = scope.run(() => useReferenceRecipe())
    if (!recipe) throw new Error('无法创建 useReferenceRecipe')
    scopes.push(scope)
    await recipe.loadStudioWorkflows()
    recipe.setWorkflowSelection(['/wf.api.json'])
    await flushMicrotasks()
    return recipe
  }

  beforeEach(() => {
    vi.useFakeTimers()
    draft.clearDraft()
    installFetchMock()
  })

  afterEach(() => {
    for (const scope of scopes) scope.stop()
    scopes = []
    draft.clearDraft()
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('text 模式对应类碎片为空 → 提交被阻止', async () => {
    const recipe = await prepareRecipe()
    draft.addPortrait(portrait())
    draft.setSlotMode('costume', 'text')

    const batch = await recipe.submit()

    expect(batch).toBeNull()
    expect(recipe.formError.value).toContain('服装槽：文本模式需要至少选择 1 条碎片')
    expect(submittedBodies).toHaveLength(0)
  })

  it('三槽都没有 image 图片 → 至少保留 1 张参考图（文本不计入）', async () => {
    const recipe = await prepareRecipe()
    draft.setSlotMode('portrait', 'text')
    draft.textFragments.value = {
      ...createEmptyRecipeTextFragments(),
      人物面部: [{ type: '人物面部', content: '圆脸' }],
    }

    const batch = await recipe.submit()

    expect(batch).toBeNull()
    expect(recipe.formError.value).toContain('至少保留 1 张参考图')
    expect(submittedBodies).toHaveLength(0)
  })

  it('素体展示 + 服装文本 → 提交被阻止', async () => {
    const recipe = await prepareRecipe()
    draft.addPortrait(portrait())
    draft.setSlotMode('costume', 'text')
    draft.textFragments.value = {
      ...createEmptyRecipeTextFragments(),
      人物服饰: [{ type: '人物服饰', content: '白色衬衫' }],
    }
    recipe.setBodyMode('bare')

    const batch = await recipe.submit()

    expect(batch).toBeNull()
    expect(recipe.formError.value).toContain('素体展示与服装文本冲突')
    expect(submittedBodies).toHaveLength(0)
  })

  it('姿势文本 + 上次选的是 pair 双人姿势 → 提交被阻止', async () => {
    const recipe = await prepareRecipe()
    draft.addPortrait(portrait())
    // 先选双人姿势（记录 lastPoseId），再清空并切文本替代
    draft.setPose(pose('pair-01'))
    draft.removePose()
    draft.setSlotMode('pose', 'text')
    draft.textFragments.value = {
      ...createEmptyRecipeTextFragments(),
      姿态动作: [{ type: '姿态动作', content: '自然站立' }],
    }

    const batch = await recipe.submit()

    expect(batch).toBeNull()
    expect(recipe.formError.value).toContain('姿势文本暂不支持双人')
    expect(submittedBodies).toHaveLength(0)
  })

  it('手动改写为空 → 提交被阻止，不静默回落自动生成', async () => {
    const recipe = await prepareRecipe()
    draft.addPortrait(portrait())
    recipe.promptOverride.value = '   '

    const batch = await recipe.submit()

    expect(batch).toBeNull()
    expect(recipe.formError.value).toContain('手动改写内容为空')
    expect(submittedBodies).toHaveLength(0)
  })

  it('手动改写非空 → 只发 prompt_override，不发槽位文本 / 追加要求', async () => {
    const recipe = await prepareRecipe()
    draft.addPortrait(portrait())
    draft.setSlotMode('costume', 'text')
    draft.textFragments.value = {
      ...createEmptyRecipeTextFragments(),
      人物服饰: [{ type: '人物服饰', content: '白色衬衫' }],
    }
    recipe.promptSuffix.value = '暖色灯光'
    recipe.promptOverride.value = '自定义最终提示词'

    const pending = recipe.submit()
    await flushMicrotasks()
    await vi.advanceTimersByTimeAsync(RECIPE_POLL_INTERVAL_MS)
    await flushMicrotasks()
    await pending

    expect(recipe.formError.value).toBe('')
    expect(submittedBodies).toHaveLength(1)
    const body = submittedBodies[0]!
    expect(body.prompt_override).toBe('自定义最终提示词')
    expect('prompt_suffix' in body).toBe(false)
    expect('costume_text' in body).toBe(false)
    expect('modifier_fragments' in body).toBe(false)
  })

  it('正面：人像图 + 服装文本 → 只发 portrait_id 与 costume_text，body_mode=costume', async () => {
    const recipe = await prepareRecipe()
    draft.addPortrait(portrait())
    draft.setSlotMode('costume', 'text')
    draft.textFragments.value = {
      ...createEmptyRecipeTextFragments(),
      人物服饰: [{ type: '人物服饰', content: '白色衬衫' }],
    }

    const pending = recipe.submit()
    await flushMicrotasks()
    await vi.advanceTimersByTimeAsync(RECIPE_POLL_INTERVAL_MS)
    await flushMicrotasks()
    await pending

    expect(recipe.formError.value).toBe('')
    expect(submittedBodies).toHaveLength(1)
    const body = submittedBodies[0]!
    expect(body.portrait_id).toBe('pt1')
    expect('costume_id' in body).toBe(false)
    expect('costume_path' in body).toBe(false)
    expect(body.costume_text).toBe('白色衬衫')
    expect(body.body_mode).toBe('costume')
    expect(recipe.batches.value[0]?.status).toBe('success')
  })
})