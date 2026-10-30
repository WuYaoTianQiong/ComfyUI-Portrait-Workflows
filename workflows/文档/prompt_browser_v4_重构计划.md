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

> S0 结束时的实测值（2026-10-30，用于和阶段 1 对比）：
> `gen_history` **272 行 / 存活 10 / 墓碑 262**；标签关联仍为 0/0（S1-2 处理）；
> `文档/` 根目录已无散落备份（21 个归档进 `backups/legacy/`）；DB 已退出 git 跟踪。

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

### 2.5 前端工程（S2 起）
```powershell
cd F:\ComfyUI_Migration\ComfyUI-Portrait-Workflows\workflows\脚本\prompt_browser_v4\frontend
npm run dev      # http://127.0.0.1:5173 ，/api、/output 已代理到 8656（开发用，改完即生效）
npm run build    # 产物到 static_next/（1.8s）；构建产物不入库，部署时需重新 build
```
**回退到旧前端**：把 `static_next` 目录改名（如 `static_next.off`）再重启服务即可，
根路径会自动回到旧版（`static/`），不需要改任何代码或配置。

迁移期间旧前端 `static/` 保持可用，随时可退回；新前端只跑在 5173，互不干扰。

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
- **状态**：✅ 2026-10-30 完成。定时器只保留 `loadHistory(false,false)`；`history.js` 里切到画廊时的一次性 `history_sync` 属事件驱动，保留

### S0-4 修复 `_job_index` 永不失效
- **文件**：`routers/history.py:226-258`
- **做法**：新增 `_invalidate_job_index()`，在 `create_job` / `update_job_items` 写入后调用；或改成基于 `gen_jobs.max(updated_at)` 的版本号比对
- **验收**：新建任务出图后，新图能匹配到来源 `prompt_id`
- **回滚**：无副作用
- **状态**：✅ 2026-10-30 完成。采用**版本签名**方案（`(COUNT(status=done), MAX(updated_at))`），不跨模块耦合、不需要 jobs 侧主动通知；契约测试 `test_disk_scan_job_index_invalidates_after_new_job` 锁死

### S0-5 合并三处重复的筛选构造器
- **文件**：`routers/history.py`
- **做法**：`list_history`（411-455 内联）、`_filtered_history_query`（512-547）、`history_facets`（550-583）、`history_ids`（587-623）统一到**一个** `build_history_query(filters)`，支持 `favorite/search/category/tag/source/date/model/orientation/missing`
- **验收**：四个端点在相同参数下返回的集合完全一致（补一条契约测试断言 `ids ⊆ list` 且计数相等）
- **回滚**：行为不变，纯重构
- **状态**：✅ 2026-10-30 完成。最终形态为两层：`_filtered_history_query`（favorite/search/category/tag/missing）+ `_apply_facet_filters`（source/date/model/orientation），`list_history` / `history_ids` / `history_facets` / `cleanup_missing` 四处共用；契约测试 `test_history_filters_consistent_between_endpoints` 对 4 组筛选参数断言「列表 == 全选」

### S0-6 墓碑回收自动化 + 备份轮转
- **文件**：`services/job_state.py`（或新 `services/maintenance.py`）、`tools/cleanup_tombstones.py`、`文档/`
- **做法**
  1. 把 `cleanup_tombstones` 的核心迁到 `services/maintenance.py::purge_tombstones(keep_days=7)`，启动时执行一次
  2. 所有 `.bak_*` 统一落到 `文档/backups/`，保留最近 10 个，其余删除
  3. 现有 19 个散落备份一次性移动归档
- **验收**：重启后 `gen_history` 墓碑数下降（当前 528 条且文件全部已不存在，可安全回收）；`文档/` 根目录只剩 `提示词收藏.db` 与 `backups/`
- **回滚**：归档前先整体复制一份到 `文档/backups/_pre_s0/`
- **状态**：✅ 2026-10-30 完成（归档目录实际用 `文档/backups/` + `backups/legacy/`，删除了 `_pre_s0` 这个中间层）
  - `services/maintenance.py`：`backup_database` / `rotate_backups` / `purge_tombstones` / `run_startup_maintenance`
  - 保留期 7 天（`created_at` 是 UTC，比较时用 UTC now，否则东八区会凭空多 8 小时）
  - 历史遗留备份进 `backups/legacy/` 且**不参与轮转**——那是过去的事故恢复点，不值得为省几十 MB 删掉；轮转只作用于新生成的备份
  - 非生产库跳过维护：冒烟测试用临时库启动时不再把 `smoke.db` 备份写进真实 `backups/`
  - 实测：`归档 21 个，清理 0 个，保留 3 个`；`墓碑 528 条，回收 266 条（保留最近 7 天）`；`gen_history` 538 → **272 行**，存活 10 条不变，部分唯一索引完好

### S0-7 收尾：版本控制卫生
- **文件**：新建/修改 `.gitignore`
- **做法**：忽略 `文档/提示词收藏.db*`、`文档/backups/`、`thumbnails/`、`logs/`、`_pb_*.log`、`__pycache__/`
- **需你确认**：是否执行 `git rm --cached 文档/提示词收藏.db`（停止跟踪，历史里已有 3MB 记录不会消失，但能防止继续膨胀）
- **验收**：`git status` 干净，不再出现 `.db` 变更
- **状态**：✅ 2026-10-30 完成。已执行 `git rm --cached`（磁盘文件与历史提交均保留）；`.gitignore` 补 `workflows/文档/*.db`、`文档/backups/`、`prompt_browser_v4/logs/`、`_pb_*.log`、`workflows/.arts/`

