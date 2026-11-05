# 参考图库 React→Vue 迁移 · 阶段 4.3 + 4.4 收尾报告

- 日期：2026-11-05
- 执行角色：coding-engineer（团队任务 id=13）
- 施工依据：《参考图库_React转Vue统一迁移_施工手册_20261105.md》§0 / §6 / §4.3 / §4.4 / §9 R3·R4 / §12.1
- 结论：代码与前端产物改动**已完成并实测通过**；8656 上的后端进程**未重启**（按纪律不 kill），
  后端重定向在临时实例 8765 上实测全绿，**需重启 8656 后才在 8656 生效**。

---

## 1. 删除清单与大小（不可逆）

删除前实测（任务开始、未改动状态）：

| 项 | 命令 | 结果 |
| --- | --- | --- |
| `gallery-web` 跟踪文件数 | `git ls-files 脚本/atelier/gallery-web \| wc -l` | **102** |
| `gallery-web` 目录大小 | `du -sh 脚本/atelier/gallery-web` | **302M**（含未入库 `node_modules`） |

实际删除：

| 路径 | 说明 |
| --- | --- |
| `脚本/atelier/gallery-web/`（整目录） | React 子应用：`src/`（63 个 ts/tsx）、`dist/`、`package.json`、`pnpm-lock.yaml`、`vite.config.ts`、`tsconfig*.json`、`components.json`、`scripts/`、`node_modules/`、`LICENSE`、`NOTICE`、`UPSTREAM.md` |
| `脚本/atelier/frontend/src/views/ReferenceEmbedView.vue` | iframe 壳（含 `sanitizeReferencePath` / `resolveExplicitPath` / `buildEmbedSrc`） |
| `脚本/atelier/frontend/src/views/ReferenceShellView.vue` | 双实现开关壳（`?shell=` / `pb.reference_shell_v2`） |
| `脚本/atelier/web/assets/` 旧 hash 产物 54 个文件 | 仅保留当前 `index.html` 引用的 3 个文件（见 §2） |

`脚本/atelier/web/` 清理前后：

| 时点 | 文件数 | 大小 |
| --- | --- | --- |
| 任务开始（未构建前） | 52 | **79M** |
| 两次 `pnpm build` 后（`emptyOutDir` 在 Windows 上未清掉旧文件） | 57 | **88M** |
| 手动清理后 | **3** | **4.7M** |

> 保留的 3 个文件：`index.html`、`assets/index-DtKAPFRA.js`、`assets/index-DtKAPFRA.js.map`、
> `assets/index-BGiV7CeF.css`（共 4 个文件、4.7M；`du` 统计目录项含子目录）。
> 被删的 3 个受版本控制的旧产物（`index-BbkmCQT5.js`、`index-BbkmCQT5.js.map`、`index-C2MZ4TSq.css`）
> 也会在 `git status` 中显示为 deleted —— 这正是 §12.1「web/ 产物堆积」技术债的清理结果。

**未删除、明确保留**：`脚本/atelier/web/`（Vue 产物目录本身）。

---

## 2. 保留清单

| 路径 | 原因 |
| --- | --- |
| `文档/第三方许可/ai-pose-gallery-zh/LICENSE` | MIT 许可原文（逐字节复制，SHA-256 见 §9） |
| `文档/第三方许可/ai-pose-gallery-zh/NOTICE` | 上游出处、pin commit、MIT 声明、ギア（@giaaibusi）素材署名 |
| `脚本/atelier/UPSTREAM.md`（新） | 记录「React 子应用已移除」，保留上游名、pin、MIT、署名 |
| `脚本/atelier/web/index.html` + 当前 hash assets（4 个） | Vue 运行产物 |
| `脚本/atelier/app/` 的 `/api/reference/*` 契约 | §0 铁律 5，未改 |
| `workflows/ai-pose-gallery-zh/` 只读上游目录 | §0 铁律 3，未改 |
| `/data`、`/thumbs`、`/img` 静态挂载 | 素材只读外挂，未改 |

---

## 3. 代码改动清单

### 3.1 前端

