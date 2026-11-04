# AI 参考图库 · atelier 融合计划

> 版本：v0.6（2026-11-04，一期验收完成 + 二期补强范围）
> 状态：一期已交付并通过验收（见[验收记录](./AI参考图库_验收记录_20261104.md)）；二期按 §13 执行。
> 关联文档：[AI 参考图库_接入与模型实测_20261104](./AI参考图库_接入与模型实测_20261104.md)、[AI 参考图库_验收记录_20261104](./AI参考图库_验收记录_20261104.md)

> 目标：把 `ai-pose-gallery-zh` 的 4,785 条参考资产接入 atelier，形成"选参考 → 出图 → 归档"的闭环。
> **atelier 是唯一生产入口**，上游 React 台不再作为长期前端。

---

## 0. 目标与非目标

**目标**

1. 在 atelier 内浏览、检索 4,345 条本地参考（pose / costume / portrait）与 440 条外链二次元服装。
2. 选中三条参考（人像 + 服装 + 姿势）即可在 atelier 内直接出图，走现有任务队列与图库归档。
3. 复用 atelier 已有的配方/提示词能力，不新建第二套生产链路。
4. 上游仓库保持零修改，可持续 `git pull`。
5. 补充能力：可选第 4 张参考（M2.5）、上传/拖拽/粘贴参考图（M3）、参考板导出（M5）。

**非目标**

- 不移植 React 合成台、5 家云端协议（Gemini / GPT / Qwen / Doubao / 云端 ComfyUI）、Cloudflare 部署。
- 不把 1.13GB 图片复制进 atelier 库或数据库。
- 不修改 `custom_nodes/ai-pose-gallery-zh` 的代码。
- 不把 440 套 CharaDB 外链服装做离线化。
- **不做批量转碎片**（会稀释个人提示词库，见 §4 M4）。
- 不做参考库收藏表。

---

## 1. 现状与约束（2026-11-04 实测）

| 项 | 实测值 |
|---|---|
| 姿势库 `data/pose-zh.json` | 1,439 条（4 体系 / 26 分类 / 5 角度） |
| 服装库 `data/costume-zh.json` | 1,407 条（8 分类，含内衣・睡衣 199、性感穿搭 140） |
| 人像库 `data/portrait-zh.json` | 1,499 条（正脸参考 893 / 造型氛围 606） |
| 外链服装 `data/costume-anime-zh.json` | 440 条，`缩略图/原图` 为 `charadb-2fi.pages.dev` 远程 URL |
| 合计 | **本地 4,345 条**；含外链共 4,785 条 |
| 图片文件 | `img` 5,784 个 / 1,063MB，`thumbs` 5,784 个 / 65MB，合计 11,568 个 / 约 1.13GB |
| 深度图 | `img/depth/*.webp` 与 `thumbs/depth/*.webp` 各 1,439 张，与 pose id **100% 一一对应**（JSON 里没有该字段，需派生） |
| id 唯一性 | 四库内部无重复，跨库也无交集（`{library}/{id}` 可作路由键） |
| 上游部署 | 真实目录 `F:\ComfyUI_Migration\custom_nodes\ai-pose-gallery-zh`；`workflows\ai-pose-gallery-zh` 是 junction，`LinkTarget` 指向同一目录 |
| atelier | FastAPI + Peewee/SQLite + Vue3；`prompts` 355 条、可见图 159 张；组件 `JustifiedGrid.vue` 可复用 |
| 工作流 | `workflows/PornMaster_Flux2Klein9B_三图角色合成_6步_自动尺寸.api.json`：`#1` 人像 / `#2` 服装 / `#3` 姿势 / `#8` 提示词 / `#40` 6 步 / `#43` 种子（已核对） |
| 四图工作流 | `workflows/PornMaster_Flux2Klein9B_四图参考_6步_自动尺寸.api.json`：`#78` 附加参考 → `#79` 缩放 1.0MP → `#80` VAEEncode → `#81/#82` 接链尾（已实跑通过） |

**硬约束**

- 参考图片只引用路径，不复制；缩略图优先用上游 `thumbs/`（65MB，已是展示尺寸）。
- 敏感过滤在后端统一生效，名单放配置（不写死）。
- 任意图片接口都要做「解析后必须落在 `reference_root` 之内」的校验。
- 上游 JSON 的 `id` 是唯一键；分类名可能变化，适配层**不得依赖分类名做逻辑主键**，只用于筛选与展示。
- **路径只能用 JSON 里的相对路径字段，禁止拼扩展名**（pose 是 `.jpg`/`.png`，costume/portrait 是 `.webp`）。

**已知坑（踩过）**

| 坑 | 处理 |
|---|---|
| `<library_root>/../custom_nodes/...` **不存在**（实测 `Test-Path` = False） | 默认根改为 `library_root / "ai-pose-gallery-zh"`（走根目录 junction） |
| Windows junction 上 `exists()/stat()` 抛 `WinError 448` | 一律先过 `app/services/paths.py::_resolve_if_reparse` |
| `Fragment` 模型已废弃 | 碎片 = `prompts` 里的一条 `【类型】\n正文`，见 §4 M4 |
| JSON 是中文键，四库字段互不相同 | 每库一张显式映射表，不做统一字段假设 |

---

## 2. 目标架构

```
┌──────────────────────────────────┐
│ ai-pose-gallery-zh（只读，零修改） │  data/*-zh.json + thumbs/ + img/ + img/depth/
└───────────────┬──────────────────┘
                │ 路径读取（junction，经 _resolve_if_reparse）
┌───────────────▼──────────────────┐
│ atelier 后端                      │
│  services/reference_library.py    │  加载 / mtime 缓存 / 检索 / 安全过滤 / DTO
│  services/recipe_prompt.py        │  三图配方提示词（移植画廊 buildRecipePrompt）
│  routers/reference_library.py     │  只读 4 端点 + 出图端点（薄封装）
│  既有 editor / jobs / images      │  注入、排队、出图、归档（全部复用）
└───────────────┬──────────────────┘
                │ /api
┌───────────────▼──────────────────┐
│ atelier 前端  /reference          │  三 Tab + 筛选 + 网格 + 只读灯箱 + 出图面板
└──────────────────────────────────┘
```

