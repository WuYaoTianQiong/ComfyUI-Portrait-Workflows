# Atelier UI unslop 体检（2026-11-14，只读审计）

> 方法：[heydamir/unslop](https://github.com/heydamir/unslop)（CC BY 4.0，作者 Damir Sokolovsky）的 audit → direction → passes 流程。本轮**只执行 audit 与 direction，未改任何代码**。
> 范围：生产 8656（`web/` 构建产物），9 路由 × 明暗 = 18 页，1440×900。
> 证据：截图 18 张 + 探针脚本 + JSON 在 `F:\ComfyUI_Migration\_docs-assets-archive\atelier-unslop-20261114\`（不入 git，遵守文档治理规则 3）。
> 关联决策：`Atelier_当前状态与待办_20261112.md` §2.3（不重写 UI / 保留 7 Tab / 暗色默认）；归档 `atelier_UI卖相提升计划_20261104.md`（令牌收口已大部分落地，本文是其执行度复核）。

---

## 0. 一句话结论

**light slop → polish mode**：骨架已是设计过的高密度工作台（令牌、双主题对比度、功能性动效、扁平 logo 都在位），剩余问题集中在四簇：**emoji 当图标、`.btn` transition 简写、暗色主色对比度略低于 4.5、10px 小字**。只修审计发现的项，不动布局 / 信息架构 / 主题 / 密度。

## 1. 实测基线（18/18 页，探针可复跑）

| 项 | 实测 |
|---|---|
| console 错误 / 横向溢出 | 0 / 0（全部 18 页） |
| 渲染渐变 / 大写宽字距标签 / 斜体 / 负字距 | 0 / 0 / 0 / 0 |
| 字重 | 400×2648、600×153、500×13、700×12 |
| 字体族 | system-ui 单族（+1 处 monospace 数字） |
| 字号 | 11px×2163（76.5%）、12px×601、16px×20、10px×19、14px×16、20px×7 |
| 圆角 | 6/4/10/999/50% 为主；离群 9999×7、20×4、14×3、8×2（全在参考库首页） |
| 静息动效 | 0（spinner / skeleton shimmer / toast-in 仅加载时出现，带 reduced-motion 回退） |
| 顶栏 / 页签 | 52px；9 个页签高度统一 27px；active = 主色 soft 底 + 主色字 |
| 对比度（暗） | text/bg 16.02、muted/panel 5.62、text-muted/surface-raised 6.94；**on-primary/primary 4.47、primary/bg 4.24、text-faint/surface-raised 3.78（三项 <4.5）** |
| 对比度（浅） | 全部 ≥8.38 |
| 硬编码 hex | grep 11 处：8 处分类色板数据、2 处 `var()` 回退、其余注释（2026-11-04 计划时为 55 处） |
| `transition: all`（时长>0 实测） | 每页 10–40 个，全部是 `.btn`（见 §2-B） |

## 2. 问题清单（sign → 位置 → 修法）

### A. 图标：彩色 emoji 当按钮/标签图标【P1，最大簇】

主页面可见彩色 emoji 13 处；含弹窗 / 灯箱 / 遮罩编辑器约 40 处模板落点：

| 落点 | 位置 |
|---|---|
| 🚀 主行动按钮（出图/试跑/开始编辑/开始超分） | `PromptDetailPane.vue:304`、`ComposerControlBar.vue:145`、`ComposerResultCenterModal.vue:245`、`EditorView.vue:712`、`UpscaleView.vue:215` |
| 🧪 试跑 / 🎲 随机 / 🧩 编译 / 📚 模板 / 🚫 负面 | `PromptView.vue:1092,1179`、`ComposerControlBar.vue:115,124,127,130,137`、`PromptTrialPanel.vue:384` |
| 📁 磁盘 / 🧹 清理失效 / ☰ 筛选 | `EditorView.vue:501`、`UpscaleView.vue:140`、`FilePicker.vue:265`、`GalleryView.vue:872,939` |
| 🔒/🔓 组合器 8 列列头锁 | `ComposerReel.vue:84` |
| 📱/🖥️ 横竖 / 📌 置顶 / 💾 存为提示词 / 📂 定位 | `WorkflowParams.vue:151`、`PromptListRow.vue:34`、`PromptDetailPane.vue:338`、`PromptMatrixStack.vue:97`、`PromptMatrixBoard.vue:230` |
| 灯箱工具 ⚡⬇🗂🔄🗑📋 | `Lightbox.vue:1114-1267` |
| 遮罩编辑器 🖌🧽🪄✋ | `MaskEditorModal.vue:612-621` |
| 👁/🚫 工作流显隐 | `TaxonomyView.vue:404` |

修法：统一一套线性图标（16px / 1.5 stroke / 随文字角色色）。**先例已在库内**：`ComposerReel.vue:91-94` 手绘 SVG 定位十字；`Lightbox.spec.ts:198-202` 已断言部分模式工具栏不含 ⚡🔄☆🗑——图标去 emoji 有既有测试模式可扩展。单色文字符号 ✓✕★☆♥✎☰ 属排版符号，保留。

### B. 动效【P2】

| sign | 位置 | 修法 |
|---|---|---|
| `.btn { transition: 0.12s }` 简写 = 全属性过渡（实测每页 10–40 个按钮） | `styles/tokens.css:411` | 点名 `color, background-color, border-color` |
| 卡片 hover 缩放/抬升 | `GalleryGrid.vue:171` scale(1.02)；`ReferenceCard.vue:168,202` translateY(-2px)/scale(1.05) | 改边框/表面阶跃；参考库皮肤按「各自内部一致」另评 |

### C. 对比度与小字【P2】

| sign | 实测 | 修法 |
|---|---|---|
| 暗色 `--primary` #6366f1：白字 4.47、作文字 4.24 | <4.5 | 暗色主色加深一档（浅色 #3730a3 已 9.93，不动） |
| `--text-faint` #737373 on #171717 | 3.78 | 提亮一档或限定纯装饰用途 |
| 10px 小字：job-badge、提示词页 4 个 ✕ 小按钮、参考库 home-slot__label | 19 处 | 提到自有令牌下限 `--fs-xs: 11px` |

### D. 一致性观察项【P3，拍板后再动】

- 圆角方言：参考库首页 20px 卡 / 9999px 药丸 vs 全局 6/10/14/999（`ReferenceHomeTab.vue`）。「两套皮肤各自内部一致」是已接受现状；最小动作是 9999→999 统一药丸令牌。
- font-weight 700 ×5：`App.vue:259`（logo）、`GalleryGrid.vue:192`、`Lightbox.vue:2208`、`ReferenceCard.vue:229`、`ReferenceStudioTab.vue:3311`。
- 提示词详情右栏未设参数时 6 个「-」空盒（`PromptDetailPane.vue` 参数区）：诚实但视觉重，可选收成一行的安静文案。

### E. 排除项（量到了但不是问题）

- 纯红 `rgb(255,0,0)` 圆点 = **用户自定义分类色**（`TaxonomyView.vue:336` `:style="{ background: cat.color }"`，数据非代码）。
- 任务页 61 个实心绿点 = 完成状态语义色，合理。
- 42 处「彩色阴影」= 中性缩略图边框环 + 主色选中左条（合法 accent 用法，非 glow）。
- 唯一渐变 = Skeleton 中性 shimmer（合法）。

## 3. Direction（unslop 五行，从产品推导；开工时参照）

- **Product**：单人本地人像出货工作台——管理提示词与参考图、批量提交 ComfyUI、看图画图比图。
- **Character**：密集、精确、安静。
- **World**：暗房与画廊——中性深灰底，生成图是唯一的丰富色彩。
- **Moments**：画廊图墙 / 灯箱里的成图、横评矩阵的对比格。
- **Signature**：能力徽标（「负向不生效」等诚实标注）——把「诚实标注模型能力」做成贯穿细节。
- **Accent 色相是方向级选择**：#6366f1 扁平统一（不是 slop 渐变），但属最常见 AI 默认紫。保留（当品牌色）或从暗房世界推导（暖琥珀 / 银盐灰蓝）——**用户拍板**，审计不擅自改。

## 4. 建议批次（全部 polish，不改行为）

| 批 | 内容 | 预估 | 验收 |
|---|---|---|---|
| 1 | emoji → 线性图标集（约 40 处 + 弹层），保留文字符号 | 0.5–1 天 | 复跑探针 emoji 盘点彩色=0；vitest（Lightbox.spec 先例）+ vue-tsc 绿 |
| 2 | `.btn` transition 点名 + 画廊 hover scale 去除 + 10px→11px | 0.5 天 | 探针 realTransitionAll=0；改前后截图对比 |
| 3 | 暗色 primary / text-faint 对比度 ≥4.5 | 0.2 天 | 探针对比度表全 ≥4.5；浅色主题数值不变 |
| 4 | 护色共规 / 圆角字阶方言收敛 / style_lint 守护；accent 色相保留、空参数盒撤回收敛 | 已交付 `c30b5f0` | 见 §6 裁决与更正 |

明确不做：布局 / 信息架构 / 7 Tab / 主题 / 密度 / 框架（已拍板，见状态文档 §2.3）。

**开工前置（2026-11-14 用户拍板）**：批次 1 与并行会话未提交改动重叠 5 个文件——`Lightbox.vue`、`PromptDetailPane.vue`、`PromptTrialPanel.vue`（含 spec）、`WorkflowParams.vue`、`PromptView.vue`，且 `web/` 构建产物处于该批半更新态。**等该批提交后再开工**（沿用 2026-11-12 对 A15 的同文件不并行决定）；开工时不重建 `web/` 混入对方 bundle，vitest 先跑基线区分对方既有失败。无重叠的 14 个目标文件清单见 §2-A。
**前置已满足**：并行批于 2026-11-14 收尾提交（`f258ef4f`），批次 1–3 同日交付，见 §6。

## 5. 复现方法

证据目录内 `unslop_probe.py`（18 页截图 + 计算样式盘点 → `unslop_report.json`）、`unslop_followup.py`（transition 时长过滤复测 + 色点定位 → `unslop_followup.json`）。注意：`transition-property` 默认值即 `all`，盘点必须过滤时长>0，否则假阳性（首版探针曾报每页 441–1060，复测修正为 10–40）。

---

## 6. 交付记录（2026-11-14，批次 1–3 已交付）

| 批 | commit | 内容 | 验收 |
|---|---|---|---|
| 1 | `8b1be99` | 新增 `Icon.vue`（lucide-vue-next，31 图标，16px / 1.5 stroke / currentColor）；约 40 处彩色 emoji 换线性图标；保留 ✓✕★☆♥✎☰ 排版符号；`Lightbox.spec` 下载/写操作断言改按 title（意图不变） | vue-tsc 0；vitest 830/830；探针 18/18 页彩色 emoji=0、零 console 错误零溢出 |
| 2 | `f1c744f` | 4 处 `transition` 简写（=all）点名属性；GalleryGrid 去 hover scale(1.02)（卡片已有边框+阴影反馈）；job-badge / 标签 ✕ / 矩阵悬浮徽标 / 参考库首页槽位计数与标签 10px→`--fs-xs` | 探针 realTransitionAll 全 0、tinyBtn 全 0 |
| 3 | `c31429d` | 暗色 `--primary` #5b5bd6（白字 5.37）；主色作文字/链接的 31 文件改 `--accent-link` #818cf8（暗底 6.34、活跃页签 soft 底 5.02，原约 2.8）；`--text-faint` #8a8a8a（5.19）；浅色主题不变 | 探针对比度复测达标；`color: var(--primary)` 落点清零 |
| 4 | `c30b5f0` | `.cat-chip.on` 护色（调暗 40%）提为明暗共规；圆角方言 9999→pill / 20→14 / 18 按内外语义→6（嵌套 14−8）/14；10px×10 与 9px×5 → `--fs-xs`；新增 `tools/style_lint.py` + ci.ps1 警告步 | style_lint 0 红；探针 18/18；参考库截图观感与全局 chrome 统一 |

每批共同验收：vue-tsc 0 错误、vitest 830/830、vite build 成功、`web/` 同步入库；e2e 无选择器漂移（不依赖被改 emoji 文本/结构）。批次 3 的 `primary/bg 3.53` 复测值对应**实底色**（非文字），作边框/填充满足 ≥3:1；文字口径看 `--accent-link` 6.34。

**批次 4 裁决与更正（2026-11-14，用户授权按全局最优拍板）**：

- **护色共规**：`.cat-chip.on` 调暗 40% 保护原为浅色专属，提为明暗共用一条规则（消除行为分叉）；暗色用户分类色白字对比度同获保障。
- **方言收敛**：一个应用一套设计语言——参考库圆角 / 字阶收进全局令牌；`ReferenceCard.vue` 头部规格注释同步退役《施工手册》旧值（20/18/10px）。
- **accent 色相保留 indigo 族**：扁平统一、对比度已达标；换色相属口味而非正确性，无品牌资产不折腾。本轮只调明度、未改色相。
- **撤回「空参数盒收敛」**：取证发现参数盒是**可编辑 input**（`v-model` 绑 draft），「-」是 placeholder；收敛成一行会丢编辑入口。§2-D 原观察基于误判（当成只读展示），以此为准更正。
- **style_lint 事实守护**：`tools/style_lint.py` 只量事实（彩色 emoji / transition 简写 / 字阶下限 / 圆角方言 / 明暗令牌对比度），上线即抓出探针漏掉的 5 处 9px（隐藏/条件元素不进渲染盘点）；ci.ps1 挂**警告步不阻断**。

**仍待拍板**：style_lint 从警告升级成 CI 门禁（会影响所有会话的 CI 行为，故不擅自升级）。

---

unslop 方法署名：Damir Sokolovsky（@heydamir），CC BY 4.0。