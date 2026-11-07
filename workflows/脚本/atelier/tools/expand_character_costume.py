"""分批扩「角色创作库」服装本地包。

用途：把 `reference-assets/character-ref-costume-60/` 从当前条数逐步扩到更多，
但**不一次性镜像 783 件**。每次按 group 轮转取 N 件，下载预览、生成缩略图、
追加 meta/manifest/SOURCE，失败时保留旧包。

许可：角色创作库官方自制素材需署名「角色创作库 @62656456」；禁止批量镜像/再分发。
本工具只服务本地个人参考；完整 783 件或对外分发前需向作者取得授权。

用法：
    python tools/expand_character_costume.py --dry-run --count 60
    python tools/expand_character_costume.py --count 60
    python tools/expand_character_costume.py --count 60 --groups 男性现代服装,女性现代服装
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests
from PIL import Image, ImageOps

CATALOG_URL = (
    "https://62656456.github.io/character-reference-library/"
    "%E7%B4%A0%E6%9D%90%E7%9B%AE%E5%BD%95.json"
)
BASE_URL = "https://62656456.github.io/character-reference-library/"
SITE_URL = "https://62656456.github.io/character-reference-library/"
DEFAULT_PACK = Path(r"F:/ComfyUI_Migration/reference-assets/character-ref-costume-60")
DEFAULT_CATALOG = Path(r"F:/ComfyUI_Migration/reference-assets/character-ref-catalog.json")
PRIORITY_GROUPS = [
    "男性现代服装",
    "女性现代服装",
    "现代职业",
    "休闲日常",
    "复古时装",
    "民族盛装",
    "汉服形制",
    "历代风华",
    "机能户外",
    "宫廷衣装",
    "原创古风",
    "职业衣装",
    "现代日常",
    "成年男装",
    "当代女装",
    "当代男装",
    "中性衣装",
]


def load_catalog(path: Path) -> list[dict]:
    if not path.is_file():
        print(f"[expand] 本地目录不存在，下载：{CATALOG_URL}")
        response = requests.get(CATALOG_URL, timeout=60)
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("素材目录顶层不是数组")
    return data


def select_items(
    catalog: list[dict], existing_ids: set[str], count: int, groups: list[str]
) -> list[dict]:
    rows = [
        item
        for item in catalog
        if item.get("category") == "服装设计"
        and item.get("isOfficial")
        and not item.get("adultOnly")
        and str(item.get("id") or "") not in existing_ids
    ]
    buckets: dict[str, list[dict]] = defaultdict(list)
    for item in rows:
        group = str(item.get("group") or "")
        if group in groups:
            buckets[group].append(item)
    picked: list[dict] = []
    while len(picked) < count:
        progressed = False
        for group in groups:
            bucket = buckets.get(group) or []
            if not bucket:
                continue
            picked.append(bucket.pop(0))
            progressed = True
            if len(picked) >= count:
                break
        if not progressed:
            break
    return picked


def item_to_meta(item: dict) -> dict:
    source_id = str(item["id"])
    item_id = f"char-{source_id}"
    tags = [str(tag) for tag in (item.get("tags") or [])]
    return {
        "id": item_id,
        "分类": item.get("group") or "",
        "服装名称": item.get("title") or "",
        "标签": tags + ["角色创作库"],
        "关键词": " ".join(tags),
        "缩略图": f"thumbs/{item_id}.webp",
        "原图": f"images/{item_id}.webp",
        "检索": " ".join(
            [source_id, item.get("title") or "", item.get("group") or "", *tags, "角色创作库", "character"]
        ),
        "来源": "角色创作库",
        "来源链接": SITE_URL,
        "素材ID": source_id,
        "署名": "角色创作库 @62656456",
    }


def download_item(session: requests.Session, item: dict, images: Path, thumbs: Path) -> None:
    source_id = str(item["id"])
    item_id = f"char-{source_id}"
    rel = str(item.get("thumbnail") or "").lstrip("./")
    if not rel:
        raise RuntimeError(f"{source_id} 没有缩略图路径")
    response = session.get(BASE_URL + rel, timeout=60)
    response.raise_for_status()
    if len(response.content) < 1000:
        raise RuntimeError(f"{source_id} 预览过小")
    image_path = images / f"{item_id}.webp"
    image_path.write_bytes(response.content)
    with Image.open(image_path) as image:
        image = image.convert("RGB")
        image = ImageOps.fit(image, (360, 540))
        image.save(thumbs / f"{item_id}.webp", "WEBP", quality=82, method=6)


def write_json_atomic(path: Path, payload: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="分批扩角色创作库服装本地包")
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--groups", default="", help="逗号分隔；空 = 内置 realistic 优先级")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    pack: Path = args.pack
    meta_path = pack / "meta.json"
    manifest_path = pack / "manifest.json"
    images = pack / "images"
    thumbs = pack / "thumbs"
    if not meta_path.is_file():
        print(f"[expand] 找不到现有 meta：{meta_path}")
        return 1
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {"items": []}
    existing = {str(item.get("id") or "").removeprefix("char-") for item in meta}
    groups = [g.strip() for g in args.groups.split(",") if g.strip()] or PRIORITY_GROUPS
    catalog = load_catalog(args.catalog)
    picked = select_items(catalog, existing, args.count, groups)
    if not picked:
        print("[expand] 没有可新增的条目")
        return 0
    print(f"[expand] 当前 {len(meta)} 件；本次选 {len(picked)} 件")
    print("[expand] 分组：", dict(Counter(item.get("group") for item in picked)))
    for item in picked[:10]:
        print(f"  {item['id']} | {item.get('title')} | {item.get('group')}")
    if args.dry_run:
        print("[expand] dry-run：未下载、未写文件")
        return 0

    images.mkdir(parents=True, exist_ok=True)
    thumbs.mkdir(parents=True, exist_ok=True)
    staging = pack / ".batch_staging"
    staging_images = staging / "images"
    staging_thumbs = staging / "thumbs"
    staging_images.mkdir(parents=True, exist_ok=True)
    staging_thumbs.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": "Atelier-character-costume-expand/1.0"})
    done: list[dict] = []
    try:
        for index, item in enumerate(picked, 1):
            download_item(session, item, staging_images, staging_thumbs)
            done.append(item)
            print(f"[expand] {index}/{len(picked)} {item['id']} ok", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[expand] 下载失败，保留旧包：{exc}")
        return 1
    finally:
        session.close()

    for item in done:
        item_id = f"char-{item['id']}"
        (staging_images / f"{item_id}.webp").replace(images / f"{item_id}.webp")
        (staging_thumbs / f"{item_id}.webp").replace(thumbs / f"{item_id}.webp")
    staging_images.rmdir()
    staging_thumbs.rmdir()
    staging.rmdir()

    for item in done:
        meta.append(item_to_meta(item))
        manifest.setdefault("items", []).append(
            {
                "id": f"char-{item['id']}",
                "source_id": item["id"],
                "title": item.get("title"),
                "group": item.get("group"),
                "tags": item.get("tags") or [],
                "source_image": item.get("image"),
                "license": "角色创作库 @62656456 署名；禁止批量镜像/再分发",
            }
        )
    write_json_atomic(meta_path, meta)
    write_json_atomic(manifest_path, manifest)
    (pack / "SOURCE.md").write_text(
        f"""# 角色创作库 · 服装精选本地包

- 来源：https://62656456.github.io/character-reference-library/
- 数量：{len(meta)} 件（分批扩充；本次 +{len(done)}）
- 许可：官方自制素材需署名「角色创作库 @62656456」+ 素材页链接；禁止批量镜像/再分发
- 用途：Atelier 服装槽本地参考；图片不提交进公开仓库
- 最后更新：{time.strftime('%Y-%m-%d %H:%M:%S')}
""",
        encoding="utf-8",
    )
    print(f"[expand] 完成：{len(meta) - len(done)} -> {len(meta)} 件")
    print("[expand] 提醒：完整 783 件/对外分发仍需作者授权")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
