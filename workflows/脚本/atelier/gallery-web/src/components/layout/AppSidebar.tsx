import { Link, useLocation } from '@tanstack/react-router'
import { ArrowLeftIcon, PaletteIcon, SparklesIcon } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from '@/components/ui/sidebar'
import { useStudio } from '@/store/studioStore'
import { ATELIER_GALLERY_PATH } from '@/lib/atelierLinks'
import { isEmbeddedMode } from '@/lib/embedded'
import { activeNavTo, navGroups } from './nav'

export function AppSidebar() {
  const pathname = useLocation({ select: (l) => l.pathname })
  const active = activeNavTo(pathname)
  const { recipe } = useStudio()
  const count = [recipe.portrait, recipe.costume, recipe.pose].filter(Boolean).length
  // embedded 状态在页面生命周期内不变，渲染时同步求值即可，无需 state/effect。
  const embedded = isEmbeddedMode()

  return (
    <Sidebar collapsible="icon">
      {/* embedded 时外层 Vue 已提供「画室 / 参考图库」品牌入口，此处隐藏以免重复。 */}
      {!embedded && (
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton size="lg" asChild tooltip="返回画室画廊">
                {/* 整页导航回 atelier：TanStack Link 会把 basepath 拼成 /ref-web/gallery；内嵌时跳出 iframe。 */}
                <a href={ATELIER_GALLERY_PATH} target={embedded ? '_top' : undefined}>
                  <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                    <PaletteIcon className="size-4" />
                  </div>
                  <div className="grid flex-1 text-left leading-tight">
                    <span className="truncate text-sm font-semibold">画室</span>
                    <span className="truncate text-xs text-muted-foreground">参考图库</span>
                  </div>
                </a>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>
      )}

      <SidebarContent>
        {/* embedded 时外层 Vue 已有返回入口，隐藏侧栏这条重复的「返回画廊」。 */}
        {!embedded && (
          <SidebarGroup>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild tooltip="返回画室画廊">
                  <a href={ATELIER_GALLERY_PATH} target={embedded ? '_top' : undefined}>
                    <ArrowLeftIcon />
                    <span className="flex-1 truncate">返回画廊</span>
                  </a>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroup>
        )}
        {navGroups.map((group) => (
          <SidebarGroup key={group.label}>
            <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
            <SidebarMenu>
              {group.items.map((item) => (
                <SidebarMenuItem key={item.to}>
                  <SidebarMenuButton asChild isActive={item.to === active} tooltip={item.title}>
                    <Link to={item.to}>
                      <item.icon />
                      <span className="flex-1 truncate">{item.title}</span>
                      {item.badge && (
                        <Badge variant="secondary" className="ml-auto h-5 px-1.5 text-[10px] font-medium">
                          {item.badge}
                        </Badge>
                      )}
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroup>
        ))}
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild tooltip="当前角色配方">
              <Link to="/studio" className="bg-sidebar-accent/70 hover:bg-sidebar-accent">
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <SparklesIcon className="size-4" />
                </div>
                <div className="grid flex-1 text-left text-xs leading-tight">
                  <span className="truncate font-semibold">角色配方槽 ({count}/3)</span>
                  <span className="truncate text-[11px] text-muted-foreground">
                    {count === 0 ? '未选择 · 点击去捏人' : '点击进入 AI 合成台'}
                  </span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