---

## 4. 阶段 1：数据层与后端分层（目标 3~5 天）

### S1-1 迁移框架化
- **做法**：`models.py` 里的 `init_db` 手写 `_migrate_column` 序列 → 改为 `playhouse.migrate` + `schema_version` 表 + 有序迁移列表 `MIGRATIONS = [(1, fn1), (2, fn2), ...]`
- **验收**：全新空库能一次建到位（`conftest._assert_schema_ready` 通过）；老库从 v0 顺序升级到最新；重复启动幂等
- **回滚**：保留旧 `init_db` 作为 `legacy_init_db()` 一版
- **状态**：✅ 2026-10-30 完成（采用自研轻量框架，未引入 `playhouse.migrate` —— 它只解决"加/删列"语法糖，事务与版本记录仍要自己写，而现有迁移全是手写 SQL，包一层反而多一个依赖面）
  - `services/migrations.py`：`schema_version` 表 + `apply_migrations()`，每个迁移在事务内执行，成功才写版本；失败整体回滚、下次启动重试
  - `models.py`：`init_db` 拆成 `_ensure_tables()`（幂等建表，不进迁移）+ `MIGRATIONS`（有序列表）。v4.x 时期散落的列/索引迁移整体固化为 **v1**，行为逐行等价
  - 防"版本号新、结构旧"：v1 末尾 `_assert_columns()` 显式校验 11 个关键列，缺列则抛错回滚、不记录版本
  - 测试：新增 `tests/test_migrations.py` 4 条（版本记录 / 幂等 / 部分唯一索引存在 / 失败回滚且不记版本），pytest **51 passed**
  - 实测：生产库启动日志 `应用迁移 v1`，`schema_version=[(1, '2026-10-30 08:42:44', ...)]`，272 行 / 存活 10 / 部分唯一索引完好；二次启动不再重复应用

### S1-2 标签收敛为单表 + 多态关联
- **做法**
  1. 新表 `entity_tags(id, entity_type TEXT, entity_id INT, tag_id INT, UNIQUE(entity_type, entity_id, tag_id))`
  2. 迁移脚本把 `image_tags` / `prompt_tags` 的存量导入，**并**把 `prompts.tags` 逗号文本拆成标签补齐
  3. 读路径全部切到 `entity_tags`；`prompts.tags` 废弃为只读兼容字段，UI 不再写它
  4. `tags` 表的 `usage_count` 改为实时聚合（或删除该冗余列）
- **验收**：同一个标签在提示词侧栏计数、图片侧栏计数、画廊筛选结果三者数字一致；补契约测试锁死
- **状态**：✅ 2026-10-30 完成（作为迁移 **v2**，一次性执行、约 1 秒）
  - `models.EntityTag(entity_type, entity_id, tag_id)` + 唯一索引；`services/taxonomy.py` 是唯一写入口（`sync_prompt_tags` / `sync_image_tags` / `add_prompt_tag_by_name` / 计数函数）
  - 拆分规则实测确定：只按 `,` `，` `;` `；` 拆，**不拆空格**（线上存在 `Moody Photography` 这类标签；`f/1.8` 是标签本身而不是分隔）
  - 双写策略：UI 仍编辑 `prompts.tags` 文本，后端写完文本立刻 `sync_prompt_tags()` 全量重算关联，前端零改动；等 S2 换成标签选择器后再让关联表成为唯一入口
  - 读路径全部切到 `entity_tags`：`/api/prompts`（tag_ids 子查询，顺带修掉 join 导致的重复行计数）、`/api/tags`（两种 scope 的批量计数）、`/api/history`（图片直接标签 ∪ 经提示词继承）、`/api/composer`（片段筛选）、图片继承逻辑
  - 实测：标签 136 → **178**（从文本自动补建 42 个），`entity_tags` 已按 315 条提示词的文本重建；`女性` 标签命中提示词 175 条、图片 3 条（经继承）；`/api/tags` 两种 scope 计数均非零
  - 顺带修复：`batch_delete_prompts` 原本 `GenHistory.delete()` 会把画廊图片记录一起抹掉，已改为与单条删除一致的「只解除关联」；`delete_tag` 现在会清理 `entity_tags`（旧实现只删 `prompt_tags`，会留悬空关联）
  - 测试：新增 `tests/test_tags.py` 6 条，pytest **57 passed**

### S1-3 写入路径收敛（原计划「三态可见性」，已调整）
- **原计划**：`is_deleted` + `missing_since` → `visibility TEXT ('live'|'hidden'|'missing')`，把部分唯一索引改成普通索引以摆脱 `conflict_where=SQL("is_deleted=0")`
- **调整原因**（执行前重新评估后改方案）：
  1. 唯一性必须**排除已隐藏行**，所以索引注定还是部分索引，`conflict_where` 字面量无法消除；
  2. `visibility` 与现有 `is_deleted` / `missing_since` 语义重叠，换列的收益只是"命名更好"，却要牵动全部读写路径与索引迁移，风险与收益不成比例；
  3. 真正反复踩的坑是**这段方言细节散落在多处**、写错就被 `except: pass` 吞掉（历史上出现过"同步永远写不进库"两次）。
