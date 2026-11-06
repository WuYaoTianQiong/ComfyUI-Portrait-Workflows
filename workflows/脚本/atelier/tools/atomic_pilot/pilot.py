"""P4 原子碎片库小规模试点：跨源组合 + dry-run 验收。

- 只读 JSON 种子 `fragments.json`，不写数据库、不接 UI。
- 兼容规则：场景 group / 服装 style / 光线 temp / 姿势 facet / 取景 framing。
- 通过 8656 的 `/api/reference/recipes` dry-run 验证提示词结构。
- 姿势图仍作唯一图片锚点；姿势文本按奇数组合作为「补充」发送，验证 8 类全生效。
"""

from __future__ import annotations

import argparse
import json
import random
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

BASE = "http://127.0.0.1:8656"
HERE = Path(__file__).parent
BANK = HERE / "fragments.json"
OUT = HERE / "pilot_results.json"
TYPES = ["人物面部", "人物身材", "人物服饰", "姿态动作", "拍摄视角", "场景环境", "光影色调", "画风技术"]
POSE_FACET = {"stand": "站姿", "walk": "站姿", "sit": "坐姿", "lean": "前倾", "kneel": "跪立"}
EXPLICIT = ("赤裸", "裸体", "乳房", "乳头", "下体", "阴部", "性交", "做爱", "情趣")


def get_json(path: str):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read())


def post_json(path: str, payload: dict):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", "replace"))


def load_bank():
    data = json.loads(BANK.read_text(encoding="utf-8"))
    by_type: dict[str, list[dict]] = defaultdict(list)
    by_id: dict[str, dict] = {}
    for item in data["fragments"]:
        by_type[item["type"]].append(item)
        by_id[item["id"]] = item
    errors = []
    for ftype in TYPES:
        if len(by_type[ftype]) < 20:
            errors.append(f"{ftype} 只有 {len(by_type[ftype])} 条（第二批要求 20）")
    for item in data["fragments"]:
        content = item.get("content", "")
        if "【" in content or "\\n" in content:
            errors.append(f"{item['id']} 含残留标题/字面量换行")
        if any(term in content for term in EXPLICIT):
            errors.append(f"{item['id']} 含明确裸露词")
        if item["type"] == "人物服饰" and item.get("meta", {}).get("coverage") != "full":
            errors.append(f"{item['id']} 服装未标 full coverage")
    return by_type, by_id, errors


def pose_choices(facet: str):
    q = f"/api/reference/items?library=pose&facet={urllib.parse.quote(POSE_FACET[facet])}&nsfw=false&page_size=30"
    items = get_json(q).get("items") or []
    items = [x for x in items if not str(x["id"]).startswith("pair")]
    front = [x for x in items if str(x["id"]).endswith("_front")]
    return front or items


