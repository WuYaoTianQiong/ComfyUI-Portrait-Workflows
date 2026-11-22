# -*- coding: utf-8 -*-
"""同种子双底模对照：按提示词库里的某条提示词，用同一个工作流分别跑多个底模。

用途：换底模后想快速看「同一提示词 / 同一种子」下的差异（构图、细节、耗时、显存）。
做法：读 UI 格式工作流 → 转 API 格式（复用 Atelier 的 workflow_parser）→ 逐个底模提交
      /prompt → 轮询 /history → 记录墙钟耗时与采样期间的峰值显存。

用法：
  python ab_双底模对照.py --prompt-id 1043 --tag V25vsV4
  python ab_双底模对照.py --prompt-id 1043 --models "krea2\\a.safetensors,krea2\\b.safetensors"
  python ab_双底模对照.py --prompt-id 1043 --workflow "通用工作流/xxx.json" --seed 42

注意：
  - 只改 UNETLoader 的 unet_name、CLIPTextEncode 的 text、EmptyLatentImage 的尺寸来源、
    KSampler 的种子，其余（采样器/步数/CFG/VAE/输出前缀模板）保持工作流原样。
  - 默认跳过 PlaySound / 预览类节点，避免无人值守时的噪音与偶发报错。
"""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ATELIER = os.path.join(HERE, "atelier")
sys.path.insert(0, ATELIER)

from app.services.workflow_parser import ensure_api_format  # noqa: E402

DB = os.path.join(ATELIER, "data", "prompts.db")
DEFAULT_WORKFLOW = os.path.join(HERE, "..", "通用工作流", "PornMaster_Krea2V4_T2I_INT8_1Pass.json")
SKIP_TYPES = {"PlaySound|pysssss", "PreviewImage"}
# 常见分辨率对应的像素量（MP），用于反推 ResolutionSelector.megapixels
ASPECTS = {
    (2, 3): "2:3 (Portrait Photo)",
    (3, 2): "3:2 (Landscape Photo)",
    (9, 16): "9:16 (Portrait Widescreen)",
    (16, 9): "16:9 (Widescreen)",
    (3, 4): "3:4 (Portrait Standard)",
    (4, 3): "4:3 (Standard)",
    (1, 1): "1:1 (Square)",
    (9, 21): "9:21 (Ultra Tall)",
}


def load_prompt(pid):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM prompts WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not row:
        sys.exit("[错误] 提示词库没有 id=%s" % pid)
    return dict(row)


