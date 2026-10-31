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
│  ├─ routers/          # 只做 HTTP 入参/出参，不写业务
│  └─ services/         # 业务与外部交互（工作流解析、任务状态机、缩略图…）
├─ frontend/            # Vue3 + TS 源码
├─ web/                 # 前端构建产物（不入库）
├─ tests/               # pytest 契约/单元测试；tests/e2e 为 Playwright
├─ tools/               # ci.ps1 / smoke.py / backup_db.py / cleanup_tombstones.py / run_prompts.py
├─ 启动.bat             # 唯一中文入口（双击即用）
└─ logs/                # 运行日志（不入库）
```

### 两个"根"别混用

| 名字 | 含义 | 放什么 |
|---|---|---|
| `settings.app_root` | 本项目目录 `<库>/脚本/atelier` | `web/`、`logs/` |
| `settings.library_root` | ComfyUI 工作流库 `<库>`（自动跳过一层「脚本」） | `*.json` 工作流、`文档/提示词收藏.db`、`thumbnails/`、`painted_masks/`、`废弃工作流/` |

包化前二者恰好是同一目录，所以历史上混用过一个 `project_root`；现在已彻底拆开。

---

## 配置

全部通过环境变量覆盖，前缀 `ATELIER_`（见 `app/config.py`）：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ATELIER_HOST` / `ATELIER_PORT` | `127.0.0.1` / `8656` | 监听地址 |
| `ATELIER_COMFYUI_API` | `http://127.0.0.1:8188` | ComfyUI 地址 |
| `ATELIER_COMFYUI_ROOT_ENV` | 自动向上探测 | 手动指定 ComfyUI 根目录 |
| `ATELIER_DB_PATH` | `<library_root>/文档/提示词收藏.db` | 主库 |
| `ATELIER_THUMBNAIL_DIR` | `<library_root>/thumbnails` | 缩略图缓存 |
| `ATELIER_NO_BROWSER` | 未设置 | 设为 `1` 时启动不自动开浏览器（CI 用） |

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
python tests\e2e\run_e2e.py  # Playwright 过 7 个页签
```

`tools/ci.ps1` 串起五道关：pytest → vue-tsc → vitest → vite build → smoke（+ E2E）。
**静态检查发现不了启动期崩溃和运行期 500，改完后端必须跑 ci.ps1。**

---

## 约定

- 命名规范见 `../文档/命名规范.md`：术语表、目录/文件/符号/API/数据库/前端六层规则。
- 一次一批：改名与改行为分开提交，避免回归时无法归因。
- Windows 坑：项目常通过 junction 访问（跨卷 `SYMLINKD`），`Path.exists()/stat()` 会抛 `WinError 448`，
  必须走 `app/services/helpers.py::_resolve_if_reparse`。
- 仓库文件是 **CRLF**，写脚本做批量替换时要用 `\r?\n` 兼容，别只匹配 `\n`。