分工原则：

- **gallery = 素材与元数据层**（只读，不跑服务）；
- **atelier = 浏览、资产、生产、归档的唯一入口**；
- **ComfyUI 插件 = 画布内选图**（保留，不参与 atelier 链路）；
- **React 台 = 调参/对照参照物**，暂不退役（用于验证上游契约是否变化）。

---

## 3. 数据与接口契约

### 3.1 每库字段映射（必须以实测字段为准）

| DTO | pose | costume | portrait | costume-anime |
|---|---|---|---|---|
| `id` | `id` | `id` | `id` | `id` |
| `name` | `姿势名称` | `服装名称` | `标题` | `服装名称` |
| `subtitle` | `姿势编号` + `角度` | — | `发型名称` | `日文名称` |
| `group` | `体系` | `分类` | `分区` | `一级分类` |
| `facet` | `分类` | — | `发长` | `分类` |
| `angle` | `角度` | — | — | — |
| `tags` | — | `标签[]` | — | `标签[]` |
| `keywords` | — | `关键词` | — | `关键词` |
| `thumb` | `缩略图` | `缩略图` | `缩略图` | 远程 URL |
| `image` | `原图` | `原图` | `原图` | 远程 URL |
| `depth` | 派生 `img/depth/{id}.webp` | — | — | — |
| `search_text` | `检索` | `检索` | `检索` | `检索` |
| `hot` / `featured` | — | — | `热门` / `精选` | — |
| `nsfw` | `体系 ∈ NSFW_POSE_SYSTEMS` | `分类 ∈ NSFW_COSTUME_CATEGORIES` | 无（上游不标） | `敏感` |
| `remote` | false | false | false | **true** |

> 上游敏感名单：`NSFW_POSE_SYSTEMS = {全身单人・性感系, 双人缠绵}`、`NSFW_COSTUME_CATEGORIES = {内衣・睡衣, 性感穿搭}`（`src/api/gallery.ts:13-14`）。`泳装・度假` **不算**敏感，别加。

### 3.2 DTO

```json
{
  "id": "full_sexy_P001_front",
  "library": "pose",
  "name": "S形站姿・胯部侧顶",
  "subtitle": "P001 · 正面",
  "group": "全身单人・性感系",
  "facet": "站姿",
  "angle": "正面",
  "tags": [],
  "keywords": "",
  "thumb_url": "/api/reference/items/pose/full_sexy_P001_front/image?kind=thumb",
  "image_url": "/api/reference/items/pose/full_sexy_P001_front/image?kind=image",
  "depth_url": "/api/reference/items/pose/full_sexy_P001_front/image?kind=depth",
  "hot": false,
  "featured": false,
  "nsfw": true,
  "remote": false
}
```

`remote=true` 时三个 URL 直接给外链，前端 `<img>` 热链、失败显示占位，**不允许**参与出图（本地节点读不到远程图）。

### 3.3 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/reference/libraries` | 四库条目数、本地/外链条数、可用性（目录是否存在） |
| GET | `/api/reference/items` | 参数：`library`、`search`、`group`、`facet`、`angle`、`nsfw`、`page`、`page_size` |
| GET | `/api/reference/items/{library}/{id}` | 单条详情 |
| GET | `/api/reference/items/{library}/{id}/image` | `kind=thumb(image/depth)`，FileResponse |
| POST | `/api/reference/recipes` | 三图 + 画风 + 补充提示词 → 透传给现有 editor 批量入口 |
| POST | `/api/reference/fragments` | **M4 可选**，单条转 `prompts` |
| POST | `/api/reference/uploads` | **M3**：上传参考图（multipart），落 `library_root/uploads/<sha1>.<ext>` |
| GET | `/api/reference/sheet` | **M5**：参考板 PNG（1800×1200，`labels=0/1`），非出图产物 |

约定：

- 检索参数名用 `search`（atelier 全站如此，不用 `q`）；
- 分页响应与全站一致：`{items, total, page, page_size}`（照 `app/routers/fragments.py:40-75` 的写法）；
- 图片端点：`resolve → 必须位于 reference_root 内 → _resolve_if_reparse → FileResponse`，越界一律 400；
- `kind` 未命中（如 costume 没有 depth）→ 404，不静默退回 thumb。

### 3.4 安全模式（简化版）

- 配置 `ATELIER_REFERENCE_ALLOW_NSFW`（默认 `0`）是唯一总闸；
- 未开启时后端强制过滤 NSFW 集合，`nsfw=1` 参数被忽略（不返回 403，避免前后端两套状态机）；
- 开启后前端显示一个开关，默认关闭，切换时弹一次确认；
- 名单放配置（`reference_nsfw_pose_systems` / `reference_nsfw_costume_categories`），前后端都不硬编码；
- 图片端点沿用同一过滤，不能靠猜 URL 绕过；
- 单人本地工具（127.0.0.1）不做账号/二次密码。

---

## 4. 分阶段计划

> 工作量按 atelier 现有规范估算（含 pytest / vue-tsc / vitest / build / smoke 回归）。

### 完成情况（2026-11-04 收尾）

| 阶段 | 状态 | 提交 |
|---|---|---|
| M1 只读参考库（后端 + 前端） | 完成 | `41d2b94` 骨架、`6f7e512` 后端、`c74bef7` 前端 |
| M2 三图出图 | 完成 | `d33e2c3` |
| M2.5 第 4 张参考 | 完成 | `d33e2c3` |
| M3 上传 / 拖拽 / 粘贴 | 完成 | `b37096a` |
| M4 单条转提示词 | 完成（收尾补） | 本次 `feat(参考库): 单条转提示词与收尾回归` |
| M5 拼图参考板 | 完成 | `094eea0` |

### M1 · 只读参考库（1–1.5 天）

**改动**

