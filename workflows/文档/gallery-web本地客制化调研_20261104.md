# gallery-web 本地客制化调研

> 调研日期：2026-11-04
> 范围：`脚本/atelier/gallery-web`（从开源项目 ai-pose-gallery-zh 复制接管、以 `/ref-web` 挂在 atelier 单端口下的 React 前端），以及它与 `脚本/atelier`（FastAPI + Vue3 本地画廊）的集成面。
> 定位前提（用户确认）：**本机单人自用、不商用、不需要任何云端出图 API**。
> 方法：5 路并行调研（源码静态审计 4 路 + Playwright 运行期实测 1 路）。报告中每条结论都标注了证据位置；「实测确认」与「静态推断」分开表述。

---

## 一、结论先行

| 序号 | 判断 | 一句话结论 |
|---|---|---|
| 1 | 云端出图并未「还在用」，而是「已裁掉、文案还在」 | 工作区副本 `ImageProviderId` 只剩 `comfyui`，生成链路全直连本机 ComfyUI；残留的是设置页的 API Key 字段、云端语义命名和外链文档。**当前 5173 端口跑的根本不是工作区副本**，而是 `custom_nodes/ai-pose-gallery-zh` 上游原版，所以还看得到 Google Gemini / OpenAI GPT Image。 |
| 2 | `/studio` 的「工作流推荐」是假的 | 它不是从 ComfyUI 拉取，而是前端写死的 4 条 Qwen 模板（`aiGenerator.ts:453-479`）。实测本机 ComfyUI 0.41.3 的 UNET 列表里 4 条模板依赖的模型**一条都不在**，首次点生成必被预检拦下。同时它完全不知道本机磁盘上已有的 11 个工作流。 |
| 3 | 「回不去画廊」是导航缺失，不是架构不可逆 | gallery-web 内部 0 个指向 `/gallery` 或 `/reference` 的链接；brand 的 `Link to="/"` 只回到 `/ref-web/`。浏览器后退要退 N+1 次，从 `/reference` 直达时 `location.replace` 只留 2 条历史，后退落到 `about:blank`。**加一个原生 `<a href="/gallery">` 就能解决 80%**。 |
| 4 | 真正的重复不是「功能多」，而是「第二套数据平面」 | gallery-web 不走 atelier 任何 `/api/*`：图库读静态 JSON，配方/历史/配置存 IndexedDB + localStorage（含 base64 图片、明文 apiKey），与 SQLite 无同步通道。同一张图、同一套元数据存在两份且互不联通。 |
| 5 | 合规文案可以砍，但三样东西不能砍 | 可砍：首页免责长条、guide 三段公网责任话术、18+ 每次弹窗。不可砍：上游代码的 **MIT 版权与许可声明**（当前目录内根本没有 LICENSE 文件）、素材作者 **ギア（@giaaibusi）** 署名、**CharaDB 图片禁止再分发**的约束。 |

---

## 二、调研基线与取证边界

### 2.1 两个端口不是同一个东西（重要）

| 端口 | 实际服务 | 判断依据 |
|---|---|---|
| `127.0.0.1:5173` | `custom_nodes/ai-pose-gallery-zh` **上游原版 dev server** | 进程命令行指向该目录；返回 HTML 含 `https://u.authbox.cn/script.js`；`/studio` 文案为「配置 API Key / Google Gemini / OpenAI GPT Image」 |
| `127.0.0.1:8656` | atelier 正式实例，`/ref-web/*` 提供**工作区改造后的 dist** | 返回 HTML 引用 `/ref-web/assets/index-CXo6LSMh.js`，与工作区 `dist/index.html` 一致；studio 文案已是「ComfyUI 设置 / 工作流模板 (API 格式)」 |

因此：**用户看到 5173 上的云端 API 与统计脚本，归因是上游原版，不是工作区副本**。工作区副本源码与 `dist` 内均无 `authbox`、无 gemini/openai/dashscope 字样、无统计脚本、无 CDN 字体。

### 2.2 工作区副本的硬性前提（易踩）

| 前提 | 证据 | 后果 |
|---|---|---|
| 必须用 `npm run build:prod` 构建 | `package.json:9` 才带 `--base=/ref-web/`；`vite.config.ts` 未设 `base` | 误用 `npm run build` 产出 `/assets/...`，挂在 `/ref-web` 下 JS 404，被 HTML 兜底后报 `Unexpected token '<'`，白屏 |
| atelier 必须部署在根路径 | `api/gallery.ts:81/92/105` 写死 `/data/*.json`；`recipeImages.ts:4-5` 补 `/{src}` | 一旦反代到 `/atelier` 子路径，参考图库整体断链 |
| `dist/` 是入库产物 | `UPSTREAM.md` 构建段 | 只改 `src` 不重建，线上看到的仍是旧外链与旧标题 |
| 5173 单跑没有数据 | `vite.config.ts:21-30` 从 gallery-web 根目录找 `data/thumbs/img`，这些目录不存在 | `pnpm dev` 单跑时 `/data/*`、`/thumbs/*`、`/img/*` 全 404，只能经 atelier 单端口访问 |

### 2.3 运行期实测结论（有数据）

