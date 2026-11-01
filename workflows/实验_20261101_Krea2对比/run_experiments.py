"""Krea2 vs ZIT 2026-11-01 实拍对比：直接提交 ComfyUI，固定 seed。

运行：
  cd workflows/脚本/atelier
  python ../../实验_20261101_Krea2对比/run_experiments.py
"""
import json
import sys
import time
from pathlib import Path

import httpx
from PIL import Image

ATELIER = Path(__file__).resolve().parents[1] / "脚本" / "atelier"
sys.path.insert(0, str(ATELIER))

from app.services.fragment_syntax import strip_headers  # noqa: E402
from app.services.workflow_parser import (  # noqa: E402
    inject_prompt,
    load_workflow,
    set_output_prefix,
)

API = "http://127.0.0.1:8188"
ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = Path(r"F:\ComfyUI_Migration\output")
SEED = 123456789
EXP_PREFIX = "exp_20261101"

VARIANTS = [
    ("ZIT_A_orig", "ZIT_基线.json", "prompt_original.txt"),
    ("ZIT_B_merged", "ZIT_基线.json", "prompt_merged.txt"),
    ("V8SE_A_orig_2.16MP_8_cfg1", "A_V8SE_原始单程.json", "prompt_original.txt"),
    ("V8SE_B_1MP_8_cfg1", "B_V8SE_1MP.json", "prompt_original.txt"),
    ("V8SE_C_1MP_12_cfg2", "C_V8SE_1MP_12步_cfg2.json", "prompt_original.txt"),
    ("V8SE_D_2.16MP_12_cfg2", "D_V8SE_2MP_12步_cfg2.json", "prompt_original.txt"),
    ("V8SE_E_C_merged", "C_V8SE_1MP_12步_cfg2.json", "prompt_merged.txt"),
    ("V25_A_int4_2.4MP_8_cfg1", "A_V25_int4_原始单程.json", "prompt_original.txt"),
    ("V25_B_int4_1MP_12_cfg2", "B_V25_int4_1MP_12步_cfg2.json", "prompt_original.txt"),
    ("V25_C_int4_1MP_8_cfg1", "C_V25_int4_1MP_8步_cfg1.json", "prompt_original.txt"),
]


def submit(api_wf: dict) -> str:
    resp = httpx.post(
        f"{API}/prompt",
        json={"prompt": api_wf, "client_id": "atelier-exp-20261101"},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"/prompt HTTP {resp.status_code}: {resp.text[:1200]}")
    return resp.json()["prompt_id"]


def wait_history(prompt_id: str, timeout: float = 600) -> dict:
    started = time.time()
    while time.time() - started < timeout:
        hist = httpx.get(f"{API}/history/{prompt_id}", timeout=10).json()
        if prompt_id in hist:
            return hist[prompt_id]
        time.sleep(1)
    raise TimeoutError(f"等待 ComfyUI 超时: {prompt_id}")


def collect_images(hist: dict) -> list[Path]:
    paths = []
    for node_out in (hist.get("outputs") or {}).values():
        for img in node_out.get("images", []) or []:
            p = OUTPUT_ROOT / (img.get("subfolder") or "") / img.get("filename", "")
            if p.is_file():
                paths.append(p)
    return paths


def main():
    results = []
    for label, wf_name, prompt_name in VARIANTS:
        prompt = strip_headers((ROOT / prompt_name).read_text(encoding="utf-8"))
        api_wf = load_workflow(str(ROOT / wf_name))
        inject_prompt(api_wf, {
            "prompt": prompt,
            "negative_prompt": "",
            "seed": SEED,
            "orientation": "portrait",
            "quality": "4K",
        })
        set_output_prefix(api_wf, f"{EXP_PREFIX}/{label}")

        started = time.time()
        try:
            prompt_id = submit(api_wf)
            hist = wait_history(prompt_id)
            elapsed = time.time() - started
            images = collect_images(hist)
            status = (hist.get("status") or {}).get("status_str", "")
            row = {
                "label": label,
                "workflow": wf_name,
                "prompt": prompt_name,
                "prompt_id": prompt_id,
                "status": status,
                "elapsed_s": round(elapsed, 2),
                "images": [],
                "error": "",
            }
            for p in images:
                try:
                    with Image.open(p) as im:
                        w, h = im.size
                except Exception:
                    w = h = None
                row["images"].append({
                    "path": str(p),
                    "filename": p.name,
                    "width": w,
                    "height": h,
                    "bytes": p.stat().st_size,
                })
            results.append(row)
            print(f"[{label}] {status} {elapsed:.1f}s images={len(images)}", flush=True)
        except Exception as exc:
            results.append({
                "label": label, "workflow": wf_name, "prompt": prompt_name,
                "status": "error", "elapsed_s": round(time.time() - started, 2),
                "images": [], "error": f"{type(exc).__name__}: {exc}",
            })
            print(f"[{label}] ERROR {type(exc).__name__}: {exc}", flush=True)

        (ROOT / "results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