- `app/services/reference_library.py`（新）：四库加载、mtime 缓存、`search_text` 子串检索、体系/分类/角度/发长 facet 索引、NSFW 过滤、DTO 映射、depth 派生、按 `(体系, 姿势编号)` 聚合用于多角度切换。
- `app/routers/reference_library.py`（新）：§3.3 的 4 个只读端点。
- `app/config.py`：`reference_enabled`、`reference_root`、`reference_allow_nsfw`、`reference_page_size`、两个 NSFW 名单。
- `app/main.py`：`include_router(..., prefix="/api")`，插在 `legacy_router` **之前**（`main.py:168` 有顺序说明）。
- 前端：`/reference` 路由 + 导航项 + `ReferenceView.vue`；复用 `JustifiedGrid.vue`；灯箱另写只读组件（`Lightbox.vue` 绑定 `HistoryItem`，不适合直接复用）。
- `tools/gen_api_types.py` 重跑（schemas 变更必须）。

**验收**

- 4,345 条本地条目全部可浏览；440 条外链可见（热链 + 失败占位）。
- 检索首屏 < 300ms（进程内缓存命中）；`search=针织`、`search=P001`、`search=波波头` 均能命中。
- 姿势库支持 `[白模 | 深度]` 切换，深度图 1,439 条全部可打开。
- 默认看不到「全身单人・性感系 / 双人缠绵 / 内衣・睡衣 / 性感穿搭」。
- 图片端点对 `..`、绝对路径、盘符、非 `reference_root` 路径返回 400；对不存在的文件 404。
- 缩略图直接用上游 `thumbs/`，atelier 侧**不**生成新缩略图缓存。
- `pytest -q` + `tools\ci.ps1` 全绿。

**回滚**：`ATELIER_REFERENCE_ENABLED=0` → 路由 404、导航隐藏；无数据库变更。

### M2 · 三图出图（0.5 天）

**改动**

- `app/services/recipe_prompt.py`（新）：把上游 `src/services/aiGenerator.ts:155 buildRecipePrompt` 逐段移植成 Python（纯中文结构化提示词，约 120 行）；只支持「无预设 / 写实人像写真」两种画风，其余按需再加。
- `POST /api/reference/recipes`：校验三个 id 存在且非 `remote` → 组提示词 → **直接调用现有 `/api/editor/faceswap/batch` 的处理函数**（`main_paths/ref_paths/ref2_paths` 传三条绝对路径，`main_node="1"`、`ref_node="2"`、`ref2_node="3"`，`workflow_path` 用三图工作流）。**不新写图片注入、不新写提交队列。**
- 前端：参考库页内「出图」面板（三图已选 + 画风 + 补充提示词 + 提交），出图后跳任务中心/画廊。

**验收**

- 先 `dry_run=true` 核对节点映射，再跑一次真实出图：6 步 Flux2 单张 30–40s（模型已缓存）。
- 任务状态 / SSE / 画廊归档 / 重试全部正常（均为现有能力，回归即可）。
- 输入缺失、`remote` 条目、文件不存在 → 可读错误，不产生半截任务。
- 生成结果进入 `gen_history`，可在画廊按标签/来源筛到。

**回滚**：删 `/api/reference/recipes` 与前端面板；M1 不受影响。

### M2.5 · 第 4 张参考图（1 天，**已验证可行**，2026-11-04 实测）

**实测结论**（详见关联文档 §3.1：6 组出图、固定种子、同提示词）

| 结论 | 证据 |
|---|---|
| 4 条 `ReferenceLatent` **不劣化、不明显变慢** | 3 参考 35.4–42.8s vs 4 参考 41.1–49.5s，脸/服装/构图无退化 |
| 第 4 张**确实生效** | 链尾追加冲突服装 → 鞋袜被换成第 4 张的黑色连裤袜 + 麂皮靴，跨两个种子稳定复现 |
| **顺序决定权重** | 同素材插在链首 → 图2 的服装几乎被完全压制（改成第 4 张的橄榄绿针织 + 皮裙）；插在链尾 → 只做部件级补充 |
| 语义重叠会**部件级混搭** | 图2 与图4 都是"整套服装"时，上衣跟图2、鞋袜跟图4 |

**改动**

- 工作流：新增 `workflows/PornMaster_Flux2Klein9B_四图参考_6步_自动尺寸.api.json`（复制 `#78 LoadImage` + `#79 ImageScaleToTotalPixels(1.0MP)` + `#80 VAEEncode` + `#81 ReferenceLatent(接 65)` + `#82 ReferenceLatent(接 68)`，`#42` 的 positive/negative 改指 81/82）。**必须接链尾**。
- atelier：`MAX_INPUTS 3→4`、`ROLE_ORDER` 加 `ref3`、`FaceswapRequest` 加 `ref3_ids/ref3_paths/ref3_node`、`_collect_sources` 与角色循环支持第 4 组、前端参考槽位 +1、`job_retry` 复用第 4 张。

**使用约束（写进 UI 文案）**

- 第 4 张只能补**图1/2/3 未覆盖的维度**：鞋/包/配饰、场景与光线、氛围质感；
- **不要**再放一套"完整服装"或"另一张人像"——会与图2/图1 争抢，导致部件级混搭；
- 不接在链首（会覆盖前序参考）。

**验收**

- 四图与三图在同样素材下，人脸/服装/姿势一致性无明显退化，耗时增幅 ≤ 8s。
- 第 4 张换成"鞋包特写"时，输出中该单品确实出现。
- 只有 3 个 `LoadImage` 的旧工作流仍可跑（`MAX_INPUTS=4` 只是上限，不强制 4 张）。

**回滚**：前端隐藏第 4 槽位 + 不选四图工作流即可；四图工作流文件独立存在，不影响三图。

### M3 · 上传 / 拖拽 / 粘贴（0.5 天）

**动机**：atelier 全站没有图片上传端点（唯一的 `UploadFile` 在 `prompts.py`，只用于导入提示词），参考图只能"先存磁盘再浏览"。网上下载、截图、剪贴板里的图每天都要用。

**改动**

