import { useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import {
  DicesIcon,
  PersonStandingIcon,
  ShirtIcon,
  SparklesIcon,
  UserRoundIcon,
  type LucideIcon,
} from 'lucide-react'
import { costumesQuery, portraitsQuery, posesQuery } from '@/api/gallery'
import { PageHeader } from '@/components/common/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { poseThumbPath, referenceImageUrl } from '@/lib/recipeImages'
import { useStudio } from '@/store/studioStore'

export const Route = createFileRoute('/')({
  staticData: { title: '图库总览' },
  loader: ({ context }) =>
    Promise.all([
      context.queryClient.ensureQueryData(posesQuery),
      context.queryClient.ensureQueryData(costumesQuery),
      context.queryClient.ensureQueryData(portraitsQuery),
    ]),
  pendingComponent: () => <Skeleton className="h-[520px] rounded-[22px]" />,
  component: DashboardPage,
})

interface RecipeSlot {
  key: string
  label: string
  to: '/portraits' | '/costumes' | '/poses'
  hint: string
  icon: LucideIcon
  name: string | null
  thumb: string | null
}

function DashboardPage() {
  const { data: posesData } = useSuspenseQuery(posesQuery)
  const { data: costumes } = useSuspenseQuery(costumesQuery)
  const { data: portraits } = useSuspenseQuery(portraitsQuery)
  const { recipe, randomizeRecipe } = useStudio()
  const qc = useQueryClient()

  const selectedCount = [recipe.portrait, recipe.costume, recipe.pose].filter(Boolean).length

  const slots: RecipeSlot[] = [
    {
      key: 'portrait',
      label: '人像',
      to: '/portraits',
      hint: '选择人像',
      icon: UserRoundIcon,
      name: recipe.portrait?.发型名称 ?? null,
      thumb: recipe.portrait ? referenceImageUrl(recipe.portrait.缩略图) : null,
    },
    {
      key: 'costume',
      label: '服装',
      to: '/costumes',
      hint: '选择服装',
      icon: ShirtIcon,
      name: recipe.costume?.服装名称 ?? null,
      thumb: recipe.costume ? referenceImageUrl(recipe.costume.缩略图) : null,
    },
    {
      key: 'pose',
      label: '姿势',
      to: '/poses',
      hint: '选择姿势',
      icon: PersonStandingIcon,
      name: recipe.pose?.姿势名称 ?? null,
      thumb: recipe.pose ? referenceImageUrl(poseThumbPath(recipe.pose)) : null,
    },
  ]

  const handleRandom = async () => {
    const [posesRes, costumeItems, portraitItems] = await Promise.all([
      qc.ensureQueryData(posesQuery),
      qc.ensureQueryData(costumesQuery),
      qc.ensureQueryData(portraitsQuery),
    ])
    randomizeRecipe({ poses: posesRes.items, costumes: costumeItems, portraits: portraitItems })
  }

  return (
    <>
      <PageHeader title="AI 角色参考库" />

      {/* 三大核心图库入口卡片 */}
      <div className="grid gap-3 sm:grid-cols-3 sm:gap-4">
        <Link
          to="/poses"
          className="group flex flex-col justify-between rounded-[20px] bg-muted p-4 transition hover:bg-muted/70"
        >
          <div className="flex items-center justify-between gap-2">
            <h2 className="flex min-w-0 items-center gap-1.5 text-base font-semibold">
              <span className="size-1.5 shrink-0 rounded-full bg-emerald-500" />
              <span className="truncate">动作姿势库</span>
            </h2>
            <Badge variant="secondary">{posesData.items.length.toLocaleString('zh-CN')}</Badge>
          </div>
          <div className="mt-3 grid grid-cols-4 gap-1.5">
            {posesData.groups.slice(0, 4).map((g) => (
              <img
                key={g.key}
                src={`/${g.order[0].缩略图}`}
                alt={g.name}
                loading="lazy"
                className="aspect-3/4 w-full rounded-lg bg-background object-cover"
              />
            ))}
          </div>
        </Link>

        <Link
          to="/costumes"
          className="group flex flex-col justify-between rounded-[20px] bg-muted p-4 transition hover:bg-muted/70"
        >
          <div className="flex items-center justify-between gap-2">
            <h2 className="flex min-w-0 items-center gap-1.5 text-base font-semibold">
              <span className="size-1.5 shrink-0 rounded-full bg-sky-500" />
              <span className="truncate">服装穿搭库</span>
            </h2>
            <Badge variant="secondary">{costumes.length.toLocaleString('zh-CN')}</Badge>
          </div>
          <div className="mt-3 grid grid-cols-4 gap-1.5">
            {costumes.slice(0, 4).map((c) => (
              <img
                key={c.id}
                src={referenceImageUrl(c.缩略图)}
                alt={c.服装名称}
                loading="lazy"
                className="aspect-3/4 w-full rounded-lg bg-background object-cover"
              />
            ))}
          </div>
        </Link>

        <Link
          to="/portraits"
          className="group flex flex-col justify-between rounded-[20px] bg-muted p-4 transition hover:bg-muted/70"
        >
          <div className="flex items-center justify-between gap-2">
            <h2 className="flex min-w-0 items-center gap-1.5 text-base font-semibold">
              <span className="size-1.5 shrink-0 rounded-full bg-violet-500" />
              <span className="truncate">人像颜值库</span>
            </h2>
            <Badge variant="secondary">{portraits.length.toLocaleString('zh-CN')}</Badge>
          </div>
          <div className="mt-3 grid grid-cols-4 gap-1.5">
            {portraits.slice(0, 4).map((p) => (
              <img
                key={p.id}
                src={`/${p.缩略图}`}
                alt={p.标题}
                loading="lazy"
                className="aspect-3/4 w-full rounded-lg bg-background object-cover"
              />
            ))}
          </div>
        </Link>
      </div>

      {/* 当前角色配方摘要 */}
      <section className="rounded-[20px] bg-muted p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold sm:text-base">当前角色配方</h2>
          <div className="flex flex-wrap items-center gap-1.5">
            <Button variant="outline" size="sm" onClick={handleRandom}>
              <DicesIcon className="size-3.5" />
              随机捏人
            </Button>
            <Button size="sm" asChild>
              <Link to="/studio">
                <SparklesIcon className="size-3.5" />
                进入合成台{selectedCount > 0 ? ` (${selectedCount}/3)` : ''}
              </Link>
            </Button>
          </div>
        </div>

        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          {slots.map(({ key, label, to, hint, icon: Icon, name, thumb }) => (
            <div key={key} className="flex min-w-0 items-center gap-2 rounded-xl bg-background p-2">
              {thumb ? (
                <img
                  src={thumb}
                  alt={name ?? label}
                  loading="lazy"
                  className="size-10 shrink-0 rounded-lg bg-muted object-cover"
                />
              ) : (
                <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                  <Icon className="size-4" />
                </div>
              )}
              <div className="min-w-0">
                <div className="text-[10px] text-muted-foreground">{label}</div>
                {name ? (
                  <div className="truncate text-xs font-medium">{name}</div>
                ) : (
                  <Link to={to} className="block truncate text-xs font-medium text-primary hover:underline">
                    {hint}
                  </Link>
                )}
              </div>
            </div>
          ))}
        </div>

        {selectedCount === 0 && (
          <p className="mt-2 text-[11px] text-muted-foreground">
            配方为空，可先随机捏人，或从上方三个图库中各挑一项。
          </p>
        )}
      </section>

      {/* 素材来源（原指南页内容压缩为一段） */}
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        素材来源：姿势与现实服装参考图源自 ギア（@giaaibusi）公开分享；二次元服装来自 たき AI · CharaDB，仅收录元数据、图片从来源站点读取，禁止再分发原图；人像库遵循 CC0 1.0 协议。部分姿势含 18+ 内容，默认由安全模式隐藏。
      </p>
    </>
  )
}