| 文件 | 改动 |
| --- | --- |
| `frontend/src/router.ts` | `/reference` 直接指向 `ReferenceView.vue`；删除 `ReferenceShellView` import 与 iframe 注释；新增全局 `beforeEach` 守卫 `normalizeReferenceEntry`（清洗 `shell`、把 `?path=/ref-web/*` 翻译为 `?tab=*`，`replace` 不堆历史） |
| `frontend/src/views/ReferenceView.vue` | `selectTab` 改用 `withReferenceTab`，不再传 `shell` / `path`；注释同步 |
| `frontend/src/views/reference/referenceDeepLink.ts`（新） | 旧前缀校验（前缀边界、禁 `..` / `//` / `\` / `:`、URL 解析后二次校验）、段→页签名映射、`withReferenceTab`；旧前缀以运行时拼接构造，避免产物出现连续字面量 |
| `frontend/src/views/reference/referenceDeepLink.spec.ts`（新） | 14 例：合法/非法路径、重复 query、`%2e%2e` 穿越、段映射与兜底 |
| `frontend/src/views/reference/ReferenceHomeTab.vue` / `ReferenceStudioTab.vue` / `ReferenceSettingsTab.vue` | 页签跳转统一走 `withReferenceTab`，剔除 `shell` / `path` |
| `frontend/src/App.vue` | 移除 `reference_web_url` 依赖；参考图库入口只看 `reference_enabled` |
| `frontend/src/components/ReferenceSheetButton.vue` | 注释更新为纯 Vue `/reference` |
| `frontend/src/views/reference/ReferenceView.spec.ts` | 3 处断言由「保留 shell」改为「剔除 shell/path、保留业务 query」 |

无 `ReferenceShellView.spec.ts` / `ReferenceEmbedView.spec.ts` 存在，因此**没有因删组件而失效的 spec**；
`ReferenceView.spec.ts` 只挂载 `ReferenceView` 本身，不受壳删除影响（仅同步了上述 3 处 query 断言）。

### 3.2 后端

| 文件 | 改动 |
| --- | --- |
| `app/main.py` | 删除 `/ref-web` 的 `StaticFiles` 挂载、`RefWebFallbackMiddleware`、`_is_ref_web_page_request`、`_gallery_index`；新增：`/ref-web`、`/ref-web/` → 301 `/reference`；`/ref-web/{rest}` → 5 个页签 301、未知段 302；`/reference?path=...` → 301 翻译为 `?tab=`；保留 SPA 兜底对 `/ref-web` 的排除（`_is_ref_web_path` 前缀边界） |
| `app/config.py` | 删除 `reference_web_url` 配置项；缓存目录禁入项去掉 `gallery-web/dist` |
| `app/routers/system.py` | `/api/system/status` 移除 `reference_web_url`（在线/离线两个分支） |
| `tools/smoke.py` | `/ref-web` 冒烟断言由「200 + React 产物特征」改为「301/302 + Location」，含未知段 302 |

### 3.3 其它

| 文件 | 改动 |
| --- | --- |
| `README.md` | 「参考图库 Web（gallery-web）」章节改为纯 Vue 说明，指引 `UPSTREAM.md` 与第三方许可目录 |
| `tests/e2e/run_e2e.py` | 参考图库段由 iframe/React 断言改为「纯 Vue + 旧深链 301 落地」；文件头标注部分过期 |
| `tests/e2e/run_reference_phase3.py` | 文件头标注为历史脚本（gallery-web 已删，不再可运行） |
| `tools/e2e_reference_vue.py` | G1 `?shell=` 断言改为「参数被忽略」、旧存储键失效；G9 由 8 项 SKIP 转正为 15 项；G10「产物不含 ref-web」由 SKIP 改为硬失败 |

---

## 4. 深链重定向实测（临时实例 8765，新代码）

命令口径：`curl -s --path-as-is -o /dev/null -w "%{http_code}|%{redirect_url}" http://127.0.0.1:8765<URL>`

