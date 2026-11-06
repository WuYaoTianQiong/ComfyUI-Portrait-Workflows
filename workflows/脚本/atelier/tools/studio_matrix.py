"""合成台工作流实测矩阵：每个工作流 × 每个可提交角色组合，真出图并记录结果。

用途：工作流增删改之后，用它一次性验证「1/2/3/4 图缺槽能否出图、出成什么样」，
而不是靠抽查几张。结果用于 `文档/参考图库_合成台工作流实测矩阵_20261106.md`。

- 组合清单来自 `tools/studio_matrix_catalog.py`（与后端同一套可裁剪判定算出）；
- 缺服装的组合会被后端自动切 bare（素体展示），记录 body_mode/body_mode_auto 供核对；
- 每组输出到 `output/studio-matrix[-tag]/`，失败组记录 error/detail。

用法（**必须分批**：连续压测会把 GGUF 反量化的 ComfyUI 压崩）：
    python tools/studio_matrix_catalog.py            # 先算组合清单
    python tools/studio_matrix.py --limit 5 --tag b1 # 每批 ≤5 组，批间重启 ComfyUI
    python tools/studio_matrix.py --limit 5 --tag b2 # 续跑：自动跳过已完成组合
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

#: tools/ 的上一级就是项目根（main.py / data / app 都在这）
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PORT = 8772
BASE = f"http://127.0.0.1:{PORT}"
TOOLS_DIR = Path(__file__).resolve().parent
CATALOG = TOOLS_DIR / "studio_matrix_catalog.json"
OUT = TOOLS_DIR / "studio_matrix_result.json"
SERVER_LOG = TOOLS_DIR / "studio_matrix_server.log"
STATE_DIR = TOOLS_DIR / "studio_matrix_state"

from app.config import settings  # noqa: E402
from app.services import reference_library, uploads  # noqa: E402


def get_json(path: str):
    with urllib.request.urlopen(BASE + path, timeout=60) as response:
        return json.loads(response.read())


def post_json(path: str, payload: dict):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, {"detail": error.read().decode("utf-8", "replace")}


def first_id(library: str) -> str:
    payload = get_json(f"/api/reference/items?library={library}&page_size=1")
    items = payload.get("items") or []
    return str(items[0]["id"]) if items else ""


def wait_job(job_id: int, timeout: int = 900) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        try:
            last = get_json(f"/api/jobs/{job_id}")
        except Exception as exc:  # noqa: BLE001
            last = {"status": "poll_error", "error": repr(exc)}
        # 注意：任务终态是 done / error（不是 failed），漏判会空等到超时
        if last.get("status") in {"done", "error", "failed"}:
            return last
        time.sleep(4)
    return {**last, "status": "timeout"}


def prepare_extra() -> str:
    """Flux 四图组合需要第 4 张（只允许 uploads 内文件）：复制一张参考图进去，跑完删除。"""
    base = uploads.uploads_dir()
    base.mkdir(parents=True, exist_ok=True)
    target = base / "_tmp_extra_ref.png"
    if target.exists():
        return str(target)
    costume_path = reference_library.resolve_image("costume", "SPR-0001", "image")
    shutil.copy2(costume_path, target)
    return str(target)


cases = json.loads(CATALOG.read_text(encoding="utf-8"))["studio"]

parser = argparse.ArgumentParser()
parser.add_argument("--limit", type=int, default=5, help="本次最多跑几组（分批跑，避免再撞显存边界）")
parser.add_argument("--tag", default="", help="输出子目录后缀，避免不同批次文件名互相覆盖")
parser.add_argument("--no-resume", action="store_true", help="不跳过已完成组合")
args = parser.parse_args()

subfolder = f"studio-matrix-{args.tag}" if args.tag else "studio-matrix"

# DB 副本固定复用：job id 跨批次递增，输出文件名不会覆盖上一批
state_dir = STATE_DIR
state_dir.mkdir(exist_ok=True)
db_copy = str(state_dir / "matrix.db")
tmp = str(state_dir)
if not os.path.exists(db_copy):
    shutil.copy2(settings.db_path, db_copy)
    for suffix in ("-wal", "-shm"):
        src = str(settings.db_path) + suffix
        if os.path.exists(src):
            shutil.copy2(src, db_copy + suffix)

env = dict(os.environ)
env.update(
    {
        "ATELIER_DB_PATH": db_copy,
        "ATELIER_THUMBNAIL_DIR": os.path.join(tmp, "thumbs"),
        "ATELIER_NO_BROWSER": "1",
        "ATELIER_PORT": str(PORT),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
)
server_log = open(SERVER_LOG, "w", encoding="utf-8")
proc = subprocess.Popen(
    [sys.executable, "main.py"],
    cwd=str(ROOT),
    env=env,
    stdout=server_log,
    stderr=subprocess.STDOUT,
)

history: list[dict] = []
if OUT.exists() and not args.no_resume:
    try:
        history = json.loads(OUT.read_text(encoding="utf-8")).get("samples") or []
    except json.JSONDecodeError:
        history = []
done = {
    (item.get("workflow"), item.get("combo"))
    for item in history
    if item.get("job_status") == "done"
}
report: dict = {"samples": history, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
extra_path = ""
submitted = 0
try:
    for _ in range(120):
        time.sleep(0.5)
        try:
            get_json("/api/reference/libraries")
            break
        except Exception:
            continue

    portrait_id = first_id("portrait")
    costume_id = first_id("costume")
    pose_id = first_id("pose")
    extra_path = prepare_extra()
    report["ids"] = {
        "portrait": portrait_id,
        "costume": costume_id,
        "pose": pose_id,
        "extra": extra_path,
    }

    slot_values = {
        "portrait": {"portrait_id": portrait_id},
        "costume": {"costume_id": costume_id},
        "pose": {"pose_id": pose_id},
        "extra": {"extra_path": extra_path},
    }

    for workflow in cases:
        if submitted >= args.limit:
            break
        for combo in workflow["submittable"]:
            if submitted >= args.limit:
                break
            if (workflow["name"], combo) in done:
                continue
            submitted += 1
            roles = combo.split("+")
            body = {
                key: value
                for role in roles
                for key, value in slot_values[role].items()
            }
            entry: dict = {"workflow": workflow["name"], "combo": combo}
            started = time.time()
            status, payload = post_json(
                "/api/reference/recipes",
                {
                    **body,
                    "workflow": workflow["name"],
                    "style": "realistic",
                    "prompt_suffix": "",
                    "seed": 20261106,
                    "seed_mode": "fixed",
                    "output_subfolder": subfolder,
                },
            )
            entry["submit_status"] = status
            entry["body_mode"] = payload.get("body_mode") if isinstance(payload, dict) else None
            entry["body_mode_auto"] = (
                payload.get("body_mode_auto") if isinstance(payload, dict) else None
            )
            prompt = payload.get("prompt") if isinstance(payload, dict) else ""
            entry["prompt"] = prompt
            entry["bare_clause"] = "素体展示" in (prompt or "")
            job_id = payload.get("job_id") if isinstance(payload, dict) else None
            if status == 200 and job_id:
                snapshot = wait_job(int(job_id))
                entry["job_status"] = snapshot.get("status")
                entry["images"] = [
                    image
                    for item in (snapshot.get("items") or [])
                    for image in (item.get("images") or [])
                ]
                entry["job_error"] = next(
                    (
                        item.get("error")
                        for item in (snapshot.get("items") or [])
                        if item.get("error")
                    ),
                    "",
                )
            else:
                entry["submit_error"] = payload
            entry["elapsed_s"] = round(time.time() - started, 1)
            report["samples"].append(entry)
            OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
finally:
    report["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if extra_path:
        try:
            os.remove(extra_path)
        except OSError:
            pass
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except Exception:
        proc.kill()
    server_log.close()
