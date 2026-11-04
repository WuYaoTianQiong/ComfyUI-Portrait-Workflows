# 画室 · Atelier

ComfyUI 的提示词资产与出图工作台。四条链路：**资产库**（提示词 / 结构性碎片 / 模板 / 标签 / 分类）、
**生产**（工作流参数注入、单次·批量·随机出图、换脸与遮罩）、**归档**（图库、软删、缺图自愈）、
**调度**（任务状态机 + 单写者线程 + SSE）。

单机工具：FastAPI + Peewee/SQLite 后端，Vue3 + TS 前端，通过 HTTP 与 ComfyUI（默认 `127.0.0.1:8188`）交互，
并把 `ComfyUI/output|input|temp` 挂成静态目录直读图片。

---

## 快速开始

```powershell
# 启动（会自动释放占用 8656 的旧进程）
.\启动.bat
# 等价于：python main.py  →  http://127.0.0.1:8656

# 全量校验（五道关 + E2E，改完必跑）
powershell -NoProfile -ExecutionPolicy Bypass -File tools\ci.ps1
```

前端源码在 `frontend/`，构建产物输出到 `web/`：

```powershell
cd frontend
npm install          # 首次
npm run build        # 产出 ../web（后端挂到 /）
npm run dev          # 开发模式，5173 端口代理到 8656
```

---

## 目录结构

```
atelier/
├─ main.py              # 启动壳：把项目根放进 sys.path 后拉起 uvicorn
├─ app/                 # 应用包（唯一的代码根）
│  ├─ config.py         # pydantic-settings；app_root / library_root 两个根，见下
│  ├─ models.py         # Peewee 模型（含 schema 迁移）
│  ├─ schemas.py        # Pydantic 出入参
│  ├─ main.py           # FastAPI 实例、中间件、路由注册、静态挂载
│  ├─ routers/          # 只做 HTTP 入参/出参，不写业务（reference_* 为 AI 参考图库）
│  └─ services/         # 业务与外部交互（reference_library / reference_sheet / uploads 为参考库链路）
├─ frontend/            # Vue3 + TS 源码
├─ web/                 # 前端构建产物（不入库）
├─ tests/               # pytest 契约/单元测试；tests/e2e 为 Playwright
├─ tools/               # ci.ps1 / smoke.py / gen_api_types.py / backup_db.py / cleanup_tombstones.py / run_prompts.py
├─ 启动.bat             # 唯一中文入口（双击即用）
└─ logs/                # 运行日志（不入库）
```

### 两个"根"别混用

| 名字 | 含义 | 放什么 |
|---|---|---|
| `settings.app_root` | 本项目目录 `<库>/脚本/atelier` | `web/`、`logs/` |
| `settings.library_root` | ComfyUI 工作流库 `<库>`（自动跳过一层「脚本」） | `*.json` 工作流、`文档/提示词收藏.db`、`thumbnails/`、`painted_masks/`、`历史工作流/` |

> 工作流自动扫描**只覆盖库根目录**；`历史工作流/` 或任意磁盘目录的工作流，在
> 「分类与标签 → 工作流」里上传自定义 JSON 后即可在下拉中选择（内容存在本机 localStorage）。

包化前二者恰好是同一目录，所以历史上混用过一个 `project_root`；现在已彻底拆开。

---

## 参考图库 Web（gallery-web）

`gallery-web/` 是从上游 `ai-pose-gallery-zh` 接管进来的 React 工作台，由本后端挂在 `/ref-web` 子路径下，
与 atelier 同端口访问（不再单独跑 8760 静态服务）。

- 源码：`gallery-web/src/`；产物：`gallery-web/dist/`（**必须随源码一起提交**，运行时不需要 Node）
- 构建：`cd gallery-web && pnpm run build:prod`（先由 `scripts/clean-dist.mjs` 清空 `dist/`，
  再执行 `vite build --base=/ref-web/`，避免旧 hash 产物堆积；Git Bash 下加 `MSYS_NO_PATHCONV=1`，
  否则基路径会被改写成 Git 安装路径）
- 素材：`/data`、`/thumbs`、`/img` 三个挂载指向上游只读目录（junction 经 `_resolve_if_reparse`），不复制、不入库
- 升级：来源、pin 的 commit 与合并步骤见 `gallery-web/UPSTREAM.md`；改完 `src/` 必须重新构建 `dist/`

---

## 配置