- **新做法**：把 upsert 收敛成唯一入口 `services/history_store.py::upsert_history()`
- **验收**：`_IS_DELETED_ZERO` 字面量消失、调用方不再手写 `conflict_target/conflict_where`；补测试锁死三条语义
- **状态**：✅ 2026-10-30 完成
  - `upsert_history(insert_values, update_values, only_when_job_null=False)`，`LIVE_ONLY_FILTER` / `CONFLICT_TARGET` 集中定义
  - `job_state._insert_history_for_item` 与 `history._sync_comfyui_history` 两处手写 upsert 全部改为调用
  - 测试 `tests/test_history_store.py` 3 条：同名 upsert 只留一行且字段更新 / 软删过的同名文件插入新行而非复活墓碑 / `only_when_job_null` 不覆盖任务写入的富参数
  - pytest **60 passed**；verify_smoke 25 通过；重启后 history total=10、有图标签 12

### S1-4 抽 service 层 + Pydantic 出入参
- **做法**：`routers/*` 只做参数校验与响应组装；业务逻辑迁到 `services/history_service.py`、`services/job_service.py` 等；所有响应定义 Pydantic 模型（`response_model=`）
- **验收**：`test_contract.py` 全绿；任何字段改名都会在测试或类型检查里炸出来

### S1-5 派生列 + 索引，去掉运行时 `json_extract`
- **做法**：`prompt_params` 的 `width/height/model/orientation` 落成真实列并建索引；分面统计改 `GROUP BY 列`；`prompt_params` 仍保留完整 JSON 作原始档案
- **验收**：`/api/history/facets` 在 10k 行数据下 <100ms
- **状态**：⚠️ 2026-10-30 **部分完成（只做索引，派生列降级）**
  - 补齐索引（迁移 **v3**，`IF NOT EXISTS` 幂等）：`gen_history(prompt_id)` / `(missing_since)` / `(source)` / `(captured_at)`、`entity_tags(tag_id, entity_type)`、`prompts(updated_at)`
  - **派生列暂不做**：当前 `gen_history` 仅 272 行、`prompts` 331 条，运行时 `json_extract` 全表扫也只有毫秒级；上真实列要连带迁移、回填、双写与前端字段切换，收益接近于零而风险不为零。等 `gen_history` 过万再启动，届时用同一条迁移套路（v4）即可

### S1-6 契约测试铺满 + CI 脚本
- **做法**：`test_contract.py` 扩到覆盖全部 89 个端点（至少 happy path + 关键错误码）；新增 `scripts/ci.ps1` 一次跑 pytest + verify_smoke
- **验收**：`ci.ps1` 通过；故意改坏一个字段名能被测试捕获
- **状态**：✅ 2026-10-30 完成（`scripts/` 实际放在 `tools/ci.ps1`）
  - `tests/test_endpoints_smoke.py`：从 `app.routes` **动态枚举** 35 个 GET 端点逐个请求，断言无 5xx（新增端点自动纳入，不用维护清单）；SSE 端点显式跳过并有护栏用例防蒙混
  - `tests/test_api_crud.py`：11 条写路径用例（分类/碎片/标签/提示词标记/图片动作/批量删除的"删得干净、关联不留孤儿"）
  - `tools/ci.ps1`：一条命令跑 pytest（**109 条**）+ verify_smoke（25 项），任一步失败即退出
  - **顺带揪出并修复 3 个真实 bug**：
    1. `list_categories` 把 `count_scope` 当成 `parent_id` 传给 `build_category_tree` → 画架侧栏分类树**永远是空的**（只有"全部图片"，4 个分类根本不显示）
    2. `delete_category` 不清 `PromptCategory`/`ImageCategory` 就直接删分类 → 外键约束开启后必抛 `FOREIGN KEY constraint failed`（删分类 500）
    3. 分类的图片计数把软删除的图也算进去 → 侧栏写 6 张、画廊实际只有 2 张；改为 join `gen_history` 并排除 `is_deleted=1`

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
- **状态**：✅ 2026-10-30 完成
  - `frontend/`：Vite 5 + Vue 3.5 + TS（strict）+ Pinia + TanStack Query v5，依赖 40 包、`npm install` 14s
  - `vite.config.ts` 代理 `/api` `/output` `/input` `/temp` → 8656；`build.outDir = ../static/v2`
  - `src/styles/tokens.css`：设计令牌（颜色/尺度/字阶），新页面只允许用变量，旧前端 11 个 CSS 文件里 6 种"面板底色"的写法不再蔓延
  - `src/api/client.ts` + `types.ts`：后端 JSON 契约的 TS 镜像，字段改名会先在契约测试里炸、再在编译期提示
  - `src/views/GalleryView.vue`：画廊第一版 —— 列表状态收敛成**一个缓存键**（彻底取代十几个 `window._galleryXxx` 裸变量）、标签交集/并集、只看缺失、搜索、分页、缺失角标
  - 实测（playwright）：卡片 10、标签 12、选 2 标签时 all=0 / any=3、0 个 JS 错误

### S2-2 画廊页（优先，痛点最集中）
- 迁移 `gallery.js`(734) + `imageViewer.js`(956)
- 虚拟滚动替代 50 条翻页
- TanStack Query 管列表/筛选/分页缓存，替掉手写 `window._galleryXxx` 与 30s 轮询
- 「文件缺失」角标与「仅看失效」筛选（接 S0-2）
- **状态**：✅ 2026-10-30 完成（虚拟滚动部分降级，见下）
  - `components/Lightbox.vue`：大图查看、`←`/`→` 翻页、`Esc` 关闭、右侧信息面板（分辨率/体积/来源/出图时间/提示词/标签/缺失提示），取代 `imageViewer.js` 的 956 行
  - 多选与批量条：卡片右上角勾选、全选本页、取消选择、下载选中、删除选中（走 `/api/history/batch_delete`，`useMutation` 成功后失效 `['history']` 缓存）
  - 卡片内联收藏（点击 ★ 直接调接口并刷新缓存），不再需要先开灯箱
  - `utils/format.ts`：体积/分辨率/出图时间/来源标签的格式化统一收口
  - **虚拟滚动暂缓**：当前 60 条/页，DOM 节点数在浏览器舒适区内；真正的瓶颈是"一次加载几百条缩略图"，等把 pageSize 提到 200+ 再上虚拟列表，避免为一个不存在的性能问题引入复杂度
  - 实测（playwright）：卡片 10、灯箱 1/10 显示完整信息、`→` 翻到 2/10、`Esc` 关闭、多选 2 张后批量条正确、0 个 JS 错误

