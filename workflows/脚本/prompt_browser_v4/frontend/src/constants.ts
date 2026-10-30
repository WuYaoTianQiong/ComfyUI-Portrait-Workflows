/**
 * 碎片类型固定 8 类，与后端 `services/composition.FRAGMENT_TYPES` 一一对应。
 *
 * 顺序即渲染顺序（人物 → 姿态 → 镜头 → 场景 → 风格）。
 * 两边必须同时改 —— 后端会拒绝不在这个列表里的类型（400）。
 */
export const FRAGMENT_TYPES = [
  '人物面部',
  '人物身材',
  '人物服饰',
  '姿态动作',
  '拍摄视角',
  '场景环境',
  '光影色调',
  '画风技术',
] as const

export type FragmentType = (typeof FRAGMENT_TYPES)[number]