- 后端新增 `app/services/uploads.py` + `POST /api/reference/uploads`（multipart）：
  - 扩展名白名单用 `paths.IMAGE_EXTENSIONS`；`.heic/.heif`（含改名成 `.jpg` 的）按 `image_formats.is_heif()` 判文件头后转 PNG；
  - 落盘 `library_root/uploads/<sha1前12>.<ext>`，**同一文件去重**（已存在直接复用）；
  - 单文件上限 25MB；**不接受客户端指定目录**，只用服务端固定目录；
  - 返回 `{path, name, width, height, bytes, dedup}`，`path` 供前端回填槽位、供出图时 `inject_input_image` 拷进 ComfyUI input。
- 前端新增 `frontend/src/components/DropZone.vue` + `frontend/src/api/upload.ts`：
  - 支持拖拽、`Ctrl+V` 粘贴位图、点击选择文件；多选按顺序进槽位；
  - 挂两处：参考库出图面板的槽位、`EditorView` 的目标图/参考槽位。
- **不做**"粘贴 URL 自动下载"：要发起外网抓取 + 域名白名单，属于新攻击面，收益低；需要远程图请先存到本地。

**验收**

- 拖 3 张图 → 3 个槽位依次填充；`Ctrl+V` 粘贴截图可入槽。
- HEIC（含改名 `.jpg`）自动转 PNG 后可正常出图。
- 同一文件重复上传不重复落盘（返回 `dedup=true`）。
- 落盘图能被出图链路读取（`inject_input_image` 拷进 input 后 LoadImage 正常）。
- 超大文件/非图片/目录穿越文件名 → 400，且有可读错误。

**回滚**：前端隐藏入口、删 `library_root/uploads` 即可；端点无数据库副作用。

### M4 · 单条转提示词（0.25 天，可选）

**改动**

- `POST /api/reference/fragments`：写 `prompts` 表，正文 `f"【{类型}】\n{内容}"`（与 `_migrate_v4_fragments_to_prompts` 同格式），`note` 打来源标记 `ref:{library}/{id}`，`tags` 带库名；按正文精确匹配去重（`fragments`/`prompts` 都**没有**唯一约束）。
- 类型映射：pose → `姿态动作`、costume → `服装与配饰`、portrait → `人物面部`。
- **只做单条**，不做批量；UI 上明确提示"会加入提示词库，参与组合创作随机池"。

**验收**

- 转出的条目能在提示词页看到、能被 composer 随机到、`usage_count` 正常。
- 重复转换提示已存在；删除该 prompt 后不影响参考库。
- 无新增表、无 schema 变更。

### M5 · 拼图参考板导出（0.5 天）

**定位**：只做"生成参考板 + 下载"，**不做预览弹窗**、**不作为出图输入**（atelier 出图直接吃 3–4 张原图，比压成一张信息量高）。

**改动**

- 后端 `app/services/reference_sheet.py` + `GET /api/reference/sheet?pose=&costume=&portrait=&extra=&labels=1`：
  - PIL 合成 **1800×1200**（上游是三列 `480×640` + padding + 标题条，atelier 按同比例实现），第 4 张存在时自动并成四列；
  - `labels=1` 画"图N · 名称"标题条（人看/带走用）；`labels=0` 纯图拼接（可喂给带"拼图节点"的工作流）；
  - 输入走 `reference_library` 的路径解析（同一套 root 校验），`remote` 条目直接 400。
- 前端：参考库页 + `EditorView` 各一个"生成参考板"按钮 → 新窗口/下载。

**验收**

- 三图/四图都能出 1800×1200，纵横比不变形（等比缩放 + 居中留边）。
- `labels=0/1` 两种模式都可用；缺图时 400 不崩。
- 单次生成 < 300ms（本地磁盘读 + PIL）。
- 产物不进 `gen_history`（不是生成图）。

**回滚**：删端点与按钮，无副作用。

### Backlog（本期不做）

| 项 | 理由 |
|---|---|
| 收藏 / 自定义标签 | 需新建表 + 后台维护，单人工具无使用场景 |
| 批量随机组合 | `editor` 的 `pair_mode=cross/zip` + `MAX_COMBOS=100` 已覆盖 |
| 拼图弹窗预览（灯箱式） | 只做导出即可；预览用图片直链足够 |
| 云端 5 家协议 | 非目标 |
| 退役 React 台 | 留作上游契约变化的对照物 |

---

## 5. 复用映射（修正版）

| 需求 | 复用什么 | 注意 |
|---|---|---|
| 图片网格 | `frontend/src/components/JustifiedGrid.vue` | `items/ratio/keyOf/targetRowHeight/gap`，纯展示，可直接用 |
| 灯箱 | 需**新写只读灯箱** | `Lightbox.vue` 的 `items` 是 `HistoryItem[]`，绑了 regenerate/jump-to-prompt |
| 选图弹窗 | **不能直接复用** `ImagePicker.vue` | 数据源硬编码 `/api/images`，无 `source/queryFn` 注入点 |
| 出图注入 | `routers/editor.py` 的 `_resolve_input_nodes` + 角色循环（`editor.py:217-256, 524-541`） | `MAX_INPUTS=3`；函数名是 `inject_input_image`（`workflow_parser.py:1278`），不是 `inject_image` |
| 磁盘素材 | `_collect_sources`（`editor.py:130-160`） | 只校验「绝对路径 + 扩展名」，不限制目录，可直接吃图库路径 |
| 缩略图 | 上游 `thumbs/` 绝对路径 | 别走 `/api/browser/thumb`，它会重新生成并缓存 4,345 张 |
| 预览/原图 | 新图片端点 | `/api/browser/*` 按设计**不做 root 白名单**，不能照抄 |
| junction 解析 | `app/services/paths.py::_resolve_if_reparse`（:81） | 解析结果可能是 `\\?\F:\...`，需去前缀 |
| 任务队列 / SSE | `services/submission.py`、`job_state.py`、`useJobStream.ts` | 出图不需要改 |
| 类型生成 | `tools/gen_api_types.py` | schemas 变更后必跑 |

---

## 6. 配置项

