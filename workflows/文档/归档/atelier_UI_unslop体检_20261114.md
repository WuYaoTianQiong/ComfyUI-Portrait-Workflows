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
| 4（拍板） | accent 色相 / 圆角方言 / 空参数盒 | — | 先拍板再动 |

明确不做：布局 / 信息架构 / 7 Tab / 主题 / 密度 / 框架（已拍板，见状态文档 §2.3）。

**开工前置（2026-11-14 用户拍板）**：批次 1 与并行会话未提交改动重叠 5 个文件——`Lightbox.vue`、`PromptDetailPane.vue`、`PromptTrialPanel.vue`（含 spec）、`WorkflowParams.vue`、`PromptView.vue`，且 `web/` 构建产物处于该批半更新态。**等该批提交后再开工**（沿用 2026-11-12 对 A15 的同文件不并行决定）；开工时不重建 `web/` 混入对方 bundle，vitest 先跑基线区分对方既有失败。无重叠的 14 个目标文件清单见 §2-A。

## 5. 复现方法

证据目录内 `unslop_probe.py`（18 页截图 + 计算样式盘点 → `unslop_report.json`）、`unslop_followup.py`（transition 时长过滤复测 + 色点定位 → `unslop_followup.json`）。注意：`transition-property` 默认值即 `all`，盘点必须过滤时长>0，否则假阳性（首版探针曾报每页 441–1060，复测修正为 10–40）。

---

unslop 方法署名：Damir Sokolovsky（@heydamir），CC BY 4.0。