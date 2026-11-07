"""服装库感知哈希去重扫描（只读，不删文件）。

对比「角色创作库本地包」与「上游 1,407 件」以及包内自身：
- sha1 完全相同 = 重复文件；
- pHash 汉明距离 ≤ --threshold 且主色差 ≤ --color  = 视觉近似。

单用 dHash 在白底人台全身图上误报极高（不同套装轮廓几乎一致），
因此改为 pHash（32×32 DCT 低频）+ 平均 RGB 距离双阈值。

用法：
    python tools/check_costume_dupes.py --report _tmp_costume_dupes.json
    python tools/check_costume_dupes.py --threshold 6 --color 12
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from app.services import reference_library  # noqa: E402

#: 32×32 DCT-II 变换矩阵，进程内只算一次。
_DCT = np.cos(
    np.pi * (2 * np.arange(32)[None, :] + 1) * np.arange(32)[:, None] / 64
) * np.sqrt(2 / 32)
_DCT[0, :] *= np.sqrt(1 / 2)


def phash(path: Path) -> tuple[int, tuple[float, float, float]] | None:
    try:
        with Image.open(path) as im:
            rgb = im.convert("RGB")
            pixels = np.asarray(
                rgb.resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float64,
            )
    except (OSError, ValueError):
        return None
    mean_rgb = pixels.reshape(-1, 3).mean(axis=0)
    gray = pixels @ np.array([0.299, 0.587, 0.114])
    coeffs = _DCT @ gray @ _DCT.T
    low = coeffs[:8, :8].flatten()
    median = np.median(low[1:])
    bits = 0
    for value in low:
        bits = (bits << 1) | (1 if value > median else 0)
    return bits, tuple(float(v) for v in mean_rgb)


def sha1_of(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect() -> tuple[list[dict], dict[str, int]]:
    records = reference_library._visible_items("costume")
    out = []
    missing: dict[str, int] = {}
    for record in records:
        rel = record.get("_image_rel") or ""
        root = record.get("_root")
        source = record.get("source", "")
        if not rel or root is None:
            missing[source] = missing.get(source, 0) + 1
            continue
        try:
            path = reference_library._safe_image_path(rel, root)
        except Exception:  # noqa: BLE001 - 缺图条目跳过，不阻断扫描
            missing[source] = missing.get(source, 0) + 1
            continue
        out.append({
            "id": record["id"],
            "source": source,
            "group": record.get("group", ""),
            "path": str(path),
        })
    return out, missing


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=int, default=6, help="pHash 汉明距离上限")
    parser.add_argument("--color", type=float, default=12.0, help="平均 RGB 欧氏距离上限")
    parser.add_argument("--limit", type=int, default=80, help="最多输出多少对近似重复")
    parser.add_argument("--report", default=str(ROOT / "_tmp_costume_dupes.json"))
    args = parser.parse_args()

    items, missing = collect()
    print(f"[dupes] 扫描 {len(items)} 件；缺图/无图字段 {missing}", flush=True)

    hashes: list[dict] = []
    for i, item in enumerate(items, 1):
        path = Path(item["path"])
        item["sha1"] = sha1_of(path)
        signature = phash(path)
        if signature is not None:
            item["phash"], item["mean_rgb"] = signature
        hashes.append(item)
        if i % 200 == 0:
            print(f"[dupes] {i}/{len(items)}", flush=True)

    exact: dict[str, list[dict]] = {}
    for item in hashes:
        exact.setdefault(item["sha1"], []).append(item)
    exact_pairs = [group for group in exact.values() if len(group) > 1]

    near = []
    usable = [item for item in hashes if "phash" in item]
    for i in range(len(usable)):
        a = usable[i]
        for j in range(i + 1, len(usable)):
            b = usable[j]
            distance = bin(a["phash"] ^ b["phash"]).count("1")
            if distance > args.threshold:
                continue
            color = sum(
                (a["mean_rgb"][k] - b["mean_rgb"][k]) ** 2 for k in range(3)
            ) ** 0.5
            if color > args.color:
                continue
            near.append({
                "distance": distance,
                "color": round(color, 1),
                "a": {"id": a["id"], "source": a["source"]},
                "b": {"id": b["id"], "source": b["source"]},
            })
    near.sort(key=lambda pair: (pair["distance"], pair["color"]))

    report = {
        "scanned": len(items),
        "missing_images": missing,
        "by_source": {
            key: sum(1 for item in items if item["source"] == key)
            for key in {item["source"] for item in items}
        },
        "exact_duplicate_groups": [
            [{"id": item["id"], "source": item["source"]} for item in group]
            for group in exact_pairs
        ],
        "near_duplicate_pairs": near[: args.limit],
        "near_duplicate_total": len(near),
        "threshold": args.threshold,
        "color_threshold": args.color,
    }
    Path(args.report).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    print(f"[dupes] 完全相同文件组：{len(exact_pairs)}")
    for group in exact_pairs[:10]:
        print("  exact:", ", ".join(item["id"] for item in group))
    print(f"[dupes] dHash≤{args.threshold} 近似对：{len(near)}（已输出前 {min(len(near), args.limit)}）")
    for pair in near[:10]:
        print(f"  d={pair['distance']} {pair['a']['id']} ↔ {pair['b']['id']}")
    print("[dupes] 报告：", args.report)


if __name__ == "__main__":
    main()
