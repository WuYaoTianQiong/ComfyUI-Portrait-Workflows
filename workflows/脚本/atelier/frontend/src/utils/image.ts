/** 图片宽高比；后端偶尔缺宽高，按 3:4 兜底，保证布局不塌。 */
export function imageAspect(item: { width?: number | null; height?: number | null }): number {
  if (item.width && item.height) return item.width / item.height
  return 3 / 4
}
