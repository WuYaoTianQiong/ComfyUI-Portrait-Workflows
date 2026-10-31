import type { CategoryNode } from '../api/types'

export type FlatCategory = CategoryNode & { depth: number }

/**
 * 分类树拍平成一维（带 depth 做缩进）。
 *
 * 层级只有两级，递归组件是过度设计；四页各自写一遍则容易漏字段。
 */
export function flattenCategories(nodes: CategoryNode[] | undefined, depth = 0): FlatCategory[] {
  const out: FlatCategory[] = []
  for (const node of nodes ?? []) {
    out.push({ ...node, depth })
    if (node.children?.length) out.push(...flattenCategories(node.children, depth + 1))
  }
  return out
}
