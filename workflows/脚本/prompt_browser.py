#!/usr/bin/env python3
"""
Prompt Browser + ComfyUI Launcher v3
- 提示词 CRUD
- 工作流选择器（自定义 UI，无原生下拉）
- 单图/批量/变体生成，支持刷新续跑
- 服务端持久化任务 + 历史同步
- 零依赖，仅 Python 标准库
"""

import sys, os, json, sqlite3, html, urllib.request, urllib.error, webbrowser
import threading, time, traceback, mimetypes
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote, quote
from typing import Optional, Any
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager

# ======== 配置 ========
HOST = "127.0.0.1"
PORT = 8653
COMFYUI_API = "http://127.0.0.1:8188"

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DB_PATH = str(PROJECT_ROOT / "文档" / "提示词收藏.db")
STATIC_DIR = SCRIPT_DIR / "static"

# 批量生成停止标志（线程安全 Event，适配多线程服务器）
batch_stop_flag = threading.Event()

# widget 名称顺序缓存
_widget_name_cache: dict[str, list[tuple[str, int]]] = {}


# ===================================================================
# 数据库
# ===================================================================

def ensure_db():
    """如果数据库不存在，则创建 prompts 表。"""
    db_file = Path(DB_PATH)
    if db_file.exists():
        return
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            prompt TEXT,
            negative_prompt TEXT,
            steps INTEGER,
            cfg_scale REAL,
            sampler TEXT,
            seed INTEGER,
            model TEXT,
            width INTEGER,
            height INTEGER,
            tags TEXT,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def init_db():
    """启动时确保 schema 完整。"""
    ensure_db()
    with get_db_rw() as conn:
        # 旧表迁移：追加 updated_at
        cols = [r[1] for r in conn.execute("PRAGMA table_info(prompts)").fetchall()]
        if "updated_at" not in cols:
            conn.execute("ALTER TABLE prompts ADD COLUMN updated_at TIMESTAMP")
            conn.execute("UPDATE prompts SET updated_at = created_at WHERE updated_at IS NULL")

        # 任务表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gen_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL,
                title TEXT,
                total INTEGER DEFAULT 0,
                done_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                items TEXT,
                workflow_path TEXT,
                orientation TEXT,
                quality TEXT,
                extra TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 历史表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gen_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER,
                prompt_id INTEGER,
                comfyui_prompt_id TEXT,
                filename TEXT,
                subfolder TEXT,
                img_type TEXT,
                view_url TEXT,
                preview TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                source TEXT DEFAULT 'local'
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_history_img
            ON gen_history(filename, subfolder, img_type)
        """)
        conn.commit()


@contextmanager
def get_db():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_db_rw():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# -------------------------------------------------------------------
# 提示词 CRUD
# -------------------------------------------------------------------

def list_prompts(search: str = "", tag: str = "") -> list[dict]:
    with get_db() as conn:
        conditions = []
        params: list[Any] = []
        if search:
            conditions.append("(prompt LIKE ? OR tags LIKE ? OR note LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like, like])
        if tag:
            conditions.append("tags LIKE ?")
            params.append(f"%{tag}%")
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"""
            SELECT id, substr(prompt, 1, 60) AS prompt_preview, tags, steps, sampler, model, name, created_at
            FROM prompts {where} ORDER BY id DESC
        """
        rows = conn.execute(sql, params).fetchall()
        return [{
            "id": r["id"], "prompt_preview": r["prompt_preview"],
            "tags": r["tags"] or "", "steps": r["steps"],
            "sampler": r["sampler"] or "", "model": r["model"] or "",
            "name": r["name"] or "", "created_at": r["created_at"] or "",
        } for r in rows]


def get_prompt(prompt_id: int) -> Optional[dict]:
    with get_db() as conn:
        r = conn.execute("SELECT * FROM prompts WHERE id = ?", (prompt_id,)).fetchone()
        if r is None:
            return None
        return {
            "id": r["id"], "name": r["name"] or "",
            "prompt": r["prompt"] or "",
            "negative_prompt": r["negative_prompt"] or "",
            "steps": r["steps"], "cfg_scale": r["cfg_scale"],
            "sampler": r["sampler"] or "", "seed": r["seed"],
            "model": r["model"] or "", "width": r["width"],
            "height": r["height"], "tags": r["tags"] or "",
            "note": r["note"] or "", "created_at": r["created_at"] or "",
            "updated_at": r["updated_at"] or "",
        }


def create_prompt(data: dict) -> int:
    with get_db_rw() as conn:
        cur = conn.execute("""
            INSERT INTO prompts (prompt, negative_prompt, steps, cfg_scale, sampler,
                                 seed, model, width, height, tags, note, name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("prompt", ""), data.get("negative_prompt", ""),
            data.get("steps"), data.get("cfg_scale"), data.get("sampler", ""),
            data.get("seed"), data.get("model", ""),
            data.get("width"), data.get("height"),
            data.get("tags", ""), data.get("note", ""),
            data.get("name", ""),
        ))
        conn.commit()
        return cur.lastrowid


