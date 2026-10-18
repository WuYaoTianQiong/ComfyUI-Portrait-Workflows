# -*- coding: utf-8 -*-
"""
批量出图：主图(姿势) × 参考图(模特)，驱动 PornMaster_Flux2Klein9B_双图参考 工作流。

原理
    工作流本体当"模板"原样不动；脚本把它 界面格式(UI) → API格式 转换，
    然后逐个组合 POST /prompt，ComfyUI 串行执行。
    显存占用与你在界面里手点一次完全一样，所以不会像"工作流内做成 batch=9"那样爆显存。

快速开始
    1) 姿势图放 input/batch/pose/ ，模特图放 input/batch/model/ （文件名随意）
    2) python batch_refswap.py --dry-run   只看计划 + 静态校验，不入队
    3) python batch_refswap.py --check     队列忙时借间隙让服务器做一次全链路校验（不出图、不吃显存）
    4) python batch_refswap.py --limit 1   跑一个组合，确认效果和文件名都对
    5) python batch_refswap.py             正式跑；已跑过的组合自动跳过（断点续跑）

其他
    --only p1:m2                 只跑指定组合（label 用文件名主名）
    --poses a.png --models b.png 临时覆盖图片清单（冒烟用）
    --limit 2                    只跑前 2 个组合
    --no-resume                  忽略已完成记录，全部重跑
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "_已完成.jsonl"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

# 角色 -> API 输入名默认值；如需改动可在 config.json 的 input_keys 里覆盖
DEFAULT_INPUT_KEYS = {
    "main_image": "image",        # LoadImage 主图
    "ref_image": "image",         # LoadImage 参考图
    "prompt": "text",             # CLIPTextEncode
    "seed": "noise_seed",         # RandomNoise
    "save": "filename_prefix",    # SaveImage
}


# --------------------------------------------------------------------------- 基础工具
def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str, code: int = 1):
    log(msg)
    sys.exit(code)


def natural_key(p) -> list:
    """让 p2 排在 p10 前面。"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(p))]


class ComfyHTTPError(Exception):
    def __init__(self, code: int, body: str):
        super().__init__(f"HTTP {code}")
        self.code = code
        self.body = body


def http_json(url: str, payload=None, timeout: int = 60):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise ComfyHTTPError(e.code, e.read().decode("utf-8", "replace")) from None
    return json.loads(raw) if raw.strip() else {}


# --------------------------------------------------------------------------- 工作流 → API
def positional_widgets(spec: dict, values: list) -> dict:
    """老版本前端不写 widgets_values_named 时的兜底：按 INPUT_TYPES 声明顺序对应 widget。"""
    names = []
    for group in ("required", "optional"):
        for name, decl in (spec.get("input", {}).get(group) or {}).items():
            t = decl[0] if isinstance(decl, (list, tuple)) and decl else None
            if isinstance(t, list) or (isinstance(t, str) and t in ("INT", "FLOAT", "STRING", "BOOLEAN", "COMBO")):
                names.append(name)
    return dict(zip(names, values))