| 项目 | 实测结果 |
|---|---|
| 页面可用性 | 8656 的 `/ref-web/`、`/ref-web/poses`、`/ref-web/studio`、`/ref-web/settings` 全部 200，console 0 错误 |
| 深链刷新 | 直接刷新 `/ref-web/poses` 正常渲染 360 张图，不白屏 |
| 外联 | 8656 构建产物**零外联**；5173 每页加载 1 次 `u.authbox.cn/script.js` 并触发 1 次 `/api/send` |
| 断网 | 拦截全部外部域名后，`/poses` 360 张图裂 0、`/costumes` 60 张图裂 0（图片全在本地 `/thumbs/`） |
| 返回入口 | 两个端口的所有页面均**无回 atelier 的可见入口**；唯一「返回合成台」只在设置页，且指向站内 `/studio` |
| 跳转环路 | `/reference` → 200 → 前端 replace 到 `/ref-web/`，`history.length=2`，后退落点 `about:blank` |
| 404 行为 | `/ref-web/not-exist-abc` 返回 200 + 空白内容区（无 404 提示）；`/ref-web/assets/not-exist.js` 返回 200 `text/html`（MIME 错配隐患） |

---

## 三、问题清单（按严重度分级）

### P0 阻断级（影响正常使用或存在法律缺口）

| 编号 | 问题 | 证据 | 建议 |
|---|---|---|---|
| P0-1 | 进入参考图库后无法回到画廊 | gallery-web 全仓无 `/gallery`、`/reference` 链接；`AppSidebar.tsx:31` brand 只回 `/ref-web/`；`router.ts:26` 硬编码 `location.replace('/ref-web/')` | 侧栏与顶栏各加一个原生 `<a href="/gallery">`；`router.ts` 改读后端 `reference_web_url` 或直接 `location.assign` |
| P0-2 | studio「推荐工作流」在本机 0 条可跑 | `aiGenerator.ts:453-479` 写死 4 条模板；实测 UNET 缺 `qwen_image_edit_2509_fp8_e4m3fn`、缺 2.1 bf16 主模型与编码器、缺动作编辑 LoRA；预检在 `aiGenerator.ts:1234-1243` 抛「工作流与本机不匹配」 | 下拉改为 `GET /api/workflows`（atelier 已扫出本机 11 个图片工作流），删除 4 条内置模板 |
| P0-3 | CharaDB 440 套服装全为外链，离线 100% 裂图，且会拖垮出图 | `costume-anime-zh.json` 440 项 × 4 字段 = 1760 个 `charadb-2fi.pages.dev` URL；`aiGenerator.ts:195-201`、`persistentImages.ts:6,26` 会真实 fetch 这些地址 | 本机私有缓存（目录必须 gitignore，**不得入库**）或后端只读代理缓存；同时收口 `referenceImageUrl` |
| P0-4 | 目录内没有 LICENSE，违反 MIT 的副本保留要求 | 上游为 MIT，`Copyright (c) 2026 Anhao`；当前只有 `UPSTREAM.md` 写了仓库地址 | 新增 `gallery-web/LICENSE`（MIT 全文 + 原版权行）与 `NOTICE`（上游仓库、pin commit、素材授权边界） |

### P1 明显影响体验或造成认知误导

| 编号 | 问题 | 证据 | 建议 |
|---|---|---|---|
| P1-1 | 设置页仍是「API 接口配置」语义，含 API Key 与假的「保存配置」 | `nav.ts:44`、`settings.tsx:22,126-143,148-153` | 改名「ComfyUI 连接」；删 Key 字段与保存按钮（配置本就 onChange 即写）；「重置」补清 `apiKey` |
| P1-2 | 双数据平面：配方/历史/上传全在浏览器 | IDB `pose_atlas_studio_db`（`idbStorage.ts:1-3`）；历史 ≤30 条 base64（`studioStore.tsx:458-476`）；apiKey 明文 `localStorage`（`:284`） | 图库改调 `/api/reference/items`；历史改 `/api/images`；上传改 `/api/reference/uploads`；apiKey 不入浏览器 |
| P1-3 | 首页统计自相矛盾，运营看板语义明显 | `index.tsx:53` 写死「11,568 本地高清图」，同页 `:41` 算出 4,785；`:71` 写死「51 款发型」 | 删除统计卡片或改动态值；删 Top10「热门」运营语义 |
| P1-4 | 合规文案堆在最高频页面，且带公网责任话术 | 首页 `index.tsx:192-209` 整段免责条 + X 外链；`guide.tsx:42-61` 三段「必读」 | 页面级免责移除；必要边界集中到 atelier「关于/素材来源」一屏，页面只留一行来源署名 |
| P1-5 | 18+ 每次解锁都强制弹窗确认 | `studioStore.tsx:635-668` | 改「首次确认一次，localStorage 记住」，文案压到 1 句 |
| P1-6 | 品牌与主题割裂，像跳进了另一个网站 | `index.html:6-11` 上游标题/author/keywords/application-name；`AppSidebar.tsx:32-37` 上游品牌；`ThemeProvider.tsx:5` 键名 `todaynew-admin:theme`、默认浅色，而 atelier 固定暗色（`tokens.css:82`） | 标题改「参考图库 · Atelier」，品牌改「画室 Atelier / 参考图库」，主题默认 `dark` 或直接去掉切换 |
| P1-7 | `ATELIER_REFERENCE_ENABLED=0` 时入口仍显示，点进去 API 全 404 | `App.vue:45-49` 只看 `reference_web_url`，不看 `reference_enabled`；`main.py:250` 挂载与开关无关 | 前端加开关判断，或后端关闭时把 `reference_web_url` 置空 |