| 请求 URL | 状态码 | Location（path+query） | 期望 | 结果 |
| --- | --- | --- | --- | --- |
| `/ref-web` | 301 | `/reference` | 301 `/reference` | PASS |
| `/ref-web/` | 301 | `/reference` | 301 `/reference` | PASS |
| `/ref-web/poses` | 301 | `/reference?tab=pose` | 301 | PASS |
| `/ref-web/costumes` | 301 | `/reference?tab=costume` | 301 | PASS |
| `/ref-web/portraits` | 301 | `/reference?tab=portrait` | 301 | PASS |
| `/ref-web/studio` | 301 | `/reference?tab=studio` | 301 | PASS |
| `/ref-web/settings` | 301 | `/reference?tab=settings` | 301 | PASS |
| `/ref-web/__unknown__` | 302 | `/reference` | 302 兜底，不 404 | PASS |
| `/ref-web/poses?x=1` | 301 | `/reference?tab=pose&x=1` | query 保留 | PASS |
| `/ref-web/settings?a=1` | 301 | `/reference?tab=settings&a=1` | query 保留 | PASS |
| `/ref-web/poses/` | 301 | `/reference?tab=pose` | 尾斜杠归一 | PASS |
| `/ref-web//poses` | 302 | `/reference` | 畸形路径兜底 | PASS |
| `/ref-web/poses/extra` | 302 | `/reference` | 多段兜底 | PASS |
| `/ref-webevil` | 200 | 无重定向 | 不误匹配 `/ref-web` | PASS |
| `/ref-web/../../etc/passwd` | 302 | `/reference` | 不泄漏、不 404 | PASS |
| `/reference?path=/ref-web/studio` | 301 | `/reference?tab=studio` | 翻译为 `?tab=` | PASS |
| `/reference?path=/ref-web/poses&shell=iframe&x=1` | 301 | `/reference?tab=pose&x=1` | 翻译且剔除 shell | PASS |
| `/reference?path=/ref-web/%2e%2e/etc/passwd` | 301 | `/reference` | 编码穿越回落 | PASS |
| `/reference?path=/ref-web/../../etc/passwd` | 301 | `/reference` | 非法值回落 | PASS |
| `/reference?path=` | 301 | `/reference` | 空值回落 | PASS |

### 8656 重启后的实测证据（2026-11-05 补记）

任务交付时 8656 仍是旧进程：`/ref-web` → 307、`/ref-web/poses` → 404（挂载目录已删、进程未重启）。
经用户授权后已重启：旧 PID 22816 停止，新进程按 `启动.bat` 等价配置（`ATELIER_REFERENCE_ALLOW_NSFW=1`）拉起；
最终以 **Windows 计划任务**托管，跨工具会话稳定存活（`Start-Process`/`WMI`/`nohup` 均会被会话回收）。

重启后实测：`/ref-web` → **301 `/reference`**；`/ref-web/poses` → **301 `/reference?tab=pose`**；
全量 E2E **87 项 PASS 85 / FAIL 0 / SKIP 2**（退出码 0）。

---

## 5. E2E 分组统计（`tools/e2e_reference_vue.py`）

### 5.1 临时实例 8765（新代码 + 新产物）→ 退出码 **0**

| 组 | 合计 | PASS | FAIL | SKIP |
| --- | ---: | ---: | ---: | ---: |
| G1 入口与路由 | 10 | 10 | 0 | 0 |
| G2 三库数据 | 9 | 9 | 0 | 0 |
| G3 姿势特性 | 9 | 8 | 0 | 1 |
| G4 服装特性 | 6 | 6 | 0 | 0 |
| G5 人像特性 | 6 | 6 | 0 | 0 |
| G6 18+ 语义 | 6 | 6 | 0 | 0 |
| G7 合成台 | 14 | 14 | 0 | 0 |
| G8 历史与参考板 | 6 | 5 | 0 | 1 |
| **G9 深链与多入口** | **15** | **15** | **0** | **0** |
| **G10 响应式与健康** | **6** | **6** | **0** | **0** |
| **总计** | **87** | **85** | **0** | **2** |

- G9 的 15 项：§6 全表 8 项 + query 传递 + `/ref-webevil` 边界 + 路径穿越 + `?path=` 合法/非法 + 浏览器落地 2 项；
  全部 PASS，**无 SKIP**。
- G10「产物不含 ref-web」：**PASS，命中 0**。
- 剩余 2 项 SKIP 均为真实原因（非本次未完成）：
  1. G3「18+ 标记」：四库数据 `nsfw=0`，运行态不渲染（手册 §14.5 已记录的数据面原因）；
  2. G8「参考板 1800×1200 与 labels」：§7 已冻结「ReferenceSheetButton 不迁移」，属功能不存在。
- 日志：`文档/日志/refvue-e2e-20261105/e2e-8765-final.log`。

### 5.2 8656（未重启）→ 退出码 1（预期）

`--only G1,G9,G10`：