| 变量 | 默认 | 说明 |
|---|---|---|
| `ATELIER_REFERENCE_ENABLED` | `1` | 0 = 路由 404、导航隐藏 |
| `ATELIER_REFERENCE_ROOT` | `library_root / "ai-pose-gallery-zh"` | 走根目录 junction；**不要**用 `../custom_nodes/...`（该路径不存在） |
| `ATELIER_REFERENCE_ALLOW_NSFW` | `0` | 1 = 允许查看敏感集合 |
| `ATELIER_REFERENCE_PAGE_SIZE` | `60` | 默认分页 |
| `ATELIER_REFERENCE_NSFW_POSE_SYSTEMS` | `全身单人・性感系,双人缠绵` | 逗号分隔 |
| `ATELIER_REFERENCE_NSFW_COSTUME_CATEGORIES` | `内衣・睡衣,性感穿搭` | 逗号分隔 |

> 依赖其他字段的默认值必须走 `model_validator(mode="after")`（`config.py:85-88`），不能把函数调用写进字段默认值。

---

## 7. 风险与回滚

| 风险 | 处理 |
|---|---|
| 上游 JSON 结构/id 变化 | 按 `id` 取值，字段缺失降级为空；启动日志打印各库条数，数量异常给 warning |
| 上游删图/加图 | 不缓存"文件是否存在"的结论，图片端点实时校验；缺失返回 404 + 前端占位 |
| 外链 440 条失效或被墙 | `remote=true` 走热链，失败显示占位，不阻塞其它条目 |
| junction 失效 / 跨卷 | 启动健康检查（`/api/reference/libraries` 返回 `available:false`）；路径一律 `_resolve_if_reparse` |
| 缩略图重复生成拖慢 | 直接用上游 `thumbs/`，禁止走会写缓存的端点 |
| M4 稀释提示词库 | 只做单条 + `note` 标记；不做批量；UI 明示会进随机池 |
| 上传端点变成任意写入 | 只写 `library_root/uploads`，扩展名白名单 + 25MB 上限，文件名由 sha1 生成，不接受客户端路径 |
| 大网格渲染卡顿 | 分页 60 + `JustifiedGrid` 懒加载；不一次性渲染 4,345 张 |
| 版权 | 仅个人学习创作；不随 atelier 发布物分发；不打包倒卖 |

**回滚**：`ATELIER_REFERENCE_ENABLED=0` 即恢复原状；M1/M2/M2.5/M3/M5 无数据库变更，M4 只增 `prompts` 行（可凭 `note=ref:*` 精确删除）。

---

## 8. 验收清单（整体）

- [x] 4,345 条本地参考可浏览、检索、筛选、预览；440 条外链可见不可出图
- [x] 姿势库白模/深度切换正常（深度 1,439 条全通）
- [x] 安全过滤后端生效，默认隐藏 4 个敏感分类；名单在配置里
- [x] 图片端点无路径穿越，越界 400、缺失 404
- [x] 三图出图走现有队列并归档；单张 6 步 ≤ 40s
- [x] 四图（可选第四槽）出图与三图无质量退化，耗时增幅 ≤ 8s
- [x] 拖拽/粘贴/选择文件入槽可用（**仅编辑页**；参考库页的槽位混源见 §13 二期）；HEIC 自动转 PNG；重复文件不重复落盘
- [x] 参考板导出 1800×1200，`labels=0/1` 双模式可用
- [x] 未新增表、未改 `custom_nodes/ai-pose-gallery-zh`
- [x] `pytest` / `vue-tsc` / `vitest` / `vite build` / `smoke` 全绿
- [x] atelier 与上游仓库 `git status` 都干净

---

## 9. 决策记录

| 日期 | 决策 |
|---|---|
| 2026-11-04 | 18+ 默认关闭；后端单一总闸 `ATELIER_REFERENCE_ALLOW_NSFW` + 前端单开关（**v0.3 简化，废弃 403 语义与双开关**） |
| 2026-11-04 | 三合一生成放在参考库页内，任务进现有任务中心 |
| 2026-11-04 | 收藏 / 自定义标签：不排期（原第四期移入 Backlog） |
| 2026-11-04 | **（v0.3）440 条 CharaDB 外链走热链展示**，标记 `remote`，禁止参与出图；不下载不代理 |
| 2026-11-04 | **（v0.3）Phase 2「转碎片」降级为 M4 单条可选**：`Fragment` 已废弃，改写入 `prompts`（`【类型】` 格式 + `note` 来源标记），且不做批量 |
| 2026-11-04 | **（v0.3）Phase 3 不新写注入/提交逻辑**，改为复用 `/api/editor/faceswap/batch`，工作量 1 天 → 0.5 天 |
| 2026-11-04 | **（v0.3）Phase 4 删除**：批量由 editor 的 cross/zip 覆盖，收藏无场景 |
| 2026-11-04 | **（v0.3）atelier 为唯一生产入口**，React 台暂留作上游契约对照，不退役 |
| 2026-11-04 | **（v0.4）第 4 张参考图实测通过，转正为 M2.5**：耗时无实质增加、生效但需接链尾且不得与前序参考语义重叠（数据见关联文档 §3.1） |
| 2026-11-04 | **（v0.5）上传/拖拽/粘贴转正为 M3**：低摩擦高频需求，0.5 天；不做 URL 抓取（外网抓取 + 域名白名单属新攻击面，收益低） |
| 2026-11-04 | **（v0.5）拼图参考板转正为 M5**：只做导出（`labels=0/1`），不做预览弹窗、不作为出图输入；排最后 |
| 2026-11-04 | **（收尾）M4 服装类型落地为「人物服饰」**：计划/手册写的「服装与配饰」不在 `fragment_syntax.FRAGMENT_TYPES` 标准 8 类中，写入非标准类型会让提示词页的类型筛选与组合器都认不出来，因此按标准类型落地 |
| 2026-11-04 | **（收尾）参考板按钮只传三核心槽**：`ReferenceSheetButton` 的 `extra` 只接受 `uploads/` 内的上传路径，而 `ReferenceView` 没有上传槽；不把参考库条目 id 混作 `extra`，避免 400 |
| 2026-11-04 | **（收尾）E2E 标签云断言改为数据自适应**：标签云只展示「确实有图片」的标签，生产库当前无此类标签；原断言把用户数据状态当成代码回归，改为有数据点选、无数据验证空状态 |
| 2026-11-04 | **（收尾）`reference_fragments` 路由必须在 `main.py` 注册**：手册白名单未列该文件，但新增 router 不注册则端点不可达，属必要的一行注册改动 |
| 2026-11-04 | **（v0.6 验收）一期通过**：主链路真跑通、安全面无漏洞、真库未污染（详见[验收记录](./AI参考图库_验收记录_20261104.md)） |
| 2026-11-04 | **（v0.6）参考库槽位改为"多来源混用"而非"再加一个上传按钮"**：`/reference/recipes` 增 `*_path`（仅 `uploads/` 内文件），前端槽位按来源传 id 或 path。理由：真实断点是"自己/磁盘的图 + 图库的服装/姿势"跨页断裂，不是缺少上传入口 |
| 2026-11-04 | **（v0.6）配置暴露给前端**：`/api/system/status` 增 `reference_enabled`（导航收起用，App.vue 已 10s 轮询）、`/api/reference/libraries` 增 `allow_nsfw`（18+ 开关置灰用），**不再用 `visible<total` 反推** |
| 2026-11-04 | **（v0.6）深度卡片改用上游 `thumbs/depth`**（5KB vs 18KB），灯箱仍用 `img/depth` |