def build_api(workflow_path, model, text, seed, width, height, prefix):
    with open(workflow_path, encoding="utf-8") as f:
        wf = json.load(f)
    api = ensure_api_format(wf)
    api = {k: v for k, v in api.items() if v["class_type"] not in SKIP_TYPES}

    hit = {"unet": 0, "clip": 0, "latent": 0, "seed": 0, "save": 0}
    for nid, node in api.items():
        t = node["class_type"]
        ins = node["inputs"]
        if t == "UNETLoader":
            ins["unet_name"] = model
            hit["unet"] += 1
        elif t == "CLIPTextEncode" and "text" in ins and ins.get("text") == "":
            ins["text"] = text
            hit["clip"] += 1
        elif t == "ResolutionSelector" and width and height:
            g = _gcd(width, height)
            key = (width // g, height // g)
            if key in ASPECTS:
                ins["aspect_ratio"] = ASPECTS[key]
            ins["megapixels"] = round(width * height / 1e6, 3)
            hit["latent"] += 1
        elif t == "KSamplerAdvanced" and "noise_seed" in ins:
            ins["noise_seed"] = seed
            hit["seed"] += 1
        elif t == "SaveImage":
            ins["filename_prefix"] = prefix
            hit["save"] += 1

    if not hit["unet"]:
        sys.exit("[错误] 工作流里没有 UNETLoader，无法替换底模")
    if not hit["clip"]:
        print("[提示] 没有找到空白的正向提示词节点，沿用工作流自带提示词")
    return api


def _gcd(a, b):
    while b:
        a, b = b, a % b
    return a


def post_prompt(api, server):
    body = json.dumps({"prompt": api, "client_id": "ab-compare"}).encode("utf-8")
    req = urllib.request.Request(server + "/prompt", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:1200]
        sys.exit("[错误] 提交失败 HTTP %s：%s" % (e.code, detail))


def wait_done(pid, server, timeout=1800):
    t0 = time.time()
    peak = 0.0
    while time.time() - t0 < timeout:
        time.sleep(0.6)
        try:
            st = json.load(urllib.request.urlopen(server + "/system_stats", timeout=10))
            d = st["devices"][0]
            used = (d["vram_total"] - d["vram_free"]) / 1024 ** 3
            peak = max(peak, used)
        except Exception:
            pass
        try:
            hist = json.load(urllib.request.urlopen(server + "/history/" + pid, timeout=10))
        except Exception:
            continue
        if pid in hist:
            return time.time() - t0, peak, hist[pid]
    return None, peak, None


def main():
    ap = argparse.ArgumentParser(description="同种子双底模对照")
    ap.add_argument("--prompt-id", type=int, required=True, help="提示词库 id")
    ap.add_argument("--models", default="krea2\\pornmasterKrea2_v25Turbo_fp8.safetensors,"
                                       "krea2\\Pornmaster_krea2_Turbo_int8_convrot_v4.safetensors",
                    help="逗号分隔的底模文件名（相对 models/diffusion_models）")
    ap.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    ap.add_argument("--seed", type=int, default=0, help="不传则沿用工作流种子")
    ap.add_argument("--width", type=int, default=0, help="覆盖出图宽（提示词库没存宽高时用）")
    ap.add_argument("--height", type=int, default=0, help="覆盖出图高")
    ap.add_argument("--tag", default="AB")
    ap.add_argument("--server", default="http://127.0.0.1:8188")
    ap.add_argument("--keep-size", action="store_true", help="不套用提示词库里的宽高")
    args = ap.parse_args()

    p = load_prompt(args.prompt_id)
    if args.keep_size:
        width = height = None
    else:
        width = args.width or p["width"]
        height = args.height or p["height"]
    seed = args.seed or (p["seed"] or 0) or 123456789
    print("提示词 : #%s %s" % (p["id"], p["name"] or "(未命名)"))
    print("尺寸   : %s" % ("沿用工作流" if not width else "%sx%s" % (width, height)))
    print("种子   : %s" % seed)
    print("工作流 : %s" % os.path.basename(args.workflow))
    print("")

    results = []
    for m in [x.strip() for x in args.models.split(",") if x.strip()]:
        short = os.path.basename(m).replace(".safetensors", "")
        prefix = "%s_%s" % (args.tag, short[:24])
        api = build_api(args.workflow, m, p["prompt"], seed, width, height, prefix)
        print("[%s] 提交…" % short)
        r = post_prompt(api, args.server)
        pid = r.get("prompt_id")
        if not pid:
            sys.exit("[错误] 未拿到 prompt_id：%s" % r)
        dur, peak, hist = wait_done(pid, args.server)
        if hist is None:
            print("[%s] 超时未完成" % short)
            continue
        status = hist.get("status", {})
        if status.get("status_str") != "success":
            print("[%s] 执行失败：%s" % (short, str(status)[:400]))
            continue
        imgs = []
        for out in hist.get("outputs", {}).values():
            imgs += out.get("images", [])
        print("[%s] 完成 %.1f s | 峰值显存 %.2f GB | 输出 %s"
              % (short, dur, peak, ", ".join(i["filename"] for i in imgs) or "-"))
        results.append({"model": short, "seconds": round(dur, 1),
                        "peak_vram_gb": round(peak, 2), "images": imgs})

    print("\n=== 汇总 ===")
    for r in results:
        print("%-28s %6.1f s  %5.2f GB  %s"
              % (r["model"][:28], r["seconds"], r["peak_vram_gb"],
                 r["images"][0]["filename"] if r["images"] else "-"))
    out = os.path.join(HERE, "..", ".tmp", "ab_%s.json" % args.tag)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"prompt_id": p["id"], "seed": seed,
                   "width": width, "height": height, "results": results},
                  f, ensure_ascii=False, indent=2)
    print("\n记录: %s" % os.path.abspath(out))


if __name__ == "__main__":
    main()