### P2 打磨项（不影响功能，但影响观感与排障）

| 编号 | 问题 | 证据 | 建议 |
|---|---|---|---|
| P2-1 | 上游 GitHub 外链常驻侧栏 | `AppSidebar.tsx:88-98` | 删除（MIT 不要求在 UI 显示链接；署名落到 LICENSE/NOTICE） |
| P2-2 | `docs.comfy.org` 外链、`nav.ts:30` 的 `PRO` 徽标 | `aiGenerator.ts:33`、`nav.ts:30` | 删除 |
| P2-3 | 404 兜底过宽，静态资源缺失也返回 HTML | `main.py:229-241` | 仅对无扩展名请求（或 `Accept` 含 `text/html`）兜底 |
| P2-4 | 未配置 `notFoundComponent` | `__root.tsx` 全仓无 notFound | 加一个带「返回图库总览」的 404 页 |
| P2-5 | 页面多处硬编码数量与 emoji | `nav.ts:36-38`（1,439/1,847/1,499）、`index.tsx:82,103,124,194`、`poses.tsx:248` | 改动态值；去 emoji，按项目偏好改用彩色文字标签 |
| P2-6 | 路径拼接不统一，潜在非法 URL | `poses.tsx:331,386,415,472` 用 `/${path}`，而 `recipeImages.ts:7-27` 遇到 `data:`/`http(s):` 会原样返回 | 统一走 `referenceImageUrl` 或后端图片端点 |
| P2-7 | `package.json` 带了无引用的 `recharts` | `package.json:24` + `ui/chart.tsx` 无路由引用 | 删依赖时**必须同时删 `chart.tsx`**，否则 `tsc -b` 失败 |
| P2-8 | `vite.config.ts` 静态目录前缀校验可绕过 | `vite.config.ts:20-48` 用 `startsWith(rootDir)` | 改 `path.resolve` + `path.relative` 校验 |

---

## 四、专项结论

### 4.1 联网与合规残留

云端能力**已裁剪完成**（源码与 dist 双重核验）：无 gemini/openai/dashscope 等字样、无硬编码密钥、无统计/埋点、无 CDN、无 sourcemap。真正需要处理的只有四块：

1. 设置页的 API Key 语义与假保存（P1-1）；
2. `docs.comfy.org` 文档外链与 settings 云端措辞（P1-1/P2-2）；
3. `index.html` 上游品牌元数据（P1-6）；
4. CharaDB 外链图源（P0-3）。

**合规取舍的判断标准**（回应「本地不商用是不是可以全删」）：

- 「平台责任/维护者不担责/独立承担法律责任」这类话术，是给公网发布者用的，本地自用可以删；
- 「禁止真人换脸、禁止未成年人」这类**使用边界**建议保留一句，属于自我约束，成本极低；
- **著作权署名不能删**：姿势/现实服装/人像的著作权归 ギア（@giaaibusi），CharaDB 图片有独立许可且明确禁止再分发。署名与来源是最小保留形式；
- **代码许可证不能删**：MIT 要求副本保留版权与许可声明。UI 里的 GitHub 链接可以删，`LICENSE` 文件不能省。

### 4.2 studio 出图台

页面 1262 行，实际是「两栏 + 底部历史 + 三个弹窗」。逐块判断：

| 区域 | 建议 | 理由 |
|---|---|---|
| 三槽位（人像/服装/姿势）选择 | **保留并精简** | 这是页面唯一不可替代的价值；atelier 后端 `/api/reference/recipes` 已完整实现（`reference_library.py:285-342` + `recipe_prompt.py:55-140`），只缺前端入口 |
| 提示词预览/编辑/复制 | 保留，改为调后端拼词 | 后端已逐段移植上游 `buildRecipePrompt`，不需要前端再写一遍 |
| 生成结果区 | 保留并精简 | 进度交给 atelier 任务中心（SSE `/api/jobs/events`） |
| 工作流模板下拉（4 条写死） | **删除**，改 `/api/workflows` | 本机 0 条可跑，纯误导；atelier 已扫描出 11 个 |
| 工作流 JSON 导入/编辑/导出 | **删除** | 与 ComfyUI 原生导出、atelier 工作流管理重复 |
| 4 个节点映射下拉、拼图节点、超时/随机种子 | **删除** | recipes 的节点与参数由后端固定，不需要前端映射 |
| 前端 canvas 参考拼图 | **删除**，改 `/api/reference/sheet` | atelier 输出 1800×1200，比前端 480×640 强 |
| IndexedDB 生成历史（≤30 条） | **删除**，改 `/api/images` | 与画廊重复且更弱；删除前先做一次导出，避免 30 条记录丢失 |
| 未决任务恢复 | **删除** | atelier 有 gen_jobs + 幂等 + 重试 |
| 12 条画风中 10 条 | 删除，只留 none/realistic | 后端原本就只留这两条，其余增加提示词噪声 |
| 检测本机模型 | **保留**，收敛为后端一个端点 | 这是 studio 唯一明显强于 atelier 的能力（atelier 只有格式校验） |
| 通用参数面板 | 暂时**保留原样** | atelier 没有等价能力，但它是纯前端第二套参数真相；若后续收回 Vue，再决定是否下沉 |
| 安全模式 + 18+ 解锁 | **保留，不能随 studio 删** | 它是全站壳层状态，三库页面依赖它做过滤 |

