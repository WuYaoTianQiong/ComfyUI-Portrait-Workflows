# prompt_browser_v4 重构计划

> 立项日期：2026-10-30
> 分支：`refactor/b0-safety`（后续每个阶段单独开分支）
> 执行原则：**阶段化、可独立上线、随时可回滚**。不推倒重写。

---

## 0. 已定技术决策

| 议题 | 决策 | 理由 |
|---|---|---|
| ORM | **保留 Peewee**，迁移改用 `playhouse.migrate` + `schema_version` 表 | 当前查询不复杂，换 SQLAlchemy 收益远期、成本集中，且会连带重写 89 个端点的数据访问 |
| 前端框架 | **Vite + Vue 3 + TypeScript + TanStack Query** | 模板语法最接近现有内联 HTML，迁移成本最低；Query 替掉手写轮询与 `window._xxx` 状态 |
| 重构顺序 | **S0 止血 → S1 数据层与后端分层 → S2 前端** | 标签/软删除的烂账不清，前端换了也只是把错的数据渲染得更漂亮 |
| 数据库 | 继续 SQLite + WAL | 单机单用户，库仅 2.8MB，换 PG 只会增加部署复杂度 |

---

## 1. 现状基线（重构前实测，2026-10-30）

后续每个阶段结束都用这张表对比，**数字只能变好不能变差**。

| 指标 | 基线值 |
|---|---|
| `gen_history` 总行 / 存活 / 墓碑 | 538 / **10** / **528（98%）** |
| `output` 目录实际文件数 | 10 |
| `image_tags` / `prompt_tags` 关联数 | **0 / 0**（136 个标签全部悬空，标签筛选实质失效） |
| `prompts` / `tags` / `templates` / `template_fragments` | 331 / 136 / 381 / 2486 |
| 后端 Python | ≈5.7k 行（routers 3.4k、services 1.6k、models 382） |
| 前端 JS / CSS / index.html | ≈8.2k / ≈3.8k / 852 行 |
| `window.*` 赋值 / 引用 | 726 / 2739 |
| 内联 `onclick` | 145 处 |
| 后端端点 / 前端 `window.api()` 调用点 | 89 / 89 |
| 契约测试 | `tests/test_contract.py` 314 行 |
| `文档/` 下 .db 备份 | 19 个，≈53MB |

---

## 2. 执行铁律（每次动手前必读）

### 2.1 必须用项目解释器
```powershell
$PY = 'C:\Users\ws\AppData\Local\Python\pythoncore-3.12-64\python.exe'
```
PATH 里的 `python` 是 Microsoft Store 版，没有依赖。所有命令一律使用 `& $PY`。

### 2.2 改完后端必须重启服务
- 当前服务 PID 会变，重启前先 `netstat -ano | findstr ":8656.*LISTENING"` 找到并结束旧进程
- 启动必须 **cd 到 `F:\ComfyUI_Migration\...\脚本\prompt_browser_v4`**，从 D: junction 启动会导致 `comfyui_root` 解析错误
- 用 `Start-Process` 时**必须带** `-RedirectStandardOutput/-RedirectStandardError`，否则进程会被工具清理

### 2.3 动库前必须备份
```powershell
# 备份到 文档/backups/，命名带阶段号
Copy-Item '文档\提示词收藏.db' "文档\backups\提示词收藏.db.bak_s0_$(Get-Date -f yyyyMMdd_HHmmss)"
```

### 2.4 每个任务的最小验证闭环（缺一不可）
1. `& $PY -m pytest -q` —— 契约测试全绿
2. `& $PY verify_smoke.py` —— 真实拉起 uvicorn（临时端口 8765）打关键接口并扫 Traceback
3. 层内自检：改了前端就用 `预览`/硬刷新（Ctrl+F5）确认，**不要只靠 curl 断言前端行为**
4. `flake8`/IDE 诊断无新增 error

---

## 3. 阶段 0：止血（目标 1~2 天，零架构变更）

> 目的：把"会自动毁数据"和"每次都在浪费性能"的问题先按住，让后续重构在安全的地基上做。

### S0-1 清理失效：改 dry-run + 熔断 + 限定范围，与缩略图清空解绑
- **文件**：`routers/history.py`、`static/history.js`、`static/index.html`
- **做法**
  1. `POST /api/history/cleanup_missing` 默认 `dry_run=true`，返回 `{total, will_clean, samples[≤10], guarded: bool}`，不写库
  2. 熔断：`will_clean / total > 0.5 且 total >= 20` → 直接拒绝执行并返回告警（防路径误判全库清空）
  3. 新增显式执行路径 `cleanup_missing?dry_run=false&confirm=true`
  4. 支持 `favorite/category_id/tag_ids/search` 参数，只清当前筛选（复用 `_filtered_history_query`）
  5. 前端按钮改为：先请求 dry-run → 弹窗展示"将清理 N 条" + 前 10 个文件名 → 二次确认才执行
  6. **删除** `history.js:234-240` 里顺带调用 `/api/thumbnail/clear` 的第二步
