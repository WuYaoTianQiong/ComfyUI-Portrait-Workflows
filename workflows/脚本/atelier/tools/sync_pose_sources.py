"""一条命令同步姿势库的两个上游，并重建 pose-studio-lite 的本地索引。

为什么需要这个脚本：
- 上游 `ai-pose-gallery-zh` 自带机器可读的 `data/pose-zh.json`，pull 完即可用；
- `pose-studio-lite` 的元数据藏在 `index.html` 的卡片 DOM 里，pull 完必须重新解析，
  并增量重建缩略图，atelier 才能读到新的 `meta.json`；
- 两边都更新时不应手动跑两次，也不应在应用启动时自动 pull（网络/上游坏数据会拖垮启动）。

用法：
    python tools/sync_pose_sources.py            # pull 两边 + 重建 PSL 索引 + 校验
    python tools/sync_pose_sources.py --check    # 只校验，不 pull、不写文件
    python tools/sync_pose_sources.py --no-pull  # 不 pull，只重建 PSL 索引 + 校验
    python tools/sync_pose_sources.py --skip-upstream / --skip-psl

退出码：0 成功；1 校验/拉取/解析失败（保留上一版 meta.json）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402

UPSTREAM_BASELINE = 1439
PSL_BASELINE = 280
BASELINE_TOLERANCE = 0.05
PSL_GENERATED = ("/meta.json", "/thumbs/", "/SOURCE.md", "/names.en.json")


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )


def git_repo(path: Path) -> bool:
    return (path / ".git").exists()


def git_status(path: Path) -> str:
    result = run(["git", "-C", str(path), "status", "--porcelain"])
    if result.returncode != 0:
        raise RuntimeError(f"{path} 不是可读的 git 仓库：{result.stderr.strip()}")
    return result.stdout.strip()


def git_commit(path: Path) -> str:
    result = run(["git", "-C", str(path), "rev-parse", "HEAD"])
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def ensure_excludes(psl_root: Path) -> None:
    """生成物写进 .git/info/exclude，保持 pose-studio-lite 工作区干净。"""
    git_dir = psl_root / ".git"
    if not git_dir.is_dir():
        return
    exclude = git_dir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    lines = existing.splitlines()
    changed = False
    for line in PSL_GENERATED:
        if line not in lines:
            lines.append(line)
            changed = True
    if changed:
        exclude.write_text("\n".join(lines) + "\n", encoding="utf-8")


def pull_repo(label: str, path: Path, allow_dirty: bool) -> None:
    if not git_repo(path):
        raise RuntimeError(f"{label} 不是 git 仓库：{path}")
    dirty = git_status(path)
    if dirty and not allow_dirty:
        raise RuntimeError(f"{label} 工作区不干净，拒绝 pull：\n{dirty[:1000]}")
    result = run(["git", "-C", str(path), "pull", "--ff-only"])
    if result.returncode != 0:
        raise RuntimeError(
            f"{label} pull 失败：\n{result.stdout.strip()}\n{result.stderr.strip()}"
        )
    print(f"[sync] {label} pull 完成：{result.stdout.strip() or '已是最新'}")


def load_en_names(root: Path) -> dict[str, str]:
    path = root / "names.en.js"
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    body = text[start : end + 1]
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        # 上游文件末尾有 trailing comma；去注释 + 去尾逗号后再试。
        body = re.sub(r"//.*?$", "", body, flags=re.MULTILINE)
        body = re.sub(r",(\s*[}\]])", r"\1", body)
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}


def normalize_name(value: str) -> str:
    """姿势名归一：去掉空白、间隔号与常见标点，用于识别跨来源重复/变体。"""
    return re.sub(r"[\s・·,，。.\-—_/|（）()]+", "", value or "")


ANGLE_ZH = {
    "front": "正面",
    "side": "侧面",
    "diag": "斜侧",
    "high": "高机位",
    "low": "低机位",
    "above": "俯视",
    "back": "背面",
}


def parse_items(root: Path, en_map: dict[str, str]) -> list[dict]:
    html = (root / "index.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    for section in soup.select("section.section"):
        category = "adult" if "adult" in (section.get("id") or "") else "normal"
        group = "成人风格" if category == "adult" else "正常姿势"
        for art in section.select("article.card"):
            raw_id = (art.get("data-id") or "").strip()
            if not raw_id:
                continue
            title = art.select_one(".title")
            name = ""
            if title:
                span = title.select_one("span")
                name = (
                    span.get_text(" ", strip=True)
                    if span
                    else title.get_text(" ", strip=True).replace(raw_id, "").strip()
                )
            img = art.select_one("img")
            file = (img.get("src") if img else "") or ""
            file = file.strip()
            if not file:
                continue
            tags = [i.get_text(" ", strip=True) for i in art.select(".tags i")]
            facet = (art.get("data-cat") or "").strip()
            series = (art.get("data-series") or "").strip()
            search = (art.get("data-text") or "").strip()
            zh = art.select_one(".prompt")
            prompt_zh = zh.get_text(" ", strip=True) if zh else ""
            btn = art.select_one("button[data-en]")
            prompt_en = (btn.get("data-en") or "").strip() if btn else ""
            match = re.search(r"_([a-z]+)\.webp$", file)
            angle = match.group(1) if match else ""
            items.append(
                {
                    "id": raw_id,
                    "name": name,
                    "name_en": en_map.get(name, ""),
                    "file": file,
                    "thumb": f"thumbs/{file}",
                    "category": category,
                    "group": group,
                    "facet": facet,
                    "series": series,
                    "series_label": tags[0] if tags else series,
                    "tags": tags,
                    "angle": angle,
                    "angle_zh": ANGLE_ZH.get(angle, angle),
                    "nsfw": category == "adult",
                    "prompt_zh": prompt_zh,
                    "prompt_en": prompt_en,
                    "search": " ".join(
                        x for x in [search, raw_id, name, facet, series, *tags] if x
                    ),
                }
            )
    return items


def write_thumbs(root: Path, items: list[dict]) -> int:
    written = 0
    for item in items:
        src = root / item["file"]
        dst = root / item["thumb"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
                continue
            with Image.open(src) as image:
                image = image.convert("RGB")
                image.thumbnail((360, 480), Image.LANCZOS)
                image.save(dst, "WEBP", quality=82, method=6)
            written += 1
        except OSError as exc:
            raise RuntimeError(f"缩略图生成失败：{src}：{exc}") from exc
    return written


def write_json_atomic(path: Path, payload: dict | list) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def write_source_md(root: Path, items: list[dict], commit: str) -> None:
    normal = sum(1 for item in items if item["category"] == "normal")
    adult = sum(1 for item in items if item["category"] == "adult")
    text = f"""# pose-studio-lite 本地素材

