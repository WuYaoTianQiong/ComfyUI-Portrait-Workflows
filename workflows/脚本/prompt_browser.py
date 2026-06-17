#!/usr/bin/env python3
"""
Prompt Browser + ComfyUI Launcher v2
- 提示词 CRUD（增删改查）
- 工作流文件选择器
- 自动扫描可用工作流
- 一键推送 ComfyUI
零依赖，仅 Python 标准库。
"""

import sys, os, json, sqlite3, html, urllib.request, urllib.error, webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote, quote
from typing import Optional, Any
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
import threading, time

# ======== 配置 ========
HOST = "127.0.0.1"
PORT = 8653
COMFYUI_API = "http://127.0.0.1:8188"

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent  # F:\ComfyUI_Migration\workflows 或类似

# 提示词数据库路径
DB_PATH = str(PROJECT_ROOT / "文档" / "提示词收藏.db")

# 默认工作流：从 PROJECT_ROOT 或 PROJECT_ROOT/workflows 下扫第一个
def _find_default_workflow():
    """找默认工作流：优先选名字带「文生图」的"""
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
# ======== 配置结束 ========


# ===================================================================
# 数据库操作
# ===================================================================

@contextmanager
def get_db():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"数据库文件不存在: {DB_PATH}")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_db_rw():
    """读写模式（用于 CRUD）"""
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"数据库文件不存在: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


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
        sql = f"SELECT id, substr(prompt, 1, 60) AS prompt_preview, tags, steps, sampler, model, created_at FROM prompts {where} ORDER BY id DESC"
        rows = conn.execute(sql, params).fetchall()
        return [{
            "id": r["id"], "prompt_preview": r["prompt_preview"],
            "tags": r["tags"] or "", "steps": r["steps"],
            "sampler": r["sampler"] or "", "model": r["model"] or "",
            "created_at": r["created_at"] or "",
        } for r in rows]


def get_prompt(prompt_id: int) -> Optional[dict]:
    with get_db() as conn:
        r = conn.execute("SELECT * FROM prompts WHERE id = ?", (prompt_id,)).fetchone()
        if r is None:
            return None
        return {
            "id": r["id"], "prompt": r["prompt"] or "",
            "negative_prompt": r["negative_prompt"] or "",
            "steps": r["steps"], "cfg_scale": r["cfg_scale"],
            "sampler": r["sampler"] or "", "seed": r["seed"],
            "model": r["model"] or "", "width": r["width"],
            "height": r["height"], "tags": r["tags"] or "",
            "note": r["note"] or "", "created_at": r["created_at"] or "",
        }


