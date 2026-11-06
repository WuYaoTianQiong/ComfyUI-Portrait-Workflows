"""原子碎片库跨源真出图（试点）：从 pilot_results 选组合，提交到临时后端并生成接触表。

用法（先起临时后端，默认 8657）：
    python tools/atomic_pilot/run_real.py --indexes 1,8,19 --tag v2
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
BANK = HERE / "fragments.json"
PILOT = HERE / "pilot_results.json"


def get(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=30) as r:
        return json.loads(r.read())


def post(base: str, path: str, payload: dict):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.status, json.loads(r.read())


def main() -> int:
    parser = argparse.ArgumentParser(description="原子库跨源真出图试点")
    parser.add_argument("--base", default="http://127.0.0.1:8657")
    parser.add_argument("--indexes", required=True, help="pilot_results 的 index，逗号分隔")
    parser.add_argument("--tag", default="v2")
    parser.add_argument("--output-subfolder", default="_tmp_p3/atomic_pilot_v2")
    parser.add_argument("--with-supplement", action="store_true", help="同时发送原子姿势文本作为补充")
    args = parser.parse_args()
    indexes = [int(x) for x in args.indexes.split(",") if x.strip()]

    bank = {x["id"]: x for x in json.loads(BANK.read_text(encoding="utf-8"))["fragments"]}
    pilot = {r["index"]: r for r in json.loads(PILOT.read_text(encoding="utf-8"))["results"]}

    jobs = []
    for order, index in enumerate(indexes):
        result = pilot[index]
        combo = {key: bank[value] for key, value in result["combo"].items()}
        body = {
            "portrait_text": f"{combo['face']['content']}；{combo['body']['content']}",
            "costume_text": combo["outfit"]["content"],
            "pose_id": result["pose_image"],
            "style": "realistic",
            "seed": 20261107 + order,
            "seed_mode": "fixed",
            "output_subfolder": args.output_subfolder,
            "modifier_fragments": "\n".join(
                f"• {label}：{combo[key]['content']}"
                for label, key in (("拍摄视角", "view"), ("场景环境", "scene"), ("光影色调", "light"), ("画风技术", "style"))
            ),
            "dry_run": False,
        }
        if args.with_supplement:
            body["pose_text"] = combo["pose"]["content"]
            body["pose_supplement"] = True
        status, payload = post(args.base, "/api/reference/recipes", body)
        job_id = payload.get("job_id")
        jobs.append({
            "order": order + 1, "pilot_index": index, "status": status, "job_id": job_id,
            "combo": result["combo"], "pose_image": result["pose_image"],
            "name": f"{combo['scene']['id']} · {combo['outfit']['id']} · {combo['pose']['id']}",
            "body": body, "error": "" if job_id else str(payload)[:300],
        })
        print(f"submit {order+1}/{len(indexes)} index={index} status={status} job={job_id}", flush=True)

    pending = {int(j["job_id"]): j for j in jobs if j.get("job_id")}
    final = {}
    deadline = time.time() + 1200
    while pending and time.time() < deadline:
        for job_id in list(pending):
            try:
                job = get(args.base, f"/api/jobs/{job_id}")
            except Exception as exc:
                print("poll error", job_id, repr(exc), flush=True); continue
            status = job.get("status")
            print(f"job {job_id} {status} {job.get('done_count')}/{job.get('total')}", flush=True)
            if status in {"done", "error", "failed"}:
                images = [
                    {
                        "filename": img.get("filename", ""),
                        "subfolder": img.get("subfolder", ""),
                        "abs_path": str(Path("F:/ComfyUI_Migration/output") / (img.get("subfolder") or "") / (img.get("filename") or "")),
                    }
                    for item in (job.get("items") or [])
                    for img in (item.get("images") or [])
                ]
                final[job_id] = {"status": status, "error": job.get("error") or "", "images": images}
                pending.pop(job_id, None)
        if pending:
            time.sleep(5)

    report = []
    for entry in jobs:
        job_id = int(entry["job_id"]) if entry.get("job_id") else None
        data = final.get(job_id) or {"status": "timeout", "error": "poll timeout", "images": []}
        report.append({**entry, **data})
    result_path = HERE / f"atomic_results_{args.tag}.json"
    result_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    images = [j for j in report if j.get("images")]
    if images:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 18)
        cell_w, cell_h, label_h = 400, 530, 48
        cols = 2
        rows = (len(images) + cols - 1) // cols
        canvas = Image.new("RGB", (cols * cell_w, rows * (cell_h + label_h)), (18, 18, 22))
        draw = ImageDraw.Draw(canvas)
        for i, job in enumerate(images):
            p = Path(job["images"][0]["abs_path"])
            img = Image.open(p).convert("RGB"); orig = img.size; img.thumbnail((cell_w, cell_h))
            x = (i % cols) * cell_w + (cell_w - img.width) // 2
            y = (i // cols) * (cell_h + label_h)
            canvas.paste(img, (x, y + label_h))
            draw.text((x + 4, y + 5), f"{job['pilot_index']} · {job['name']}"[:36], fill=(235,235,240), font=font)
            draw.text((x + 4, y + 27), f"{orig[0]}×{orig[1]} · {job['status']}", fill=(160,160,175), font=font)
        contact = HERE / f"atomic_pilot_contact_{args.tag}.png"
        canvas.save(contact)
        print("contact", contact, canvas.size, flush=True)
    print(json.dumps([{k: j[k] for k in ("pilot_index","status","job_id","error","images")} for j in report], ensure_ascii=False, indent=2), flush=True)
    return 0 if all(j["status"] == "done" for j in report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