- 来源：https://github.com/zg-405/pose-studio-lite
- 提交：`{commit}`
- 许可证：Apache-2.0（见 `LICENSE`）
- 同步日期：{dt.date.today().isoformat()}
- 数量：{len(items)} 张（正常 {normal} / 成人 {adult}）
- 图片：`normal/`、`adult/`，900×1200 WebP，白底线稿人台
- 索引：`meta.json`（id/中文名/英文名/分类/系列/角度/NSFW/中英提示词/检索串）
- 缩略图：`thumbs/`，360×480 WebP

## 更新

```bash
python "F:/ComfyUI_Migration/ComfyUI-Portrait-Workflows/workflows/脚本/atelier/tools/sync_pose_sources.py"
```

生成物（`meta.json`、`thumbs/`、`SOURCE.md`、`names.en.json`）已加入 `.git/info/exclude`，
不会弄脏上游工作区。详细方案见
`workflows/文档/参考图库_姿势库双源合并_方案_20261106.md`。
"""
    (root / "SOURCE.md").write_text(text, encoding="utf-8")


def validate_psl(root: Path, items: list[dict]) -> list[str]:
    errors: list[str] = []
    if not items:
        return ["pose-studio-lite 解析到 0 条"]
    ids = Counter(item["id"] for item in items)
    duplicates = [item_id for item_id, count in ids.items() if count > 1]
    if duplicates:
        errors.append(f"重复 id：{duplicates[:10]}")
    for item in items:
        for key in ("file", "thumb"):
            rel = item.get(key) or ""
            if not rel:
                errors.append(f"{item['id']} 缺 {key}")
            elif not (root / rel).is_file():
                errors.append(f"{item['id']} {key} 不存在：{rel}")
        if not item.get("prompt_zh") or not item.get("prompt_en"):
            errors.append(f"{item['id']} 中英提示词为空")
    if abs(len(items) - PSL_BASELINE) > PSL_BASELINE * BASELINE_TOLERANCE:
        print(
            f"[sync] 警告：pose-studio-lite 条数 {len(items)} 偏离基线 {PSL_BASELINE}"
            f"（±{int(BASELINE_TOLERANCE * 100)}%），请确认上游是否改版"
        )
    return errors


def validate_upstream(root: Path) -> tuple[int, list[str]]:
    errors: list[str] = []
    path = root / "data" / "pose-zh.json"
    if not path.is_file():
        return 0, [f"上游姿势元数据不存在：{path}"]
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return 0, [f"上游姿势元数据读取失败：{exc}"]
    if not isinstance(rows, list) or not rows:
        return 0, ["上游姿势元数据不是非空数组"]
    for row in rows:
        if not isinstance(row, dict):
            errors.append("上游存在非对象条目")
            continue
        for key in ("缩略图", "原图"):
            rel = str(row.get(key) or "").strip()
            if rel and not (root / rel).is_file():
                errors.append(f"上游 {row.get('id', '?')} {key} 不存在：{rel}")
    if abs(len(rows) - UPSTREAM_BASELINE) > UPSTREAM_BASELINE * BASELINE_TOLERANCE:
        print(
            f"[sync] 警告：上游条数 {len(rows)} 偏离基线 {UPSTREAM_BASELINE}"
            f"（±{int(BASELINE_TOLERANCE * 100)}%）"
        )
    return len(rows), errors


def write_state(state_path: Path, payload: dict) -> None:
    write_json_atomic(state_path, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="同步姿势库双来源并重建 PSL 索引")
    parser.add_argument("--check", action="store_true", help="只校验，不 pull、不写文件")
    parser.add_argument("--no-pull", action="store_true", help="不 pull，只重建 PSL 索引")
    parser.add_argument("--skip-upstream", action="store_true", help="跳过上游图库")
    parser.add_argument("--skip-psl", action="store_true", help="跳过 pose-studio-lite")
    parser.add_argument("--allow-dirty", action="store_true", help="允许工作区不干净")
    parser.add_argument("--upstream", type=Path, help="覆盖上游图库目录")
    parser.add_argument("--psl", type=Path, help="覆盖 pose-studio-lite 目录")
    args = parser.parse_args()

    upstream = (args.upstream or settings.reference_root).expanduser()
    psl = (args.psl or settings.pose_extra_dir)
    if psl is not None:
        psl = Path(psl).expanduser()

    if not args.skip_psl and psl is None:
        print("[sync] 失败：未配置 pose-studio-lite 目录（ATELIER_POSE_EXTRA_DIR 或 --psl）")
        return 1
    if not args.skip_upstream and not upstream.is_dir():
        print(f"[sync] 失败：上游图库目录不存在：{upstream}")
        return 1

    psl_commit = git_commit(psl) if psl is not None and git_repo(psl) else ""
    upstream_commit = git_commit(upstream) if git_repo(upstream) else ""

    if args.check:
        print("[sync] 只校验，不修改任何文件")
    else:
        if not args.no_pull:
            try:
                if not args.skip_upstream:
                    pull_repo("ai-pose-gallery-zh", upstream, args.allow_dirty)
                    upstream_commit = git_commit(upstream)
                if not args.skip_psl:
                    ensure_excludes(psl)
                    pull_repo("pose-studio-lite", psl, args.allow_dirty)
                    psl_commit = git_commit(psl)
            except RuntimeError as exc:
                print(f"[sync] 失败：{exc}")
                return 1

        if not args.skip_psl:
            ensure_excludes(psl)
            try:
                items = parse_items(psl, load_en_names(psl))
                written = write_thumbs(psl, items)
                preflight = validate_psl(psl, items)
                if preflight:
                    print("[sync] 失败：PSL 预校验未通过，保留旧 meta.json：")
                    for error in preflight[:20]:
                        print(f"  - {error}")
                    return 1
                write_json_atomic(
                    psl / "meta.json",
                    {
                        "source": {
                            "repo": "https://github.com/zg-405/pose-studio-lite",
                            "commit": psl_commit,
                            "license": "Apache-2.0",
                            "downloaded": dt.date.today().isoformat(),
                        },
                        "count": len(items),
                        "categories": {
                            category: {
                                "count": sum(
                                    1 for item in items if item["category"] == category
                                ),
                                "facets": dict(
                                    Counter(
                                        item["facet"]
                                        for item in items
                                        if item["category"] == category
                                    )
                                ),
                            }
                            for category in ("normal", "adult")
                        },
                        "items": items,
                    },
                )
                (psl / "names.en.json").write_text(
                    json.dumps(load_en_names(psl), ensure_ascii=False, indent=1),
                    encoding="utf-8",
                )
                write_source_md(psl, items, psl_commit)
                print(f"[sync] pose-studio-lite 重建完成：{len(items)} 条，缩略图更新 {written} 张")
            except (OSError, ValueError, RuntimeError) as exc:
                print(f"[sync] 失败：PSL 重建失败：{exc}")
                return 1

    errors: list[str] = []
    psl_count = 0
    upstream_count = 0
    if not args.skip_psl:
        meta_path = psl / "meta.json"
        if not meta_path.is_file():
            errors.append(f"PSL 索引不存在：{meta_path}")
        else:
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                psl_items = meta.get("items") or []
                psl_count = len(psl_items)
                errors.extend(validate_psl(psl, psl_items))
            except (OSError, ValueError) as exc:
                errors.append(f"PSL 索引读取失败：{exc}")
    if not args.skip_upstream:
        upstream_count, upstream_errors = validate_upstream(upstream)
        errors.extend(upstream_errors)

    if errors:
        print("[sync] 校验失败：")
        for error in errors[:30]:
            print(f"  - {error}")
        if len(errors) > 30:
            print(f"  ... 另有 {len(errors) - 30} 条")
        return 1

    state = {
        "ok": True,
        "updated": dt.datetime.now().isoformat(timespec="seconds"),
        "sources": {
            "ai-pose-gallery-zh": {
                "path": str(upstream),
                "commit": upstream_commit,
                "count": upstream_count,
            },
            "pose-studio-lite": {
                "path": str(psl) if psl is not None else "",
                "commit": psl_commit,
                "count": psl_count,
            },
        },
    }
    if not args.check and psl is not None:
        write_state(psl.parent / "sync-state.json", state)

    # 同名不等于同图：两套线稿可能同名不同渲染/角度。只提示，不自动去重。
    try:
        upstream_rows = json.loads(
            (upstream / "data" / "pose-zh.json").read_text(encoding="utf-8")
        )
        psl_meta = json.loads((psl / "meta.json").read_text(encoding="utf-8"))
        upstream_names = {
            normalize_name(row.get("姿势名称"))
            for row in upstream_rows
            if isinstance(row, dict) and row.get("姿势名称")
        }
        psl_names = {
            normalize_name(item.get("name"))
            for item in (psl_meta.get("items") or [])
            if item.get("name")
        }
        overlap = upstream_names & psl_names
        if overlap:
            print(
                f"[sync] 提示：{len(overlap)} 个姿势名与上游同名（可能是变体/重复），"
                "已按来源保留两套，不做自动去重"
            )
    except (OSError, ValueError):
        pass

    print(
        f"[sync] 校验通过：upstream={upstream_count}，pose-studio-lite={psl_count}，"
        f"合计={upstream_count + psl_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