**最小落地路径**：先把工作流下拉换成 `/api/workflows`（低风险、可立即验证 11 个工作流）；再把提交改为 `POST /api/reference/recipes`；最后逐步删除模板/编辑器/拼图/IDB 历史。

一个改造时必须注意的坑：gallery-web 的服装合并了 `costume-zh` 与 `costume-anime-zh` 两个库，而 atelier 的 `costume_id` 固定解析 `costume` 库（`reference_library.py:229-237`）。anime 条目直接传 id 会 404，需要给 recipes 增加 `costume_library` 字段，或先把 anime 上传成路径。

### 4.3 单向跳转

**根因不是 `replace`**，而是三件事叠加：

1. gallery-web 是独立 React 文档，整页接管 URL，不共享 atelier 外壳（顶栏、ComfyUI 状态、任务角标全部消失）；
2. 内部 0 个返回入口，brand 的 `Link to="/"` 只能回 `/ref-web/` 总览，容易被误认为「返回」；
3. 内部导航全部 `pushState`，后退要退 N+1 次；从 `/reference` 直达时 `replace` 抹掉唯一来源条目，后退落到 `about:blank`。

**方案对比**：

| 方案 | 改动 | 工作量 | 风险 | 结论 |
|---|---|---|---|---|
| 一：加返回入口 | `AppSidebar.tsx`、`AppHeader.tsx`、新增 `lib/atelierLinks.ts` | 小（约 0.5 小时 + 构建 + 回归） | 低 | **立即执行** |
| 二：回退 Vue `ReferenceView.vue` | 恢复 1795 + 708 + 96 行三个已删文件，改 router/App.vue，重建 `web/` | 中（1 小时恢复 + 2-4 小时回归） | 中高，会丢失 studio/配方槽/三大库筛选/440 套服装 | **不推荐**。用户抱怨的是「回不去」，不是「功能太多」 |
| 三：统一外壳（轻量） | 品牌/标题/主题/字体对齐 | 中（4-6 小时） | 中 | 第二阶段执行 |
| 三：统一外壳（iframe） | 新增 `ReferenceFrameView.vue` | 中（3-6 小时） | 中高，顶层 URL 固定、深链不可分享、history 污染 | 不推荐 |

**实现要点（容易踩）**：

- 必须用原生 `<a href="/gallery">` 或 `location.assign`，**不能用 TanStack `Link`**（会被 basepath 拼成 `/ref-web/gallery` → 404 → HTML 兜底）；
- 不要用 `replace` 回画廊，否则「返回」后无法再前进到参考图库，仍是一刀切；
- `<a>` 还支持中键新标签，符合本地使用习惯。

### 4.4 页面内容与数据层

**页面级处置**：

| 路由 | 判定 | 删除前须知 |
|---|---|---|
| `/` | 精简保留 | 删统计卡片、Top10、免责条、X 外链；保留三库入口与配方摘要 |
| `/poses` | 保留 | 核心功能，atelier Vue 端暂无等价浏览 UI；小修硬编码与 emoji |
| `/costumes` | 保留 + 精简 | 来源/合规文案移 about；「前往来源原图」保留（这是不本地分发 CharaDB 原图的合规做法） |
| `/portraits` | 保留 + 精简 | 去 Top10 角标与 51 硬编码；保留 CC0 一行 |
| `/settings` | 合并或删除 | 影响 `nav.ts:44`、`studio.tsx:372`、`RecipeDock.tsx:21`、`settings.tsx:70` |
| `/guide` | 删除或合并 | 影响 `nav.ts:45`、`index.tsx:206`、`RecipeDock.tsx:21`；来源与许可并入 atelier「关于」 |
| `/studio` | 见 4.2 | 它依赖三库 query 与 `RecipeState`，不能单独删共用的 `lib/recipeImages.ts`、`types/gallery.ts` |

**数据层收敛（按优先级）**：

- **P0**：`api/gallery.ts` 三个 `queryFn` 改调 `/api/reference/items?library=...`；图片 URL 改用后端图片端点；18+ 策略只保留一处（前端硬编码名单 `api/gallery.ts:13-14` 与后端 `ATELIER_REFERENCE_*` 会漂移）。
  > 前置决策：后端默认 `reference_allow_nsfw=False`（`config.py:96`），不改配置就切 API，前端「解锁 18+」会失效。
- **P1**：历史改 `/api/images`；上传改 `/api/reference/uploads`；删除 IDB 里的 base64 配方副本；配置由后端 `/api/system/status` 下发；删历史前先提供一次性导出。
- **P2**：清空 `settings`/`guide`/首页运营内容；三库 UI 长期二选一（迁进 Vue 或只留只读浏览层）。

