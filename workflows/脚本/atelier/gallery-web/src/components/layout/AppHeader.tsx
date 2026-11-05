import { Link, useMatches } from '@tanstack/react-router'
import { ArrowLeftIcon, DicesIcon, ShieldCheckIcon, SparklesIcon } from 'lucide-react'
import { Fragment } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { costumesQuery, portraitsQuery, posesQuery } from '@/api/gallery'
import { AtelierTopNav } from '@/components/layout/AtelierTopNav'
import { ThemeToggle } from '@/components/theme/ThemeToggle'
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { SidebarTrigger } from '@/components/ui/sidebar'
import { ATELIER_GALLERY_PATH } from '@/lib/atelierLinks'
import { isEmbeddedMode } from '@/lib/embedded'
import { useStudio } from '@/store/studioStore'

export function AppHeader() {
  const { recipe, randomizeRecipe, safeMode, toggleSafeMode } = useStudio()
  // embedded 状态在页面生命周期内不变，渲染时同步求值即可，无需 state/effect。
  const embedded = isEmbeddedMode()
  const qc = useQueryClient()
  const crumbs = useMatches({
    select: (matches) =>
      matches.filter((m) => m.staticData.title).map((m) => ({ title: m.staticData.title!, path: m.pathname })),
  })

  const selectedCount = [recipe.portrait, recipe.costume, recipe.pose].filter(Boolean).length

  // embedded 时外层 Vue 已提供「画室画廊」根入口，面包屑只保留当前页；
  // 若过滤后为空（例如当前页标题恰好就是根标题），回退原 crumbs，避免渲染空白面包屑。
  const crumbBase = embedded ? crumbs.filter((c) => c.title !== '画室画廊' && c.path !== '/') : crumbs
  const breadcrumbCrumbs = crumbBase.length > 0 ? crumbBase : crumbs

  const handleRandom = async () => {
    const [posesRes, costumes, portraits] = await Promise.all([
      qc.ensureQueryData(posesQuery),
      qc.ensureQueryData(costumesQuery),
      qc.ensureQueryData(portraitsQuery),
    ])
    randomizeRecipe({
      poses: posesRes.items,
      costumes,
      portraits,
    })
  }

  return (
    <header className="@container/header flex shrink-0 flex-col">
      {/* 第一层：atelier 全局导航（跨应用，整页跳转）；iframe 内嵌时由外层 Vue 提供，此处隐藏。 */}
      {!embedded && <AtelierTopNav />}

      {/* 第二层：沿用原有工具条，断点、尺寸与行为均保持不变。 */}
      <div className="flex min-h-14 shrink-0 items-center gap-2 border-b border-border/60 px-4">
        <SidebarTrigger className="-ml-1" />
        {/* 跨应用返回入口：原生 a 整页导航，见 lib/atelierLinks.ts 的说明；embedded 时外层 Vue 已有该入口，隐藏。 */}
        {!embedded && (
          <>
            <Button variant="ghost" size="sm" asChild className="gap-1.5 px-2">
              <a
                href={ATELIER_GALLERY_PATH}
                target={embedded ? '_top' : undefined}
                aria-label="返回画室画廊"
                title="返回画室画廊"
              >
                <ArrowLeftIcon className="size-4" />
                <span className="hidden @lg/header:inline">画室画廊</span>
              </a>
            </Button>
            <Separator orientation="vertical" className="mr-2 h-4 data-vertical:self-center" />
          </>
        )}
        <Breadcrumb className="min-w-0 flex-1">
          <BreadcrumbList className="flex-nowrap">
            {breadcrumbCrumbs.map((c, i) => (
              <Fragment key={c.path}>
                {i > 0 && <BreadcrumbSeparator />}
                <BreadcrumbItem className="min-w-0">
                  {i === breadcrumbCrumbs.length - 1 ? (
                    <BreadcrumbPage className="truncate">{c.title}</BreadcrumbPage>
                  ) : (
                    <BreadcrumbLink asChild>
                      <Link to={c.path}>{c.title}</Link>
                    </BreadcrumbLink>
                  )}
                </BreadcrumbItem>
              </Fragment>
            ))}
          </BreadcrumbList>
        </Breadcrumb>

        <div className="ml-auto flex shrink-0 items-center gap-1 @lg/header:gap-2">
          <Button
            variant={safeMode ? 'outline' : 'secondary'}
            size="sm"
            onClick={toggleSafeMode}
            title={safeMode ? '当前已开启安全模式（已隐藏 18+ 敏感内容），点击可解锁完整图库' : '当前已显示 18+ 完整图库，点击可切回安全模式'}
            className={
              safeMode
                ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-700 hover:bg-emerald-500/10 dark:text-emerald-400'
                : 'border-rose-500/30 bg-rose-500/10 text-rose-700 hover:bg-rose-500/20 dark:text-rose-400'
            }
          >
            <ShieldCheckIcon className="size-3.5" />
            <span className="hidden @2xl/header:inline">{safeMode ? '安全模式 (SFW)' : '18+ 完整模式'}</span>
            <span className="@2xl/header:hidden">{safeMode ? 'SFW' : '18+'}</span>
          </Button>
          <Button variant="outline" size="sm" onClick={handleRandom} className="hidden @3xl/header:inline-flex">
            <DicesIcon className="size-3.5" />
            随机捏人
          </Button>
          <Button size="sm" asChild>
            <Link to="/studio" aria-label={`AI 合成台，已选 ${selectedCount} 项参考图`}>
              <SparklesIcon className="size-3.5" />
              <span className="hidden @lg/header:inline">AI 合成台</span>
              {selectedCount > 0 && (
                <span className="ml-1 rounded-full bg-primary-foreground/20 px-1.5 py-0.2 text-[11px] font-bold">
                  {selectedCount}/3
                </span>
              )}
            </Link>
          </Button>
          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}