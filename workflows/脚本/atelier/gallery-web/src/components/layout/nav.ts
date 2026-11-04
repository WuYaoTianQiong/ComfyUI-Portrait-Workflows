import type { LinkProps } from '@tanstack/react-router'
import {
  LayoutDashboardIcon,
  PersonStandingIcon,
  PlugZapIcon,
  ShirtIcon,
  SparklesIcon,
  UserRoundIcon,
  type LucideIcon,
} from 'lucide-react'

export interface NavItem {
  title: string
  to: NonNullable<LinkProps['to']>
  icon: LucideIcon
  badge?: string
}

export interface NavGroup {
  label: string
  items: NavItem[]
}

export const navGroups: NavGroup[] = [
  {
    label: '工作台',
    items: [
      { title: '图库总览', to: '/', icon: LayoutDashboardIcon },
      { title: 'AI 角色合成台', to: '/studio', icon: SparklesIcon, badge: 'PRO' },
    ],
  },
  {
    label: '三大参考图库',
    items: [
      { title: '动作姿势库', to: '/poses', icon: PersonStandingIcon },
      { title: '服装穿搭库', to: '/costumes', icon: ShirtIcon },
      { title: '人像颜值库', to: '/portraits', icon: UserRoundIcon },
    ],
  },
  {
    label: '配置',
    items: [{ title: 'ComfyUI 连接', to: '/settings', icon: PlugZapIcon }],
  },
]

const allItems = navGroups.flatMap((g) => g.items)

export function activeNavTo(pathname: string): string | undefined {
  let best: string | undefined
  for (const { to } of allItems) {
    const hit = to === '/' ? pathname === '/' : pathname === to || pathname.startsWith(`${to}/`)
    if (hit && (!best || to.length > best.length)) best = to
  }
  return best
}