### 4.5 运行期实测的额外发现

- 8656 构建产物**零外联**，断网时三库页面裂图 0（说明「必须联网才能用」是上游原版/CharaDB 造成的错觉）。
- 深链刷新正常，但缺失静态资源被 HTML 兜底（P2-3）。
- 未验证项（需后续补）：未点击生成按钮、未进灯箱、未验证 Firefox/WebKit、未验证工作区副本自身 dev 模式的外联。

---

## 五、分阶段路线图

### 阶段一：先让「能用、能回去」（约 0.5-1 天）

1. 加返回画廊入口（侧栏 + 顶栏，原生 `<a>`）。
2. `router.ts` 去掉硬编码 `/ref-web/`，读后端配置。
3. studio 工作流下拉改 `/api/workflows`，删 4 条写死模板。
4. 补 `LICENSE` + `NOTICE`。
5. `npm run build:prod` 重建 dist，重启 atelier 验证。

验收：从 `/gallery` 进参考图库，任意页面点返回能回画廊，后退能回参考图库；studio 下拉能看到本机 11 个工作流且不再报「不匹配」。

### 阶段二：去掉误导与噪声（约 1-2 天）

1. 设置页改「ComfyUI 连接」，删 API Key 字段、假保存按钮，修重置漏清 Key。
2. `index.html` 与侧栏品牌对齐 atelier；主题默认暗色。
3. 首页删统计卡片/Top10/免责长条；guide 压缩合并到「关于/素材来源」。
4. 18+ 改首次确认一次。
5. 18+ 策略与入口开关（P1-7）修正；404 兜底收敛。

验收：页面不再出现「11,568」矛盾数字、不再出现云端 API 措辞、不再有上游品牌与外链。

### 阶段三：数据层收敛（约 3-5 天，可分多次）

1. 图库改调 `/api/reference/items`（含分页与 NSFW 策略决策）。
2. 历史/上传/配置改走 atelier；删 IDB base64（先导出）。
3. CharaDB 440 套本地化或代理缓存。
4. studio 三槽位提交改 `POST /api/reference/recipes`。

验收：清空浏览器存储后图库/历史/上传仍可用；同一张图不再同时存在于 SQLite 与 IndexedDB；断网后二次元服装不裂图或明确标注「需联网」。

---

## 六、待决策项（需要用户拍板）

| 编号 | 决策 | 选项 |
|---|---|---|
| D1 | 二次元 440 套服装怎么处理 | A. 本机私有缓存（不入库，可离线）；B. 后端只读代理（首次联网后缓存）；C. 保留外链并明确标「需联网」 |
| D2 | 18+ 总闸默认值 | A. 本机默认允许，前端只做展示过滤；B. 仅 loopback 允许；C. 维持默认关闭（前端解锁会失效） |
| D3 | React 台长期去向 | A. 保留，只做 `/ref-web` 只读浏览层 + 配方薄 UI；B. 逐步迁进 Vue，最终删 React 台 |
| D4 | 通用参数面板是否保留 | A. 保留原样（继续维护 React）；B. 下沉到 Python 后端；C. 暂时放弃 |
| D5 | IDB 里已有的 30 条生成历史 | A. 先导出再删；B. 直接删（不可恢复） |

---

## 七、证据索引

| 主题 | 关键文件:行号 |
|---|---|
| 跳转入口 | `frontend/src/router.ts:22-35`、`App.vue:45-49,83-89`、`gallery-web/src/components/layout/AppSidebar.tsx:25-43,88-98`、`nav.ts:25-48` |
| 静态挂载与兜底 | `app/main.py:222-262`、`:229-241`、`:250-254` |
| 工作流推荐 | `gallery-web/src/services/aiGenerator.ts:41-90,453-479,1234-1243`、`routes/studio.tsx:725-746` |
| recipes 后端 | `app/routers/reference_library.py:166-190,229-237,285-342`、`app/services/recipe_prompt.py:55-140` |
| 存储 | `gallery-web/src/lib/idbStorage.ts:1-3,35-59`、`store/studioStore.tsx:45-50,270-292,458-476`、`lib/persistentImages.ts:6,17-27` |
| 图库数据源 | `gallery-web/src/api/gallery.ts:13-14,77-108`、`app/main.py:256-264` |
| 合规与品牌 | `gallery-web/index.html:6-11`、`routes/index.tsx:192-209`、`routes/guide.tsx:42-80`、`package.json:2,9,24` |
| 实测产物 | `脚本/atelier/.screenshots/probe-5173-poses.png`、`probe-8656-deeplink-poses.png`、`probe-8656-reference-landing.png`、`probe-offline-5173-poses.png` |

> 说明：本文第一节至第七节为调研与方案结论。阶段一已于 2026-11-04 实施并通过实测，进展见第八节。

---

## 八、决策结果与阶段一进展（2026-11-04 追加）

### 8.1 五项决策已拍板

