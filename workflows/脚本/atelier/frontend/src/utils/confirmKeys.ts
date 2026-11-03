import { isConfirmSkipped, resetConfirmSkip } from './naive'

/**
 * 可「下次不再提示」的确认框登记表。
 *
 * 只登记不破坏数据的重复确认：出图、替换、提交、重算分类这类。
 * 删除 / 清理 / 停止任务这类操作不登记 —— 永久跳过风险太大，每次都问。
 */
export interface ConfirmPromptMeta {
  key: string
  label: string
}

export const CONFIRM_PROMPTS = {
  batchGenerate: { key: 'prompt.batchGenerate', label: '批量出图' },
  batchReplace: { key: 'prompt.batchReplace', label: '替换碎片出图' },
  smartSegment: { key: 'prompt.smartSegment', label: '智能分段' },
  editorSubmit: { key: 'editor.submit', label: '图像编辑提交' },
  autoClassify: { key: 'taxonomy.autoClassify', label: '一键自动分类' },
  backfillTaxonomy: { key: 'gallery.backfillTaxonomy', label: '补齐图片分类/标签' },
} as const satisfies Record<string, ConfirmPromptMeta>

/** 当前已经记住「不再提示」的那些确认框，用于分类与标签页的恢复入口。 */
export function listSkippedPrompts(): ConfirmPromptMeta[] {
  return Object.values(CONFIRM_PROMPTS).filter((p) => isConfirmSkipped(p.key))
}

export function resetAllConfirmSkips(): void {
  for (const p of Object.values(CONFIRM_PROMPTS)) resetConfirmSkip(p.key)
}