仍待定（不阻塞 M1）：

1. 出图面板是否需要「按 `(体系, 姿势编号)` 一次带入 5 个角度做批量对比」——M2 之后看实际使用再定。
2. 画风预设要补几种（M2 先给"无预设/写实"两种）。

---

## 10. 新会话开工指引

> 新会话只看这两份文档即可开工，不需要回顾历史对话。

**先读**

1. 本文档（契约与阶段）
2. [AI 参考图库_接入与模型实测_20261104](./AI参考图库_接入与模型实测_20261104.md)（数据规模、模型步数、踩坑）

**环境**

| 项 | 路径 / 地址 |
|---|---|
| atelier 代码 | `F:\ComfyUI_Migration\ComfyUI-Portrait-Workflows\workflows\脚本\atelier` |
| 参考库（只读） | `F:\ComfyUI_Migration\custom_nodes\ai-pose-gallery-zh`；入口 junction `workflows\ai-pose-gallery-zh` |
| 生成工作流 | `workflows\PornMaster_Flux2Klein9B_三图角色合成_6步_自动尺寸.api.json` |
| 四图工作流 | `workflows\PornMaster_Flux2Klein9B_四图参考_6步_自动尺寸.api.json` |
| ComfyUI | `127.0.0.1:8188` |
| atelier | `127.0.0.1:8656`（前端开发 `5173`） |
| 数据库 | `workflows\文档\提示词收藏.db`（Peewee，schema 走 `app/models.py` 的 `MIGRATIONS`） |

**M1 开工顺序**

1. 读五个扩展点：`app/config.py:67-113`、`app/main.py:140-171`、`app/routers/editor.py:130-256`、`app/routers/fragments.py:40-75`、`app/services/paths.py:81`
2. 写 `app/services/reference_library.py`：加载四份 JSON（注意中文键与逐库映射）、mtime 缓存、检索、facet、NSFW 过滤、DTO、depth 派生
3. 写 `app/routers/reference_library.py`：4 个只读端点 + 图片端点（root 包含校验）
4. 注册路由（`legacy_router` 之前）、加配置项（依赖字段的默认值用 `model_validator`）
5. `python tools/gen_api_types.py`
6. 前端 `/reference`：路由 + 导航 + 页面（`JustifiedGrid` + 新只读灯箱 + 筛选栏 + 白模/深度切换）
7. 回归：`python -m pytest -q`，再 `powershell -NoProfile -ExecutionPolicy Bypass -File tools\ci.ps1`

**M1 验收自查**

- [ ] 4,345 条可浏览，检索首屏 < 300ms
- [ ] 默认看不到 4 个敏感分类；`ALLOW_NSFW=0` 时 `nsfw=1` 被忽略而非 403
- [ ] 图片端点拒绝 `..`、绝对路径、盘符、root 外路径
- [ ] 深度图 1,439 条全部可打开
- [ ] atelier 与上游仓库 `git status` 都干净

**项目约定（容易踩）**