- **验收**：当前库 10 存活 0 缺失 → dry-run 返回 `will_clean=0`；手工把某张图改名后 dry-run 返回 1 且样本名正确
- **回滚**：纯新增参数，旧调用方式仍然工作
- **状态**：✅ 2026-10-30 完成
  - 实现：`cleanup_missing` 默认 `dry_run=true`，返回 `{total, will_clean, samples, guarded, message}`；执行需 `dry_run=false&confirm=true`；熔断阈值「≥20 条且缺失占比 >50%」；筛选参数与画廊一致（顺带抽出 `_apply_facet_filters`，list_history / history_ids / cleanup_missing 三处共用）
  - 前端：两段式（预览 → 确认），删除「顺带清空全站缩略图缓存」；`?v=` 未改（静态资源已由中间件 no-store）
  - 验证：pytest 43 passed（新增 4 条契约用例：dry-run 不写库 / 缺 confirm 不执行 / 熔断拦截 / 按分类限定范围）；`verify_smoke.py` 25 通过 1 跳过、无 Traceback；重启后真实请求：`total=10, will_clean=0`、无 confirm 时 `success=false`、`/gallery` 200

### S0-2 缺失状态改为可自愈的派生列
- **文件**：`models.py`、`services/integrity.py`（新建）、`services/job_state.py`、`routers/history.py`、`static/gallery.js`、`static/index.html`
- **做法**
  1. `_migrate_column(db, "gen_history", "missing_since", "missing_since DATETIME")`
  2. 新建 `services/integrity.py::scan_missing(batch=2000)`：只读扫描存活记录，文件不在 → 写 `missing_since=now`；文件回来了 → 清空该列
  3. 挂到 `writer_loop` 里**低频执行**（启动后首次 + 每 10 分钟），不要塞进 30s 的 sync
  4. `GET /api/history` 增加 `missing: bool = Query(None)` 过滤；列表项返回 `missing: bool`
  5. 画廊：给缺失项加角标（🚫 文件缺失），筛选栏加「仅看失效」
- **验收**：改名一张图 → 最多 10 分钟角标出现 → 改回原名 → 角标消失，且 `favorite`/标签/分类**一个都没丢**
- **回滚**：列可留，代码回退即可
- **状态**：✅ 2026-10-30 完成
  - 后端：`gen_history.missing_since`（迁移列）+ `services/integrity.py::scan_missing()`（分批 500、每批一次批量 UPDATE、只写派生列）+ `writer_loop(integrity_interval=600)` 启动即跑一次；`/api/history` 与 `/api/history/ids` 支持 `missing=1`，列表项新增 `missing` 字段
  - 前端：卡片 `is-missing` 灰化 + 顶部居中标「🚫 文件缺失」；筛选下拉新增「🚫 仅失效」；`store.js` 统一带上 `missing` 参数
  - 顺带修复（验收时发现的既有 bug）：`ui.js::applyUiState` 原会按 localStorage 先切一次 Tab 并改写 URL，导致**直接访问 `/gallery`、`/composer` 被踢回提示词页**。已改为「首屏 Tab 只由 URL 决定」，`/gallery` 现在稳定停留在画廊
  - 验证：pytest 45 passed（新增 missing 筛选 + 巡检标记/自愈 2 条）；`verify_smoke.py` 25 通过 1 跳过、无 Traceback；真实浏览器（playwright）：10 张卡片中 1 张带 `is-missing`、切「仅失效」后剩 1 张、0 个 JS 错误；真实库改名 → 巡检 `marked=1` → 接口命中 → 还原 → `cleared=1` 自愈，记录全程未被删除

### S0-3 去掉前端重复的全量同步
- **文件**：`static/app.js:115-122`
- **做法**：删除前端 `setInterval(.../api/history_sync...)` 那一段。后台 `writer_loop(sync_interval=30)` 已经在做同一件事，前端只保留 `loadHistory()` 刷新
- **验收**：画廊新图仍在 30s 内出现（来自后台线程）；Network 面板 30s 周期内不再出现 `history_sync` 请求

### S0-4 修复 `_job_index` 永不失效
- **文件**：`routers/history.py:226-258`
- **做法**：新增 `_invalidate_job_index()`，在 `create_job` / `update_job_items` 写入后调用；或改成基于 `gen_jobs.max(updated_at)` 的版本号比对
- **验收**：新建任务出图后，新图能匹配到来源 `prompt_id`
- **回滚**：无副作用