def update_prompt(prompt_id: int, data: dict) -> bool:
    with get_db_rw() as conn:
        fields = []
        params: list[Any] = []
        for key in ("name", "prompt", "negative_prompt", "steps", "cfg_scale", "sampler",
                    "seed", "model", "width", "height", "tags", "note"):
            if key in data:
                fields.append(f"{key} = ?")
                params.append(data[key])
        if not fields:
            return False
        fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(prompt_id)
        conn.execute(f"UPDATE prompts SET {', '.join(fields)} WHERE id = ?", params)
        conn.commit()
        return True


def delete_prompt(prompt_id: int) -> bool:
    with get_db_rw() as conn:
        cur = conn.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
        conn.commit()
        return cur.rowcount > 0


def list_tags() -> list[str]:
    with get_db() as conn:
        rows = conn.execute("SELECT tags FROM prompts WHERE tags IS NOT NULL AND tags != ''").fetchall()
        all_tags: set[str] = set()
        for r in rows:
            for t in r["tags"].split(","):
                t = t.strip()
                if t:
                    all_tags.add(t)
        return sorted(all_tags)


# -------------------------------------------------------------------
# 工作流
# -------------------------------------------------------------------

def list_workflows(base_dir: Path, sort_by: str = "mtime") -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()
    for d in [base_dir, base_dir / "废弃工作流"]:
        if d.exists():
            for f in d.glob("*.json"):
                try:
                    content = json.loads(f.read_text(encoding="utf-8"))
                    if not any(isinstance(v, dict) and "class_type" in v for v in content.values()):
                        continue
                except Exception:
                    continue
                fp = str(f)
                if fp not in seen:
                    seen.add(fp)
                    results.append({
                        "path": fp,
                        "name": f.name,
                        "mtime": f.stat().st_mtime,
                    })
    if sort_by == "mtime":
        results.sort(key=lambda x: x["mtime"], reverse=True)
    else:
        results.sort(key=lambda x: x["name"])
    return results


def _find_default_workflow():
    candidates = []
    for d in [PROJECT_ROOT, PROJECT_ROOT / "废弃工作流"]:
        if d.exists():
            for f in sorted(d.glob("*.json")):
                try:
                    content = json.loads(f.read_text(encoding="utf-8"))
                    if any(isinstance(v, dict) and "class_type" in v for v in content.values()):
                        candidates.append(str(f))
                except Exception:
                    continue
    for c in candidates:
        if "文生图" in c:
            return c
    return candidates[0] if candidates else ""


DEFAULT_WORKFLOW = _find_default_workflow()


# ===================================================================
# ComfyUI 推送
# ===================================================================

