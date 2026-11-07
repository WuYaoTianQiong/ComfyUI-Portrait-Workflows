/**
 * 前端 API 类型 —— **不手写**，由后端 OpenAPI 生成（命名规范 §8.3 / §9）。
 *
 * 唯一真源：`app/schemas.py`（Pydantic）→ `/openapi.json`
 * → `openapi-typescript` → `./openapi.d.ts`。
 * 本文件只做一件"人干的事"：把 `components['schemas']['XxxResponse']`
 * 起一个前端读得顺的名字，并对**响应模型**套 `Required<>` ——
 * Pydantic 里带默认值的字段在 schema 里是可选的，但服务端返回时一定带全
 * （response_model 会填默认值），前端不该为此到处判 `undefined`。
 *
 * 重新生成：
 *     python tools/gen_api_types.py          # 只重写 openapi.json / openapi.d.ts
 * 生成物不手改；本文件的别名如果想调整，改这里，不要改 `openapi.d.ts`。
 */

import type { components } from './openapi'

type Schemas = components['schemas']

// ---------------------------------------------------------------------------
// 标签 / 分类
// ---------------------------------------------------------------------------

export type TagRef = Required<Schemas['TagRef']>
export type CategoryRef = Required<Schemas['CategoryRef']>

export type TagRow = Required<Schemas['TagRow']>

export type CategoryNode = Required<Omit<Schemas['CategoryNode'], 'children'>> & {
  children: CategoryNode[]
}

// ---------------------------------------------------------------------------
// 图片（原"历史/画廊"）
// ---------------------------------------------------------------------------

// `version`（源文件 st_mtime_ns 字符串）是缩略图强缓存新增的附加字段：
// openapi-typescript 会把「带 default 的属性」当成必定存在而生成必填，
// 但老快照 / 旧后端 / 测试 fixture 里都可能没有它，这里显式保持可选。
// 其余字段仍按 Required<> 处理（列表接口事实上总会返回）。
export type HistoryItem = Omit<Required<Schemas['HistoryItem']>, 'version'> & {
  version?: string | null
}
// 分页信封：字段名/数量仍取自 schema，只把 `items` 换成上面那个 Required 版本
// （schema 里的 `items` 引用的是原始组件类型，不会跟着别名一起变）
export type HistoryPage = Omit<Required<Schemas['HistoryListResponse']>, 'items'> & {
  items: HistoryItem[]
}
export type ImageFacets = Required<Schemas['FacetsResponse']>
export type ImageIdsPage = Required<Schemas['HistoryIdsResponse']>
export type ImageRunInfo = Required<Schemas['ImageRunInfo']>
export type ImageDetail = Omit<
  Required<Schemas['ImageDetailResponse']>,
  'run' | 'version'
> & {
  run: ImageRunInfo
  // 与 HistoryItem 一致：新增附加字段保持可选
  version?: string | null
}

// ---------------------------------------------------------------------------
// 任务
// ---------------------------------------------------------------------------

export type JobItem = Schemas['JobItem']
export type JobSnapshot = Schemas['JobSnapshot']

// ---------------------------------------------------------------------------
// 提示词
// ---------------------------------------------------------------------------

export type PromptListItem = Required<Schemas['PromptListItem']>
export type PromptListPage = Omit<Required<Schemas['PromptListResponse']>, 'prompts'> & {
  prompts: PromptListItem[]
}
export type PromptDetail = Required<Schemas['PromptDetail']>

// ---------------------------------------------------------------------------
// 系统
// ---------------------------------------------------------------------------

export type SystemStats = Required<Schemas['StatsResponse']>