### S0-5 合并三处重复的筛选构造器
- **文件**：`routers/history.py`
- **做法**：`list_history`（411-455 内联）、`_filtered_history_query`（512-547）、`history_facets`（550-583）、`history_ids`（587-623）统一到**一个** `build_history_query(filters)`，支持 `favorite/search/category/tag/source/date/model/orientation/missing`
- **验收**：四个端点在相同参数下返回的集合完全一致（补一条契约测试断言 `ids ⊆ list` 且计数相等）
- **回滚**：行为不变，纯重构

### S0-6 墓碑回收自动化 + 备份轮转
- **文件**：`services/job_state.py`（或新 `services/maintenance.py`）、`tools/cleanup_tombstones.py`、`文档/`
- **做法**
  1. 把 `cleanup_tombstones` 的核心迁到 `services/maintenance.py::purge_tombstones(keep_days=7)`，启动时执行一次
  2. 所有 `.bak_*` 统一落到 `文档/backups/`，保留最近 10 个，其余删除
  3. 现有 19 个散落备份一次性移动归档
- **验收**：重启后 `gen_history` 墓碑数下降（当前 528 条且文件全部已不存在，可安全回收）；`文档/` 根目录只剩 `提示词收藏.db` 与 `backups/`
- **回滚**：归档前先整体复制一份到 `文档/backups/_pre_s0/`

### S0-7 收尾：版本控制卫生
- **文件**：新建/修改 `.gitignore`
- **做法**：忽略 `文档/提示词收藏.db*`、`文档/backups/`、`thumbnails/`、`logs/`、`_pb_*.log`、`__pycache__/`
- **需你确认**：是否执行 `git rm --cached 文档/提示词收藏.db`（停止跟踪，历史里已有 3MB 记录不会消失，但能防止继续膨胀）
- **验收**：`git status` 干净，不再出现 `.db` 变更

---

## 4. 阶段 1：数据层与后端分层（目标 3~5 天）

### S1-1 迁移框架化
- **做法**：`models.py` 里的 `init_db` 手写 `_migrate_column` 序列 → 改为 `playhouse.migrate` + `schema_version` 表 + 有序迁移列表 `MIGRATIONS = [(1, fn1), (2, fn2), ...]`
- **验收**：全新空库能一次建到位（`conftest._assert_schema_ready` 通过）；老库从 v0 顺序升级到最新；重复启动幂等
- **回滚**：保留旧 `init_db` 作为 `legacy_init_db()` 一版

### S1-2 标签收敛为单表 + 多态关联
- **做法**
  1. 新表 `entity_tags(id, entity_type TEXT, entity_id INT, tag_id INT, UNIQUE(entity_type, entity_id, tag_id))`
  2. 迁移脚本把 `image_tags` / `prompt_tags` 的存量导入，**并**把 `prompts.tags` 逗号文本拆成标签补齐
  3. 读路径全部切到 `entity_tags`；`prompts.tags` 废弃为只读兼容字段，UI 不再写它
  4. `tags` 表的 `usage_count` 改为实时聚合（或删除该冗余列）
- **验收**：同一个标签在提示词侧栏计数、图片侧栏计数、画廊筛选结果三者数字一致；补契约测试锁死

### S1-3 二态软删除 → 三态可见性
- **做法**：`is_deleted`（0/1）+ `missing_since` → `visibility TEXT ('live'|'hidden'|'missing')` + `hidden_at/missing_since`；同步写入的 `ON CONFLICT` 目标从部分索引改为普通唯一索引，摆脱 `conflict_where=SQL("is_deleted=0")` 的手写字面量
- **验收**：`job_state.py` 里 `_IS_DELETED_ZERO` 字面量可以删掉；出图 upsert 不再需要特殊方言处理

### S1-4 抽 service 层 + Pydantic 出入参
- **做法**：`routers/*` 只做参数校验与响应组装；业务逻辑迁到 `services/history_service.py`、`services/job_service.py` 等；所有响应定义 Pydantic 模型（`response_model=`）
- **验收**：`test_contract.py` 全绿；任何字段改名都会在测试或类型检查里炸出来

### S1-5 派生列 + 索引，去掉运行时 `json_extract`
- **做法**：`prompt_params` 的 `width/height/model/orientation` 落成真实列并建索引；分面统计改 `GROUP BY 列`；`prompt_params` 仍保留完整 JSON 作原始档案
- **验收**：`/api/history/facets` 在 10k 行数据下 <100ms

### S1-6 契约测试铺满 + CI 脚本
- **做法**：`test_contract.py` 扩到覆盖全部 89 个端点（至少 happy path + 关键错误码）；新增 `scripts/ci.ps1` 一次跑 pytest + verify_smoke
- **验收**：`ci.ps1` 通过；故意改坏一个字段名能被测试捕获