- 仓库文件是 CRLF，批量替换要兼容 `\r?\n`。
- junction 路径判断用 `app/services/paths.py::_resolve_if_reparse`，避免 `WinError 448`；结果可能带 `\\?\` 前缀。
- 前端 API 类型不手写：`schemas.py` → `openapi.json` → `openapi.d.ts` → `types.ts`。
- 改库前必须备份；schema 变更只走 `MIGRATIONS`，版本号只增不改；**建表不进迁移**（`_ensure_tables` 里 `create_tables(safe=True)`）。
- 不修改 `custom_nodes/ai-pose-gallery-zh`；要改行为就在 atelier 侧实现。
- 工作流只放 `workflows/` 根目录与 `历史工作流/`，不放进项目目录。
- 参考库图片**只用 JSON 里的相对路径**，不拼扩展名（pose `.jpg`/`.png`，其余 `.webp`）。

---

## 11. 能力对照：atelier 能否替代画廊 Web 端

> 结论：**浏览、筛选、检索、选参考、本地出图、上传、参考板导出全部覆盖**；不覆盖的只剩「云端出图」与「工作流页内编辑器」两类，均为非目标。

| 画廊 Web 功能 | atelier 落地后 | 说明 |
|---|---|---|
| 图库总览（统计 + 热门 Top10 速选） | ✅ 覆盖 | 首页卡片 + `热门` 字段筛选，成本极低 |
| 三库浏览 / 分类·体系·发长筛选 | ✅ 覆盖 | M1 的 facet |
| 中文检索（名称/编号/分类/英文词） | ✅ 覆盖 | 直接复用上游 `检索` 拼接串 |
| 卡片内 5 角度切换（同一姿势） | ✅ 覆盖 | 按 `(体系, 姿势编号)` 聚合，前端切 `id` 即可 |
| 白模 / 深度图切换 | ✅ 覆盖 | 深度图 1,439 条齐全，路径派生 |
| 灯箱大图 / 缩放 | ✅ 覆盖 | 新写只读灯箱（`ZoomViewport` 可参考） |
| 复制姿势 ID / 英文 Prompt | ✅ 覆盖 | 纯前端 |
| 下载原图 | ✅ 覆盖 | 图片端点直链，`kind=image` |
| 精选题集 / 热门榜单 | ✅ 覆盖 | `精选`/`热门` 字段 |
| 加入配方 → 组合三图 | ✅ 覆盖（且更省事） | 参考槽位在 atelier 页内 |
| 本地 ComfyUI 出图 | ➕ 更强 | 任务中心、SSE、去重命名、重试、画廊归档、按来源筛 |
| 生成结果历史 | ➕ 更强 | 画廊 + DB（替代浏览器 IndexedDB） |
| 提示词库联动 | ➕ 更强 | `prompts` / composer / 碎片语法 |
| 12 种画风预设 | 🔸 部分 | M2 只做「无预设 / 写实人像写真」，其余按需 |
| 工作流导入导出（`.api.json`） | 🔸 部分 | atelier 走 `workflows/` 目录 + 工作流选择，不做页内编辑器 |
| 3+N 附加自定义参考图（第 4 张起） | 🔸 已验证可行，M2.5 实现 | 需四图工作流变体（链尾追加），语义不能与图1/2/3 重叠 |
| 拖拽/粘贴/选择文件上传参考图 | ✅ M3 | 新上传端点 + `DropZone.vue`；**不做 URL 抓取** |
| 三合一拼图参考板导出（1800×1200） | 🔸 M5 | 只做导出（`labels=0/1`），不做预览弹窗、不作为出图输入 |
| 云端 5 家协议（Gemini/GPT/Qwen/Doubao） | ❌ 非目标 | 本地 ComfyUI 已够用 |
| API Key 配置页 | ❌ 不需要 | atelier 只连本地 ComfyUI |
| 免责声明 / 使用说明页 | 🔸 部分 | 在 atelier README + 参考库页脚各放一段短声明 |

---

## 12. 多会话并行施工方案

### 12.1 结论：6 个会话、4 个波次、同时最多 3 个

| 波次 | 会话 | 任务 | 依赖 | 预估 |
|---|---|---|---|---|
| A | 会话 1（前半） | **骨架**：配置项 + 3 个空壳 router 注册 + 前端路由/导航 + 生成类型 + commit | — | 0.5h |
| B | 会话 1（后半） | M1 后端：`reference_library.py` service + 4 只读端点 | A | 1d |
| B | 会话 2 | M1 前端：`/reference` 页（三 Tab + 筛选 + 网格 + 只读灯箱） | A | 1d |
| B | 会话 3 | M3 上传：端点 + `DropZone` + EditorView 挂载 | A | 0.5d |
| C | 会话 4 | M2 出图 + M2.5 第 4 槽（**唯一允许打 `/prompt` 的会话**） | B | 1.5d |
| C | 会话 5 | M5 拼图参考板（后端 + 独立按钮组件，不挂载） | B（只读 service） | 0.5d |
| D | 会话 6 | M4 单条转提示词 + 挂载拼图按钮 + 全量回归 + 文档回写 | C | 0.5d |

为什么用"独立 router 文件"拆：`app/main.py`、`app/config.py`、`frontend/src/router.ts`、`openapi.json`、`openapi.d.ts` 都是**全局共享文件**，只在波次 A 由会话 1 独占修改；之后每个会话只碰自己的文件，天然不冲突。

### 12.2 并发纪律（必须遵守）

1. **一个文件在同一波次只能有一个所有者**（见 §12.3）；跨波次交接前**先 commit**。
2. **同一时间最多 3 个会话**。本机单 GPU、单 SQLite、单 ComfyUI，瓶颈是冲突不是 CPU。
3. **只有会话 4 可以提交 `/prompt` 出图**；其它会话验证一律 `dry_run=true` 或只跑单测。
4. **不要两个会话同时跑 `tools/gen_api_types.py`**（重写全局快照）与 `tools/ci.ps1`（抢 8765 端口 + `dist` 产物）。日常回归用 `python -m pytest -q -k <模块>`，`ci.ps1` 只在波次 D 跑一次。
5. **atelier 服务只有一个实例**：改后端前先确认 8656 上没有旧进程（多实例会出现"改了代码行为照旧"）。
6. **子代理（子进程）用法**：每个会话最多挂 2 个，且都用在"只读"上——① `code-explorer` 探查扩展点；② 跑测试并汇总失败原因。**不要让子代理写文件**（并发写同一文件没有合并机制），写代码由会话主代理串行做。

### 12.3 文件归属矩阵

| 文件 | 所有者 |
|---|---|
| `app/config.py`、`app/main.py`、`frontend/src/router.ts`、`frontend/src/App.vue`（导航）、`frontend/openapi.json`、`frontend/src/api/openapi.d.ts` | **会话 1（仅波次 A）** |
| `app/services/reference_library.py`、`app/routers/reference_library.py`（只读端点）、`tests/test_reference_library.py` | 会话 1 |
| `frontend/src/views/ReferenceView.vue`（初版）、`frontend/src/api/reference.ts`、`frontend/src/components/RefLightbox.vue` | 会话 2 |
| `app/services/uploads.py`、`app/routers/reference_upload.py`、`frontend/src/components/DropZone.vue`、`frontend/src/api/upload.ts`、`frontend/src/views/EditorView.vue`（槽位挂载） | 会话 3 |
| `app/services/recipe_prompt.py`、`app/routers/reference_library.py`（新增 `/recipes`）、`app/routers/editor.py`、`app/services/job_retry.py`、`ReferenceView.vue`（出图面板）、`EditorView.vue`（第 4 槽） | 会话 4 |
| `app/services/reference_sheet.py`、`app/routers/reference_sheet.py`、`frontend/src/components/ReferenceSheetButton.vue`、`frontend/src/api/sheet.ts` | 会话 5 |
| `app/routers/reference_fragments.py`、`tools/smoke.py`、`tests/` 收口、文档 | 会话 6 |

### 12.4 每波交接检查

- 波次 A 结束：`pytest -q` 绿 + `python tools/gen_api_types.py` + `git commit -m "feat(reference): 接入骨架与契约"`。
- 波次 B/C 结束：各自 `pytest -q -k reference|upload|sheet` 绿 + `git commit`（一个会话一个 commit，消息带模块名）。
- 波次 D：`tools\ci.ps1` 全绿 + 文档 §4 勾选状态回写 + 最终 commit。

### 12.5 每个会话的提示词

**完整可复制版已单独抽成施工手册，避免两处漂移**：
[AI参考图库_施工手册_20261104](./AI参考图库_施工手册_20261104.md)

手册里按会话分节，每节包含：开场白（整段复制即可）、任务清单、文件白名单/禁止项、完成信号、commit 消息。
新开对话框时只需粘开场白，会话会自己读本文档与实测文档。

### 12.6 上下文与提问方式

- 每个会话开场只给：**施工手册里该节的「开场白」**，不要粘贴历史对话（文档已包含全部契约与实测数据）。
- 不要把文档全文粘进提示词——让会话自己读文件，省上下文。
- 每个会话结束都要它交四样东西：改动摘要 / 文件清单 / 验证命令与结果 / 已知限制；缺验证结果视为未完成。

---

## 13. 二期 · 收尾补强（3 个会话）

一期已验收（见[验收记录](./AI参考图库_验收记录_20261104.md)）。二期只收口验收记录 §4 的必修 1–3 与建议 5–7，**不再扩功能**。

### 13.1 会话与波次

| 波次 | 会话 | 任务 | 依赖 | 预估 |
|---|---|---|---|---|
| A（串行） | A | 后端补齐：槽位路径入参、配置暴露、深度缩略图、加载日志 | 一期已交付 | 2–3h |
| B（并行） | B | 前端接新契约：槽位混源、导航/18+ 配置驱动、`thumbs/depth`、参考板传第 4 张 | A | 3h |
| B（并行） | C | 测试与门禁：`test_reference_sheet` / `test_reference_recipes` / 前端 spec / smoke 补端点 | A | 2h |

B 与 C 文件不重叠，可同时开；A 必须先完成（前端要等新字段与生成的类型）。

### 13.2 范围

**必修**

1. **槽位多来源**：`RecipeRequest` 增 `portrait_path / costume_path / pose_path / extra_path`（优先级：`*_id` 非空用库条目，否则用路径；路径**必须**位于 `library_root/uploads`，扩展名白名单 + `is_file()`）。前端三个核心槽 + 第 4 槽支持"库条目 / 上传图"二选一，提交时按来源传 `*_id` 或 `*_path`。
2. **导航收起**：`/api/system/status` 增 `reference_enabled`（`App.vue` 已每 10s 轮询），前端按它 `v-if`。
3. **18+ 开关**：`/api/reference/libraries` 增 `allow_nsfw`，前端读它置灰，**删除 `visible < total` 推断**。
4. `workflows/uploads/` 忽略（已完成，`ada52d7`）。

**建议**

5. **深度缩略图**：DTO 增 `depth_thumb_url`（`thumbs/depth/{id}.webp`，仅 pose）+ `kind=depth_thumb`；卡片用它，灯箱仍用 `depth_url`。
6. **加载可观测**：`reference_library` 加模块级 `logger`；JSON 缺失/解析失败/条数为 0/偏离基线（1439/1407/1499/440 ±5%）打 warning；启动时 info 打印四库条数。
7. **测试与门禁**：`tests/test_reference_sheet.py`（1800×1200、labels 双模式、remote 400、缺图 400、缓存命中）、`tests/test_reference_recipes.py`（dry_run 节点映射 1/2/3 与 1/2/3/78、path 入参、uploads 外路径 400、remote 400、缺输入 400；`monkeypatch` 掉 `faceswap_batch` 不真提交）、前端 `RefLightbox.spec.ts` + `ReferenceView.spec.ts`、`tools/smoke.py` 补详情/图片/`recipes dry_run`。

**顺手收口（随 A 一起，各一行）**

- `/reference/ping` 只保留一个（当前 4 个 router 各注册一次，只有第一个生效）。
- `media_type_for` 兜底改为 `application/octet-stream`。
- `kind=depth` 对 remote 库改为 404（与 §3.3「kind 未命中 → 404」一致）。
- 参考板按钮传 `extra`，使"四图四列"可达；`EditorView` 补一个参考板入口。

**不做（进 Backlog）**

- `_find_record` 改 id 字典索引、多角度聚合下沉 service（当前 28ms，无实际影响）。
- 错误类型统一、`BASE_HAIR_NAME` 抽常量（重构收益低于风险）。

### 13.3 文件归属（二期）

| 文件 | 所有者 |
|---|---|
| `app/routers/system.py`（仅 status 返回）、`app/services/reference_library.py`、`app/routers/reference_library.py`、`tests/test_reference_library.py`、`frontend/openapi.json`、`frontend/src/api/openapi.d.ts` | A |
| `frontend/src/views/ReferenceView.vue`、`views/EditorView.vue`、`App.vue`、`api/reference.ts`、`api/sheet.ts` | B |
| `tests/test_reference_sheet.py`、`tests/test_reference_recipes.py`、`frontend/src/components/RefLightbox.spec.ts`、`frontend/src/views/ReferenceView.spec.ts`、`tools/smoke.py` | C |

### 13.4 验收（二期）

- [ ] 三个核心槽 + 第 4 槽都能"库条目 / 上传图"二选一，混源出图成功一次（如：上传自己的人像 + 图库服装 + 图库姿势）
- [ ] `REFERENCE_ENABLED=0` 时导航 10s 内消失；`REFERENCE_ALLOW_NSFW=0` 时 18+ 开关置灰且不再依赖条数推断
- [ ] 深度卡片走 `thumbs/depth`，一页 60 张传输 < 400KB
- [ ] `/reference/libraries` 与启动日志能看出各库条数；JSON 损坏时有 warning
- [ ] `test_reference_sheet.py` / `test_reference_recipes.py` / 2 个前端 spec 存在且绿
- [ ] `smoke.py` 覆盖详情 / 图片 / `recipes dry_run`
- [ ] `pytest -q` + `ci.ps1` 全绿；`git status` 干净