### S2-3 提示词页
- 迁移 `prompt.js`(1591) + `category.js` + `tag.js`
- **状态**：🟡 2026-10-30 第一轮完成
  - 三栏布局：左（分类树 + 标签云）/ 中（列表 + 搜索 + 分页）/ 右（详情编辑）
  - 分类树拍平成一维带深度缩进 —— 层级只有两级，递归组件属于过度设计
  - 标签云抽成 `components/TagCloud.vue`，画廊与提示词页共用（交集/并集都在里面），并给标签区封了 `46vh` 高度，避免 95 个标签把侧栏撑满
  - 详情编辑：名称/标签/正向/负向/备注，`dirty` 计算属性判断未保存改动，撤销与保存按钮联动；保存走 `PUT /api/prompts/{id}` 并失效 `['prompts']`/`['prompt', id]` 缓存
  - 收藏 / 置顶 / 五星评级三个 mutation，成功后同步刷新列表与详情
  - 实测（playwright）：列表 331 条（50/页）、分类 4 个、标签 95 个、详情正常加载（提示词 540 字）、分类筛选 303 条、两标签 all=0 / any=2、0 个 JS 错误
  - **第二轮**（2026-10-30 完成）：多选（行内圆形勾选 + 全选本页）、批量收藏 / 批量出图 / 批量删除（走 `/api/prompts/batch_*`），导入导出入口（导出直开 `/api/prompts/export`，导入读 JSON 后 POST `/api/prompts/import`）
  - 批量条改成**底部居中浮条**：放在 340px 的列表栏里会被挤成竖排文字（"收/藏"、"批/量/出/图"），浮条宽度自适应且不占列表高度

### S2-4 出图闭环（原「组合器与换脸」，顺序调整）
- **调整原因**：新前端此前只有"浏览/整理"，缺了最核心的"选提示词 → 出图 → 画廊出现新图"闭环，功能上无法替代旧版。先把闭环补上，组合器/换脸留到 S2-4b。
- **状态**：✅ 2026-10-30 完成
  - `composables/useSettings.ts`：工作流/画质/方向，独立 `pb.*` 键持久化到 localStorage（不再和画廊筛选混在 UiState 里）
  - `composables/useGenerate.ts`：提交 `/api/run` 后用 **SSE**（`/api/jobs/events?ids=<id>`）跟踪进度，终态自动关连接并失效 `['history']` 缓存 —— 取代旧前端 1Hz 轮询（双 tab 就打双倍后端）
  - 提示词详情页顶部出图条：工作流下拉（默认取后端 `default`）、画质 2K~12K、横竖屏、🚀 出图、任务状态（排队中/生成中/完成/失败，中文化）
  - 顶栏加 ComfyUI 在线状态灯（10s 轮询 `/api/status`），离线时不会让人误以为能出图
  - **实测完整闭环**（playwright，真实跑了一张图）：状态灯「在线」→ 工作流 10 个可选 → 点出图 → `生成中…` → SSE 推送 `完成 1/1` → 画廊图片数 10 → **11**，0 个 JS 错误
- **S2-4b**：组合器第一轮（2026-10-30 完成）
  - 三栏：筛选（搜索/分类/标签）/ 碎片池（8 类分组，可折叠）/ 组合画布 + 预览 + 试跑
  - 画布严格按 `【类型】\n内容` 渲染，与后端 `composition.render` 完全一致；同类型只保留一个碎片（格式约束）
  - 试跑走 `/api/composer/run`；随机组合走 `/api/composer/batch_random_run`，**画布上的碎片作为 `fixed_fragments` 固定**，其余类型由后端随机填充
  - **碎片池懒加载**：线上有 2105 个碎片（提示词碎片 × 8 类 + 碎片库合并去重），全渲染会产生 6000+ DOM 节点；每组默认 30 个 + "展开全部"，DOM 降到 240
  - `useWorkflows` 抽成 composable，提示词页与组合器共用工作流列表与默认值填充逻辑
  - 实测（playwright）：8 个分组、2105 个碎片、点 8 个填满画布 8/8、预览格式正确、0 个 JS 错误
  - **第二轮**（2026-10-30 完成）：组合模板 —— 另存为 / 套用 / 删除 + 本地筛选
    - 画布槽位从"只存内容"改为 `{content, promptId, source}`：模板是**引用式**的（存 `prompt_id + 类型`），没有 prompt_id 就无法建立引用
    - 碎片库来源的碎片无法存进模板（后端 `FragmentRef.prompt_id` 必填），保存时明确提示"N 个碎片库碎片不会被保存"
    - 覆盖 381 个模板：下拉加本地筛选框（数据量小，不走接口）
    - **事故与恢复（需记录）**：验证脚本删除时用"取下拉最后一项"定位，结果删掉了一个真实模板（`侧身立于花海之中`，8 个碎片）。已从 `文档/backups/提示词收藏.db.pre_s1_2_*` 备份查出并回写，新 id=385、碎片 8 条完整，模板总数回到 381。**教训：验证脚本做删除类操作，必须按"自己刚创建的那条记录"精确匹配，不能按列表位置取。**
  - **第三轮待做**：碎片库管理页