def _get_widget_order(node_type: str) -> list[tuple[str, int]]:
    if node_type in _widget_name_cache:
        return _widget_name_cache[node_type]
    entries: list[tuple[str, int]] = []
    try:
        safe = quote(node_type, safe="")
        req = urllib.request.Request(f"{COMFYUI_API}/object_info/{safe}", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            info = json.loads(resp.read().decode("utf-8"))
        nd = info.get(node_type, {})
        for group in ["required", "optional"]:
            for k, v in nd.get("input", {}).get(group, {}).items():
                if not isinstance(v, list) or len(v) == 0:
                    continue
                first = v[0]
                if isinstance(first, list):
                    entries.append((k, 1))
                elif isinstance(first, str) and len(v) >= 2 and isinstance(v[1], dict):
                    if first in ("INT", "FLOAT", "STRING", "BOOLEAN"):
                        slots = 2 if v[1].get("control_after_generate") else 1
                        entries.append((k, slots))
    except Exception:
        pass
    _widget_name_cache[node_type] = entries
    return entries


def _ensure_api_format(workflow: dict) -> dict:
    if "nodes" not in workflow or not isinstance(workflow["nodes"], list):
        return workflow
    link_map: dict[int, tuple[str, int]] = {}
    for link in workflow.get("links", []):
        if isinstance(link, list) and len(link) >= 4:
            link_map[link[0]] = (str(link[1]), int(link[2]))

    SKIP_TYPES = {"Note", "MarkdownNote", "Label (rgthree)", "Comment", "StickyNote"}
    api: dict[str, dict] = {}
    for node in workflow["nodes"]:
        node_type = node.get("type", "unknown")
        if node_type in SKIP_TYPES:
            continue
        nid = str(node.get("id", 0))
        api[nid] = {"class_type": node_type, "inputs": {}}
        raw_inputs = node.get("inputs", [])
        wv = node.get("widgets_values", [])

        if not isinstance(raw_inputs, list):
            if isinstance(raw_inputs, dict):
                api[nid]["inputs"] = dict(raw_inputs)
            continue

        wv_by_name: dict[str, object] = {}
        if wv:
            w_entries = _get_widget_order(node_type)
            if w_entries:
                pos = 0
                for name, slots in w_entries:
                    if pos + slots <= len(wv):
                        wv_by_name[name] = wv[pos]
                    pos += slots

        for inp in raw_inputs:
            name = inp.get("name", "")
            if not name:
                continue
            link_id = inp.get("link")
            if link_id is not None:
                src = link_map.get(link_id)
                if src:
                    api[nid]["inputs"][name] = [src[0], src[1]]
            elif "widget" in inp:
                val = inp.get("widget", {}).get("value")
                if val is None and name in wv_by_name:
                    val = wv_by_name[name]
                if val is not None:
                    api[nid]["inputs"][name] = val

        if wv and (not isinstance(raw_inputs, list) or len(raw_inputs) == 0):
            for wname, _ in w_entries:
                if wname not in api[nid]["inputs"] and wname in wv_by_name:
                    api[nid]["inputs"][wname] = wv_by_name[wname]

    return api


def send_to_comfyui(workflow_path: str, prompt_data: dict, workflow_content: Optional[str] = None) -> dict:
    if workflow_content:
        workflow = json.loads(workflow_content)
    else:
        if not os.path.exists(workflow_path):
            raise FileNotFoundError(f"工作流文件不存在: {workflow_path}")
        with open(workflow_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)

    workflow = _ensure_api_format(workflow)

    clip_nodes = []
    for node_id, node in workflow.items():
        if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode":
            if node.get("inputs", {}).get("clip") is not None:
                clip_nodes.append((node_id, node))

    if len(clip_nodes) == 0:
        raise RuntimeError(f"工作流中没有可用的 CLIPTextEncode 节点（全部悬空）")

    clip_nodes[0][1]["inputs"]["text"] = prompt_data["prompt"]
    if len(clip_nodes) >= 2:
        clip_nodes[1][1]["inputs"]["text"] = prompt_data["negative_prompt"]

    seed_val = prompt_data.get("seed_override") or prompt_data.get("seed", 0)
    if seed_val and seed_val != 0:
        for node_id, node in workflow.items():
            if isinstance(node, dict) and node.get("class_type") in ("KSampler", "KSamplerAdvanced"):
                if "noise_seed" in node["inputs"]:
                    node["inputs"]["noise_seed"] = seed_val
                elif "seed" in node["inputs"]:
                    node["inputs"]["seed"] = seed_val

    orientation = prompt_data.get("orientation", "portrait")
    for node_id, node in workflow.items():
        if isinstance(node, dict) and node.get("class_type") == "EmptyLatentImage":
            w, h = node["inputs"].get("width", 640), node["inputs"].get("height", 960)
            if orientation == "landscape" and h > w:
                node["inputs"]["width"], node["inputs"]["height"] = h, w
            elif orientation == "portrait" and w > h:
                node["inputs"]["width"], node["inputs"]["height"] = h, w
            break

    quality = prompt_data.get("quality", "4K")
    quality_map = {
        "2K": (2160, 3840),
        "4K": (2560, 4096),
        "6K": (3200, 5120),
        "8K": (3840, 6400),
        "12K": (5120, 8192),
    }
    if quality in quality_map:
        res, max_res = quality_map[quality]
        for node_id, node in workflow.items():
            if isinstance(node, dict) and node.get("class_type") == "SeedVR2VideoUpscaler":
                node["inputs"]["resolution"] = res
                node["inputs"]["max_resolution"] = max_res
                break

    payload = json.dumps({"prompt": workflow}).encode("utf-8")
    req = urllib.request.Request(
        f"{COMFYUI_API}/prompt",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"ComfyUI 连接失败: {e.reason}")


# ===================================================================
# 任务 / 历史持久化
# ===================================================================

def _build_view_url(img: dict) -> str:
    return f"/api/image?filename={quote(img['filename'])}&subfolder={quote(img.get('subfolder', ''))}&type={img.get('type', 'output')}"


def create_job(job_type: str, title: str, items: list[dict], workflow_path: str,
             orientation: str, quality: str, extra: Optional[dict] = None) -> int:
    with get_db_rw() as conn:
        cur = conn.execute("""
            INSERT INTO gen_jobs (job_type, status, title, total, items, workflow_path, orientation, quality, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (job_type, "pending", title, len(items), json.dumps(items), workflow_path, orientation, quality,
              json.dumps(extra) if extra else None))
        conn.commit()
        return cur.lastrowid


def update_job_items(job_id: int, items: list[dict], status: Optional[str] = None):
    done = sum(1 for i in items if i.get("status") == "done")
    errors = sum(1 for i in items if i.get("status") in ("error", "cancelled"))
    with get_db_rw() as conn:
        conn.execute("""
            UPDATE gen_jobs SET status=?, done_count=?, error_count=?, items=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (status or "running", done, errors, json.dumps(items), job_id))
        conn.commit()


def get_job(job_id: int) -> Optional[dict]:
    with get_db() as conn:
        r = conn.execute("SELECT * FROM gen_jobs WHERE id = ?", (job_id,)).fetchone()
        if not r:
            return None
        return dict(r)


def list_jobs(active_only: bool = False, limit: int = 50) -> list[dict]:
    with get_db() as conn:
        if active_only:
            rows = conn.execute("""
                SELECT * FROM gen_jobs WHERE status IN ('pending', 'running')
                ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM gen_jobs ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]


def insert_history(conn, job_id: Optional[int], prompt_id: Optional[int],
                   pid: Optional[str], images: list[dict], preview: str = "",
                   source: str = "local"):
    for img in images:
        conn.execute("""
            INSERT OR IGNORE INTO gen_history
            (job_id, prompt_id, comfyui_prompt_id, filename, subfolder, img_type, view_url, preview, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (job_id, prompt_id, pid, img["filename"], img.get("subfolder", ""),
              img.get("type", "output"), _build_view_url(img), preview, source))


def list_history(limit: int = 50) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM gen_history ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]


def delete_history_item(item_id: int) -> bool:
    with get_db_rw() as conn:
        cur = conn.execute("DELETE FROM gen_history WHERE id = ?", (item_id,))
        conn.commit()
        return cur.rowcount > 0


def clear_history() -> bool:
    with get_db_rw() as conn:
        conn.execute("DELETE FROM gen_history")
        conn.commit()
        return True


def sync_comfyui_history() -> int:
    """把 ComfyUI 全局 /history 合并到本地历史表。"""
    try:
        req = urllib.request.Request(f"{COMFYUI_API}/history", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            hist = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return 0
    if not hist:
        return 0
    added = 0
    with get_db_rw() as conn:
        for pid, data in hist.items():
            outputs = data.get("outputs", {})
            for node_out in outputs.values():
                for img in node_out.get("images", []):
                    insert_history(conn, None, None, pid, [img], preview="", source="comfyui_sync")
                    added += 1
        conn.commit()
    return added


# ===================================================================
# ComfyUI 状态轮询 / 任务监控
# ===================================================================

def _fetch_json(url: str, timeout: int = 5) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _post_comfyui(path: str, data: Optional[dict] = None) -> Optional[int]:
    try:
        body = json.dumps(data).encode("utf-8") if data is not None else b""
        headers = {"Content-Type": "application/json"} if data is not None else {}
        req = urllib.request.Request(f"{COMFYUI_API}{path}", data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except Exception:
        return None


def _get_job_status_snapshot(job: dict) -> dict:
    """根据 ComfyUI queue/history 计算任务实时状态。"""
    items = json.loads(job.get("items") or "[]")
    qdata = _fetch_json(f"{COMFYUI_API}/queue")
    running: set[str] = set()
    pending: set[str] = set()
    if qdata:
        for item in qdata.get("queue_running", []):
            if isinstance(item, list) and len(item) > 1:
                running.add(str(item[1]))
        for item in qdata.get("queue_pending", []):
            if isinstance(item, list) and len(item) > 1:
                pending.add(str(item[1]))

    hist = _fetch_json(f"{COMFYUI_API}/history")
    if hist is None:
        hist = {}

    # 全局进度，只对应当前正在跑的任务
    progress_data: Optional[dict] = None
    current_pid: Optional[str] = None
    if qdata and qdata.get("queue_running"):
        first = qdata["queue_running"][0]
        if isinstance(first, list) and len(first) > 1:
            current_pid = str(first[1])
            prog = _fetch_json(f"{COMFYUI_API}/progress")
            if prog:
                progress_data = {
                    "progress": prog.get("progress", 0),
                    "max": prog.get("max", 0),
                    "current_node": prog.get("current_node", ""),
                }

    per_item = []
    done_count = 0
    error_count = 0
    db_changed = False
    with get_db_rw() as conn:
        for item in items:
            pid = item.get("comfyui_prompt_id")
            status = item.get("status", "pending")
            iprogress = None
            if pid and pid in hist:
                status = "done"
                images = []
                for node_out in hist[pid].get("outputs", {}).values():
                    for img in node_out.get("images", []):
                        images.append(img)
                item["images"] = images
                done_count += 1
                insert_history(conn, job["id"], item.get("prompt_id"), pid, images,
                               preview=item.get("prompt_preview", ""), source="local")
                db_changed = True
            elif pid and pid in running:
                status = "running"
                if pid == current_pid and progress_data:
                    iprogress = progress_data
            elif pid and pid in pending:
                status = "pending"
            elif status in ("done", "error", "cancelled"):
                if status == "done":
                    done_count += 1
                elif status in ("error", "cancelled"):
                    error_count += 1
            else:
                status = "unknown"
            item["status"] = status
            item["progress"] = iprogress
            per_item.append(item)

        # 如果状态变化，回写 DB
        if db_changed or job.get("status") in ("pending", "running"):
            overall = job["status"]
            if overall not in ("stopped", "done", "error"):
                if done_count + error_count == len(items):
                    overall = "done" if error_count == 0 else "error"
                elif any(i.get("status") == "running" for i in per_item):
                    overall = "running"
                elif any(i.get("status") == "pending" for i in per_item):
                    overall = "pending"
                else:
                    overall = "unknown"
            conn.execute("""
                UPDATE gen_jobs SET status=?, done_count=?, error_count=?, items=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (overall, done_count, error_count, json.dumps(per_item), job["id"]))
            conn.commit()

    return {
        "id": job["id"],
        "job_type": job["job_type"],
        "status": overall if overall not in ("stopped",) else job["status"],
        "title": job["title"],
        "total": len(items),
        "done_count": done_count,
        "error_count": error_count,
        "items": per_item,
        "workflow_path": job["workflow_path"],
        "orientation": job["orientation"],
        "quality": job["quality"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }


def job_monitor_loop():
    """后台守护线程：定期同步活跃任务状态。"""
    while True:
        try:
            time.sleep(5)
            jobs = list_jobs(active_only=True, limit=20)
            for job in jobs:
                try:
                    _get_job_status_snapshot(job)
                except Exception:
                    traceback.print_exc()
            # 每 30 秒同步一次 ComfyUI 全局历史
            if int(time.time()) % 30 < 6:
                try:
                    sync_comfyui_history()
                except Exception:
                    traceback.print_exc()
        except Exception:
            traceback.print_exc()


# ===================================================================
# HTTP 请求处理
# ===================================================================

class PromptHandler(BaseHTTPRequestHandler):

    def _send_json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _send_html(self, content: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _send_error(self, msg: str, status: int = 400):
        self._send_json({"error": msg}, status)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _serve_static(self, rel_path: str):
        rel_path = rel_path.replace("\\", "/").lstrip("/")
        if not rel_path:
            rel_path = "index.html"
        parts = rel_path.split("/")
        if any(p == ".." for p in parts):
            return False
        file_path = STATIC_DIR.joinpath(*parts)
        if not file_path.exists() or not file_path.is_file():
            return False
        content_type, _ = mimetypes.guess_type(str(file_path))
        if not content_type:
            content_type = "application/octet-stream"
        try:
            with open(file_path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            if rel_path.endswith(".js") or rel_path.endswith(".css"):
                self.send_header("Cache-Control", "public, max-age=3600")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
            return True
        except Exception as e:
            self._send_error(str(e), 500)
            return True

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)

        if not path.startswith("/api/"):
            if self._serve_static(path):
                return
            self._send_error("Not Found", 404)
            return

        path = path.rstrip("/")

        if path == "/api/prompts":
            search = qs.get("search", [""])[0]
            tag = qs.get("tag", [""])[0]
            try:
                prompts = list_prompts(search, tag)
                self._send_json({"prompts": prompts, "total": len(prompts)})
            except Exception as e:
                self._send_error(str(e), 500)

        elif path.startswith("/api/prompts/"):
            try:
                pid = int(path.split("/")[-1])
                p = get_prompt(pid)
                if p is None:
                    self._send_error("提示词不存在", 404)
                else:
                    self._send_json(p)
            except Exception as e:
                self._send_error(str(e), 500)

        elif path == "/api/tags":
            try:
                tags = list_tags()
                self._send_json({"tags": tags})
            except Exception as e:
                self._send_error(str(e), 500)

        elif path == "/api/workflows":
            try:
                sort_by = qs.get("sort", ["mtime"])[0]
                wfs = list_workflows(PROJECT_ROOT, sort_by)
                self._send_json({"workflows": wfs, "default": DEFAULT_WORKFLOW})
            except Exception as e:
                self._send_error(str(e), 500)

        elif path == "/api/progress":
            # 保留兼容，但新版前端主要用 /api/jobs/:id
            prompt_id = qs.get("prompt_id", [""])[0]
            if not prompt_id:
                self._send_error("缺少 prompt_id")
                return
            try:
                req_h = urllib.request.Request(f"{COMFYUI_API}/history/{prompt_id}", method="GET")
                done = False
                images = []
                try:
                    with urllib.request.urlopen(req_h, timeout=5) as resp_h:
                        hist = json.loads(resp_h.read().decode("utf-8"))
                        if prompt_id in hist:
                            done = True
                            for node_out in hist[prompt_id].get("outputs", {}).values():
                                for img in node_out.get("images", []):
                                    images.append(img)
                except urllib.error.HTTPError as e:
                    if e.code != 404:
                        raise
                except Exception:
                    pass
                self._send_json({"done": done, "images": images, "status": "done" if done else "unknown"})
            except Exception as e:
                self._send_error(str(e), 500)

        elif path == "/api/jobs":
            try:
                active_only = qs.get("active", [""])[0] in ("1", "true", "yes")
                limit = int(qs.get("limit", ["50"])[0])
                jobs = list_jobs(active_only=active_only, limit=limit)
                self._send_json({"jobs": jobs})
            except Exception as e:
                self._send_error(str(e), 500)

        elif path.startswith("/api/jobs/"):
            try:
                parts = path.split("/")
                if len(parts) >= 4 and parts[-1] == "cancel":
                    job_id = int(parts[-2])
                else:
                    job_id = int(parts[-1])
                job = get_job(job_id)
                if job is None:
                    self._send_error("任务不存在", 404)
                    return
                if len(parts) >= 4 and parts[-1] == "cancel":
                    # cancel 由 POST 处理
                    self._send_error("请使用 POST 取消任务", 405)
                    return
                snapshot = _get_job_status_snapshot(job)
                self._send_json(snapshot)
            except Exception as e:
                self._send_error(str(e), 500)

        elif path == "/api/history":
            try:
                limit = int(qs.get("limit", ["50"])[0])
                items = list_history(limit=limit)
                self._send_json({"items": items})
            except Exception as e:
                self._send_error(str(e), 500)

        elif path == "/api/history_sync":
            try:
                added = sync_comfyui_history()
                items = list_history(limit=50)
                self._send_json({"added": added, "items": items})
            except Exception as e:
                self._send_error(str(e), 500)

        elif path == "/api/validate_workflow":
            wp = qs.get("path", [""])[0]
            if not wp or not os.path.exists(wp):
                self._send_json({"valid": False, "error": "文件不存在"})
                return
            try:
                with open(wp, "r", encoding="utf-8") as f:
                    wf = json.load(f)
                has_clip = any(
                    isinstance(v, dict) and v.get("class_type") == "CLIPTextEncode"
                    for v in wf.values()
                )
                self._send_json({"valid": has_clip, "name": os.path.basename(wp)})
            except Exception as e:
                self._send_json({"valid": False, "error": str(e)})

        elif path == "/api/image":
            filename = qs.get("filename", [""])[0]
            subfolder = qs.get("subfolder", [""])[0]
            img_type = qs.get("type", ["output"])[0]
            if not filename:
                self._send_error("缺少 filename")
                return
            try:
                url = f"{COMFYUI_API}/view?filename={quote(filename)}&subfolder={quote(subfolder)}&type={img_type}"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    img_data = resp.read()
                self.send_response(200)
                self.send_header("Content-Type", resp.headers.get("Content-Type", "image/png"))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(img_data)
            except Exception as e:
                self._send_error(str(e), 500)

        elif path == "/api/config":
            self._send_json({
                "workflow_path": DEFAULT_WORKFLOW,
                "workflow_name": os.path.basename(DEFAULT_WORKFLOW) if DEFAULT_WORKFLOW else "未设置",
                "db_path": DB_PATH,
            })

        elif path == "/api/status":
            try:
                req = urllib.request.Request(f"{COMFYUI_API}/queue", method="GET")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    queue = json.loads(resp.read().decode("utf-8"))
                    self._send_json({
                        "comfyui": "online",
                        "queue_running": len(queue.get("queue_running", [])),
                        "queue_pending": len(queue.get("queue_pending", [])),
                    })
            except Exception:
                self._send_json({"comfyui": "offline", "queue_running": 0, "queue_pending": 0})

        else:
            self._send_error("Not Found", 404)

    def do_POST(self):
        global batch_stop_flag
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/run":
            body = self._read_body()
            prompt_id = body.get("id")
            workflow_path = body.get("workflow_path", DEFAULT_WORKFLOW)
            if not prompt_id:
                self._send_error("缺少 prompt id")
                return
            p = get_prompt(prompt_id)
            if p is None:
                self._send_error("提示词不存在", 404)
                return
            try:
                wf_content = body.get("workflow_content")
                p["orientation"] = body.get("orientation", "portrait")
                p["quality"] = body.get("quality", "4K")
                p["seed_override"] = body.get("seed_override", 0)
                items = [{
                    "prompt_id": prompt_id,
                    "seed": p.get("seed_override", 0),
                    "prompt_preview": (p.get("name") or p.get("prompt", ""))[:40],
                }]
                job_id = create_job("single", "单图生成", items, workflow_path, p["orientation"], p["quality"])
                result = send_to_comfyui(workflow_path, p, workflow_content=wf_content)
                comfy_pid = result.get("prompt_id", "")
                items[0]["comfyui_prompt_id"] = comfy_pid
                items[0]["status"] = "pending"
                update_job_items(job_id, items, status="running")
                dims = ""
                if p.get("width") and p.get("height"):
                    dims = f"{p['width']}×{p['height']}"
                self._send_json({"success": True, "job_id": job_id, "result": result, "dimensions": dims})
            except Exception as e:
                traceback.print_exc()
                self._send_error(f"{type(e).__name__}: {e}", 500)

        elif path == "/api/batch_generate":
            body = self._read_body()
            items = body.get("items", [])
            workflow_path = body.get("workflow_path", DEFAULT_WORKFLOW)
            wf_content = body.get("workflow_content")
            orientation = body.get("orientation", "portrait")
            quality = body.get("quality", "4K")
            if not items:
                self._send_error("缺少 items")
                return

            title = body.get("title", "批量生成")
            job_id = create_job("batch", title, items, workflow_path, orientation, quality)

            results = []
            errors = []
            for i, item in enumerate(items):
                if batch_stop_flag.is_set():
                    errors.append({"index": i, "prompt_id": item.get("prompt_id"), "error": "已取消"})
                    item["status"] = "cancelled"
                    continue
                pid = item.get("prompt_id")
                if not pid:
                    errors.append({"index": i, "error": "缺少 prompt_id"})
                    item["status"] = "error"
                    item["error"] = "缺少 prompt_id"
                    continue
                p = get_prompt(pid)
                if p is None:
                    errors.append({"index": i, "prompt_id": pid, "error": f"提示词 {pid} 不存在"})
                    item["status"] = "error"
                    item["error"] = f"提示词 {pid} 不存在"
                    continue
                try:
                    p["orientation"] = orientation
                    p["quality"] = quality
                    p["seed_override"] = item.get("seed", 0)
                    result = send_to_comfyui(workflow_path, p, workflow_content=wf_content)
                    comfy_pid = result.get("prompt_id", "")
                    item["comfyui_prompt_id"] = comfy_pid
                    item["status"] = "pending"
                    item["prompt_preview"] = (p.get("name") or p.get("prompt", ""))[:40]
                    results.append({"index": i, "prompt_id": pid, "comfyui_prompt_id": comfy_pid})
                except Exception as e:
                    traceback.print_exc()
                    errors.append({"index": i, "prompt_id": pid, "error": str(e)})
                    item["status"] = "error"
                    item["error"] = str(e)

            batch_stop_flag.clear()
            status = "running" if results else "error"
            update_job_items(job_id, items, status=status)
            self._send_json({"success": len(results) > 0, "job_id": job_id, "results": results, "errors": errors})

        elif path.startswith("/api/jobs/") and path.endswith("/cancel"):
            try:
                job_id = int(path.split("/")[-2])
                job = get_job(job_id)
                if job is None:
                    self._send_error("任务不存在", 404)
                    return
                # 1. 通知 ComfyUI 停止当前任务并清空队列
                _post_comfyui("/interrupt")
                _post_comfyui("/queue", {"clear": True})
                # 2. 设置全局停止标志，防止后续提交继续入队
                batch_stop_flag.set()
                # 3. 更新 DB 状态
                items = json.loads(job.get("items") or "[]")
                for item in items:
                    if item.get("status") not in ("done",):
                        item["status"] = "cancelled"
                        item["error"] = "已取消"
                update_job_items(job_id, items, status="stopped")
                self._send_json({"success": True, "job_id": job_id})
            except Exception as e:
                self._send_error(str(e), 500)

        elif path == "/api/batch_stop":
            # 兼容旧接口
            batch_stop_flag.set()
            _post_comfyui("/interrupt")
            _post_comfyui("/queue", {"clear": True})
            self._send_json({"success": True})

        elif path == "/api/prompts":
            body = self._read_body()
            try:
                new_id = create_prompt(body)
                self._send_json({"success": True, "id": new_id}, 201)
            except Exception as e:
                self._send_error(str(e), 500)

        elif path == "/api/history_sync":
            try:
                added = sync_comfyui_history()
                items = list_history(limit=50)
                self._send_json({"added": added, "items": items})
            except Exception as e:
                self._send_error(str(e), 500)

        else:
            self._send_error("Not Found", 404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path.startswith("/api/prompts/"):
            try:
                pid = int(path.split("/")[-1])
                body = self._read_body()
                ok = update_prompt(pid, body)
                if ok:
                    self._send_json({"success": True})
                else:
                    self._send_error("更新失败或不存在", 404)
            except Exception as e:
                self._send_error(str(e), 500)
        else:
            self._send_error("Not Found", 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path.startswith("/api/prompts/"):
            try:
                pid = int(path.split("/")[-1])
                ok = delete_prompt(pid)
                if ok:
                    self._send_json({"success": True})
                else:
                    self._send_error("提示词不存在", 404)
            except Exception as e:
                self._send_error(str(e), 500)

        elif path.startswith("/api/history/"):
            try:
                item_id = int(path.split("/")[-1])
                ok = delete_history_item(item_id)
                self._send_json({"success": ok})
            except Exception as e:
                self._send_error(str(e), 500)

        elif path == "/api/history":
            try:
                clear_history()
                self._send_json({"success": True})
            except Exception as e:
                self._send_error(str(e), 500)

        else:
            self._send_error("Not Found", 404)

    def log_message(self, fmt, *args):
        print(f"[{datetime.now():%H:%M:%S}] {args[0]} {args[1]} {args[2]}")


def open_browser():
    time.sleep(0.5)
    url = f"http://{HOST}:{PORT}"
    print(f"  浏览器已自动打开: {url}")
    webbrowser.open(url)


# ===================================================================
# 入口
# ===================================================================

if __name__ == "__main__":
    print("=" * 56)
    print("  Prompt Browser + ComfyUI Launcher v3")
    print("=" * 56)
    print(f"  DB:       {DB_PATH}")
    print(f"  工作流:    {DEFAULT_WORKFLOW or '(未找到)'}")
    print(f"  ComfyUI:  {COMFYUI_API}")
    print(f"  本地页面:  http://{HOST}:{PORT}")
    print("=" * 56)
    print("  按 Ctrl+C 停止服务")
    print()

    init_db()
    threading.Thread(target=job_monitor_loop, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), PromptHandler)
    threading.Thread(target=open_browser, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.server_close()
