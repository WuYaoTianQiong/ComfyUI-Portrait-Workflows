import { ref, watch } from 'vue'

import { readSession, writeSession } from './useSessionState'

/**
 * 提示词页的“浏览状态”：侧栏布局 + 筛选/页码/选中项/滚动位置。
 *
 * 与业务逻辑无关，只负责把这些偏好持久化到 localStorage：
 * - `pb.promptUi`：这台机器的布局偏好；
 * - `pb.session.prompt`：上次看到哪儿。
 */
const UI_KEY = 'pb.promptUi'
const SESSION_KEY = 'pb.session.prompt'

interface PromptUi {
  pageSize: number
  sort: string
  order: 'asc' | 'desc'
  collapsed: boolean
  width: number
}

export interface PromptSession {
  page: number
  search: string
  categoryId: number | null
  tagIds: number[]
  tagMatch: 'all' | 'any'
  fragmentType: string
  fragmentMatch: 'has' | 'only'
  selectedId: number | null
  selectedIds: number[]
  scrollTop: number
}

function readUi(): Partial<PromptUi> {
  try {
    const raw = localStorage.getItem(UI_KEY)
    return raw ? (JSON.parse(raw) as Partial<PromptUi>) : {}
  } catch {
    return {}
  }
}

export const SORT_OPTIONS = [
  { value: 'default', label: '默认' },
  { value: 'created', label: '创建时间' },
  { value: 'name', label: '名称' },
  { value: 'usage', label: '使用次数' },
  { value: 'rating', label: '评级' },
]

export const PAGE_SIZES = [20, 50, 100, 200]

export function usePromptWorkspace() {
  const savedUi = readUi()
  const pageSize = ref(savedUi.pageSize ?? 50)
  const sort = ref(savedUi.sort ?? 'default')
  const order = ref<'asc' | 'desc'>(savedUi.order ?? 'desc')
  const sidebarCollapsed = ref(savedUi.collapsed ?? false)
  const sidebarWidth = ref(Math.min(600, Math.max(280, savedUi.width ?? 380)))

  function saveUi() {
    try {
      localStorage.setItem(
        UI_KEY,
        JSON.stringify({
          pageSize: pageSize.value,
          sort: sort.value,
          order: order.value,
          collapsed: sidebarCollapsed.value,
          width: sidebarWidth.value,
        }),
      )
    } catch {
      /* 隐私模式下忽略 */
    }
  }

  watch([pageSize, sort, order, sidebarCollapsed, sidebarWidth], saveUi)

  const savedSession = readSession<PromptSession>(SESSION_KEY, {
    page: 1,
    search: '',
    categoryId: null,
    tagIds: [],
    tagMatch: 'all',
    fragmentType: '',
    fragmentMatch: 'has',
    selectedId: null,
    selectedIds: [],
    scrollTop: 0,
  })

  const page = ref(savedSession.page)
  const search = ref(savedSession.search)
  const categoryId = ref<number | null>(savedSession.categoryId)
  const tagIds = ref<number[]>(savedSession.tagIds)
  const tagMatch = ref<'all' | 'any'>(savedSession.tagMatch)
  const fragmentType = ref<string>(savedSession.fragmentType)
  const fragmentMatch = ref<'has' | 'only'>(savedSession.fragmentMatch)
  const selectedId = ref<number | null>(savedSession.selectedId)
  const selectedIds = ref<Set<number>>(new Set(savedSession.selectedIds))

  const listEl = ref<HTMLElement | null>(null)
  let scrollSaveTimer: number | undefined

  function saveSession() {
    writeSession(SESSION_KEY, {
      page: page.value,
      search: search.value,
      categoryId: categoryId.value,
      tagIds: tagIds.value,
      tagMatch: tagMatch.value,
      fragmentType: fragmentType.value,
      fragmentMatch: fragmentMatch.value,
      selectedId: selectedId.value,
      selectedIds: Array.from(selectedIds.value),
      scrollTop: listEl.value?.scrollTop ?? savedSession.scrollTop,
    })
  }

  watch(
    () =>
      [
        page.value,
        search.value,
        categoryId.value,
        tagIds.value.join(','),
        tagMatch.value,
        fragmentType.value,
        fragmentMatch.value,
        selectedId.value,
        Array.from(selectedIds.value).sort((a, b) => a - b).join(','),
      ].join('|'),
    saveSession,
  )

  /** 滚动很频繁，节流后再写，避免每滚一像素都序列化一次。 */
  function onListScroll() {
    if (scrollSaveTimer) return
    scrollSaveTimer = window.setTimeout(() => {
      scrollSaveTimer = undefined
      saveSession()
    }, 300)
  }

  function cancelScrollSave() {
    if (scrollSaveTimer) {
      window.clearTimeout(scrollSaveTimer)
      scrollSaveTimer = undefined
    }
  }

  return {
    pageSize,
    sort,
    order,
    sidebarCollapsed,
    sidebarWidth,
    page,
    search,
    categoryId,
    tagIds,
    tagMatch,
    fragmentType,
    fragmentMatch,
    selectedId,
    selectedIds,
    listEl,
    savedSession,
    saveUi,
    saveSession,
    onListScroll,
    cancelScrollSave,
    SORT_OPTIONS,
    PAGE_SIZES,
  }
}
