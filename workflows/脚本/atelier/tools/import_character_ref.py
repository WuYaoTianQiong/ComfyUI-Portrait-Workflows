"""全量导入角色创作库（服装 783 + 发型 489）。

用户已确认获得作者授权（2026-11-07）；素材仍仅作本地参考，不提交进公开仓库。

- 服装：783 件全部下载原图，统一转 webp（q92），重建 meta/manifest/SOURCE。
- 发型：489 件全部下载原图；宽高比 > 1.2 的双视图拆成
  左半正面（带脸，仅浏览）与右半背面（无脸，供第 4 槽）；
  178 张单面头像只入库浏览，标记不可用于发型槽。
- 断点续传：目标文件已存在且非空时默认跳过；`--force` 强制重下。

用法：
    python tools/import_character_ref.py --dry-run
    python tools/import_character_ref.py --only costume
    python tools/import_character_ref.py --only hair --workers 6
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from PIL import Image, ImageOps

ASSETS = Path(r"F:/ComfyUI_Migration/reference-assets")
CATALOG = ASSETS / "character-ref-catalog.json"
COSTUME_PACK = ASSETS / "character-ref-costume-60"
HAIR_PACK = ASSETS / "character-ref-hair"
SITE_URL = "https://62656456.github.io/character-reference-library/"
SIGN = "角色创作库 @62656456"
LICENSE = "角色创作库 @62656456 署名；禁止批量镜像/再分发（作者已授权本机全量参考）"

COSTUME_CATEGORY = "服装设计"
HAIR_CATEGORY = "发型装造"
DUAL_VIEW_RATIO = 1.2


def load_catalog(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("素材目录顶层不是数组")
    return data


def pick(catalog: list[dict], category: str) -> list[dict]:
    rows = [
        item
        for item in catalog
        if item.get("category") == category
        and item.get("isOfficial")
        and not item.get("adultOnly")
    ]
    return sorted(rows, key=lambda item: str(item.get("id") or ""))


def http_get(session: requests.Session, url: str, retries: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, timeout=90)
            response.raise_for_status()
            if len(response.content) < 1000:
                raise RuntimeError(f"内容过小（{len(response.content)} B）")
            return response.content
        except Exception as exc:  # noqa: BLE001 - 重试后统一上报
            last = exc
            if attempt < retries:
                time.sleep(attempt)
    raise RuntimeError(f"下载失败：{url}（{last}）")


def fetch_image(session: requests.Session, item: dict) -> tuple[bytes, bool]:
    """优先原图；原图缺失时回退站点预览图（返回 payload, 是否回退）。"""
    try:
        return http_get(session, str(item["image"])), False
    except Exception:  # noqa: BLE001 - 原图失败再试预览
        rel = str(item.get("thumbnail") or "").lstrip("./")
        if not rel:
            raise
        return http_get(session, SITE_URL + rel), True


def write_json_atomic(path: Path, payload: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def save_webp(image: Image.Image, dest: Path, quality: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    image.save(tmp, "WEBP", quality=quality, method=6)
    tmp.replace(dest)


def open_rgb(payload: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(payload))
    return ImageOps.exif_transpose(image).convert("RGB")


def make_thumb(image: Image.Image, dest: Path) -> None:
    thumb = ImageOps.fit(image, (360, 540), method=Image.Resampling.LANCZOS)
    save_webp(thumb, dest, 82)


def costume_meta(item: dict, item_id: str) -> dict:
    source_id = str(item["id"])
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
            [
                source_id,
                item.get("title") or "",
                item.get("group") or "",
                item.get("recipeDescription") or "",
                *tags,
                "角色创作库",
                "character",
            ]
        ),
        "来源": "角色创作库",
        "来源链接": SITE_URL,
        "素材ID": source_id,
        "署名": SIGN,
    }


def hair_meta(item: dict, item_id: str, dual: bool) -> dict:
    source_id = str(item["id"])
    tags = [str(tag) for tag in (item.get("tags") or [])]
    return {
        "id": item_id,
        "标题": item.get("title") or "",
        "分区": item.get("group") or "",
        "标签": tags + ["角色创作库"],
        "关键词": " ".join(tags),
        "缩略图": f"thumbs/{item_id}.webp",
        "原图": f"images/{item_id}.webp",
        "正面": f"front/{item_id}.webp" if dual else "",
        "背面": f"back/{item_id}.webp" if dual else "",
        "视图": "正背" if dual else "单面",
        "可用于发型槽": dual,
        "检索": " ".join(
            [
                source_id,
                item.get("title") or "",
                item.get("group") or "",
                item.get("recipeDescription") or "",
                *tags,
                "角色创作库",
                "发型",
                "character",
            ]
        ),
        "来源": "角色创作库",
        "来源链接": SITE_URL,
        "素材ID": source_id,
        "署名": SIGN,
        "原图尺寸": f"{item.get('width')}x{item.get('height')}",
    }


def import_costume_item(
    session: requests.Session, item: dict, pack: Path, force: bool
) -> dict:
    item_id = f"char-{item['id']}"
    image_path = pack / "images" / f"{item_id}.webp"
    thumb_path = pack / "thumbs" / f"{item_id}.webp"
    if not force and image_path.is_file() and thumb_path.is_file():
        return {"item": item, "skipped": True}
    payload, fallback = fetch_image(session, item)
    image = open_rgb(payload)
    save_webp(image, image_path, 92)
    make_thumb(image, thumb_path)
    return {"item": item, "skipped": False, "fallback": fallback, "size": image.size}


def import_hair_item(
    session: requests.Session, item: dict, pack: Path, force: bool
) -> dict:
    item_id = f"char-{item['id']}"
    image_path = pack / "images" / f"{item_id}.webp"
    thumb_path = pack / "thumbs" / f"{item_id}.webp"
    dual = int(item.get("width") or 0) > int(item.get("height") or 0) * DUAL_VIEW_RATIO
    front_path = pack / "front" / f"{item_id}.webp"
    back_path = pack / "back" / f"{item_id}.webp"
    expected = [image_path, thumb_path]
    if dual:
        expected += [front_path, back_path]
    if not force and all(path.is_file() for path in expected):
        return {"item": item, "dual": dual, "skipped": True}
    payload, fallback = fetch_image(session, item)
    image = open_rgb(payload)
    width, height = image.size
    save_webp(image, image_path, 92)
    make_thumb(image, thumb_path)
    if dual:
        left = image.crop((0, 0, width // 2, height))
        right = image.crop((width // 2, 0, width, height))
        save_webp(left, front_path, 92)
        save_webp(right, back_path, 92)
    return {
        "item": item,
        "dual": dual,
        "skipped": False,
        "fallback": fallback,
        "size": image.size,
    }


def run(items: list[dict], worker, pack: Path, workers: int, force: bool) -> list[dict]:
    session = requests.Session()
    session.headers.update({"User-Agent": "Atelier-character-ref-import/2.0"})
    results: list[dict] = []
    failures: list[tuple[str, str]] = []
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(worker, session, item, pack, force): item for item in items
            }
            for index, future in enumerate(as_completed(futures), 1):
                item = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:  # noqa: BLE001 - 单条失败不阻断整批
                    failures.append((str(item.get("id")), str(exc)))
                if index % 20 == 0 or index == len(items):
                    print(
                        f"[import] {index}/{len(items)} 完成，失败 {len(failures)}",
                        flush=True,
                    )
    finally:
        session.close()
    if failures:
        print("[import] 失败条目：")
        for source_id, message in failures:
            print(f"  {source_id}: {message}")
    return results


def write_costume(pack: Path, items: list[dict], results: list[dict]) -> int:
    by_id = {str(result["item"]["id"]): result["item"] for result in results}
    if len(by_id) != len(items):
        missing = [item["id"] for item in items if item["id"] not in by_id]
        print(f"[import] 服装缺少 {len(missing)} 件，保持旧 meta 不动：{missing[:8]}")
        return len(missing)
    meta = [costume_meta(item, f"char-{item['id']}") for item in items]
    manifest = {
        "source": SITE_URL,
        "count": len(meta),
        "authorized": "用户确认作者已授权（2026-11-07）；仅本机参考，不再分发",
        "license": LICENSE,
        "items": [
            {
                "id": f"char-{item['id']}",
                "source_id": item["id"],
                "title": item.get("title"),
                "group": item.get("group"),
                "tags": item.get("tags") or [],
                "source_image": item.get("image"),
                "license": LICENSE,
            }
            for item in items
        ],
    }
    write_json_atomic(pack / "meta.json", meta)
    write_json_atomic(pack / "manifest.json", manifest)
    (pack / "SOURCE.md").write_text(
        f"""# 角色创作库 · 服装全量本地包