- **S2-4c** 批量换脸（2026-10-30 完成）
  - `components/ImagePicker.vue`：从画廊多选图片，**标出选择顺序**（1:1 配对就是按两侧选中顺序一一对应，顺序是有效信息）；`missing=0` 过滤掉已失效的图
  - `views/FaceswapView.vue`：双选择器 + 设置面板（工作流 / 节点映射 / 组合方式 / 种子 / 提示词）
  - **节点映射提前探测**：选定工作流后立刻 `POST /api/faceswap/nodes`，把 LoadImage 节点显示出来；工作流不是双图（只有 1 个或 0 个 LoadImage）时直接红色提示并禁用提交 —— 选到文生图工作流是常见误操作，不该等提交才报 400
  - 组合方式：**全组合**（主图 × 参考图笛卡尔积）与 **1:1 配对**（按选中顺序），数量不等时禁用提交并说明原因
  - 种子三模式（固定 / 递增 / 随机）、提示词留空用后端内置换脸提示
  - 实测（playwright）：选 2×2 → 全组合 4 张 / 1:1 → 2 张；主图加到 3 张时 1:1 报数量不匹配且提交按钮禁用；换上双图工作流后节点映射显示「主图 4 / 参考 9，2 个 LoadImage」、提交按钮可用；0 个 JS 错误

### S2-5 任务中心
- **状态**：✅ 2026-10-30 完成
  - `views/JobCenterView.vue`：任务列表（类型徽章 / 标题 / 状态 / 进度条 / 耗时 / 取消）+ 展开看每条明细（缩略图、状态、seed、错误信息）
  - **走 SSE 而非轮询**：后端本来就广播任务状态变化（`/api/jobs/events`），前端再定时拉 `/api/jobs` 是把已推过来的信息再问一遍
  - 顶栏「任务」页签带进行中数量角标（只查 active、5 秒一次，不另开长连接）
  - 耗时格式化到天级（历史任务动辄几百分钟，"485m01s" 读不出来）
  - 实测（playwright）：60 个任务卡片、状态中文化、展开明细内容正确、只看进行中过滤正确、0 个 JS 错误

### S2-6 切换根路径（新前端接管 8656）
- **状态**：✅ 2026-10-30 完成
  - 构建产物输出到 `static_next/`（`npm run build`，1.8s；产物 191KB / gzip 62KB，对比旧前端 8.2k 行 JS + 3.8k 行 CSS）
  - `main.py` 按**目录是否存在**决定用哪套前端，不靠开关也不靠环境变量：
    - `static_next/index.html` 存在 → 根路径走新前端（`/assets` 挂构建资源，404 回落到新 index.html）
    - 不存在 → 根路径走旧前端（`static/`，原逻辑原样保留）
  - **回退方式**：把 `static_next` 改名（如 `static_next.off`）再重启服务即可，零代码改动、零配置残留
  - **没有把旧前端挂到 `/legacy`**：它内部用绝对路径引用资源（`/base.css`、`/favicon.svg`），挪到子路径后这些引用会打到新前端上直接白屏；"目录开关"方案让旧前端始终待在根路径，兼容性最好
  - 旧前端文件（`static/`）**保留在磁盘与 git 里**，作为回退保障；确认不再需要时再删
  - 新前端补了内联 SVG favicon（避免控制台 404），标题从「Prompt Browser · 新前端」改为正式名
  - 实测：根路径返回新 index.html、`/assets/*.js` 200（163KB）、`/assets/*.css` 200；playwright 打开 8656 → 标题 `Prompt Browser`、画廊 11 张卡片、16 个标签、5 个页签全部可切换、**0 个 JS 错误**


### 工程债 C：Pydantic 出入参（核心端点）
- **状态**：🟡 2026-10-30 部分完成 —— 给前端实际依赖的 **11 个端点**加了响应模型，其余端点仍返回裸 dict
  - 新增 `schemas.py`：HistoryItem / PromptDetail / TagRow / CategoryNode / FragmentRow / JobSnapshot / StatsResponse / WorkflowListResponse 等 22 个模型，字段与 `frontend/src/api/types.ts` 一一对应
  - 加了 `response_model` 的端点：`/history`、`/history/facets`、`/history/ids`、`/prompts`、`/prompts/{id}`、`/tags`、`/categories`、`/fragments`、`/jobs`、`/stats`、`/workflows`
  - **响应会按模型过滤**：模型里没声明的字段会被丢掉 —— 这既是保护（契约漂移在首次请求就暴露），也是风险（模型漏字段前端就拿 undefined），所以必须有测试盯着
  - **新增 `tests/test_schemas.py`（8 条）**：用正则解析前端 types.ts 的 interface，断言「前端声明的字段后端模型都有」+「登记的模型前端都有对应 interface」+ 实际请求各端点断言关键字段在响应里
  - **顺带修掉 3 个真实问题**：
    1. `prompts.py` 里有一个**旧的本地 `class PromptDetail`**，覆盖了从 schemas 导入的同名类；它字段更少（没有 categories/tags_detail/updated_at），一旦挂上 response_model 就会把前端要的分类关联字段**过滤掉** —— 提示词详情页的分类高亮会失效
    2. `view_url` 后端可能返回 `None`，前端类型却声明 `string`；响应模型直接报 500。模型与前端类型都改为可空
    3. 任务的 `extra` 存的是 **JSON 字符串**而非对象，前端类型声明是对象；响应模型校验失败导致 `/api/jobs` 500、任务中心空白。改为对外还原成对象（`_parse_extra`）
  - **教训**：加 `response_model` 前必须先确认模块里没有同名类覆盖 —— Python 的模块级名字是"后定义覆盖先定义"，`from schemas import PromptDetail` 会被后面的 `class PromptDetail` 顶掉，而且不报错
  - 未做：其余 58 个端点、请求体（Pydantic 请求模型）与 service 层拆分（沿用原计划随页做）
