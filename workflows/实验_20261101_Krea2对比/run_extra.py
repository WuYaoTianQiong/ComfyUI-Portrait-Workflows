"""2026-11-01 追加：Qwen2.1 turbo LoRA / Z-Image + NSFW LoRA / Flux.2 Klein 9B Q4 中文实测。"""
import copy
import json
import sys
import time
from pathlib import Path

import httpx
from PIL import Image

HERE = Path(__file__).resolve().parent
WORKFLOWS = HERE.parent
ATELIER = WORKFLOWS / "脚本" / "atelier"
sys.path.insert(0, str(ATELIER))

from app.services.fragment_syntax import strip_headers  # noqa: E402
from app.services.workflow_parser import (  # noqa: E402
    inject_prompt,
    load_workflow,
    set_output_prefix,
)

API = "http://127.0.0.1:8188"
OUTPUT_ROOT = Path(r"F:\ComfyUI_Migration\output")
SEED = 123456789
PREFIX = "exp_20261101"


def submit(api_wf: dict) -> str:
    r = httpx.post(f"{API}/prompt", json={"prompt": api_wf, "client_id": "atelier-exp-extra"}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"/prompt HTTP {r.status_code}: {r.text[:1500]}")
    return r.json()["prompt_id"]


def wait_history(prompt_id: str, timeout: float = 900) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        hist = httpx.get(f"{API}/history/{prompt_id}", timeout=10).json()
        if prompt_id in hist:
            return hist[prompt_id]
        time.sleep(1)
    raise TimeoutError(prompt_id)


def collect(hist: dict) -> list[Path]:
    out = []
    for node_out in (hist.get("outputs") or {}).values():
        for img in node_out.get("images", []) or []:
            p = OUTPUT_ROOT / (img.get("subfolder") or "") / img.get("filename", "")
            if p.is_file():
                out.append(p)
    return out


def run_ui(label: str, wf: dict, prompt: str) -> dict:
    api_wf = load_workflow_from_dict(wf)
    inject_prompt(api_wf, {
        "prompt": prompt,
        "negative_prompt": "",
        "seed": SEED,
        "orientation": "portrait",
        "quality": "4K",
    })
    set_output_prefix(api_wf, f"{PREFIX}/{label}")
    return run_api(label, api_wf)


def load_workflow_from_dict(wf: dict) -> dict:
    tmp = HERE / "_tmp_wf.json"
    tmp.write_text(json.dumps(wf, ensure_ascii=False), encoding="utf-8")
    try:
        return load_workflow(str(tmp))
    finally:
        tmp.unlink(missing_ok=True)


def run_api(label: str, api_wf: dict) -> dict:
    t0 = time.time()
    row = {"label": label, "images": [], "error": ""}
    try:
        pid = submit(api_wf)
        hist = wait_history(pid)
        row["elapsed_s"] = round(time.time() - t0, 2)
        row["status"] = (hist.get("status") or {}).get("status_str", "")
        for p in collect(hist):
            with Image.open(p) as im:
                w, h = im.size
            row["images"].append({"path": str(p), "width": w, "height": h, "bytes": p.stat().st_size})
    except Exception as exc:
        row["elapsed_s"] = round(time.time() - t0, 2)
        row["status"] = "error"
        row["error"] = str(exc)[:1500]
    return row


def qwen_turbo(wf: dict) -> dict:
    wf = copy.deepcopy(wf)
    # 在 NSFW LoRA 之后再串一个 turbo LoRA
    wf["nodes"].append({
        "id": 11, "type": "LoraLoaderModelOnly", "pos": [0, 0], "size": [300, 100],
        "flags": {}, "order": 11, "mode": 0,
        "inputs": [{"name": "model", "type": "MODEL", "link": 11}],
        "outputs": [{"name": "MODEL", "type": "MODEL", "links": [2], "slot_index": 0}],
        "widgets_values": ["qwen21\\qwen_image_2.1_turbo_lora_avg_rank_178_bf16.safetensors", 1.0],
    })
    # 复用 link 2（4->7）为 11->7，新增 link 11（4->11）
    for link in wf["links"]:
        if link[0] == 2:
            link[1], link[2] = 11, 0
    wf["links"].append([11, 4, 0, 11, 0, "MODEL"])
    for n in wf["nodes"]:
        if n["id"] == 4:
            n["outputs"][0]["links"] = [11]
        if n["id"] == 7:
            n["widgets_values"][2] = 8  # steps
            n["widgets_values"][3] = 1.0
    return wf


def zimage_neinei(wf: dict) -> dict:
    wf = copy.deepcopy(wf)
    wf["nodes"].append({
        "id": 11, "type": "NunchakuZImageTurboLoraStackV4", "pos": [0, 0], "size": [320, 180],
        "flags": {}, "order": 11, "mode": 0,
        "inputs": [
            {"name": "model", "type": "MODEL", "link": 11},
            {"name": "clip", "type": "CLIP", "link": 12},
        ],
        "outputs": [
            {"name": "MODEL", "type": "MODEL", "links": [1], "slot_index": 0},
            {"name": "CLIP", "type": "CLIP", "links": [7, 8], "slot_index": 1},
        ],
        "widgets_values": [1, True, True, "neinei_zimage_lora_v1.safetensors", 0.8],
    })
    for link in wf["links"]:
        if link[0] == 1:      # loader -> KSampler model
            link[1], link[2] = 11, 0
        elif link[0] in (7, 8):  # CLIP -> text encoders
            link[1], link[2] = 11, 1
    wf["links"] += [
        [11, 1, 0, 11, 0, "MODEL"],
        [12, 2, 0, 11, 1, "CLIP"],
    ]
    for n in wf["nodes"]:
        if n["id"] == 1:
            n["outputs"][0]["links"] = [11]
        if n["id"] == 2:
            n["outputs"][0]["links"] = [12]
    return wf


def flux2_api(prompt: str) -> dict:
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "flux-2-klein-9b-Q4_K_M.gguf"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "flux2\\qwen_3_8b_fp8mixed.safetensors", "type": "flux2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2\\flux2-vae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": 832, "height": 1216, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
            "latent_image": ["6", 0], "seed": SEED, "steps": 4, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {
            "images": ["8", 0], "filename_prefix": f"{PREFIX}/Flux2Klein9B_Chinese_832"}},
    }


def main():
    prompt = strip_headers((HERE / "prompt_original.txt").read_text(encoding="utf-8"))
    results = []

    qwen = json.loads((WORKFLOWS / "历史工作流" / "Qwen21_NSFW_文生图_25步_int8_12G.json").read_text(encoding="utf-8"))
    results.append(run_ui("Qwen21_turboNSFW_8step_832", qwen_turbo(qwen), prompt))

    zi = json.loads((WORKFLOWS / "历史工作流" / "ZImage_nunchaku_草稿线_9步_竖构图832x1216.json").read_text(encoding="utf-8"))
    results.append(run_ui("ZImageTurbo_neineiLoRA_832", zimage_neinei(zi), prompt))

    results.append(run_api("Flux2Klein9B_Chinese_832", flux2_api(prompt)))

    out = HERE / "extra_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in results:
        print(r["label"], r["status"], r.get("elapsed_s"), [i["path"] for i in r["images"]], r["error"][:200])


if __name__ == "__main__":
    main()