- 来源：{SITE_URL}
- 数量：{len(meta)} 件（全量 783）
- 授权：用户确认已获作者授权（2026-11-07）
- 许可：素材需署名「{SIGN}」+ 素材页链接；本包仅本机参考，不再分发
- 用途：Atelier 服装槽本地参考；图片不提交进公开仓库
- 最后更新：{time.strftime('%Y-%m-%d %H:%M:%S')}
""",
        encoding="utf-8",
    )
    print(f"[import] 服装写入 {len(meta)} 件 -> {pack}")
    return 0


def write_hair(pack: Path, items: list[dict], results: list[dict]) -> int:
    by_id = {str(result["item"]["id"]): result for result in results}
    if len(by_id) != len(items):
        missing = [item["id"] for item in items if item["id"] not in by_id]
        print(f"[import] 发型缺少 {len(missing)} 件，保持旧 meta 不动：{missing[:8]}")
        return len(missing)
    meta: list[dict] = []
    manifest_items: list[dict] = []
    for item in items:
        result = by_id[str(item["id"])]
        item_id = f"char-{item['id']}"
        dual = bool(result.get("dual"))
        meta.append(hair_meta(item, item_id, dual))
        manifest_items.append(
            {
                "id": item_id,
                "source_id": item["id"],
                "title": item.get("title"),
                "group": item.get("group"),
                "tags": item.get("tags") or [],
                "views": "正背" if dual else "单面",
                "usable_for_hair_slot": dual,
                "front": f"front/{item_id}.webp" if dual else "",
                "back": f"back/{item_id}.webp" if dual else "",
                "source_image": item.get("image"),
                "license": LICENSE,
            }
        )
    manifest = {
        "source": SITE_URL,
        "count": len(meta),
        "dual_view": sum(1 for row in manifest_items if row["usable_for_hair_slot"]),
        "single_view": sum(1 for row in manifest_items if not row["usable_for_hair_slot"]),
        "authorized": "用户确认作者已授权（2026-11-07）；仅本机参考，不再分发",
        "license": LICENSE,
        "items": manifest_items,
    }
    write_json_atomic(pack / "meta.json", meta)
    write_json_atomic(pack / "manifest.json", manifest)
    (pack / "SOURCE.md").write_text(
        f"""# 角色创作库 · 发型全量本地包