### S2-7 收尾（可选）
- 删除 `static/*.js` 手写模块与 `?v=N` 版本号机制，静态目录只留构建产物与 vendor

### S2-8 前端测试 + 类型检查 + CI 扩展
- **状态**：✅ 2026-10-30 完成
  - **vitest + @vue/test-utils + happy-dom**，36 条用例（`format` / `buildQuery` / `TagCloud` / `Lightbox` / `ImagePicker`）。挑的都是**最容易回归的判断**：标签云隐藏零计数但保留已选项、灯箱键盘翻页不越界、ImagePicker 保留选择顺序（1:1 配对依赖它）、`buildQuery` 必须保留 `0` 与 `false`
  - **vue-tsc --noEmit 进 CI** —— TS strict 之前只在编辑器里生效，命令行从没跑过；第一次跑就抓出 6 个类型错误，其中一个是真实功能失效：`ComposerView` 里 `canvas[type] === item.content` 拿 `CanvasSlot` 和 `string` 比，**"该碎片已在画布里"的高亮一直是坏的**
  - **`tests/e2e/run_e2e.py`**：数据库副本 + 临时端口 8766 + Playwright，跑五个页签共 13 项断言（渲染、筛选联动、详情加载、碎片填入画布、预览格式、无 JS 错误）。跑在副本上，不碰线上数据、不占 8656
  - **`tools/ci.ps1` 扩到五道关**：pytest → verify_smoke → vue-tsc → vitest → vite build（附加 E2E）。前端依赖缺失时自动跳过前端三关并说明原因
  - 之前每次改前端都是"写完 → playwright 手验 → 脚本删掉"，没有回归保护；现在有了

---

## 5.5 尚未覆盖的功能（端点覆盖核对结果）

后端 88 个端点里，新前端**没有入口**的有 37 个。按性质分两类：

**A. 功能回退（旧版有、新版没有，用户会察觉）**

| 功能 | 端点 | 优先级 |
|---|---|---|
| 🧹 清理失效 | `history/cleanup_missing` | ✅ 已补（2026-10-30，见下） |
| 画廊分面筛选（来源/日期/模型/方向） | `history/facets` | 高 |
| 全选全部（跨页） | `history/ids` | 中 |
| 分类管理（增删改 + 关联提示词） | `categories/*` | 中 |
| 标签管理（增删改 + 关联提示词） | `tags/*` | 中 |
| 碎片库管理 | `fragments` CRUD | 中 |
| 自动分类 | `categories/auto-classify` | 中 |
| 批量补跑（给没图的提示词出图） | `generate_missing/*` | 中 |
| 文件浏览器（换脸从磁盘选图） | `fs/list` `fs/image` `fs/thumb` | 中 |
| 统计 | `stats` | 低 |

**B. 新功能欠账**：裸文本跑图（`run_text`）、模板批量导入（`templates/batch_import`）、组合器第三轮

**C. 工程债**：`S1-4` Pydantic 出入参（88 个端点响应仍是裸 dict）、`S2-7` 删旧前端 8.2k 行死代码、设计系统的基础组件（`tokens.css` 已有，组件未抽）





### P0-7 提示词关联分类
- **状态**：✅ 2026-10-30 完成
  - 提示词详情页新增「分类」区块：所有分类以 chip 列出，点一下关联 / 再点取消；已关联的用分类色实心高亮
  - 走 `POST/DELETE /api/categories/{cat_id}/prompts/{prompt_id}` —— 分类**没有文本字段**，关联只存在于 `prompt_categories` 表，不像标签那样"改文本再同步"
  - 成功后同时失效 `['prompt', id]` / `['prompts']` / `['categories']` 三个缓存（详情、列表、分类计数都会变）
  - 组件测试 4 条锁住：列出所有分类、已关联高亮、点未关联走 POST、点已关联走 DELETE
  - 实测：详情页列出 4 个分类（测试分类/组合提示词/单项提示词/零散提示词），0 个 JS 错误




### P0-10 批量补跑缺图
- **状态**：✅ 2026-10-30 完成
  - 提示词页工具栏新增「补跑缺图」，弹出 `components/MissingRunPanel.vue`：列出所有「有提示词但没出图」的条目（缺图判定在后端按 DB 关联做，前端不自己判断）
  - 默认全选，可逐条取消；顶部可换工作流 / 画质 / 横竖屏（与出图条共用同一份全局设置）
  - 提交走 `POST /api/generate_missing`，带上勾选的 `prompt_ids`；后端与缺图集合取交集，不会重复出图
  - 提交后用 SSE 跟踪任务进度（「任务」页看），完成自动刷新画廊
  - 每条提示词用的是**它自己保存的参数**（steps/cfg/采样器/分辨率），面板只决定工作流与画幅
  - 组件测试 4 条：列出缺图、默认全选、取消勾选计数变化、提交带 prompt_ids 与工作流
  - 实测：生产库 331 条提示词里 **326 条缺图**，面板正确列出 326 条、默认全选、按钮显示「补跑 326 条」、0 个 JS 错误（**未点击提交**，没有触发任何出图）