---

## 4.5 UX / UI 优化节奏（为什么不是现在）

UX/UI 分三段走，**不在 S0/S1 期间做视觉重设计**——那两阶段会不断改数据语义和接口，
样式先做等于做完再返工。具体安排：

| 时期 | 做什么 | 不做什么 |
|---|---|---|
| S0（本周） | 只修"用了会错/会烦"的地方：缺失角标与筛选、空状态文案、按钮行为可预期、首屏 Tab 跟着 URL 走 | 不动配色、间距、字体、布局 |
| S1 末（新增 S1.5，2~3 天） | **设计系统落地**：颜色/间距/字阶/圆角/阴影/动效令牌（`tokens.css`）+ 基础组件（Button/Select/Modal/Toast/Card/Tag/Badge/EmptyState）+ 一个组件预览页 | 不逐页改样式 |
| S2（1~2 周） | 每迁一页就套用 S1.5 的令牌与组件，顺手做视觉升级：画廊虚拟滚动、图片 hover 信息层、批量操作条、键盘导航、骨架屏 | 不再新增零散 CSS |

放在 S1.5 的理由：S2 是逐页迁移，如果边迁边设计，会出现"画廊一套风格、提示词页另一套"；
先把令牌和组件定死，迁移时只是拼装，返工最少、评审也最容易。

---

## 5. 阶段 2：前端重构（目标 1~2 周，可与 S1 并行）

### S2-1 工程骨架
- `frontend/`（Vite + Vue3 + TS + Pinia + TanStack Query + Vue Router）
- dev server 代理 `/api` → `http://127.0.0.1:8656`
- 构建产物 `dist/` 由 FastAPI 挂载；开发期两套并存，用路径前缀切换

### S2-2 画廊页（优先，痛点最集中）
- 迁移 `gallery.js`(734) + `imageViewer.js`(956)
- 虚拟滚动替代 50 条翻页
- TanStack Query 管列表/筛选/分页缓存，替掉手写 `window._galleryXxx` 与 30s 轮询
- 「文件缺失」角标与「仅看失效」筛选（接 S0-2）

### S2-3 提示词页
- 迁移 `prompt.js`(1591) + `category.js` + `tag.js`

### S2-4 组合器与换脸
- 迁移 `composer-core/workbench/random/templates/fragments.js` + `faceswap.js`

### S2-5 下线旧前端
- 删除 `static/*.js` 手写模块与 `?v=N` 版本号机制，静态目录只留构建产物与 vendor

---

## 6. 风险登记表

| 风险 | 影响 | 对策 |
|---|---|---|
| 路径误判导致大范围标失效 | 高 | S0-1 熔断 + S0-2 可自愈派生列，**任何情况下不自动硬删记录** |
| DB 被 ComfyUI 主进程独占 | 中 | 动库前确认服务已停；WAL 下只读可并发，写操作前后各备份一次 |
| 从 D: junction 启动导致 `comfyui_root` 解析错 | 高 | 启动脚本必须 cd 到 F: 真实路径（已写进铁律 2.2） |
| 前端改动"改完没生效" | 中 | `?v=N` 已被 Cache-Control no-store 兜底，验证时仍要 Ctrl+F5 |
| 迁移不可逆 | 高 | 每次迁移前 `文档/backups/` 备份 + `schema_version` 记录，回滚靠备份而非 downgrade |
| 阶段 2 与阶段 1 并行冲突 | 中 | 前端只消费 JSON 契约，后端契约测试一旦全绿即冻结，双方按契约开发 |

---

## 7. 进度跟踪

### 阶段 0
- [x] S0-1 清理失效 dry-run + 熔断 + 解绑缩略图
- [x] S0-2 `missing_since` 派生列 + 角标 + 筛选（含路由首屏 Tab bug 修复）
- [ ] S0-3 删前端 30s `history_sync`
- [ ] S0-4 修 `_job_index` 失效
- [ ] S0-5 合并筛选构造器
- [ ] S0-6 墓碑回收自动化 + 备份归档
- [ ] S0-7 gitignore / DB 停止跟踪

### 阶段 1
- [ ] S1-1 迁移框架化
- [ ] S1-2 标签收敛
- [ ] S1-3 三态可见性
- [ ] S1-4 service 层 + Pydantic
- [ ] S1-5 派生列 + 索引
- [ ] S1-6 契约测试铺满 + CI

### 阶段 2
- [ ] S2-1 工程骨架
- [ ] S2-2 画廊页
- [ ] S2-3 提示词页
- [ ] S2-4 组合器/换脸
- [ ] S2-5 下线旧前端