def create_prompt(data: dict) -> int:
    with get_db_rw() as conn:
        cur = conn.execute("""
            INSERT INTO prompts (prompt, negative_prompt, steps, cfg_scale, sampler,
                                 seed, model, width, height, tags, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("prompt", ""), data.get("negative_prompt", ""),
            data.get("steps"), data.get("cfg_scale"), data.get("sampler", ""),
            data.get("seed"), data.get("model", ""),
            data.get("width"), data.get("height"),
            data.get("tags", ""), data.get("note", ""),
        ))
        conn.commit()
        return cur.lastrowid


def update_prompt(prompt_id: int, data: dict) -> bool:
    with get_db_rw() as conn:
        fields = []
        params: list[Any] = []
        for key in ("prompt", "negative_prompt", "steps", "cfg_scale", "sampler",
                     "seed", "model", "width", "height", "tags", "note"):
            if key in data:
                fields.append(f"{key} = ?")
                params.append(data[key])
        if not fields:
            return False
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


def list_workflows(base_dir: Path, sort_by: str = "mtime") -> list[dict]:
    """扫描可用工作流文件"""
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


# ===================================================================
# ComfyUI 推送
# ===================================================================

# widget 名称顺序缓存
_widget_name_cache: dict[str, list[tuple[str, int]]] = {}

def _get_widget_order(node_type: str) -> list[tuple[str, int]]:
    """返回 widget 名称及在 widgets_values 中占的槽位数"""
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
    """画布格式 -> API 格式。links[link_id] 转成 [node_id, slot]；widget 值按名匹配"""
    if "nodes" not in workflow or not isinstance(workflow["nodes"], list):
        return workflow
    # link_id → (source_node_id, source_slot)
    link_map: dict[int, tuple[str, int]] = {}
    for link in workflow.get("links", []):
        if isinstance(link, list) and len(link) >= 4:
            link_map[link[0]] = (str(link[1]), int(link[2]))

    # 非执行节点类型（UI 装饰元素）直接跳过
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

        # 如果有 widgets_values，按名称映射（ComfyUI API 查询）
        wv_by_name: dict[str, object] = {}
        if wv:
            w_entries = _get_widget_order(node_type)
            if w_entries:
                pos = 0
                for name, slots in w_entries:
                    if pos + slots <= len(wv):
                        wv_by_name[name] = wv[pos]  # 第一个值（seed），跳过后续槽位
                    pos += slots

        # 遍历 inputs 构建 API 格式
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
            # else: 已断开的空输入，不赋值
        
        # 画布 inputs 为空但 widgets_values 非空的节点（Seed/Primitive 等）
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

    # 找 CLIPTextEncode 时跳过没有 CLIP 连线的节点（它们是悬空/未使用的）
    clip_nodes = []
    for node_id, node in workflow.items():
        if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode":
            if node.get("inputs", {}).get("clip") is not None:
                clip_nodes.append((node_id, node))

    if len(clip_nodes) == 0:
        raise RuntimeError(f"工作流中没有可用的 CLIPTextEncode 节点（全部悬空）")

    # 第一个有效 CLIPTextEncode → 正面提示词
    clip_nodes[0][1]["inputs"]["text"] = prompt_data["prompt"]
    # 如果有第二个，用作负面提示词；否则只改正面
    if len(clip_nodes) >= 2:
        clip_nodes[1][1]["inputs"]["text"] = prompt_data["negative_prompt"]

    # 用提示词的宽高覆盖 EmptyLatentImage
    pw = prompt_data.get("width")
    ph = prompt_data.get("height")
    if pw and ph:
        for node_id, node in workflow.items():
            if isinstance(node, dict) and node.get("class_type") == "EmptyLatentImage":
                node["inputs"]["width"] = pw
                node["inputs"]["height"] = ph
                break

    # 更新种子
    for node_id, node in workflow.items():
        if isinstance(node, dict) and node.get("class_type") == "KSampler":
            if prompt_data.get("seed") and prompt_data["seed"] != 0:
                node["inputs"]["seed"] = prompt_data["seed"]
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

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)

        if path in ("", "/"):
            self._send_html(HTML_PAGE)

        elif path == "/api/prompts":
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
            prompt_id = qs.get("prompt_id", [""])[0]
            if not prompt_id:
                self._send_error("缺少 prompt_id")
                return
            try:
                # 查 queue 判断当前在跑哪个 prompt
                running_id = ""
                pending_count = 0
                is_ours = False
                req_q = urllib.request.Request(f"{COMFYUI_API}/queue", method="GET")
                try:
                    with urllib.request.urlopen(req_q, timeout=5) as resp_q:
                        qdata = json.loads(resp_q.read().decode("utf-8"))
                        for item in qdata.get("queue_running", []):
                            if isinstance(item, list) and len(item) > 1:
                                running_id = item[1]
                        pending_count = len(qdata.get("queue_pending", []))
                        # 判断我们的 prompt 是否在 running 或 pending 中
                        all_ids = set()
                        for item in qdata.get("queue_running", []):
                            if isinstance(item, list) and len(item) > 1:
                                all_ids.add(item[1])
                        for item in qdata.get("queue_pending", []):
                            if isinstance(item, list) and len(item) > 1:
                                all_ids.add(item[1])
                        is_ours = prompt_id in all_ids
                except Exception:
                    pass

                # 查 ComfyUI progress（全局，只有 running_id 匹配时才有效）
                progress = 0
                max_val = 0
                current_node = ""
                if running_id == prompt_id:
                    try:
                        req_p = urllib.request.Request(f"{COMFYUI_API}/progress", method="GET")
                        with urllib.request.urlopen(req_p, timeout=5) as resp_p:
                            prog = json.loads(resp_p.read().decode("utf-8"))
                            progress = prog.get("progress", 0)
                            max_val = prog.get("max", 0)
                            current_node = prog.get("current_node", "") or ""
                    except Exception:
                        pass

                # 查 history 判断是否完成
                done = False
                images = []
                req_h = urllib.request.Request(f"{COMFYUI_API}/history/{prompt_id}", method="GET")
                try:
                    with urllib.request.urlopen(req_h, timeout=5) as resp_h:
                        hist = json.loads(resp_h.read().decode("utf-8"))
                        if prompt_id in hist:
                            done = True
                            outputs = hist[prompt_id].get("outputs", {})
                            for node_id, node_out in outputs.items():
                                for img_data in node_out.get("images", []):
                                    images.append(img_data)
                except urllib.error.HTTPError as e:
                    if e.code != 404:
                        raise
                except Exception:
                    pass

                # 状态推断
                status = "unknown"
                if done:
                    status = "done"
                elif running_id == prompt_id:
                    status = "running"
                elif is_ours:
                    status = "pending"
                else:
                    status = "unknown"

                self._send_json({
                    "status": status,
                    "done": done,
                    "progress": progress,
                    "max": max_val,
                    "current_node": current_node,
                    "pending_count": pending_count,
                    "images": images,
                })
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
            # 代理 ComfyUI 的出图
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
                result = send_to_comfyui(workflow_path, p, workflow_content=wf_content)
                dims = ""
                if p.get("width") and p.get("height"):
                    dims = f"{p['width']}×{p['height']}"
                self._send_json({"success": True, "result": result, "dimensions": dims})
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_error(f"{type(e).__name__}: {e}", 500)

        elif path == "/api/prompts":
            # 创建新提示词
            body = self._read_body()
            try:
                new_id = create_prompt(body)
                self._send_json({"success": True, "id": new_id}, 201)
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
# 嵌入的 HTML 页面（含完整 CSS + JS）
# ===================================================================
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Prompt Browser · 提示词管理器 v2</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", sans-serif; background: #0f0f11; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }

header { background: #1a1a1e; border-bottom: 1px solid #2a2a30; padding: 10px 20px; display: flex; align-items: center; gap: 12px; flex-shrink: 0; flex-wrap: wrap; }
header h1 { font-size: 16px; font-weight: 600; color: #fff; }
header .subtitle { font-size: 11px; color: #888; }
header .status { margin-left: auto; display: flex; align-items: center; gap: 6px; font-size: 12px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.status-dot.online { background: #4ade80; }
.status-dot.offline { background: #f87171; }
.status-dot.loading { background: #fbbf24; animation: pulse 1s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

.workflow-selector { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #aaa; }
.workflow-selector select { background: #1e1e24; border: 1px solid #333; color: #e0e0e0; padding: 4px 8px; border-radius: 4px; font-size: 12px; max-width: 520px; outline: none; }
.workflow-selector select:focus { border-color: #6366f1; }
.sort-btn { background: none; border: 1px solid #444; color: #888; padding: 2px 6px; border-radius: 3px; cursor: pointer; font-size: 11px; line-height: 1.4; transition: 0.15s; }
.sort-btn:hover { border-color: #6366f1; color: #818cf8; }

.container { display: flex; flex: 1; overflow: hidden; }
.sidebar { width: 400px; min-width: 280px; max-width: 800px; border-right: none; display: flex; flex-direction: column; background: #141416; position: relative; }
.resize-handle { width: 4px; cursor: col-resize; background: #2a2a30; flex-shrink: 0; transition: background 0.15s; }
.resize-handle:hover, .resize-handle:active { background: #6366f1; }
.sidebar .toolbar { padding: 10px; border-bottom: 1px solid #2a2a30; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.sidebar .toolbar input, .sidebar .toolbar select { background: #1e1e24; border: 1px solid #333; color: #e0e0e0; padding: 5px 8px; border-radius: 4px; font-size: 12px; outline: none; }
.sidebar .toolbar input:focus { border-color: #6366f1; }
.sidebar .toolbar input { flex: 1; min-width: 80px; }
.sidebar .toolbar select { max-width: 120px; }
.sidebar .toolbar .count-badge { font-size: 11px; color: #888; align-self: center; }

.prompt-list { flex: 1; overflow-y: auto; padding: 4px; }
.prompt-list::-webkit-scrollbar { width: 5px; }
.prompt-list::-webkit-scrollbar-thumb { background: #333; border-radius: 3px; }
.prompt-item { padding: 8px 10px; border-radius: 6px; cursor: pointer; margin: 2px 0; transition: background 0.15s; border-left: 3px solid transparent; }
.prompt-item:hover { background: #1e1e24; }
.prompt-item.active { background: #1e1e28; border-left-color: #6366f1; }
.prompt-item .preview { font-size: 12px; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; color: #ccc; }
.prompt-item .meta { font-size: 10px; color: #666; margin-top: 3px; display: flex; gap: 6px; flex-wrap: wrap; }
.prompt-item .meta .tag { background: #25253a; color: #818cf8; padding: 1px 5px; border-radius: 3px; font-size: 9px; }
.prompt-item .meta .badge { background: #1e2a1e; color: #6ee7b7; padding: 1px 5px; border-radius: 3px; font-size: 9px; }

.main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.detail { flex: 1; overflow-y: auto; padding: 20px; }
.detail::-webkit-scrollbar { width: 5px; }
.detail::-webkit-scrollbar-thumb { background: #333; border-radius: 3px; }
.detail .placeholder { text-align: center; color: #555; margin-top: 60px; font-size: 14px; }
.detail .section { margin-bottom: 16px; }
.detail .section h3 { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }
.detail .section .content { background: #1a1a1e; border-radius: 6px; padding: 12px; font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.detail .section .content.neg { color: #fca5a5; border-left: 3px solid #ef4444; }
.detail .section .content.pos { border-left: 3px solid #6366f1; }
.detail .params { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 6px; }
.detail .param-item { background: #1a1a1e; border-radius: 4px; padding: 6px 10px; }
.detail .param-item .label { font-size: 9px; color: #888; }
.detail .param-item .value { font-size: 13px; font-weight: 500; margin-top: 1px; }
.detail .note-box { background: #1e1a10; border-radius: 6px; padding: 10px; font-size: 12px; color: #d4a574; border-left: 3px solid #d4a574; }
.detail .actions { display: flex; gap: 8px; margin-bottom: 16px; }

.output-area { border-top: 1px solid #2a2a30; background: #111; display: none; flex-direction: column; flex-shrink: 0; max-height: 40%; }
.output-area.show { display: flex; }
.output-header { display: flex; align-items: center; justify-content: space-between; padding: 6px 16px; font-size: 12px; color: #888; border-bottom: 1px solid #2a2a30; }
.output-header .close-output { background: none; border: none; color: #666; cursor: pointer; font-size: 16px; padding: 0 4px; }
.output-body { flex: 1; overflow: auto; padding: 10px 16px; display: flex; align-items: center; justify-content: center; min-height: 80px; }
.output-body img { max-width: 100%; max-height: 100%; border-radius: 6px; box-shadow: 0 2px 12px rgba(0,0,0,0.4); cursor: zoom-in; }
/* 图片查看器 lightbox */
.lightbox { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 1000; align-items: center; justify-content: center; cursor: zoom-out; }
.lightbox.show { display: flex; }
.lightbox img { max-width: 95%; max-height: 95%; object-fit: contain; border-radius: 4px; box-shadow: 0 4px 32px rgba(0,0,0,0.6); cursor: default; }
.progress-bar-wrap { width: 100%; height: 4px; background: #2a2a30; border-radius: 2px; overflow: hidden; margin: 0 16px 4px; }
.progress-bar-fill { height: 100%; background: #6366f1; border-radius: 2px; width: 0%; transition: width 0.3s; }
.progress-info { font-size: 11px; color: #888; text-align: center; padding: 2px 16px 6px; }
.footer { border-top: 1px solid #2a2a30; padding: 10px 20px; display: flex; align-items: center; gap: 10px; background: #141416; flex-shrink: 0; }
.footer .workflow-path { flex: 1; font-size: 11px; color: #666; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.footer .workflow-path span { color: #888; }

.btn { background: #6366f1; color: #fff; border: none; padding: 6px 16px; border-radius: 5px; cursor: pointer; font-size: 13px; font-weight: 500; transition: background 0.15s; white-space: nowrap; }
.btn:hover { background: #5558e6; }
.btn:disabled { background: #333; color: #666; cursor: not-allowed; }
.btn-sm { padding: 4px 10px; font-size: 11px; border-radius: 4px; }
.btn-danger { background: #ef4444; }
.btn-danger:hover { background: #dc2626; }
.btn-warning { background: #f59e0b; color: #1a1a1e; }
.btn-warning:hover { background: #d97706; }
.btn-success { background: #22c55e; }
.btn-success:hover { background: #16a34a; }
.btn-ghost { background: transparent; color: #aaa; border: 1px solid #333; }
.btn-ghost:hover { background: #2a2a30; }

#toast { position: fixed; top: 20px; right: 20px; background: #1a1a1e; border: 1px solid #333; border-radius: 8px; padding: 10px 18px; font-size: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.4); transform: translateX(120%); opacity: 0; transition: 0.3s; z-index: 100; max-width: 400px; }
#toast.show { transform: translateX(0); opacity: 1; }
#toast.success { border-color: #22c55e; }
#toast.error { border-color: #ef4444; }
#toast.info { border-color: #6366f1; }

/* Modal */
.modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 200; align-items: center; justify-content: center; }
.modal-overlay.active { display: flex; }
.modal { background: #1a1a1e; border: 1px solid #333; border-radius: 10px; width: 680px; max-width: 94vw; max-height: 88vh; display: flex; flex-direction: column; }
.modal-header { padding: 14px 20px; border-bottom: 1px solid #2a2a30; display: flex; justify-content: space-between; align-items: center; }
.modal-header h2 { font-size: 15px; color: #fff; }
.modal-header .close-btn { background: none; border: none; color: #888; font-size: 20px; cursor: pointer; padding: 0 4px; }
.modal-header .close-btn:hover { color: #fff; }
.modal-body { padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }
.modal-body label { font-size: 11px; color: #aaa; display: flex; flex-direction: column; gap: 3px; }
.modal-body input, .modal-body textarea, .modal-body select { background: #0f0f11; border: 1px solid #333; color: #e0e0e0; padding: 7px 10px; border-radius: 4px; font-size: 12px; outline: none; font-family: inherit; }
.modal-body input:focus, .modal-body textarea:focus { border-color: #6366f1; }
.modal-body textarea { min-height: 80px; resize: vertical; }
.modal-body .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.modal-footer { padding: 12px 20px; border-top: 1px solid #2a2a30; display: flex; gap: 8px; justify-content: flex-end; }

/* 复制按钮 */
.copy-btn { background: #2a2a30; border: 1px solid #555; color: #aaa; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; margin-left: 10px; transition: 0.15s; vertical-align: middle; }
.copy-btn:hover { background: #6366f1; border-color: #6366f1; color: #fff; }
.copy-btn.copied { background: #22c55e; border-color: #22c55e; color: #fff; }
.section-header { display: flex; align-items: center; }

/* 批量选择 */
.batch-toolbar { display: none; padding: 8px 10px; border-bottom: 1px solid #2a2a30; align-items: center; gap: 6px; background: #1a1a2e; }
.batch-toolbar.show { display: flex; }
.batch-toolbar .batch-info { font-size: 11px; color: #818cf8; flex: 1; }
.prompt-item .item-row { display: flex; align-items: flex-start; gap: 6px; }
.prompt-item .item-check { margin-top: 2px; accent-color: #6366f1; cursor: pointer; flex-shrink: 0; }
.prompt-item .item-body { flex: 1; min-width: 0; }
.batch-progress { display: none; padding: 8px 10px; border-bottom: 1px solid #2a2a30; background: #111; }
.batch-progress.show { display: block; }
.batch-progress .bp-bar-wrap { height: 6px; background: #2a2a30; border-radius: 3px; overflow: hidden; margin-top: 4px; }
.batch-progress .bp-bar-fill { height: 100%; background: #6366f1; border-radius: 3px; width: 0%; transition: width 0.3s; }
.batch-progress .bp-text { font-size: 11px; color: #888; }
</style>
</head>
<body>

<header>
  <h1>📋 Prompt Browser</h1>
  <span class="subtitle">v2 · 提示词管理器</span>
  <div class="workflow-selector">
    <span>工作流:</span>
    <select id="workflowSelect" onchange="onWorkflowChange()"></select>
    <button class="sort-btn" id="sortBtn" onclick="toggleWorkflowSort()" title="切换排序方式">↕ 最近</button>
    <button class="sort-btn" onclick="document.getElementById('wfPicker').click()" title="从其他目录加载工作流">📁</button>
    <input type="file" id="wfPicker" accept=".json" style="display:none" onchange="pickWorkflowFile(event)">
  </div>
  <div class="status" id="statusBar">
    <span class="status-dot loading" id="statusDot"></span>
    <span id="statusText">检查 ComfyUI...</span>
  </div>
</header>

<div class="container">
  <div class="sidebar" id="sidebar">
    <div class="toolbar">
      <button class="btn btn-sm btn-success" onclick="openCreateModal()">+ 新建</button>
      <input type="text" id="searchInput" placeholder="搜索..." oninput="debounceSearch()">
      <select id="tagFilter" onchange="loadPrompts()"><option value="">标签</option></select>
      <span class="count-badge" id="countBadge">0</span>
      <button class="btn btn-sm btn-ghost" id="batchToggle" onclick="toggleBatchMode()">☑ 批量</button>
    </div>
    <div class="batch-toolbar" id="batchToolbar">
      <input type="checkbox" id="batchSelectAll" onchange="toggleSelectAll(this.checked)" style="accent-color:#6366f1;cursor:pointer;">
      <span style="font-size:11px;color:#aaa;">全选</span>
      <span class="batch-info" id="batchInfo">已选 0 项</span>
      <button class="btn btn-sm btn-success" id="batchRunBtn" onclick="batchRun()" disabled>🚀 批量跑图</button>
      <button class="btn btn-sm btn-danger" id="batchStopBtn" onclick="batchStop()" style="display:none;">⏹ 停止</button>
    </div>
    <div class="batch-progress" id="batchProgress">
      <div class="bp-text" id="batchProgressText">准备中...</div>
      <div class="bp-bar-wrap"><div class="bp-bar-fill" id="batchProgressFill"></div></div>
    </div>
    <div class="prompt-list" id="promptList"></div>
  </div>
  <div class="resize-handle" id="resizeHandle"></div>

  <div class="main">
    <div class="detail" id="detailPanel">
      <div class="placeholder">← 从左侧选择一个提示词</div>
    </div>
    <div class="output-area" id="outputArea">
      <div class="output-header">
        <span id="outputTitle">🖼️ 生成结果</span>
        <button class="close-output" onclick="closeOutput()">&times;</button>
      </div>
      <div class="progress-bar-wrap"><div class="progress-bar-fill" id="progressFill"></div></div>
      <div class="progress-info" id="progressInfo"></div>
      <div class="output-body" id="outputBody"></div>
    </div>
    <div class="footer">
      <div class="workflow-path" id="workflowPath">工作流: <span id="workflowLabel">加载中...</span></div>
      <button class="btn" id="runBtn" onclick="runPrompt()" disabled>🚀 跑图</button>
    </div>
  </div>
</div>

<!-- Lightbox -->
<div class="lightbox" id="lightbox" onclick="closeLightbox()">
  <img id="lightboxImg" src="" alt="">
</div>

<!-- Toast -->
<div id="toast"></div>

<!-- Modal -->
<div class="modal-overlay" id="modalOverlay">
  <div class="modal">
    <div class="modal-header">
      <h2 id="modalTitle">新建提示词</h2>
      <button class="close-btn" onclick="closeModal()">&times;</button>
    </div>
    <div class="modal-body" id="modalBody">
      <label>正面提示词 *
        <textarea id="f_prompt" rows="4"></textarea>
      </label>
      <label>负面提示词
        <textarea id="f_neg" rows="2"></textarea>
      </label>
      <div class="form-row">
        <label>步数 <input type="number" id="f_steps" placeholder="30"></label>
        <label>CFG <input type="number" step="0.1" id="f_cfg" placeholder="4.0"></label>
      </div>
      <div class="form-row">
        <label>采样器 <input id="f_sampler" placeholder="euler"></label>
        <label>种子 <input type="number" id="f_seed" placeholder="0"></label>
      </div>
      <div class="form-row">
        <label>模型 <input id="f_model" placeholder="模型名称"></label>
        <label>标签 <input id="f_tags" placeholder="逗号分隔,如: 人像,室外"></label>
      </div>
      <label>备注 <input id="f_note" placeholder="可选备注"></label>
      <input type="hidden" id="f_id" value="">
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost" onclick="closeModal()">取消</button>
      <button class="btn btn-success" onclick="savePrompt()">保存</button>
    </div>
  </div>
</div>

<script>
// ======== 全局状态 ========
let allPrompts = [];
let selectedId = null;
let comfyStatus = "offline";
let workflowList = [];

// ======== 加载提示词 ========
async function loadPrompts() {
  const url = "/api/prompts?search=" + encodeURIComponent(document.getElementById("searchInput").value) +
    "&tag=" + encodeURIComponent(document.getElementById("tagFilter").value);
  try {
    var resp = await fetch(url);
    var data = await resp.json();
    allPrompts = data.prompts || [];
    renderList(allPrompts);
    document.getElementById("countBadge").textContent = allPrompts.length;
  } catch (e) {
    showToast("加载失败: " + e.message, "error");
  }
}

// ======== 加载标签 ========
async function loadTags() {
  try {
    var resp = await fetch("/api/tags");
    var data = await resp.json();
    var sel = document.getElementById("tagFilter");
    (data.tags || []).forEach(function(t) {
      var opt = document.createElement("option");
      opt.value = t;
      opt.textContent = t;
      sel.appendChild(opt);
    });
  } catch (_) {}
}

var workflowSort = "mtime";

// ======== 加载工作流列表 ========
async function loadWorkflows() {
  try {
    var resp = await fetch("/api/workflows?sort=" + workflowSort);
    var data = await resp.json();
    var sel = document.getElementById("workflowSelect");
    sel.innerHTML = "";
    workflowList = data.workflows || [];
    // 如果有自定义工作流，加到列表最前面
    var customName = "";
    try { customName = localStorage.getItem("customWorkflowName") || ""; } catch(_) {}
    if (customName) {
      workflowList.unshift({
        path: "__custom__" + customName,
        name: "📁 " + customName,
      });
    }
    if (workflowList.length === 0) {
      sel.innerHTML = '<option value="">无可用工作流</option>';
      return;
    }
    var defaultPath = data.default || "";
    workflowList.forEach(function(w) {
      var opt = document.createElement("option");
      opt.value = w.path;
      opt.textContent = w.name;
      sel.appendChild(opt);
    });
    // 优先用 localStorage 保存的，其次服务端默认，最后第一个
    var preferPath = _savedWorkflow || defaultPath;
    if (preferPath) {
      for (var i = 0; i < sel.options.length; i++) {
        if (sel.options[i].value === preferPath) {
          sel.selectedIndex = i;
          break;
        }
      }
    }
    if (!sel.value && workflowList.length > 0) {
      sel.value = workflowList[0].path;
    }
    onWorkflowChange();
  } catch (_) {}
}

function onWorkflowChange() {
  var sel = document.getElementById("workflowSelect");
  var name = sel.options[sel.selectedIndex]?.text || "未知";
  document.getElementById("workflowLabel").textContent = name;
  document.getElementById("workflowPath").title = sel.value || "";
  savePrefs();
}

function toggleWorkflowSort() {
  workflowSort = (workflowSort === "mtime") ? "name" : "mtime";
  document.getElementById("sortBtn").innerHTML = "↕ " + (workflowSort === "mtime" ? "最近" : "名称");
  savePrefs();
  loadWorkflows();
}

// ======== 渲染列表 ========
var batchMode = false;
var selectedIds = new Set();

function renderList(prompts) {
  var list = document.getElementById("promptList");
  list.innerHTML = "";
  if (prompts.length === 0) {
    list.innerHTML = '<div style="text-align:center;color:#555;padding:40px;font-size:13px;">暂无匹配的提示词</div>';
    return;
  }
  prompts.forEach(function(p) {
    var div = document.createElement("div");
    div.className = "prompt-item" + (p.id === selectedId ? " active" : "");
    div.dataset.id = p.id;
    var tags = (p.tags || "").split(",").filter(Boolean);
    var tagsHtml = tags.map(function(t) {
      return '<span class="tag">' + escHtml(t.trim()) + '</span>';
    }).join("");
    var preview = escHtml(p.prompt_preview);
    if (p.prompt_preview.length >= 60) preview += "...";
    var content =
      '<div class="preview">' + preview + '</div>' +
      '<div class="meta">' +
        (p.steps ? '<span class="badge">' + p.steps + '步</span>' : "") +
        (p.sampler ? '<span style="color:#888;">' + escHtml(p.sampler) + '</span>' : "") +
        tagsHtml +
      '</div>';
    if (batchMode) {
      var checked = selectedIds.has(p.id) ? " checked" : "";
      div.innerHTML = '<div class="item-row"><input type="checkbox" class="item-check" data-id="' + p.id + '"' + checked + ' onclick="event.stopPropagation();toggleItemSelect(' + p.id + ',this.checked)"><div class="item-body">' + content + '</div></div>';
    } else {
      div.innerHTML = content;
    }
    div.onclick = function(e) {
      if (e.target.classList.contains("item-check")) return;
      selectPrompt(p.id);
    };
    list.appendChild(div);
  });
}

// ======== 选中提示词 ========
async function selectPrompt(id) {
  selectedId = id;
  updateRunBtn();
  // 刷新高亮
  renderList(allPrompts);
  try {
    var resp = await fetch("/api/prompts/" + id);
    var p = await resp.json();
    renderDetail(p);
  } catch (e) {
    showToast("加载详情失败: " + e.message, "error");
  }
}

// ======== 渲染详情 ========
var _currentPromptData = null;

function renderDetail(p) {
  _currentPromptData = p;
  var panel = document.getElementById("detailPanel");
  var tags = (p.tags || "").split(",").filter(Boolean);
  var tagHtml = tags.map(function(t) {
    return '<span style="background:#25253a;color:#818cf8;padding:2px 8px;border-radius:4px;font-size:11px;margin-right:4px;">' + escHtml(t.trim()) + '</span>';
  }).join("");

  panel.innerHTML =
    '<div class="actions">' +
      '<button class="btn btn-sm btn-warning" onclick="openEditModal(' + p.id + ')">✏️ 编辑</button>' +
      '<button class="btn btn-sm btn-danger" onclick="deletePrompt(' + p.id + ')">🗑️ 删除</button>' +
    '</div>' +
    '<div class="section"><h3 class="section-header">📝 正面提示词 <button class="copy-btn" onclick="copyPromptText(this, 0)">复制</button></h3><div class="content pos">' + escHtml(p.prompt) + '</div></div>' +
    '<div class="section"><h3 class="section-header">🚫 负面提示词 <button class="copy-btn" onclick="copyPromptText(this, 1)">复制</button></h3><div class="content neg">' + escHtml(p.negative_prompt || "(空)") + '</div></div>' +
    '<div class="section"><h3>⚙️ 参数</h3><div class="params">' +
      '<div class="param-item"><div class="label">步数</div><div class="value">' + (p.steps || "-") + '</div></div>' +
      '<div class="param-item"><div class="label">CFG</div><div class="value">' + (p.cfg_scale || "-") + '</div></div>' +
      '<div class="param-item"><div class="label">采样器</div><div class="value">' + escHtml(p.sampler || "-") + '</div></div>' +
      '<div class="param-item"><div class="label">种子</div><div class="value">' + (p.seed ?? "-") + '</div></div>' +
      '<div class="param-item"><div class="label">分辨率</div><div class="value">' + (p.width ? p.width + "×" + p.height : "-") + '</div></div>' +
      '<div class="param-item"><div class="label">模型</div><div class="value" style="font-size:11px;">' + escHtml(p.model || "-") + '</div></div>' +
      (p.width ? '<div style="grid-column:1/-1;background:#1a1a2e;border-radius:6px;padding:6px 12px;font-size:11px;color:#818cf8;text-align:center;">🔄 推送时将工作流分辨率覆盖为 ' + p.width + '×' + p.height + '</div>' : '') +
    '</div></div>' +
    (p.note ? '<div class="section"><h3>📌 备注</h3><div class="note-box">' + escHtml(p.note) + '</div></div>' : "") +
    '<div class="section"><h3>🏷️ 标签</h3><div>' + (tagHtml || '<span style="color:#666;font-size:13px;">无标签</span>') + '</div></div>' +
    '<div style="color:#555;font-size:11px;margin-top:16px;">创建时间: ' + (p.created_at || "未知") + '</div>';
}

// ======== Modal CRUD ========
function openCreateModal() {
  document.getElementById("modalTitle").textContent = "新建提示词";
  document.getElementById("f_id").value = "";
  document.getElementById("f_prompt").value = "";
  document.getElementById("f_neg").value = "";
  document.getElementById("f_steps").value = "";
  document.getElementById("f_cfg").value = "";
  document.getElementById("f_sampler").value = "";
  document.getElementById("f_seed").value = "";
  document.getElementById("f_model").value = "";
  document.getElementById("f_tags").value = "";
  document.getElementById("f_note").value = "";
  document.getElementById("modalOverlay").classList.add("active");
}

async function openEditModal(id) {
  document.getElementById("modalTitle").textContent = "编辑提示词 #" + id;
  document.getElementById("f_id").value = id;
  try {
    var resp = await fetch("/api/prompts/" + id);
    var p = await resp.json();
    document.getElementById("f_prompt").value = p.prompt || "";
    document.getElementById("f_neg").value = p.negative_prompt || "";
    document.getElementById("f_steps").value = p.steps || "";
    document.getElementById("f_cfg").value = p.cfg_scale || "";
    document.getElementById("f_sampler").value = p.sampler || "";
    document.getElementById("f_seed").value = p.seed || "";
    document.getElementById("f_model").value = p.model || "";
    document.getElementById("f_tags").value = p.tags || "";
    document.getElementById("f_note").value = p.note || "";
    document.getElementById("modalOverlay").classList.add("active");
  } catch (e) {
    showToast("加载失败: " + e.message, "error");
  }
}

function closeModal() {
  document.getElementById("modalOverlay").classList.remove("active");
}

async function savePrompt() {
  var data = {
    prompt: document.getElementById("f_prompt").value,
    negative_prompt: document.getElementById("f_neg").value,
    steps: parseInt(document.getElementById("f_steps").value) || null,
    cfg_scale: parseFloat(document.getElementById("f_cfg").value) || null,
    sampler: document.getElementById("f_sampler").value,
    seed: parseInt(document.getElementById("f_seed").value) || null,
    model: document.getElementById("f_model").value,
    tags: document.getElementById("f_tags").value,
    note: document.getElementById("f_note").value,
  };
  var id = document.getElementById("f_id").value;
  var isEdit = !!id;
  try {
    var resp;
    if (isEdit) {
      resp = await fetch("/api/prompts/" + id, { method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data) });
    } else {
      resp = await fetch("/api/prompts", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data) });
    }
    var r = await resp.json();
    if (r.success) {
      showToast(isEdit ? "✅ 已更新" : "✅ 已创建", "success");
      closeModal();
      loadTags();
      loadPrompts();
      if (isEdit) selectPrompt(parseInt(id));
    } else {
      showToast("❌ " + (r.error || "失败"), "error");
    }
  } catch (e) {
    showToast("❌ " + e.message, "error");
  }
}

async function deletePrompt(id) {
  if (!confirm("确定删除提示词 #" + id + " 吗？")) return;
  try {
    var resp = await fetch("/api/prompts/" + id, { method: "DELETE" });
    var r = await resp.json();
    if (r.success) {
      showToast("🗑️ 已删除", "success");
      if (selectedId === id) {
        selectedId = null;
        document.getElementById("detailPanel").innerHTML = '<div class="placeholder">← 从左侧选择一个提示词</div>';
      }
      loadTags();
      loadPrompts();
      updateRunBtn();
    } else {
      showToast("❌ " + (r.error || "删除失败"), "error");
    }
  } catch (e) {
    showToast("❌ " + e.message, "error");
  }
}

// ======== 发送到 ComfyUI ========
async function runPrompt() {
  if (!selectedId) return;
  var btn = document.getElementById("runBtn");
  btn.disabled = true;
  btn.textContent = "⏳ 发送中...";
  var workflowPath = document.getElementById("workflowSelect").value;
  var runBody = { id: selectedId, workflow_path: workflowPath };
  if (workflowPath && workflowPath.indexOf("__custom__") === 0) {
    runBody.workflow_content = localStorage.getItem("customWorkflowContent") || "";
  }
  try {
    var resp = await fetch("/api/run", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(runBody),
    });
    var data = await resp.json();
    if (data.success) {
      var pId = data.result?.prompt_id || "";
      if (pId) showProgress(pId);
      var dimMsg = "";
      if (data.dimensions) {
        dimMsg = " · " + data.dimensions;
      }
      showToast("✅ 已推送" + dimMsg + " (ID: " + pId + ")", "success");
    } else {
      showToast("❌ " + (data.error || "推送失败"), "error");
    }
  } catch (e) {
    showToast("❌ " + e.message, "error");
  } finally {
    btn.textContent = "🚀 跑图";
    updateRunBtn();
  }
}

// ======== 检查 ComfyUI 状态 ========
async function checkStatus() {
  var dot = document.getElementById("statusDot");
  var text = document.getElementById("statusText");
  try {
    var resp = await fetch("/api/status");
    var s = await resp.json();
    comfyStatus = s.comfyui;
    if (s.comfyui === "online") {
      dot.className = "status-dot online";
      text.textContent = "ComfyUI 在线 · 运行中:" + s.queue_running + " 队列:" + s.queue_pending;
    } else {
      dot.className = "status-dot offline";
      text.textContent = "ComfyUI 离线";
    }
  } catch (_) {
    dot.className = "status-dot offline";
    text.textContent = "ComfyUI 未响应";
    comfyStatus = "offline";
  }
  updateRunBtn();
}

function updateRunBtn() {
  var btn = document.getElementById("runBtn");
  btn.disabled = !(selectedId && comfyStatus === "online" &&
    document.getElementById("workflowSelect").value);
}

// ======== 工具 ========
function escHtml(s) {
  if (!s) return "";
  var d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function escAttr(s) {
  if (!s) return "";
  return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, "&#10;").replace(/\r/g, "&#13;");
}

var debounceTimer;
function debounceSearch() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(loadPrompts, 300);
}

function showToast(msg, type) {
  var t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "show " + (type || "info");
  clearTimeout(t._hide);
  t._hide = setTimeout(function() { t.className = ""; }, 3000);
}

// ======== 复制功能 ========
function copyPromptText(btn, type) {
  if (!_currentPromptData) return;
  var text = type === 0 ? (_currentPromptData.prompt || '') : (_currentPromptData.negative_prompt || '');
  navigator.clipboard.writeText(text).then(function() {
    btn.textContent = "已复制";
    btn.classList.add("copied");
    setTimeout(function() { btn.textContent = "复制"; btn.classList.remove("copied"); }, 1500);
  }, function() {
    showToast("复制失败", "error");
  });
}

// ======== 批量模式 ========
function toggleBatchMode() {
  batchMode = !batchMode;
  selectedIds.clear();
  document.getElementById("batchToolbar").classList.toggle("show", batchMode);
  document.getElementById("batchToggle").textContent = batchMode ? "✕ 取消批量" : "☑ 批量";
  updateBatchInfo();
  renderList(allPrompts);
}

function toggleItemSelect(id, checked) {
  if (checked) selectedIds.add(id); else selectedIds.delete(id);
  updateBatchInfo();
}

function toggleSelectAll(checked) {
  if (checked) {
    allPrompts.forEach(function(p) { selectedIds.add(p.id); });
  } else {
    selectedIds.clear();
  }
  renderList(allPrompts);
  updateBatchInfo();
}

function updateBatchInfo() {
  var count = selectedIds.size;
  document.getElementById("batchInfo").textContent = "已选 " + count + " 项";
  document.getElementById("batchRunBtn").disabled = count === 0 || comfyStatus !== "online";
}

// ======== 批量跑图 ========
var batchRunning = false;
var batchStopFlag = false;

async function batchRun() {
  if (selectedIds.size === 0) return;
  var workflowPath = document.getElementById("workflowSelect").value;
  if (!workflowPath) { showToast("请先选择工作流", "error"); return; }

  batchRunning = true;
  batchStopFlag = false;
  var ids = Array.from(selectedIds);
  var total = ids.length;
  var done = 0;
  var failed = 0;

  document.getElementById("batchRunBtn").style.display = "none";
  document.getElementById("batchStopBtn").style.display = "";
  document.getElementById("batchProgress").classList.add("show");
  document.getElementById("batchProgressText").textContent = "0/" + total + " 完成";
  document.getElementById("batchProgressFill").style.width = "0%";

  for (var i = 0; i < ids.length; i++) {
    if (batchStopFlag) break;
    var pid = ids[i];
    document.getElementById("batchProgressText").textContent = (i + 1) + "/" + total + " 正在推送 #" + pid + "...";
    var runBody = { id: pid, workflow_path: workflowPath };
    if (workflowPath.indexOf("__custom__") === 0) {
      runBody.workflow_content = localStorage.getItem("customWorkflowContent") || "";
    }
    try {
      var resp = await fetch("/api/run", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(runBody),
      });
      var data = await resp.json();
      if (data.success) {
        done++;
      } else {
        failed++;
      }
    } catch (e) {
      failed++;
    }
    document.getElementById("batchProgressFill").style.width = Math.round(((i + 1) / total) * 100) + "%";
    document.getElementById("batchProgressText").textContent = (i + 1) + "/" + total + " 完成";
    // 等待一下再发下一个，避免瞬间打满队列
    if (i < ids.length - 1 && !batchStopFlag) {
      await new Promise(function(r) { setTimeout(r, 1500); });
    }
  }

  batchRunning = false;
  document.getElementById("batchRunBtn").style.display = "";
  document.getElementById("batchStopBtn").style.display = "none";
  var msg = batchStopFlag ? "批量跑图已停止，" : "批量跑图完成，";
  msg += "成功 " + done + "，失败 " + failed;
  showToast(msg, failed > 0 ? "error" : "success");
  setTimeout(function() {
    document.getElementById("batchProgress").classList.remove("show");
  }, 3000);
}

function batchStop() {
  batchStopFlag = true;
  document.getElementById("batchProgressText").textContent = "正在停止...";
}

// ======== localStorage 持久化 ========
function savePrefs() {
  var outputImg = document.querySelector("#outputBody img");
  var prefs = {
    workflowPath: document.getElementById("workflowSelect").value,
    workflowSort: workflowSort,
    sidebarWidth: document.getElementById("sidebar").style.width || "",
    lastOutput: outputImg ? outputImg.src : (localStorageLastOutput || ""),
  };
  localStorageLastOutput = prefs.lastOutput;
  try { localStorage.setItem("promptBrowserPrefs", JSON.stringify(prefs)); } catch(_) {}
}
var localStorageLastOutput = "";
function loadPrefs() {
  try {
    var raw = localStorage.getItem("promptBrowserPrefs");
    if (!raw) return;
    var prefs = JSON.parse(raw);
    if (prefs.workflowSort) workflowSort = prefs.workflowSort;
    document.getElementById("sortBtn").innerHTML = "↕ " + (workflowSort === "mtime" ? "最近" : "名称");
    if (prefs.sidebarWidth) document.getElementById("sidebar").style.width = prefs.sidebarWidth;
    _savedWorkflow = prefs.workflowPath || "";
    // 恢复上次出图
    if (prefs.lastOutput) {
      localStorageLastOutput = prefs.lastOutput;
    }
  } catch(_) {}
}

// 页面加载完成后检查是否有历史出图
function restoreLastOutput() {
  if (!localStorageLastOutput) return;
  var area = document.getElementById("outputArea");
  var body = document.getElementById("outputBody");
  body.innerHTML = "";
  var el = document.createElement("img");
  el.src = localStorageLastOutput;
  el.style.cursor = "zoom-in";
  el.title = "点击查看大图（上次生成结果）";
  el.onclick = function() { openLightbox(el.src); };
  body.appendChild(el);
  area.classList.add("show");
  document.getElementById("outputTitle").textContent = "🖼️ 上次生成结果";
  document.getElementById("progressFill").style.width = "100%";
  document.getElementById("progressInfo").textContent = "✅ 已完成";
}
var _savedWorkflow = "";
var _customWorkflowPath = "";

// ======== 自定义工作流加载 ========
function pickWorkflowFile(event) {
  var file = event.target.files[0];
  if (!file) return;
  // 通过 API 验证
  var formData = new FormData();
  // 读取文件内容后发送路径验证 — 但浏览器只能拿到文件名，拿不到完整路径
  // 改用上传方式：把文件内容发到服务器保存为一个临时引用
  var reader = new FileReader();
  reader.onload = function(e) {
    var content = e.target.result;
    // 快速前端校验
    try {
      var wf = JSON.parse(content);
      // 兼容 API 格式 {node_id: {class_type}} 和 画布格式 {nodes: [{type}]}
      var hasClip = false;
      if (wf.nodes && Array.isArray(wf.nodes)) {
        hasClip = wf.nodes.some(function(n) { return n && n.type === "CLIPTextEncode"; });
      } else {
        hasClip = Object.values(wf).some(function(v) {
          return v && v.class_type === "CLIPTextEncode";
        });
      }
      if (!hasClip) {
        showToast("❌ 所选文件没有 CLIPTextEncode 节点", "error");
        return;
      }
    } catch(_) {
      showToast("❌ 无效的 JSON 文件", "error");
      return;
    }
    // 保存到 localStorage
    try { localStorage.setItem("customWorkflowName", file.name); } catch(_) {}
    try { localStorage.setItem("customWorkflowContent", content); } catch(_) {}
    _customWorkflowPath = "__custom__" + file.name;
    showToast("✅ 已加载自定义工作流: " + file.name, "success");
    loadWorkflows();
  };
  reader.readAsText(file);
  event.target.value = "";
}

// ======== 侧栏拖动缩放 ========
(function setupResize() {
  var handle = document.getElementById("resizeHandle");
  var sidebar = document.getElementById("sidebar");
  var isDragging = false;
  handle.addEventListener("mousedown", function(e) {
    isDragging = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  });
  document.addEventListener("mousemove", function(e) {
    if (!isDragging) return;
    var w = Math.max(280, Math.min(800, e.clientX - 2));
    sidebar.style.width = w + "px";
    savePrefs();
  });
  document.addEventListener("mouseup", function() {
    if (isDragging) {
      isDragging = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      savePrefs();
    }
  });
})();

// ======== 生成进度 & 出图 ========
var currentPromptId = null;
var progressTimer = null;

function showProgress(promptId) {
  currentPromptId = promptId;
  var area = document.getElementById("outputArea");
  area.classList.add("show");
  document.getElementById("progressFill").style.width = "0%";
  document.getElementById("progressInfo").textContent = "排队中...";
  document.getElementById("outputTitle").textContent = "⏳ 生成中";
  document.getElementById("outputBody").innerHTML = "";
  if (progressTimer) clearInterval(progressTimer);
  progressTimer = setInterval(pollProgress, 1000);
}

function openLightbox(src) {
  document.getElementById("lightboxImg").src = src;
  document.getElementById("lightbox").classList.add("show");
}
function closeLightbox() {
  document.getElementById("lightbox").classList.remove("show");
}
document.addEventListener("keydown", function(e) {
  if (e.key === "Escape") closeLightbox();
});

function closeOutput() {
  document.getElementById("outputArea").classList.remove("show");
  if (progressTimer) { clearInterval(progressTimer); progressTimer = null; }
  currentPromptId = null;
}

async function pollProgress() {
  if (!currentPromptId) return;
  try {
    var resp = await fetch("/api/progress?prompt_id=" + encodeURIComponent(currentPromptId));
    var data = await resp.json();
    if (data.error) { showToast("进度查询失败: " + data.error, "error"); return; }

    var fill = document.getElementById("progressFill");
    var info = document.getElementById("progressInfo");
    var title = document.getElementById("outputTitle");

    if (data.status === "pending") {
      fill.style.width = "0%";
      info.textContent = "⏳ 排队中... (前 " + (data.pending_count || "?") + " 个)";
      title.textContent = "⏳ 排队中";
      return;
    }

    if (data.status === "running") {
      var pct = data.max > 0 ? Math.round((data.progress / data.max) * 100) : -1;
      if (pct >= 0) {
        fill.style.width = Math.min(pct, 100) + "%";
        info.textContent = data.current_node
          ? pct + "% · " + data.current_node : pct + "%";
        title.textContent = "⏳ 生成中 " + pct + "%";
      } else {
        fill.style.width = "30%";
        var dot = ".".repeat(((Date.now() / 800) | 0) % 4);
        info.textContent = "⏳ 生成中" + dot;
        title.textContent = "⏳ 生成中";
      }
      return;
    }

    if (data.status === "done" || data.done) {
      clearInterval(progressTimer);
      progressTimer = null;
      fill.style.width = "100%";
      info.textContent = "✅ 完成!";
      title.textContent = "🖼️ 生成结果";
      // 显示图片
      var body = document.getElementById("outputBody");
      body.innerHTML = "";
      if (data.images && data.images.length > 0) {
        var img = data.images[0];
        var viewUrl = "/api/image?filename=" + encodeURIComponent(img.filename)
          + "&subfolder=" + encodeURIComponent(img.subfolder || "")
          + "&type=" + (img.type || "output");
        var el = document.createElement("img");
        el.src = viewUrl;
        el.alt = img.filename;
        el.style.cursor = "zoom-in";
        el.title = "点击查看大图";
        el.onclick = function() { openLightbox(el.src); };
        el.onload = function() { title.textContent = "🖼️ " + img.filename; savePrefs(); };
        body.appendChild(el);
        if (data.images.length > 1) {
          var info2 = document.createElement("div");
          info2.style.cssText = "font-size:11px;color:#666;text-align:center;margin-top:8px;";
          info2.textContent = "共 " + data.images.length + " 张输出";
          body.appendChild(info2);
        }
        savePrefs();
      } else {
        body.innerHTML = '<div style="color:#666;font-size:13px;">生成完成，但未找到输出图片（可能还在写入）</div>';
      }
      // 再轮询几次确保图片加载
      return;
    }

    // unknown — 可能还没进队列
    fill.style.width = "0%";
    info.textContent = "⏳ 等待入队...";
    title.textContent = "⏳ 等待中";
  } catch (_) {}
}

// ======== 初始化 ========
loadPrefs();
loadTags();
loadPrompts();
loadWorkflows();
checkStatus();
setInterval(checkStatus, 5000);
// 延迟恢复上次出图（等页面渲染完）
setTimeout(restoreLastOutput, 500);
</script>
</body>
</html>"""

# ===================================================================
# 入口
# ===================================================================

if __name__ == "__main__":
    print("=" * 56)
    print("  Prompt Browser + ComfyUI Launcher v2")
    print("=" * 56)
    print(f"  DB:       {DB_PATH}")
    print(f"  工作流:    {DEFAULT_WORKFLOW or '(未找到)'}")
    print(f"  ComfyUI:  {COMFYUI_API}")
    print(f"  本地页面:  http://{HOST}:{PORT}")
    print("=" * 56)
    print("  按 Ctrl+C 停止服务")
    print()

    server = HTTPServer((HOST, PORT), PromptHandler)
    threading.Thread(target=open_browser, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.server_close()