### P0-11 换脸从磁盘选图（文件浏览器）
- **状态**：✅ 2026-10-30 完成
  - 新增 `components/FilePicker.vue`：左侧子目录列表 + 右侧图片网格 + 路径栏 + 「⬆ 上级」+ 快速跳转（ComfyUI/output、工作流目录、用户目录、盘符）
  - 换脸页的主图/参考图各加一个「📁 磁盘」按钮，**画廊素材与磁盘素材可以混用** —— 后端 `faceswap/batch` 本来就同时接受 `main_ids/main_paths` 与 `ref_ids/ref_paths`
  - 打开时**自动进入 ComfyUI/output**（后端 path 为空时只返回盘符列表，停在根目录的话用户要先点一次盘符才看得到图，而换脸最常用的素材就在 output 里）
  - 不做递归目录树：深目录会卡，改成"逐级进入"的平铺导航
  - 组件测试 4 条：列出图片与子目录、点图切换选中、确定后 emit 路径、打开时带入已有选择
  - 实测：自动进入 `F:\ComfyUI_Migration\output`、列出 11 张图、选中后计数变 1、确定后按钮显示「📁 磁盘 1」、0 个 JS 错误（**未提交换脸任务**）
### P0-8 碎片库管理（组合器第三轮）
- **状态**：✅ 2026-10-30 完成
  - 管理页新增第三个页签「碎片库」：搜索 + 按类型筛选 + 新建（类型/名称/内容）+ 列表（类型徽章/名称/内容/使用次数）+ 就地编辑 + 删除
  - 类型下拉固定 8 类；抽出 `src/constants.ts` 的 `FRAGMENT_TYPES` 供组合器与管理页共用，消除"同一份类型列表写两遍、后端改了前端不知道"的风险
  - 组合器页面改为引用共享常量（原来本地硬编码一份）
  - 组件测试 2 条：碎片库页签列出碎片、新增碎片调 POST /api/fragments
  - 实测：6 个碎片正确列出、类型徽章与筛选正常、0 个 JS 错误（未做增删改）
### P0-9 自动分类
- **状态**：✅ 2026-10-30 完成
  - **管理页 → 分类页签**：「一键自动分类」按钮，全量重算所有提示词的类型分类（组合 / 单项 / 零散，按正文里【类型】的数量判定），完成后提示「N 条提示词的分类发生变化」
  - **提示词详情页**：分类区块标题右侧「自动归类」按钮，只重算当前这条
  - 两个入口都会同时失效 `['prompt', id]` / `['prompts']` / `['categories']` 三个缓存（详情、列表、分类计数都会变）
  - 组件测试 2 条：管理页调全量端点、详情页调单条端点
  - 实测：两个入口按钮就位；详情页点「自动归类」后高亮分类仍为 1 个（幂等，结果不变）、0 个 JS 错误
### P0-13 提示词标签选择器
- **状态**：✅ 2026-10-30 完成
  - 详情页的标签从「逗号分隔文本框」换成 `components/TagInput.vue`：已选标签是 chip（点 ✕ 移除），下方输入框可输入关键字从库中点选，也可直接回车创建新标签
  - **只改本地草稿、由「保存」统一落库** —— 不直接调 `/api/tags/{id}/prompts/{id}` 关联端点。这与后端既有的双写设计一致（文本是唯一事实来源，保存时 `sync_prompt_tags()` 同步关联表）；两套写入路径并存必然打架（一边改文本一边改关联，下次同步会把关联冲掉）
  - 拆分规则与后端 `split_tags` 一致：只按中英文逗号与分号拆，**不拆空格**（库里 "Moody Photography" 是单个标签）
  - 候选**按使用数降序**：库里 178 个标签有 100mm、1128x2008 这类尺寸参数标签，不排序时空输入弹出来的全是它们，真正会用的「女性/古风/包」反而看不到
  - 组件测试 7 条：展示已选、候选排除已选、关键字过滤、点候选追加、回车建新标签、点叉移除、重复添加被忽略
  - 实测：某提示词 9 个已选 chip、输入「古」出 2 个候选、点候选后 10 个 chip 且出现「有未保存的修改」、0 个 JS 错误（未点保存，生产数据未变）
### P0-4/5 分类与标签管理面板
- **状态**：✅ 2026-10-30 完成（增删改部分）
  - 新增「管理」页签，内含 分类 / 标签 两个页签 —— 两件事结构一样（列表 + 新建 + 改名 + 删除 + 配色），合并成一个页面；旧前端把它们散在三个弹窗里，找入口要翻半天
  - 新建：名称输入 + 8 色板 + 添加；改名：**点名称就地编辑**（不用弹窗）；删除：带确认，分类会提示"会解除与所有提示词的关联"
  - 标签页加「只看未使用」过滤 —— 库里 178 个标签有 80 多个是零计数孤儿（历史体系遗留），清理它们时用得上
  - 组件测试 4 条：默认展示分类、新建调 POST、点名称进入编辑态、只看未使用过滤正确
  - 实测：分类 4 行 / 标签 178 行、内联编辑可用、0 个 JS 错误
  - **待做**：给提示词**关联**分类（`categories/{cat_id}/prompts/{prompt_id}`）—— 应放在提示词详情页而不是管理页
