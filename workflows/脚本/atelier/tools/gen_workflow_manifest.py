"""生成/校验工作流清单（稳定 id + sha256）。

用法：
    python tools/gen_workflow_manifest.py          # 重新生成
    python tools/gen_workflow_manifest.py --check  # CI：清单与磁盘必须一致
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services.workflow_manifest import (  # noqa: E402
    MANIFEST_FILENAME,
    content_sha256,
    load_manifest,
    manifest_path,
    stable_id_for_path,
)
from app.services.workflow_catalog import is_valid_workflow  # noqa: E402
from app.services.workflow_parser import (  # noqa: E402
    apply_quality_tiers,
    detect_workflow_caps,
    detect_workflow_params,
    find_loadimage_nodes,
    load_workflow,
    loadimage_role,
)


def _scan_dirs() -> list[Path]:
    candidates = [
        settings.library_root / "通用工作流",
        settings.library_root / "图库专用工作流",
        settings.library_root / "我的工作流",
        settings.library_root,
    ]
    out: list[Path] = []
    seen: set[str] = set()
    for directory in candidates:
        key = str(directory).lower()
        if key in seen or not directory.is_dir():
            continue
        seen.add(key)
        out.append(directory)
    return out


def _scope_for(relative: str) -> str:
    head = relative.split("/", 1)[0]
    return {
        "通用工作流": "general",
        "图库专用工作流": "studio",
        "我的工作流": "user",
        "历史工作流": "archive",
    }.get(head, "root")


def _entry_for(
    path: Path,
    existing_by_file: dict[str, str],
    existing_by_sha: dict[str, str],
    status: str = "active",
) -> dict | None:
    try:
        relative = path.resolve().relative_to(settings.library_root.resolve()).as_posix()
        workflow = load_workflow(str(path))
    except Exception:
        return None
    sha = content_sha256(path)
    # 身份优先沿用旧清单：先按路径（改内容），再按内容（改文件名）。
    workflow_id = (
        existing_by_file.get(relative)
        or existing_by_sha.get(sha)
        or stable_id_for_path(relative)
    )
    params = apply_quality_tiers(detect_workflow_params(workflow), None)
    caps = detect_workflow_caps(workflow)
    loadimages = find_loadimage_nodes(workflow)
    slots = [role for _node_id, title in loadimages if (role := loadimage_role(title))]
    return {
        "id": workflow_id,
        "name": path.name,
        "file": relative,
        "sha256": sha,
        "status": status,
        "dir_scope": _scope_for(relative),
        "input_count": len(loadimages),
        "slots": slots,
        "quality_mode": params.get("quality_mode") or "none",
        "quality_tiers": params.get("quality_tiers") or [],
        "default_ratio": params.get("default_ratio") or "",
        "prompt": bool(caps.get("prompt")),
        "negative": bool(caps.get("negative")),
    }


def build_manifest() -> dict:
    previous = load_manifest()
    existing_by_file = {
        str(entry.get("file") or ""): str(entry.get("id") or "")
        for entry in previous.get("workflows") or []
        if entry.get("file") and entry.get("id")
    }
    existing_by_sha = {
        str(entry.get("sha256") or ""): str(entry.get("id") or "")
        for entry in previous.get("workflows") or []
        if entry.get("sha256") and entry.get("id")
    }
    entries: dict[str, dict] = {}
    for directory in _scan_dirs():
        for path in sorted(directory.glob("*.json")):
            if path.name == MANIFEST_FILENAME or path.name.startswith("."):
                continue
            if not is_valid_workflow(path):
                continue
            entry = _entry_for(path, existing_by_file, existing_by_sha)
            if entry:
                entries[entry["file"]] = entry

    # 历史归档只登记、不进入下拉；保留同一套稳定 id 与内容哈希。
    archive = settings.library_root / "历史工作流"
    if archive.is_dir():
        for path in sorted(archive.rglob("*.json")):
            if path.name == MANIFEST_FILENAME or path.name.startswith("."):
                continue
            if not is_valid_workflow(path):
                continue
            entry = _entry_for(
                path, existing_by_file, existing_by_sha, status="archived",
            )
            if entry:
                entries[entry["file"]] = entry
    return {
        "schema": 1,
        "workflows": [entries[key] for key in sorted(entries)],
    }


def _check(manifest: dict) -> int:
    problems: list[str] = []
    known: set[str] = set()
    for entry in manifest.get("workflows") or []:
        relative = str(entry.get("file") or "")
        known.add(relative)
        path = settings.library_root / relative
        if not path.is_file():
            problems.append(f"清单里的文件不存在: {relative}")
            continue
        actual = content_sha256(path)
        if actual != entry.get("sha256"):
            problems.append(f"内容已变化（需要重新生成清单）: {relative}")
    for entry in build_manifest()["workflows"]:
        if entry["file"] not in known:
            problems.append(f"磁盘上有未登记工作流: {entry['file']}")
    for problem in problems:
        print(f"ERROR {problem}")
    print(f"清单 {len(known)} 条，问题 {len(problems)} 个")
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = parser.parse_args()

    target = manifest_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if args.check:
        if not target.is_file():
            print(f"ERROR 缺少清单: {target}")
            return 1
        return _check(json.loads(target.read_text(encoding="utf-8")))

    manifest = build_manifest()
    target.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"已写入 {target}（{len(manifest['workflows'])} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