def ui_to_api(wf: dict, object_info: dict, mute_play_sound: bool = False):
    """把界面格式工作流转成 /prompt 需要的 API 格式。

    返回 (api_graph, dropped_dict)；dropped 里是被丢掉的前端专用/静音节点及原因。
    """
    nodes = wf.get("nodes") or []
    links = {l[0]: l for l in (wf.get("links") or []) if isinstance(l, list) and len(l) >= 6}

    kept, dropped = {}, {}
    for n in nodes:
        nid, ct, mode = n.get("id"), n.get("type"), n.get("mode", 0)
        if mode in (2, 4):
            dropped[nid] = f"{ct}（节点已静音/绕过）"
        elif ct not in object_info:
            dropped[nid] = f"{ct}（前端专用节点，后端无此类型）"
        else:
            kept[nid] = n

    api = {}
    for nid, n in kept.items():
        ct = n["type"]
        spec = object_info[ct]
        inp_spec = spec.get("input") or {}
        allowed = set(inp_spec.get("required") or {}) | set(inp_spec.get("optional") or {})

        inputs = {}
        wvn = n.get("widgets_values_named")
        pairs = wvn.items() if isinstance(wvn, dict) else positional_widgets(spec, n.get("widgets_values") or []).items()
        for k, v in pairs:
            if k in allowed:      # 丢掉前端专用 widget（如 LoadImage 的 upload、RandomNoise 的 control_after_generate）
                inputs[k] = v

        for inp in n.get("inputs") or []:
            name, lid = inp.get("name"), inp.get("link")
            if lid is None or name is None:
                continue
            lk = links.get(lid)
            if lk is None:
                continue
            src = lk[1]
            if src not in kept:
                raise RuntimeError(
                    f"节点 {nid}({ct}) 的输入 '{name}' 来自被丢弃的节点 {src}，无法自动转换。\n"
                    f"    处理办法：在工作流里删掉/绕过那个节点，或用界面 File → Export (API) 导出后把文件路径填到 config.json 的 workflow。")
            inputs[name] = [str(src), lk[2]]

        api[str(nid)] = {"class_type": ct, "inputs": inputs, "_meta": {"title": n.get("title") or ct}}

    if mute_play_sound:
        for node in api.values():
            if node["class_type"].startswith("PlaySound"):
                node["inputs"]["mode"] = "none"
    return api, dropped


def static_check(api: dict, object_info: dict):
    """离线检查：必填输入是否齐全、引用节点是否存在、输入名是否合法。"""
    problems, warns = [], []
    for nid, node in api.items():
        ct = node["class_type"]
        spec = object_info.get(ct)
        if spec is None:
            problems.append(f"节点 {nid}: 后端不认识类型 {ct}")
            continue
        inp_spec = spec.get("input") or {}
        req = set(inp_spec.get("required") or {})
        opt = set(inp_spec.get("optional") or {})
        given = set(node["inputs"])
        missing = sorted(req - given)
        if missing:
            problems.append(f"节点 {nid} ({ct}): 缺必填输入 {missing}")
        unknown = sorted(given - req - opt)
        if unknown:
            warns.append(f"节点 {nid} ({ct}): 后端不认识的输入 {unknown}（会被服务器拒绝）")
        for k, v in node["inputs"].items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0].isdigit():
                if v[0] not in api:
                    problems.append(f"节点 {nid}.{k} 指向不存在的节点 {v[0]}")
    return problems, warns


# --------------------------------------------------------------------------- 图片清单
def resolve_images(specs, base_dir: Path, label: str) -> list:
    """specs 支持精确相对路径或通配符，返回相对 base_dir 的 posix 路径列表。"""
    found, seen = [], set()
    for s in specs:
        s = str(s).replace("\\", "/")
        if any(c in s for c in "*?["):
            try:
                hits = [p for p in sorted(base_dir.glob(s), key=natural_key) if p.is_file()]
            except OSError as e:
                die(f"[!] {label}：读取 {base_dir} 失败：{e}")
            hits = [p for p in hits if p.suffix.lower() in IMAGE_EXT]
            if not hits:
                die(f"[!] {label}：通配符 '{s}' 在 {base_dir} 下没匹配到图片\n"
                    f"    请把图片放进去，或在 config.json 里改成实际文件名。")
        else:
            p = base_dir / s
            try:
                ok = p.is_file()
            except OSError as e:
                die(f"[!] {label}：无法访问 {p}：{e}")
            if not ok:
                die(f"[!] {label}：找不到文件 {p}")
            hits = [p]
        for h in hits:
            rel = h.relative_to(base_dir).as_posix()
            if rel not in seen:
                seen.add(rel)
                found.append(rel)
    return found


def resolve_seed(cfg: dict, idx: int) -> int:
    s = cfg.get("seed", 100000)
    if isinstance(s, bool):
        die("[!] config.seed 不能是 true/false")
    if isinstance(s, int):
        return s
    if s == "random":
        return random.randint(0, 2 ** 31 - 1)
    if s == "increment":
        return int(cfg.get("seed_base", 0)) + idx
    die(f"[!] config.seed 只能是整数 / \"random\" / \"increment\"，当前是 {s!r}")