def pick(pool, predicate):
    candidates = [x for x in pool if predicate(x)]
    return random.choice(candidates) if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser(description="原子碎片库跨源 dry-run 试点")
    parser.add_argument("--count", type=int, default=10, help="采样组合数，默认 10")
    parser.add_argument("--seed", type=int, default=20261107, help="随机种子")
    args = parser.parse_args()
    target = max(1, args.count)

    by_type, by_id, errors = load_bank()
    if errors:
        print("BANK ERRORS:")
        for e in errors:
            print(" ", e)
        return 1

    random.seed(args.seed)
    scenes = by_type["场景环境"]
    lights = by_type["光影色调"]
    outfits = by_type["人物服饰"]
    styles = by_type["画风技术"]
    poses = by_type["姿态动作"]
    views = by_type["拍摄视角"]
    faces = by_type["人物面部"]
    bodies = by_type["人物身材"]

    combos = []
    seen = set()
    attempts = 0
    while len(combos) < target and attempts < target * 30:
        attempts += 1
        scene = random.choice(scenes)
        light = pick(lights, lambda x: scene["meta"]["group"] in x["meta"]["scene_fit"] and x["meta"]["temp"] in scene["meta"]["light_fit"])
        outfit = pick(outfits, lambda x: scene["meta"]["group"] in x["meta"]["scene_fit"] and set(x["meta"]["style"]) & set(scene["meta"]["style_fit"]))
        style = pick(styles, lambda x: scene["meta"]["group"] in x["meta"]["scene_fit"] and set(x["meta"]["style_fit"]) & set(outfit["meta"]["style"]) if outfit else False)
        pose = random.choice(poses)
        view = pick(views, lambda x: pose["meta"]["facet"] in x["meta"]["pose_fit"] and x["meta"]["framing"] in pose["meta"]["view_fit"])
        face = random.choice(faces)
        body = random.choice(bodies)
        if not all((light, outfit, style, pose, view)):
            continue
        key = (scene["id"], light["id"], outfit["id"], style["id"], pose["id"], view["id"], face["id"], body["id"])
        if key in seen:
            continue
        seen.add(key)
        combos.append({
            "face": face, "body": body, "outfit": outfit, "pose": pose,
            "view": view, "scene": scene, "light": light, "style": style,
        })

    if len(combos) < target:
        print(f"只生成 {len(combos)} 套兼容组合，检查 bank 的 meta")
        return 1

    results = []
    for index, combo in enumerate(combos):
        facet = combo["pose"]["meta"]["facet"]
        poses_pool = pose_choices(facet)
        if not poses_pool:
            print("no pose for facet", facet); return 1
        pose_image = random.choice(poses_pool)
        supplement = index % 2 == 1
        body = {
            "portrait_text": f"{combo['face']['content']}；{combo['body']['content']}",
            "costume_text": combo["outfit"]["content"],
            "pose_id": pose_image["id"],
            "style": "realistic",
            "seed": 20261107 + index,
            "seed_mode": "fixed",
            "modifier_fragments": "\n".join(
                f"• {label}：{combo[key]['content']}"
                for label, key in (("拍摄视角", "view"), ("场景环境", "scene"), ("光影色调", "light"), ("画风技术", "style"))
            ),
            "dry_run": True,
        }
        if supplement:
            body["pose_text"] = combo["pose"]["content"]
            body["pose_supplement"] = True
        status, response = post_json("/api/reference/recipes", body)
        prompt = response.get("prompt_raw") or "" if isinstance(response, dict) else ""
        checks = {
            "status_200": status == 200,
            "no_header": "【" not in prompt,
            "no_literal_newline": "\\n" not in prompt,
            "no_missing_figure_refs": "图2" not in prompt and "图3" not in prompt,
            "body_costume": isinstance(response, dict) and response.get("body_mode") == "costume" and response.get("body_mode_auto") is False,
            "no_bare": "素体展示" not in prompt and "不穿任何服装" not in prompt,
            "scene_present": combo["scene"]["content"].rstrip("。") in prompt,
            "outfit_present": combo["outfit"]["content"].rstrip("。") in prompt,
            "view_present": combo["view"]["content"].rstrip("。") in prompt,
            "light_present": combo["light"]["content"].rstrip("。") in prompt,
            "style_present": combo["style"]["content"].rstrip("。") in prompt,
            "supplement_matches": isinstance(response, dict) and bool(response.get("supplements", {}).get("pose")) is supplement,
            "pose_supplement_clause": (combo["pose"]["content"].rstrip("。") in prompt) if supplement else ("此外需体现" not in prompt),
        }
        results.append({
            "index": index + 1,
            "status": status,
            "all_ok": all(checks.values()),
            "checks": checks,
            "prompt_len": len(prompt),
            "supplement": supplement,
            "pose_image": pose_image["id"],
            "pose_facet": facet,
            "combo": {
                "face": combo["face"]["id"], "body": combo["body"]["id"],
                "outfit": combo["outfit"]["id"], "pose": combo["pose"]["id"],
                "view": combo["view"]["id"], "scene": combo["scene"]["id"],
                "light": combo["light"]["id"], "style": combo["style"]["id"],
            },
        })
        print(
            f"{index+1:02d} {combo['scene']['id']:18s} {combo['outfit']['id']:22s} "
            f"{facet:5s} {combo['view']['id']:18s} supp={int(supplement)} "
            f"len={len(prompt):4d} ok={results[-1]['all_ok']}"
        )

    report = {
        "combo_count": len(results),
        "all_ok": sum(1 for r in results if r["all_ok"]),
        "results": results,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False))
    print("saved", OUT)
    return 0 if report["all_ok"] == report["combo_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