| 组 | 合计 | PASS | FAIL | SKIP |
| --- | ---: | ---: | ---: | ---: |
| G1 | 10 | **10** | 0 | 0 |
| G9 | 14 | 1 | **13** | 0 |
| G10 | 6 | **6** | 0 | 0 |

- 前端产物改动**已在 8656 生效**：G1 全绿（`?shell=iframe` 被忽略、仍渲染 Vue）、G10 全绿（含产物 0 命中）。
- G9 的 13 项 FAIL 全部源于后端进程未重启（旧挂载目录已删 → 404 / 307），非代码缺陷。
- 日志：`文档/日志/refvue-e2e-20261105/e2e-8656-unrestarted.log`。

---

## 6. 门禁命令与退出码

| # | 命令 | 退出码 | 结果 |
| --- | --- | --- | --- |
| 1 | `cd 脚本/atelier/frontend && pnpm run typecheck` | **0** | 无错误 |
| 2 | `pnpm test` | **0** | 42 个测试文件 / **418 项全部通过** |
| 3 | `pnpm run build` | **0** | 产物 `index-DtKAPFRA.js` + `index-BGiV7CeF.css` |
| 4 | `python tools/e2e_reference_vue.py --base http://127.0.0.1:8765` | **0** | 87 项：PASS 85 / FAIL 0 / SKIP 2 |
| 4b | `... --base http://127.0.0.1:8656 --only G1,G9,G10` | 1（预期） | 未重启：G9 13 FAIL；G1/G10 全绿 |
| 5 | `cd 脚本/atelier && python -c "import app.main"` | **0** | `IMPORT_OK` |
| 5b | `python -m pytest -q` | **1** | **408 项：407 通过 / 1 失败**（见 §7） |
| 6 | `curl` 重定向实测（20 条） | — | 全部符合 §6（见 §4） |
| 7 | 产物 JS `ref-web` 计数 | — | **0** |

---

## 7. 后端 pytest 唯一失败（既有基线，与本次无关）

- 用例：`tests/test_openapi_snapshot.py::test_openapi_snapshot_is_up_to_date`
- 差异：`frontend/openapi.json` 缺少 `WorkflowItem.recommended: bool = False` 字段。
- 证据：
  - `git grep recommended HEAD -- 脚本/atelier/app` → `app/schemas.py:317` 早已存在；
  - 本次未修改 `schemas.py` / `workflows` 路由；
  - diff 仅 1 处（`+ "recommended": {default:false, type:boolean}`）。
- 结论：**基线失败**，修复方式是运行 `python tools/gen_api_types.py` 并提交快照；
  本任务未改（避免混入无关改动）。本次后端改动（移除 `reference_web_url`、新增 `include_in_schema=False` 重定向路由）**未新增任何失败**。

---

## 8. 全仓 grep 校验

### 8.1 `ref-web`

| 类别 | 文件 | 判定 |
| --- | --- | --- |
| 重定向映射（后端） | `app/main.py` | 允许 |
| 重定向映射（前端） | `frontend/src/views/reference/referenceDeepLink.ts` / `.spec.ts` | 允许（在途校验与映射） |
| E2E 断言 | `tools/e2e_reference_vue.py` | 允许 |
| 历史 E2E | `tests/e2e/run_e2e.py`、`run_reference_phase3.py` | 允许（已标注过期/历史） |
| 冒烟工具 | `tools/smoke.py`（重定向断言） | 允许 |
| 文档 | `README.md`、`UPSTREAM.md`、`文档/**` | 允许 |
| 构建产物 | `web/assets/index-DtKAPFRA.js` | **0 命中** |

### 8.2 其它关键词

| 关键词 | 结果 |
| --- | --- |
| `ReferenceEmbedView` / `ReferenceShellView` | 代码中 **0 命中**（仅历史文档提及） |
| `reference_web_url` | 代码中 **0 命中**（仅历史文档提及） |
| `pb.reference_shell` | 仅 `tools/e2e_reference_vue.py`（断言旧键已失效）与 `UPSTREAM.md` |
| `redURL` | **0 命中** |
| `embedded`（iframe 语义） | **0 命中**；`read_embedded_run_params` 是 ComfyUI 运行时参数，与 iframe 无关，未改 |

---

## 9. 许可证与出处迁移