# --------------------------------------------------------------------------- 提交与等待
def submit(api: dict, base_url: str, client_id: str) -> str:
    try:
        res = http_json(base_url + "/prompt", {"prompt": api, "client_id": client_id}, timeout=180)
    except ComfyHTTPError as e:
        detail = e.body
        try:
            errors = json.loads(e.body).get("node_errors") or {}
            if errors:
                detail = json.dumps(errors, ensure_ascii=False, indent=2)
        except Exception:
            pass
        raise RuntimeError(f"服务器拒绝了任务 (HTTP {e.code})：\n{detail}") from None
    return res["prompt_id"]


def wait_done(pid: str, base_url: str, timeout: int) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            hist = http_json(base_url + f"/history/{pid}", timeout=30)
        except Exception:
            time.sleep(3)
            continue
        if pid in hist:
            return hist[pid]
        time.sleep(2)
    raise TimeoutError(f"等待超过 {timeout}s 仍未完成")


def extract_outputs(entry: dict) -> list:
    out = []
    for o in (entry.get("outputs") or {}).values():
        for img in o.get("images") or []:
            sub = img.get("subfolder") or ""
            out.append(f"{sub}/{img['filename']}" if sub else img["filename"])
    return out


def append_manifest(record: dict) -> None:
    with open(MANIFEST, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_done() -> set:
    if not MANIFEST.exists():
        return set()
    done = set()
    with open(MANIFEST, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("ok"):
                done.add(f"{r['pose']}|{r['model']}")
    return done


# --------------------------------------------------------------------------- 主流程
def parse_args():
    ap = argparse.ArgumentParser(description="姿势 × 模特 批量出图（双图参考工作流）")
    ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--dry-run", action="store_true", help="只打印计划 + 静态校验，不入队")
    ap.add_argument("--check", action="store_true",
                    help="借队列忙的间隙提交整张图交给服务器全链路校验，然后立刻撤回（不出图、不吃显存）")
    ap.add_argument("--only", action="append", default=[], help="只跑指定组合，如 --only p1:m2（可重复）")
    ap.add_argument("--poses", default=None, help="临时覆盖姿势图清单，逗号分隔")
    ap.add_argument("--models", default=None, help="临时覆盖模特图清单，逗号分隔")
    ap.add_argument("--limit", type=int, default=0, help="最多跑前 N 个组合")
    ap.add_argument("--no-resume", action="store_true", help="忽略已完成记录，全部重跑")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    cfg_path = Path(args.config)
    if not cfg_path.is_file():
        die(f"[!] 找不到配置文件 {cfg_path}")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    base_url = str(cfg["comfy_url"]).rstrip("/")
    workflow_path = Path(cfg["workflow"])
    if not workflow_path.is_file():
        die(f"[!] 找不到工作流文件 {workflow_path}")
    input_dir = Path(cfg["input_dir"])

    try:
        object_info = http_json(base_url + "/object_info", timeout=120)
    except Exception as e:
        die(f"[!] 连不上 ComfyUI ({base_url})：{e}\n    请确认 ComfyUI 已启动，或改 config.json 里的 comfy_url。")

    wf = json.loads(workflow_path.read_text(encoding="utf-8"))
    if "nodes" in wf:                       # 界面格式 → 自动转换
        api_template, dropped = ui_to_api(wf, object_info, bool(cfg.get("mute_play_sound", True)))
    else:                                   # 已经是 File → Export (API) 的格式
        api_template, dropped = wf, {}

    problems, warns = static_check(api_template, object_info)
    log(f"[*] 工作流：{workflow_path.name}")
    log(f"[*] 转换出 {len(api_template)} 个后端节点"
        + (f"，丢弃前端专用/静音节点 {len(dropped)} 个" if dropped else ""))
    for nid, why in dropped.items():
        log(f"    - 丢 {nid}: {why}")
    for w in warns:
        log(f"    ! {w}")
    if problems:
        for p in problems:
            log(f"    x {p}")
        die("[!] 转换结果有问题，已中止（不提交）。")

    # ---- 图片清单
    node_ids = cfg["nodes"]
    input_keys = {**DEFAULT_INPUT_KEYS, **(cfg.get("input_keys") or {})}
    poses = [s.strip() for s in args.poses.split(",")] if args.poses else cfg["poses"]
    models = [s.strip() for s in args.models.split(",")] if args.models else cfg["models"]
    pose_files = resolve_images(poses, input_dir, "姿势图")
    model_files = resolve_images(models, input_dir, "模特图")
    log(f"[*] 姿势图 {len(pose_files)} 张，模特图 {len(model_files)} 张 -> 共 {len(pose_files) * len(model_files)} 个组合")

    jobs = [{"pose": p, "model": m} for p in pose_files for m in model_files]
    if args.only:
        want = set()
        for spec in args.only:
            pose_label, _, model_label = spec.partition(":")
            pose_label = pose_label or None
            model_label = model_label or None
            for f in pose_files:
                for m in model_files:
                    pl, ml = Path(f).stem, Path(m).stem
                    if (pose_label is None or pl == pose_label) and (model_label is None or ml == model_label):
                        want.add(f"{f}|{m}")
        jobs = [j for j in jobs if f"{j['pose']}|{j['model']}" in want]
        if not jobs:
            die("[!] --only 没匹配到任何组合")

    done = set() if args.no_resume else load_done()
    if done:
        log(f"[*] 已完成记录 {len(done)} 条（{MANIFEST.name}），将跳过重复组合")

    # ---- 生成每个组合的实际输入
    def build(template: dict, job: dict, idx: int):
        api = copy.deepcopy(template)
        pose_rel, model_rel = job["pose"], job["model"]
        pose_label, model_label = Path(pose_rel).stem, Path(model_rel).stem
        seed = resolve_seed(cfg, idx)

        api[node_ids["main_image"]]["inputs"][input_keys["main_image"]] = pose_rel
        api[node_ids["ref_image"]]["inputs"][input_keys["ref_image"]] = model_rel
        api[node_ids["prompt"]]["inputs"][input_keys["prompt"]] = cfg["prompt"]
        api[node_ids["seed"]]["inputs"][input_keys["seed"]] = seed
        api[node_ids["save"]]["inputs"][input_keys["save"]] = str(cfg["filename_prefix"]).format(
            pose=pose_label, model=model_label, i=idx, seed=seed)

        for nid, patch in (cfg.get("overrides") or {}).items():
            api[str(nid)]["inputs"].update(patch)
        return api, pose_label, model_label, seed

    if args.check:
        # 队列忙时，新任务只会排到队尾，不会立刻执行 -> 提交后马上撤回 = 免费的全链路校验。
        queue = http_json(base_url + "/queue", timeout=30)
        n_run = len(queue.get("queue_running") or [])
        n_pending = len(queue.get("queue_pending") or [])
        if n_run + n_pending == 0:
            log("[*] 当前 ComfyUI 队列空闲：提交后会被立刻执行，做不到「只校验不出图」。")
            log("[*] 队列空闲时请直接跑一个组合（既校验又拿到图）： python batch_refswap.py --limit 1")
            return 0
        api, pl, ml, seed = build(api_template, jobs[0], 0)
        log(f"[*] 队列忙（运行 {n_run} / 排队 {n_pending}），借这段间隙提交整张图校验，随后立刻撤回：")
        log(f"    组合 {pl} × {ml}，seed={seed}，主图 {jobs[0]['pose']}，参考图 {jobs[0]['model']}")
        try:
            pid = submit(api, base_url, "refswap_check")
        except Exception as e:
            die(f"[!] 校验失败：{e}")
        try:
            http_json(base_url + "/queue", {"delete": [pid]}, timeout=30)
        except Exception as e:
            log(f"    ! 撤回失败，请去界面队列里手动删掉任务 {pid}：{e}")
        log(f"[*] 服务器接受了整张图（节点类型 / 必填输入 / LoadImage 文件存在性 全部通过），已撤回 {pid}，未消耗显存。")
        return 0

    if args.dry_run:
        log("[*] 计划（--dry-run，不入队）：")
        for i, job in enumerate(jobs):
            api, pl, ml, seed = build(api_template, job, i)
            skip = "（已完成，跳过）" if f"{job['pose']}|{job['model']}" in done else ""
            log(f"    [{i + 1:>2}] {pl:<12} × {ml:<12} seed={seed} -> "
                f"{api[node_ids['save']]['inputs'][input_keys['save']]}_{{序号}}.png {skip}")
        api, pl, ml, seed = build(api_template, jobs[0], 0)
        log("[*] 第 1 个组合实际写进 API 的值（自查用）：")
        log(f"    主图节点 {node_ids['main_image']}  = {api[node_ids['main_image']]['inputs'][input_keys['main_image']]}")
        log(f"    参考图节点 {node_ids['ref_image']} = {api[node_ids['ref_image']]['inputs'][input_keys['ref_image']]}")
        log(f"    提示词节点 {node_ids['prompt']}  = {api[node_ids['prompt']]['inputs'][input_keys['prompt']][:40]}...")
        log(f"    种子节点 {node_ids['seed']}    = {seed}")
        log("[*] 静态校验（必填输入/引用/输入名）已通过。"
            "端到端确认请先跑一个组合： python batch_refswap.py --limit 1")
        return 0

    # ---- 正式执行
    total = len(jobs)
    ok_n = skip_n = fail_n = 0
    client_id = f"refswap_{int(time.time())}"
    log(f"[*] 开始提交，共 {total} 个组合（Ctrl+C 可中断，已完成部分已写入 {MANIFEST.name}）")
    try:
        for i, job in enumerate(jobs):
            key = f"{job['pose']}|{job['model']}"
            api, pl, ml, seed = build(api_template, job, i)
            prefix = api[node_ids["save"]]["inputs"][input_keys["save"]]
            if key in done:
                skip_n += 1
                log(f"[{i + 1}/{total}] 跳过 {pl} × {ml}（已完成）")
                continue
            t0 = time.time()
            try:
                pid = submit(api, base_url, client_id)
                entry = wait_done(pid, base_url, int(cfg.get("max_wait_seconds", 1800)))
                files = extract_outputs(entry)
                ok = bool(files)
                append_manifest({"pose": pl, "model": ml, "pose_file": job["pose"], "model_file": job["model"],
                                 "prompt_id": pid, "seed": seed, "prefix": prefix, "files": files,
                                 "ok": ok, "time": datetime.now().isoformat(timespec="seconds")})
                if ok:
                    ok_n += 1
                    log(f"[{i + 1}/{total}] OK  {pl} × {ml}  {time.time() - t0:.0f}s -> "
                        + ", ".join(f"output/{f}" for f in files))
                else:
                    fail_n += 1
                    log(f"[{i + 1}/{total}] 无输出 {pl} × {ml}")
            except KeyboardInterrupt:
                raise
            except Exception as e:
                fail_n += 1
                append_manifest({"pose": pl, "model": ml, "pose_file": job["pose"], "model_file": job["model"],
                                 "seed": seed, "prefix": prefix, "ok": False, "error": str(e),
                                 "time": datetime.now().isoformat(timespec="seconds")})
                log(f"[{i + 1}/{total}] 失败 {pl} × {ml}：{e}")
    except KeyboardInterrupt:
        log("\n[!] 用户中断。已完成的组合都已记入 " + MANIFEST.name + "，重跑会自动跳过。")

    log(f"[*] 结束：成功 {ok_n}，跳过 {skip_n}，失败 {fail_n}，记录在 {MANIFEST}")
    return 0 if fail_n == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