### P0-3 全选全部（跨页）
- **状态**：✅ 2026-10-30 完成
  - 工具栏常驻「全选全部 N 张」：走 `/api/history/ids`（不分页）拉当前筛选下的全部 id
  - 放在工具栏而不是批量条里 —— 批量条只在"已有选择"时出现，而"全选全部"恰恰是**没有选择时**才用得上的入口
  - 抽出 `historyFilterParams()`，列表查询与全选共用同一份筛选参数，避免两处口径漂移
  - 组件测试 1 条锁住：点「全选全部」确实请求了 `/api/history/ids`
  - 实测：工具栏按钮「全选全部 11 张」→ 批量条「已选 11 张」→ 确认命中 ids 接口 → 取消后浮条消失，0 个 JS 错误
### P0-2 画廊分面筛选
- **状态**：✅ 2026-10-30 完成
  - 侧栏新增 4 组分面：来源 / 年月 / 模型 / 方向，每维单选、再点取消；chip 显示各值计数
  - 计数取自 `/api/history/facets`，后端按「当前筛选（不含分面维度自身）」计算，避免"数出来的和筛出来的对不上"
  - 长模型名（整个 safetensors 文件名）截断显示，`title` 保留完整值
  - 组件测试 2 条锁住不变量：点 chip 会把该维度加进查询参数、再点一次取消
  - 实测：点「comfyui_sync」→ 11 张变 3 张，再点恢复 11 张，0 个 JS 错误
### P0-1 清理失效（新前端补回 S0-1 的功能）
- **状态**：✅ 2026-10-30 完成
  - 画廊工具栏新增「🧹 清理失效」，两段式：**先 dry_run 预览**（数量 + 样本文件名 + 全部失效警告）→ 用户确认 → `dry_run=false&confirm=true` 执行；后端熔断（缺失占比过半）时直接拒绝并提示
  - 清理范围 = 当前筛选，但**刻意不传 `missing`**：「只看文件缺失」是"待清理清单"不是"清理范围"，带上它预览恒为 0，用户会以为功能坏了
  - 新增 `composables/useToast.ts` + `components/ToastHost.vue`：全局轻提示，替代旧前端的 `window.showToast()` 全局函数
  - 组件测试 3 条锁住不变量：必须先发 dry_run、不带 confirm、执行前不带 missing
  - 实测：生产库点击 → toast「扫描 11 条记录，文件均存在，无需清理」，0 个 JS 错误

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
- [x] S0-3 删前端 30s `history_sync`
- [x] S0-4 修 `_job_index` 失效
- [x] S0-5 合并筛选构造器
- [x] S0-6 墓碑回收自动化 + 备份归档
- [x] S0-7 gitignore / DB 停止跟踪

### 阶段 1
- [x] S1-1 迁移框架化
- [x] S1-2 标签收敛
- [x] S1-3 写入路径收敛（原三态可见性方案已调整）
- [ ] S1-4 service 层 + Pydantic
- [x] S1-5 索引（派生列部分降级，待数据量上来再做）
- [x] S1-6 契约测试铺满 + CI

### 阶段 2
- [x] S2-1 工程骨架
- [x] S2-2 画廊页（虚拟滚动暂缓）
- [x] S2-3 提示词页（含批量操作与导入导出）
- [x] S2-4 出图闭环（SSE 进度 + 工作流/画质/方向 + 状态灯）
- [x] S2-4c 批量换脸
- [x] S2-5 任务中心
- [x] S2-6 切换根路径（新前端接管 8656，回退=改名 static_next 目录）
- [ ] S2-7 删除旧前端 static/*.js（确认不再需要后）
- [x] S2-8 前端测试 + 类型检查 + CI 扩展


### 工程债 A：设计系统基础组件抽取
- **状态**：✅ 2026-10-30 完成
  - **不抽 Button/Select**：Vue 里 `<button class="btn">` 更灵活，抽成组件反而要透传 slot 与 class，收益低于成本
  - **抽 `components/Modal.vue`**：此前 `MissingRunPanel` 与 `FilePicker` 各写了一份 overlay + panel + head + foot（结构几乎一样、样式各写一遍）。统一后：遮罩/圆角/阴影/ESC 关闭只有一处实现；`Teleport to body` 避免被父容器 overflow/transform 裁掉；支持 `width`/`height` 与 `head`/`actions`/`footer` 三个 slot
  - **抽 `components/EmptyState.vue`**：散落各页面的 **15 处** `.empty` div，样式各写一遍、文案格式也不统一。统一后支持 `text`/`icon`/`hint`/`size`(sm|big)/`compact`（行内提示用）
  - `useToast` + `ToastHost`（S2-8 已做）构成第三块：全局轻提示
  - 替换清单：ImagePicker / TagCloud / ComposerView / GalleryView / JobCenterView / ManageView / PromptView / MissingRunPanel / FilePicker
  - **踩到两个 Vue 3 的坑**（都由 `vue-tsc` 抓到）：
    1. `text="{{ expr }}"` 属性内插值在 Vue 3 已被移除，必须写 `:text="expr"`（TagCloud 的空状态文案一开始渲染成了字面量）
    2. `Teleport` 的内容不在 wrapper DOM 里，组件测试必须加 `stubs: { teleport: true }`，否则 `findAll` 一条都查不到（MissingRunPanel / FilePicker 的测试因此全灭）
  - 验证：CI 五道关全绿；playwright 实测磁盘弹层与补跑弹层渲染正常、Teleport 挂在 body 下、**Esc 可关闭**（Modal 新增能力）、326 条补跑列表完整、0 个 JS 错误