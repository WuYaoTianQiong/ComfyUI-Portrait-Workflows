export interface PoseItem {
  source?: 'upload'
  /** 是否使用灰阶深度图（Depth Map）代替素体白模 */
  useDepth?: boolean
  id: string
  体系: string
  姿势编号: string
  分类: string
  姿势名称: string
  角度: string
  缩略图: string
  原图: string
  检索: string
}

export interface PoseGroup {
  key: string
  system: string
  number: string
  name: string
  category: string
  items: PoseItem[]
  angles: Record<string, PoseItem>
  order: PoseItem[]
}

export interface CostumeItem {
  source?: 'upload' | 'charadb'
  一级分类?: '现实' | '二次元'
  来源?: string
  来源地址?: string
  日文名称?: string
  敏感?: boolean
  id: string
  分类: string
  服装名称: string
  标签: string[]
  关键词: string
  缩略图: string
  预览图: string
  原图: string
  检索: string
}

export interface PortraitItem {
  source?: 'upload'
  id: string
  分区: string
  发长: string
  发型名称: string
  标题: string
  宽: number
  高: number
  字节数: number
  精选: boolean
  热门: boolean
  缩略图: string
  原图: string
  检索: string
}

export interface ExtraReferenceImage {
  role?: 'character_sheet'
  id: string
  name: string
  url: string
}

export interface RecipeState {
  portrait: PortraitItem | null
  costume: CostumeItem | null
  pose: PoseItem | null
  workflowImages?: Record<string, ExtraReferenceImage>
  workflowImagesIdentity?: string
  extraImages?: ExtraReferenceImage[]
}

export type ImageProviderId = 'comfyui'

export interface ProviderEndpointConfig {
  baseUrl: string
  apiKey: string
  model: string
  customModel: string
}

export type WorkflowScalar = string | number | boolean

export interface WorkflowParameterOverrides {
  workflowId: string
  values: Record<string, Record<string, WorkflowScalar>>
}

export interface ComfyUiParams {
  parameterOverrides?: WorkflowParameterOverrides
  /**
   * 当前工作流选择：`/api/workflows` 返回的工作流绝对路径，或 `'custom'`（用户导入的 JSON）。
   * 旧版内置模板 ID 已废弃；读到旧值时由 studioStore 迁移为空串，再由合成台自动选中本机工作流。
   */
  workflowPreset: string
  workflowJson: string
  promptNodeId: string
  portraitNodeId: string
  costumeNodeId: string
  poseNodeId: string
  stitchedNodeId: string
  randomizeSeed: boolean
  /** 单次生成最长等待秒数 */
  timeoutSec: number
  /** 配置结构版本，用于迁移旧版默认值 */
  configVersion?: number
}

export interface ApiConfig {
  activeProvider: ImageProviderId
  stylePreset: string
  providers: Record<ImageProviderId, ProviderEndpointConfig>
  comfyuiParams: ComfyUiParams
}

export interface GenerationHistoryItem {
  id: string
  createdAt: number
  provider: ImageProviderId
  model: string
  prompt: string
  imageUrl: string
  recipeSummary: string
  snapshot?: GenerationSnapshot
}


export interface GenerationSnapshot {
  recipe: RecipeState
  prompt: string
  settings: Omit<ApiConfig, 'providers'>
  models: Record<ImageProviderId, Pick<ProviderEndpointConfig, 'model' | 'customModel'>>
  submittedWorkflowJson?: string
}