| 决策 | 结果 |
|---|---|
| D1 二次元 440 套 | A：本机私有缓存（不入库、gitignore），缺失时后端代理兜底 |
| D2 18+ 总闸 | A：维持现状（启动脚本已注入允许），仅在需要局域网访问时加 loopback 加固 |
| D3 React 台去向 | A：保留，作为 `/ref-web` 只读浏览层 + 配方薄 UI；同一功能半年内被迫改两次再触发迁回 Vue |
| D4 通用参数面板 | A：保留原样、冻结不投入 |
| D5 IDB 30 条历史 | A：先导出再删 |

### 8.2 阶段一已完成项（均经真实浏览器实测）

| 项 | 结果 |
|---|---|
| 返回画廊入口 | 侧栏 brand、侧栏菜单、顶栏共 3 个原生 `<a href="/gallery">`；无 `/ref-web/gallery` 污染链接；点击后正确落到 atelier `/gallery` |
| `/reference` 跳转 | 改为读 `/api/system/status` 的 `reference_web_url`（尾斜杠归一化、4s 超时、失败回落），并使用 `location.replace`；后退直接回 `/gallery`，5.6 秒后仍停留，回弹已消除 |
| studio 工作流列表 | 下拉 12 项（本机 11 个工作流 + 自定义兜底），无「· 推荐」；首次自动选中后端 `default`（MoodyKrea2 文生图），加载无 console 错误 |
| 后端内容端点 | 新增 `GET /api/workflows/content?path=`；路径必须 resolve 在 `search_dirs()` 内且为 `.json`，越界返回 404，空参 400 |
| 许可 | 新增 `LICENSE`（与上游逐字节一致）与 `NOTICE`（含 ギア 署名、CC0、CharaDB 禁止再分发三条边界）；`UPSTREAM.md` 增补许可节 |
| 产物 | `gallery-web/dist` 与 Vue `web/` 已重建，资源前缀 `/ref-web/assets/`；运行中实例按请求读盘，无需重启 |

### 8.3 仍未实施（阶段二 / 阶段三）

- 阶段二：设置页「ComfyUI 连接」语义与 API Key 字段、`index.html` 与侧栏品牌、首页统计/Top10/免责条、guide 合并、18+ 首次确认、入口开关判断、404 兜底收敛。
- 阶段三：图库改调 `/api/reference/items`、历史/上传/配置改走 atelier、CharaDB 本地化、IDB 历史导出、studio 三槽位提交改 `POST /api/reference/recipes`。

### 8.4 已知项（不阻塞）

- gallery-web dev 模式（5173）的 `vite.config.ts` 未代理 `/api`，studio 下拉在 dev 下会提示读取失败；生产 `/ref-web` 与 `/api` 同源不受影响。
- `frontend/web/assets/` 仍有 3 个旧 hash 文件（`emptyOutDir` 未生效），`index.html` 只引用新 hash，运行不受影响。
- `src/workflows/qwen_image_edit_2509_3img.api.json` 已无引用（上游残留资源，未删）。
---

## 九、阶段三进展

> 追加说明：本阶段按四批实施、每批独立验收，提交链为 `71b171c`（阶段一）→ `0d61018`（阶段二）→ `95f52a4`（阶段三）→ `38b81dd`（阶段四）；另有 `159e329` 单独记录并行会话的双人姿势提示词改动，未混入上述四批。下文每条结论均标注「实测确认」或「未能验证」，未执行的检查不计为通过。

### 8.1 阶段一：IDB 历史导出与历史数据源迁移（T1/T2/T3，commit 71b171c）

**改动文件**

| 文件 | 改动 |
|---|---|
| `gallery-web/src/lib/legacyHistoryExport.ts`（新增） | 只读 IDB `pose_atlas_history_v3`，导出 JSON 与逐张 PNG；每张间隔 150ms；不删除原数据；无数据返回 0 且不触发下载 |
| `gallery-web/src/routes/settings.tsx` | 设置页新增「旧生成记录导出」按钮；无数据时 `disabled` 并显示「未发现旧生成记录」 |
| `gallery-web/src/api/history.ts`（新增） | 调 `GET /api/images?page=1&page_size=30&sort=newest` 并把后端字段映射为前端记录结构 |
| `gallery-web/src/store/studioStore.tsx`、`gallery-web/src/routes/studio.tsx` | 历史区改只读展示（标注「来自 atelier 画廊的历史」），删除本地清空与单条删除；`completeGeneration` 不再写 base64 历史；保留既有导入导出工具供用户手动导出旧数据 |

**验收结果（T3 PASS，133 项硬检查 / 0 失败）**

| 检查项 | 结果 | 结论 |
|---|---|---|
| `pnpm exec tsc -b --noEmit`、`pnpm exec oxlint src`、Vue `pnpm run typecheck`、`python -c "import app.main"` | 全部退出码 0 | 实测确认 |
| 六路由访问 | 均返回 200 | 实测确认 |
| 返回画廊入口 | 3 个 | 实测确认 |
| 18+ 首次确认 | 只弹一次 | 实测确认 |
| studio 工作流下拉 | 选中后端 `default` | 实测确认 |
| 四库页面正常/断网 | 裂图 0 | 实测确认 |
| 旧记录导出实测 | 产出 JSON 与 PNG，且 IDB 原数据保留 | 实测确认 |
| 历史区数据源 | 30 条来自 `/api/images` | 实测确认 |

**遗留与未能验证**