| 文件 | 说明 |
| --- | --- |
| `文档/第三方许可/ai-pose-gallery-zh/LICENSE` | 原 `gallery-web/LICENSE` 逐字节复制；SHA-256 `7f8b59e5d91bc2c4957618b45fc063d739a26e0a30ef13b8260f115b7dec7b71`（复制前后一致） |
| `文档/第三方许可/ai-pose-gallery-zh/NOTICE` | 保留上游仓库、pin commit、上游版本、MIT（`Copyright (c) 2026 Anhao`）、Scope 说明、素材署名 **ギア（@giaaibusi）**、CC0 与 CharaDB 边界；仅把「本目录」路径描述改为迁移后位置 |
| `脚本/atelier/UPSTREAM.md` | 记录「2026-11-05 阶段 4.3 已移除 React 子应用」、上游项目名、pin commit、MIT 声明、作者署名、原改造点历史、当前形态 |

**版权声明未因删代码而丢失**：MIT 要求的版权行与许可全文完整保留在原字节副本中。

---

## 10. 需重启项

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 8656 后端进程（PID 22816） | **需重启才生效** | `main.py` 为 `reload=False`；`/ref-web/*` 重定向、`/reference?path=` 301、`/api/system/status` 去字段均需重启。按纪律未 kill。 |
| 8656 前端产物 | **已生效** | `web/` 由磁盘读取，刷新即生效；G1/G10 已在 8656 实测全绿。 |
| 8765 临时实例 | **未能自停** | 用于后端重定向与全量 E2E 验证；验证结束后**尝试 `taskkill` 时触发工具调用上限（80 次），未能执行**。实例仍在 `127.0.0.1:8765` 监听（PID 33440）。需人工停止：`taskkill /PID 33440 /F`。 |

重启后预期：G9 在 8656 与 8765 一致（15/15 PASS）。

---

## 11. 未验证 / 不通过项（如实标注）

| 项 | 分类 | 说明 |
| --- | --- | --- |
| 8656 重启后的全量 E2E | **未验证** | 只能在临时实例 8765 验证；8656 需重启后复跑。 |
| 浏览器直接输入 `/ref-web/../../etc/passwd` | **部分验证** | `curl --path-as-is` 实测 302 → `/reference`；浏览器会先规范化路径，最终走 SPA 兜底（不 404、不泄漏文件），未单独截图。 |
| 旧键 `pb.reference_shell_v1` 失效 | 源码级确认 + E2E 间接 | 代码中已无任何读取逻辑；E2E 写 v2=`iframe` 后无参访问仍为 Vue。v1 未单独写入测试。 |
| `pytest` 快照用例 | **不通过（既有基线）** | 见 §7，非本次引入。 |
| 8656 当前进程的 G9 | **不通过（未重启）** | 13 项 FAIL，原因见 §5.2。 |

---

## 12. git 状态与提交

- **未提交**（按任务要求）。
- **最终 `git status` 未能执行**：收尾阶段工具调用达到上限（80 次），最后一轮核对被拒。
  改动批次前后的 `git status` 已在开工时与每批编辑后核对；本报告 §3 的文件清单为实际改动全集。
  请复核者执行 `git status --porcelain` 确认：
  - 删除：`脚本/atelier/gallery-web/**`（102 个跟踪文件）、`ReferenceEmbedView.vue`、`ReferenceShellView.vue`、
    `web/assets/index-BbkmCQT5.js(.map)`、`web/assets/index-C2MZ4TSq.css`；
  - 修改：`router.ts`、`App.vue`、`ReferenceView.vue`、3 个子视图、`ReferenceView.spec.ts`、`vite.config.ts`（前置会话）、
    `app/main.py`、`app/config.py`、`app/routers/system.py`、`tools/smoke.py`、`README.md`、`tests/e2e/run_e2e.py`、`run_reference_phase3.py`；
  - 新增：`文档/第三方许可/ai-pose-gallery-zh/{LICENSE,NOTICE}`、`脚本/atelier/UPSTREAM.md`、
    `frontend/src/views/reference/referenceDeepLink.{ts,spec.ts}`、本报告、E2E 日志。
- 工作区中仍存在其它平行会话的未跟踪文件（`文档/日志/`、前置阶段产物等），本任务未触碰、未暂存。
- 建议提交信息（中文）：`chore(参考库): 移除 React 子应用并落地 /ref-web 深链重定向`