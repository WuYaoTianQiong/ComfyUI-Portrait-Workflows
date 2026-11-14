"""提示词批量跑图：按集合（e/f）投喂给 Krea2 的两个工作流。

两个工作流都是单程 8 步画质优先版，第二程节点在 JSON 里是 bypass(mode=4)。
ComfyUI 的 /prompt 接口没有 bypass 语义，直接提交会把第二程也跑一遍，
所以本脚本先把 bypass 节点从图里摘掉、把下游链接改接到它的上游。

用法：
    python tools/run_prompts.py --set f --dry-run
    python tools/run_prompts.py --set f
    python tools/run_prompts.py --set f --models porn
    python tools/run_prompts.py --set f --only F01,F13,F25
    python tools/run_prompts.py --set e --seed 0
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services import comfyui_client as comfy  # noqa: E402
from app.services.workflow_parser import ensure_api_format, inject_prompt, set_output_prefix  # noqa: E402
from tools.prompt_sets import META, SETS  # noqa: E402

WORKFLOW_DIRS = (
    settings.library_root / "通用工作流",
    settings.library_root,
)

WORKFLOWS = {
    "porn": "PornMaster_Krea2V25_T2I_FP8_1Pass.json",
    "moody": "MoodyKrea2_V8SE_T2I_FP8_1Pass.json",
}


def workflow_path(model_key: str) -> Path:
    """按新目录结构找文件；兼容旧库根布局。"""
    name = WORKFLOWS[model_key]
    for directory in WORKFLOW_DIRS:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    searched = ", ".join(str(d) for d in WORKFLOW_DIRS)
    raise FileNotFoundError(f"找不到工作流 {name}；已查找: {searched}")


def drop_bypassed_nodes(workflow: dict) -> int:
    """摘掉 mode=4 的 bypass 节点，并把下游链接改接到它同类型的上游。

    返回被摘掉的节点数。递归处理 bypass 链（175→176 这类）。
    """
    nodes = workflow.get("nodes") or []
    bypass_ids = {str(n.get("id")) for n in nodes if n.get("mode") == 4}
    if not bypass_ids:
        return 0

    by_id = {str(n.get("id")): n for n in nodes}
    link_map: dict[int, tuple[str, int]] = {}
    for link in workflow.get("links") or []:
        if isinstance(link, list) and len(link) >= 5:
            link_map[link[0]] = (str(link[1]), int(link[2]))

    def upstream(node_id: str, want_type: str, seen: frozenset = frozenset()):
        if node_id in seen:
            return None
        seen = seen | {node_id}
        node = by_id.get(node_id) or {}
        for inp in node.get("inputs") or []:
            if inp.get("type") != want_type or inp.get("link") is None:
                continue
            src = link_map.get(inp["link"])
            if not src:
                continue
            if src[0] in bypass_ids:
                return upstream(src[0], want_type, seen)
            return src
        return None

    new_links = []
    for link in workflow.get("links") or []:
        if not (isinstance(link, list) and len(link) >= 6):
            new_links.append(link)
            continue
        lid, frm, fslot, to, tslot, ltype = link[:6]
        if str(to) in bypass_ids:
            continue
        if str(frm) in bypass_ids:
            src = upstream(str(frm), ltype)
            if src is None:
                continue
            frm, fslot = int(src[0]), src[1]
        new_links.append([lid, frm, fslot, to, tslot, ltype])

    workflow["links"] = new_links
    workflow["nodes"] = [n for n in nodes if str(n.get("id")) not in bypass_ids]
    return len(bypass_ids)


def build_task(set_key: str, prompt_key: str, model_key: str, seed: int) -> dict:
    path = workflow_path(model_key)
    workflow = json.loads(path.read_text(encoding="utf-8"))
    dropped = drop_bypassed_nodes(workflow)
    api = ensure_api_format(workflow)
    inject_prompt(
        api,
        {
            "prompt": SETS[set_key][prompt_key],
            "negative_prompt": "",
            "seed": 0 if seed == 0 else seed,
            "seed_override": None if seed == 0 else seed,
            "orientation": "keep",
            "quality": "4K",
        },
    )
    prefix = f"{set_key.upper()}_group/{prompt_key}_{model_key}"
    set_output_prefix(api, prefix)
    return {
        "key": prompt_key,
        "model": model_key,
        "workflow": WORKFLOWS[model_key],
        "api": api,
        "nodes": len(api),
        "bypass_dropped": dropped,
        "prefix": prefix,
        "prompt_id": "",
        "状态": "待提交",
        "耗时": 0.0,
        "images": [],
        "错误": "",
    }


def collect_images(entry: dict) -> list[dict]:
    images = []
    for node_out in (entry.get("outputs") or {}).values():
        for img in node_out.get("images") or []:
            images.append(
                {
                    "filename": img.get("filename", ""),
                    "subfolder": img.get("subfolder", ""),
                    "type": img.get("type", "output"),
                }
            )
    return images


def wait_all(tasks: list[dict], interval: float, timeout: int) -> None:
    pending = {t["prompt_id"]: t for t in tasks if t["prompt_id"]}
    deadline = time.time() + timeout

    while pending and time.time() < deadline:
        for pid in list(pending):
            hist = comfy.get_history_for_prompt(pid)
            if not hist or pid not in hist:
                continue
            entry = hist[pid]
            task = pending.pop(pid)
            status = (entry.get("status") or {}).get("status_str", "")
            task["耗时"] = round(time.time() - task["submitted_at"], 1)
            if status == "error":
                task["状态"] = "失败"
                messages = (entry.get("status") or {}).get("messages") or []
                task["错误"] = json.dumps(messages, ensure_ascii=False)[:300]
            else:
                task["状态"] = "完成"
                task["images"] = collect_images(entry)
        if pending:
            time.sleep(interval)

    for task in pending.values():
        task["状态"] = "超时"


def main() -> int:
    parser = argparse.ArgumentParser(description="提示词批量跑图（Krea2 双工作流）")
    parser.add_argument("--set", dest="set_key", default="f", choices=sorted(SETS), help="提示词集合")
    parser.add_argument("--models", default="porn,moody", help="porn / moody / porn,moody")
    parser.add_argument("--only", default="", help="只跑指定编号，逗号分隔")
    parser.add_argument("--seed", type=int, default=20261027, help="0 = 每张随机")
    parser.add_argument("--dry-run", action="store_true", help="只打印任务，不提交")
    parser.add_argument("--timeout", type=int, default=3600, help="整体等待上限（秒）")
    parser.add_argument("--interval", type=float, default=2.0, help="轮询间隔（秒）")
    args = parser.parse_args()

    prompts = SETS[args.set_key]
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    bad = [m for m in models if m not in WORKFLOWS]
    if bad:
        print(f"未知工作流: {bad}，可选: {list(WORKFLOWS)}")
        return 2

    keys = [k.strip() for k in args.only.split(",") if k.strip()] or list(prompts)
    bad_keys = [k for k in keys if k not in prompts]
    if bad_keys:
        print(f"未知提示词: {bad_keys}，可选: {list(prompts)}")
        return 2

    tasks = [build_task(args.set_key, k, m, args.seed) for m in models for k in keys]
    if not args.dry_run and not comfy.is_online():
        print(f"ComfyUI 未响应: {settings.comfyui_api}，先启动再跑。")
        return 1

    print("=" * 100)
    print(f"集合 {args.set_key.upper()} | ComfyUI {settings.comfyui_api} | seed={args.seed or '随机'} | {len(tasks)} 张")
    for t in tasks:
        meta = META.get(args.set_key, {}).get(t["key"], ("", "", ""))
        label = " | ".join(x for x in meta if x)
        print(f"  {t['key']:<4}{t['model']:<7}节点 {t['nodes']:>2}  {t['prefix']:<28}{label}")
    print("=" * 100)

    if args.dry_run:
        print("dry-run：未提交。")
        return 0

    for t in tasks:
        t["submitted_at"] = time.time()
        try:
            result = comfy.push_prompt(t["api"])
            t["prompt_id"] = result.get("prompt_id", "")
            t["状态"] = "已入队"
            print(f"[提交] {t['key']} {t['model']} -> {t['prompt_id']}")
        except Exception as exc:
            t["状态"] = "提交失败"
            t["错误"] = f"{type(exc).__name__}: {exc}"
            print(f"[提交失败] {t['key']} {t['model']}: {t['错误']}")

    wait_all(tasks, args.interval, args.timeout)

    print()
    print("=" * 100)
    print(f"{'编号':<6}{'工作流':<8}{'状态':<8}{'耗时':>9}  输出")
    print("-" * 100)
    for t in tasks:
        files = ", ".join(i["filename"] for i in t["images"]) or t["错误"][:60]
        print(f"{t['key']:<6}{t['model']:<8}{t['状态']:<8}{t['耗时']:>8.1f}s  {files}")
    print("=" * 100)

    output_root = Path(settings.comfyui_root) / "output"
    done = [t for t in tasks if t["状态"] == "完成"]
    print(f"完成 {len(done)}/{len(tasks)}；图片目录 {output_root / (args.set_key.upper() + '_group')}")

    report = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "set": args.set_key,
        "seed": args.seed,
        "comfyui": settings.comfyui_api,
        "tasks": [
            {
                "key": t["key"],
                "model": t["model"],
                "workflow": t["workflow"],
                "prompt_id": t["prompt_id"],
                "status": t["状态"],
                "elapsed": t["耗时"],
                "images": t["images"],
                "error": t["错误"],
            }
            for t in tasks
        ],
    }
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    report_path = log_dir / f"run_{args.set_key}_group_{time.strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告 {report_path}")

    return 0 if len(done) == len(tasks) else 1


if __name__ == "__main__":
    raise SystemExit(main())