- 未能验证：真实非 headless 浏览器对多文件连续下载的拦截策略与 headless 验收环境是否存在差异。
- 未能验证：运行中实例 8656 是否即时加载重建后的 `dist`。

### 8.2 阶段二：CharaDB 440 套本地缓存（T4/T5/T6/T7，commit 0d61018）

**改动文件**

| 文件 | 改动 |
|---|---|
| `app/services/reference_remote_cache.py`（新增） | 白名单 host、仅允许 `http(s)`、缓存键安全段名、命中免请求、`asyncio` 并发去重、原子写、`Content-Type` 校验、20MB 上限、重试、限速、`warm_many` 统计；模块头注明「仅本机参考、禁止再分发」 |
| `app/config.py` | 新增 `reference_cache_dir`（默认 `atelier/.cache/reference-remote`）、`reference_remote_hosts` 等 6 项配置；启动时校验缓存目录不与 `reference_root`、`data`、`dist` 互相包含 |
| `app/services/reference_library.py`、`app/routers/reference_library.py` | `costume-anime` DTO 图片 URL 改为后端端点；DTO 新增 `number`/`source_url`/`search_text`；图片端点缓存优先、未命中代理下载后原子写、失败返回 502；`depth` 仍 404 |
| `tools/warm_reference_cache.py`（新增） | 高并发预热，支持 `limit`/`concurrency`/`rate`/`retry`/`kinds`、断点续跑、统计与失败退出码；脚本头带许可注释 |
| `app/routers/reference_library.py`（recipes 段） | `RecipeRequest.costume_library`（`costume`/`costume-anime`，默认 `costume`）；外链服装缓存就绪即可出图，失败 502；第 4 张仍走节点 78 |
| 根 `.gitignore` | 新增 `workflows/脚本/atelier/.cache/` |

**验收结果（T7 PASS）**

| 检查项 | 结果 | 结论 |
|---|---|---|
| pytest | 52 项全绿（33 library + 18 recipes + 1 openapi） | 实测确认 |
| 预热抽样与重复执行 | 首次下载、再次命中缓存并跳过 | 实测确认 |
| 图片端点缓存命中/未命中 | 已缓存 200；未缓存经死代理返回 502（等价断网） | 实测确认 |
| recipes `dry_run` | 三图节点 1/2/3；四图节点 1/2/3/78 | 实测确认 |
| 缓存目录入库状态 | 被根 `.gitignore` 命中 | 实测确认 |
| E2E | 226 项通过 | 实测确认 |
| 全量预热（T10 期间执行） | `total=880 / cached=27 / downloaded=853 / failed=0 / 965.86s`；440 条目 × 2 个有效图片字段共 880 个文件全部落盘 | 实测确认 |

**遗留与未能验证**

- 未能验证：真实物理断网与防火墙断网场景，验收以指向不可达代理的方式等价模拟。
- 未能验证：上游缺图时的回退路径，仅有 fixture 样本，无真实缺图条目可复现。
- 说明：全量预热 `total=880` 对应 440 套 × 2 个有效图片字段；`depth`/`depth_thumb` 对 `costume-anime` 无意义，由路由层按既定语义返回 404。

### 8.3 阶段三：图库数据层切后端（T8/T9/T10 → T16 修复 → T17 复验，commit 95f52a4）

**改动文件**

| 文件 | 改动 |
|---|---|
| `gallery-web/src/lib/referenceAdapter.ts`（新增） | 并行分页拉全量（`page_size=200`、最多 6 并发、按 `id` 去重、任一页失败整体 reject、`total` 增长补拉、200 页上限）；DTO 映射为页面既有中文结构；NSFW 聚合函数 |
| `gallery-web/src/api/gallery.ts` | 三个 queryFn 改调 `/api/reference/items`；服装并行拉 `costume` 与 `costume-anime`（现实在前）；删除 `NSFW_POSE_SYSTEMS`/`NSFW_COSTUME_CATEGORIES` 与 `isNsfwPoseSystem`/`isNsfwCostumeCategory`；`isNsfwPose`/`isNsfwCostume` 改为读 `nsfw` 字段 |
| `gallery-web/src/types/gallery.ts` | 补充 `library`/`nsfw`/`depthUrl`/`depthThumbUrl`/`sourceUrl` 等可选字段 |
| `gallery-web/src/lib/recipeImages.ts` | 深度图优先使用后端 `depthThumbUrl`/`depthUrl` |
| `gallery-web/src/routes/poses.tsx`、`costumes.tsx`、`portraits.tsx` | 18+ 药丸改由数据聚合；图片统一走 `referenceImageUrl`/`poseThumbPath`/`poseImagePath`；搜索、分组、加载更多行为不变 |
| `gallery-web/src/routes/index.tsx` | T16 修复首页两处 `/${缩略图}` 拼接，改走 `referenceImageUrl(...)`（原 `//api` 协议相对地址导致 8 张裂图与 `ERR_NAME_NOT_RESOLVED`） |

**验收结果**