全部通过环境变量覆盖，前缀 `ATELIER_`（见 `app/config.py`）：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ATELIER_HOST` / `ATELIER_PORT` | `127.0.0.1` / `8656` | 监听地址 |
| `ATELIER_COMFYUI_API` | `http://127.0.0.1:8188` | ComfyUI 地址 |
| `ATELIER_COMFYUI_ROOT_ENV` | 自动向上探测 | 手动指定 ComfyUI 根目录 |
| `ATELIER_COMFYUI_OUTPUT_DIR` | `<comfyui_root>/output` | 出图根目录；ComfyUI 用 `--output-directory` 时指向同一目录 |
| `ATELIER_DB_PATH` | `<library_root>/文档/提示词收藏.db` | 主库 |
| `ATELIER_THUMBNAIL_DIR` | `<library_root>/thumbnails` | 缩略图缓存 |
| `ATELIER_NO_BROWSER` | 未设置 | 设为 `1` 时启动不自动开浏览器（CI 用） |
| `ATELIER_REFERENCE_ENABLED` | `1` | `0` = 参考库路由全部 404（整体回滚） |
| `ATELIER_REFERENCE_ROOT` | `<library_root>/ai-pose-gallery-zh` | 上游只读参考库（junction，勿用 `../custom_nodes/...`） |
| `ATELIER_REFERENCE_ALLOW_NSFW` | `0` | `1` = 允许查看敏感集合 |
| `ATELIER_REFERENCE_PAGE_SIZE` | `60` | 参考库默认分页 |
| `ATELIER_REFERENCE_NSFW_POSE_SYSTEMS` | `全身单人・性感系,双人缠绵` | 逗号分隔的敏感姿势体系 |
| `ATELIER_REFERENCE_NSFW_COSTUME_CATEGORIES` | `内衣・睡衣,性感穿搭` | 逗号分隔的敏感服装分类 |

### 出图归档位置

顶栏「出图：…」按钮可设置**相对 ComfyUI output 的子目录**，留空时保持旧的平铺行为。
支持变量：`{date}`、`{month}`、`{year}`、`{workflow}`、`{job_id}`、`{quality}`、`{orientation}`，
例如 `{date}/{workflow}` 会落到 `output/2026-11-01/工作流名/`。「浏览…」可在 output 内逐级选择或新建目录；
目录由后端校验（拒绝绝对路径、盘符与 `..`），磁盘兜底扫描会递归读取子目录，弹窗里的「打开出图目录」
直接在资源管理器打开当前根目录。

出图根目录由 ComfyUI 决定（这里只显示、不在这里改）；需要换盘/换根时设置 `ATELIER_COMFYUI_OUTPUT_DIR`，
并让 ComfyUI 使用同一 output 目录。任意图片所在处（画廊卡片、灯箱、提示词出图历史、任务中心、
组合结果、对比、图像选择器）都提供「定位」，灯箱信息卡也会显示 `output/子目录/文件名`。

### 替换碎片出图

「替换碎片」不写回提示词库。生成的图片**不挂原提示词**：`prompt_id` 为空，实际替换文本写入
`prompt_params.prompt`，按「临时提示词」展示，并用 `source_prompt_id/source_prompt_name` 保留来源；
画廊卡片会标「替换」。单条提示词详情和勾选后的批量栏都有入口。

弹窗会记住上次的碎片类型、替换内容、范围与“缺少时跳过/追加”策略；缺少目标类型时可选「追加」，
在末尾补一段 `【类型】\n内容`，而不是只能跳过。替换输入框和候选列表按弹窗高度弹性分配。

### 批量提交

提示词批量、组合器随机批量、换脸批量都是**后台队列**：接口只建任务并立即返回 `job_id`，
由 `job-submitter` 线程串行 push 到 ComfyUI；进度在任务页 / 结果中心看。
服务重启时尚未提交的条目会标为「提交中断」，可在任务页用「重试」重新入队。

---

## 数据与备份

- 主库：`<library_root>/文档/提示词收藏.db`（WAL 模式）。
- 每次启动会**在线备份**（`sqlite3.backup()`，不会漏掉 WAL）到 `文档/backups/`，并按数量轮转；
  历史手工备份归档在 `backups/legacy/`，不参与轮转。
- 启动同时回收超过保留期的**墓碑**（`is_deleted=1` 且超期）。活记录一行不碰。
- 手动备份：`python tools/backup_db.py --tag before_xxx`；清墓碑：`python tools/cleanup_tombstones.py`。

**改库前必须备份**，任何 schema 变更都要走 `app/models.py` 的 `MIGRATIONS` 列表（版本号只增不改）。

---

## 测试与 CI

```powershell
python -m pytest -q          # 契约 + 单元（临时库，绝不碰生产库）
python tools\smoke.py        # 真起 uvicorn（库副本 + 临时端口），打关键接口并扫日志
python tests\e2e\run_e2e.py  # Playwright 过主要页签（含批量超分）
```

`tools/ci.ps1` 串起五道关：pytest → vue-tsc → vitest → vite build → smoke（+ E2E）。
**静态检查发现不了启动期崩溃和运行期 500，改完后端必须跑 ci.ps1。**

---

## 约定

- 命名规范见 `../文档/命名规范.md`：术语表、目录/文件/符号/API/数据库/前端六层规则。
- 一次一批：改名与改行为分开提交，避免回归时无法归因。
- Windows 坑：项目常通过 junction 访问（跨卷 `SYMLINKD`），`Path.exists()/stat()` 会抛 `WinError 448`，
  必须走 `app/services/paths.py::_resolve_if_reparse`。
- 仓库文件是 **CRLF**，写脚本做批量替换时要用 `\r?\n` 兼容，别只匹配 `\n`。
- 前端 API 类型**不手写**：`schemas.py` → `frontend/openapi.json` → `frontend/src/api/openapi.d.ts` → `types.ts`（别名层）。
  改了 `schemas.py` 或路由后执行 `python tools/gen_api_types.py`；忘记时 `tests/test_openapi_snapshot.py` 会失败。