- 来源：{SITE_URL}
- 数量：{len(meta)} 件（正背双视图 {manifest['dual_view']}，单面 {manifest['single_view']}）
- 形态：双视图左半为正面（带脸，仅浏览），右半为背面（无脸，供第 4 槽）
- 授权：用户确认已获作者授权（2026-11-07）
- 许可：素材需署名「{SIGN}」+ 素材页链接；本包仅本机参考，不再分发
- 用途：Atelier 发型槽本地参考；图片不提交进公开仓库
- 最后更新：{time.strftime('%Y-%m-%d %H:%M:%S')}
""",
        encoding="utf-8",
    )
    print(
        f"[import] 发型写入 {len(meta)} 件（双视图 {manifest['dual_view']} / "
        f"单面 {manifest['single_view']}）-> {pack}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="全量导入角色创作库服装/发型")
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--only", choices=("all", "costume", "hair"), default="all")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0, help="仅处理前 N 件，用于试跑")
    parser.add_argument("--force", action="store_true", help="已存在的文件也重下")
    parser.add_argument("--no-meta", action="store_true", help="只下载，不写 meta/manifest/SOURCE")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    catalog = load_catalog(args.catalog)
    costume_items = pick(catalog, COSTUME_CATEGORY) if args.only in ("all", "costume") else []
    hair_items = pick(catalog, HAIR_CATEGORY) if args.only in ("all", "hair") else []
    if args.limit:
        costume_items = costume_items[: args.limit]
        hair_items = hair_items[: args.limit]

    print(
        f"[import] 目录：服装 {len(costume_items)} / 发型 {len(hair_items)}；"
        f"workers={args.workers}"
    )
    for item in costume_items[:5]:
        print(f"  costume {item['id']} | {item.get('group')} | {item.get('title')}")
    for item in hair_items[:5]:
        print(f"  hair    {item['id']} | {item.get('group')} | {item.get('title')}")
    if args.dry_run:
        existing_costume = len(list((COSTUME_PACK / "images").glob("*.webp")))
        existing_hair = len(list((HAIR_PACK / "images").glob("*.webp")))
        print(f"[import] dry-run：服装已有 {existing_costume}，发型已有 {existing_hair}")
        return 0

    failures = 0
    if costume_items:
        print("[import] 开始服装")
        results = run(costume_items, import_costume_item, COSTUME_PACK, args.workers, args.force)
        if args.no_meta:
            failures += sum(1 for item in costume_items if item["id"] not in {r["item"]["id"] for r in results})
        else:
            failures += write_costume(COSTUME_PACK, costume_items, results)
    if hair_items:
        print("[import] 开始发型")
        results = run(hair_items, import_hair_item, HAIR_PACK, args.workers, args.force)
        if args.no_meta:
            failures += sum(1 for item in hair_items if item["id"] not in {r["item"]["id"] for r in results})
        else:
            failures += write_hair(HAIR_PACK, hair_items, results)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())