| 检查项 | 结果 | 结论 |
|---|---|---|
| T10 首轮 | FAIL 327/343，唯一根因为首页两处图片拼接 | 实测确认 |
| T17 复验 | PASS 343/343、0 失败 | 实测确认 |
| 六路由 | 200，console 错误 0 | 实测确认 |
| 首页正常/断网 | 12 张图裂图 0、外部请求 0 | 实测确认 |
| poses/costumes/portraits | 正常与断网均裂图 0 | 实测确认 |
| 二次元断网 | 60 张裂图 0；页面请求的 60 条图片全部命中所列 440/440 缓存集合 | 实测确认 |
| 深度模式 | 360 张图走后端端点 | 实测确认 |
| 18+ 药丸 | 聚合显示、安全模式隐藏与解锁均正常 | 实测确认 |
| 交互回归 | P001 搜索、体系切换、加载更多 60→120；服装分类/标签（剩余 155→5）、二次元 CharaDB、加载更多；人像分区/发长 | 实测确认 |
| studio 工作流下拉 | 仍选中后端 `default` | 实测确认 |

**遗留与未能验证**

- 未能验证：断网由 Playwright 浏览器层阻断请求实现，不是服务端真实断网。
- 未能验证：未逐张渲染全部 440 套素材，仅覆盖抽样的 60 条请求集合。
- 未能验证：仅在 Chromium 下执行，未覆盖其他浏览器内核。
- 未能验证：运行中实例 8656 是否加载重建后的 `dist`。

### 8.4 阶段四：studio 三槽位提交后端（T11/T12/T13，commit 38b81dd）

**改动文件**

| 文件 | 改动 |
|---|---|
| `gallery-web/src/services/recipeClient.ts`（新增） | 只 `POST /api/reference/recipes`；`pollJob` 间隔 1.5s、上限 30min、处理终态与 `AbortError`、连续 3 次失败才抛错；`jobResultUrls` 生成 `/api/media/image` 地址；导出 `GenerationProgress`/`ActiveJobInfo` |
| `gallery-web/src/store/studioStore.tsx` | `startGeneration` 组装槽位（含 `costume_library`）、执行第 4 张规则、拦截上传槽、串联提交→轮询→结果图/失败；`activeTask` 改为 `ActiveJobInfo`，旧 `{task:{promptId}}` 结构安全迁移为 null |
| `gallery-web/src/services/aiGenerator.ts` | 删除 631 行直连 ComfyUI 提交链路，保留连接检测、工作流解析、提示词与拼图能力 |
| `gallery-web/src/routes/studio.tsx` | 进度条与 `percent`、结果图、错误重试、原生 `<a href="/jobs">` 任务中心、参数面板 D4 冻结说明、提示词只读加独立「补充要求」、画风收敛为 `none`/`realistic`、移除提交前组合校验、上传槽提示 |

**验收结果（T13 PASS，434 项硬检查 / 0 失败）**

| 检查项 | 结果 | 结论 |
|---|---|---|
| 真实提交 | 生成 job 197（`costume-anime` / `charadb-O001`） | 实测确认 |
| 请求体 | 含三槽位 id、`costume_library`、`style`，不含完整 prompt | 实测确认 |
| 进度展示 | UI 显示进度 | 实测确认 |
| 真实出图 | 5 分钟内完成；结果图 `naturalWidth>0`，URL 走 `/api/media/image` | 实测确认 |
| 直连残留 | 无 `/prompt`、`:8188`、`/comfy` 提交请求 | 实测确认 |
| 失败分支 | 后端 400 的 `detail` 正确显示并可重试 | 实测确认 |
| `dry_run` 节点映射 | TestClient 三图 1/2/3、四图 1/2/3/78 | 实测确认 |
| 任务中心 | `/jobs` 返回 200 | 实测确认 |
| 8656 操作纪律 | 验收前后 GET 均 200，未重启、未 kill | 实测确认 |

**遗留与未能验证**

- 未能验证：服务端未缓存 anime 条目的首次下载与断网 502 分支，因全量缓存已覆盖、测试中未命中该分支。
- 未能验证：刷新页面后恢复轮询、停止跟踪任务未列入 T13 必测清单，未执行。
- 未能验证：仅在 Chromium 下执行。

### 8.5 全局运行状态与遗留

| 项 | 状态 |
|---|---|
| 运行中实例 8656 | 实测确认：仍运行旧后端代码，未重启；前后 GET 均 200 |
| 后端改动的线上生效条件 | 实测确认：`costume_library`、远程缓存/代理、recipes 放行均需重启 8656 才对线上实例生效；按纪律未操作 8656 |
| 前端产物 | 实测确认：`gallery-web/dist` 已重建并随各提交入库；未能验证 8656 是否已按请求读到新 `dist` |
| 缓存目录 | 实测确认：`workflows/脚本/atelier/.cache/reference-remote` 已被根 `.gitignore` 命中，不入库、不进 `dist` |
| 素材许可边界 | 实测确认（代码注释与文档约定）：CharaDB 素材仅本机参考、禁止再分发 |
| 提交链 | 实测确认：`71b171c` → `0d61018` → `95f52a4` → `38b81dd`；另有 `159e329` 单独记录并行会话的双人姿势提示词改动，范围与本阶段四批隔离 |

遗留事项：真实物理断网、非 headless 多文件下载拦截、非 Chromium 内核、8656 加载新 `dist` 四项未验证，需在后续验收中补齐；后端改动在 8656 重启前不会对线上实例生效。