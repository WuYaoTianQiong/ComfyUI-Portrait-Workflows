"""工作流目录扫描 —— 哪些 json 是可用的 ComfyUI 工作流、它们有哪些可注入能力。

`routers/comfyui.py`（`/api/workflows`）与 `routers/system.py`（`/api/system/config`
要报默认工作流）都需要这套判定，抽到服务层，避免路由之间互相 import 私有函数。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import settings
from app.services.workflow_parser import (
    find_loadimage_nodes,
    is_video_workflow,
    loadimage_role,
    load_workflow,
    detect_workflow_caps,
    detect_workflow_params,
)

logger = logging.getLogger(__name__)

#: 历史归档目录：**不参与 all 范围的自动扫描**；用户可在「分类与标签 → 工作流」手动上传任意目录的 JSON。
ARCHIVE_DIR = settings.library_root / "历史工作流"
# 兼容旧引用
DEPRECATED_DIR = ARCHIVE_DIR

#: 探测缓存：路径 → (mtime, caps, params, media_kind)。文件没改动就不重复解析。
_meta_cache: dict[str, tuple[float, dict[str, bool], dict, str]] = {}
#: 槽位缓存：路径 → (mtime, 图片槽位数, 是否可做参考合成)
_slot_cache: dict[str, tuple[float, int, bool]] = {}


def search_dirs() -> list[Path]:
    """自动扫描目录（通用工作流列表）：只扫库根目录。

    其他位置（历史工作流 / 任意磁盘目录）走前端「上传自定义工作流」，
    内容存在本机 localStorage，出图时随请求带给后端。
    """
    return [settings.library_root]


def studio_dirs() -> list[Path]:
    """参考图库合成台专用的工作流目录（按优先级）。

    合成台要的是"能塞进人像/服装/姿势参考图"的编辑类工作流，与库根那批
    文生图 / 换衣 / 超分工作流不是一类东西。扫描目录（按优先级）：

    1. `图库专用工作流/`：本机适配、实测能出图的三图合成（GGUF Q5_K_M / Nunchaku fp4），
       文件名带 `图库专用_` 前缀，见该目录 README；
    2. `我的工作流/`：用户自己丢进来的编辑类工作流，见该目录 README；
    3. 上游开源项目自带的专用工作流：`<参考库>/src/workflows/*.api.json`
       （例如 qwen_image_edit_2509_3img，引用本机没有的 2509 fp8，选中会报不匹配）；
    4. `历史工作流/画廊旧版/`：旧位置，仅兜底（已被第 1 项取代）；
    5. 库根：用户临时放进来的编辑类工作流。
    """
    dirs = [
        settings.library_root / "图库专用工作流",
        settings.library_root / "我的工作流",
        settings.reference_dir / "src" / "workflows",
        settings.library_root / "历史工作流" / "画廊旧版",
        settings.library_root,
    ]
    out: list[Path] = []
    seen: set[str] = set()
    for d in dirs:
        key = str(d).lower()
        if key in seen:
            continue
        seen.add(key)
        if d.is_dir():
            out.append(d)
    return out


def _studio_slots(path: Path) -> tuple[int, bool]:
    """返回 (图片槽位数, 是否能用于参考合成)。

    参考合成至少要有 1 个 `LoadImage*`（放参考图）+ 1 个文本编码节点（放提示词）；
    文生图工作流没有 LoadImage、纯超分工作流没有文本编码，都会被判成不可用。

    额外一条：**有 LoadImage 但标题一个业务角色都识别不出**的工作流同样不可用。
    合成台靠 `loadimage_role()` 把 LoadImage 映射到人像/服装/姿势槽，角色认不出来
    就永远只能 400「该工作流没有人像输入」。常见于 UI 格式 `.json`（节点标题是
    `图像`/`主体` 这类默认名），解析出的 LoadImage 纯属误导。这类工作流不能出现在
    下拉里，否则用户选中后才失败。

    注意与「完全没有 LoadImage」区分：后者已由 `slots >= 1` 拦下，
    这里只在 `slots >= 1` 的前提下补充角色判据，不重复处理同一个原因。
    """
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return 0, False
    cached = _slot_cache.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1], cached[2]
    try:
        workflow = load_workflow(str(path))
        slots = sum(
            1
            for node in workflow.values()
            if isinstance(node, dict) and str(node.get("class_type", "")).startswith("LoadImage")
        )
        has_prompt = bool(detect_workflow_caps(workflow).get("prompt"))
        # 角色判据只看 `find_loadimage_nodes()`（class_type == "LoadImage"），
        # 与 recipes 端点 `_role_nodes()` 的判定保持一致。
        loadimage_nodes = find_loadimage_nodes(workflow)
        has_role = any(loadimage_role(title) for _node_id, title in loadimage_nodes)
        unroleable = bool(loadimage_nodes) and not has_role
        ready = slots >= 1 and has_prompt and not unroleable
    except Exception:  # noqa: BLE001
        slots, ready = 0, False
    _slot_cache[str(path)] = (mtime, slots, ready)
    return slots, ready


def is_valid_workflow(filepath: Path) -> bool:
    try:
        content = json.loads(filepath.read_text(encoding="utf-8"))
        # API 格式：扁平 {节点id: {class_type: ...}}
        if any(isinstance(v, dict) and "class_type" in v for v in content.values()):
            return True
        # 界面格式：{nodes: [...]}。load_workflow/ensure_api_format 能直接转换，
        # 与 /validate_workflow 的判定保持一致（旧逻辑只认 API 格式，
        # 导致界面里保存的工作流全部不出现在下拉列表中）。
        nodes = content.get("nodes")
        return isinstance(nodes, list) and any(
            isinstance(n, dict) and n.get("type") for n in nodes
        )
    except Exception:
        return False


def _load_meta(path: Path) -> tuple[float, dict[str, bool], dict, str]:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return 0.0, {}, {}, "image"
    cached = _meta_cache.get(str(path))
    if cached and cached[0] == mtime:
        return cached
    try:
        workflow = load_workflow(str(path))
        caps = detect_workflow_caps(workflow)
        params = detect_workflow_params(workflow)
        # 工作流可在 extra.atelier 里声明可选画质档位（如 Qwen 去掉低于原生的档）。
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            atelier = (raw.get("extra") or {}).get("atelier") if isinstance(raw, dict) else None
            if isinstance(atelier, dict):
                tiers = atelier.get("quality_tiers")
                if isinstance(tiers, list) and tiers:
                    params["quality_tiers"] = [str(t) for t in tiers]
                if isinstance(atelier.get("default_quality"), str):
                    params["default_quality"] = atelier["default_quality"]
        except Exception:
            pass
        media_kind = "video" if is_video_workflow(workflow) else "image"
    except Exception as exc:
        logger.debug("探测工作流能力失败 %s：%s", path.name, exc)
        caps, params, media_kind = {}, {}, "image"
    _meta_cache[str(path)] = (mtime, caps, params, media_kind)
    return _meta_cache[str(path)]


def get_workflow_meta(path: Path) -> tuple[dict[str, bool], dict]:
    """返回某工作流的注入能力与参数描述；解析失败时返回空 dict（schema 默认全 True）。"""
    _, caps, params, _ = _load_meta(path)
    return caps, params


def get_workflow_media_kind(path: Path) -> str:
    """返回 `image` / `video`；视频工作流默认不进入 Atelier 工作流下拉。"""
    return _load_meta(path)[3]


def find_default_workflow(include_video: bool = False, scope: str = "all") -> str:
    """默认工作流：studio 范围优先 T0 定稿的三槽链路，all 范围优先文件名带「文生图」。"""
    items = list_valid_workflows(include_video=include_video, scope=scope)
    if scope == "studio":
        # 合成台默认要「人像+服装+姿势」正好三槽：四图会多要一张、双图/单图会缺槽。
        # 来源权重只用于兜底排序；`_PREFERRED_STUDIO_NAMES` 里的定稿项永远排最前。
        ready = [w for w in items if w["studio_ready"]]
        if ready:
            three = [w for w in ready if w["image_slots"] == 3]
            pool = three or ready

            def _pref(item: dict) -> int:
                name = item["name"]
                if name in _PREFERRED_STUDIO_NAMES:
                    return _PREFERRED_STUDIO_NAMES.index(name)
                return len(_PREFERRED_STUDIO_NAMES)

            pool.sort(
                key=lambda w: (-_STUDIO_SOURCE_RANK.get(w["source"], 0), _pref(w), w["name"])
            )
            return pool[0]["path"]
    for item in items:
        if "文生图" in item["path"]:
            return item["path"]
    return items[0]["path"] if items else ""


def _path_source(path: Path) -> str:
    """给路径打来源标签，前端下拉据此分组/解释。"""
    try:
        rel = path.relative_to(settings.library_root)
    except ValueError:
        return "外部"
    head = rel.parts[0] if rel.parts else ""
    if head == "图库专用工作流":
        return "图库专用"
    if head == "我的工作流":
        return "我的工作流"
    if rel.parts[:2] == ("历史工作流", "画廊旧版"):
        return "旧版归档"
    if len(rel.parts) > 1:
        return "上游原版"
    return "库根"


#: studio 下拉的排序权重：图库专用 > 我的工作流 > 上游原版 > 旧版归档/库根
_STUDIO_SOURCE_RANK = {"图库专用": 5, "我的工作流": 4, "上游原版": 3, "旧版归档": 2, "库根": 1}

#: 本机实测能出图、作为默认选中的工作流（按优先级排列）。
#: 2026-11-05 T0 三候选实测对比后定稿：Qwen21+VNCCS 三图 25 步单人
#: （人像 + 服装 + 姿势三槽齐全、带姿势 LoRA），与参考库配方的默认保持一致。
#: 与它在同一来源（图库专用工作流/）的候选按 mtime 排，所以这里写文件名即可。
_PREFERRED_STUDIO_NAMES = ("图库专用_Qwen21+VNCCS_三图_25步_单人.api.json",)

#: 合成台下拉里打「推荐」标签的工作流。
#: 2026-11-05 实测定档：它是唯一同时具备「人像槽 + 服装槽 + 姿势槽 + 姿势 LoRA」的链路，
#: 5 姿势 × 3 种子 15/15 PASS，热跑 27s（cfg 2.5 后 81–110s）。
_RECOMMENDED_STUDIO_NAMES = ("图库专用_Qwen21+VNCCS_三图_25步_单人.api.json",)

#: studio 下拉的屏蔽名单：文件名 → 不可用原因。
#: 上游参考库的 `src/workflows` 是只读目录，缺模型的工作流无法靠移文件隐藏，只能在这里排除；
#: 维护方式：当 `wf_probe.py`（逐工作流实测）判定为 LOAD_FAIL / REJECTED / ERROR / TIMEOUT 时追加。
_UNUSABLE_STUDIO: dict[str, str] = {
    "qwen_image_edit_2509_3img.api.json": "缺模型 qwen_image_edit_2509_fp8_e4m3fn.safetensors，选中会报不匹配",
}


def studio_sort_key(item: dict) -> tuple:
    """studio 列表排序：三槽优先 → 来源权重 → 新到旧。"""
    return (
        item.get("image_slots") == 3,
        _STUDIO_SOURCE_RANK.get(item.get("source", ""), 0),
        item.get("mtime", 0.0),
    )


def list_valid_workflows(include_video: bool = False, scope: str = "all") -> list[dict]:
    """扫描可用工作流，附 caps/params/media_kind/mtime 与合成台槽位信息。

    - `scope="all"`（默认）：只扫库根目录，给「分类与标签 → 工作流」与 atelier 通用下拉用；
      历史工作流等其他目录走前端手动上传。
    - `scope="studio"`：参考图库合成台用，扫描 `studio_dirs()`（参考库专用 + 画廊旧版 + 库根），
      并只保留**能做参考合成**的工作流（有 LoadImage 槽位 + 有文本编码节点）；
      文生图 / 纯超分这类塞不进参考图的，直接不出现，避免用户选中后才报「与本机不匹配」。

    `include_video=False`（默认）时跳过含 SaveVideo / VideoCombine 的工作流：
    画廊只处理图片，视频工作流请直接在 ComfyUI 里跑。
    """
    directories = studio_dirs() if scope == "studio" else search_dirs()
    results: list[dict] = []
    seen: set[str] = set()
    for directory in directories:
        if not directory.is_dir():
            continue
        for file in sorted(directory.glob("*.json")):
            if not is_valid_workflow(file):
                continue
            blocked_reason = _UNUSABLE_STUDIO.get(file.name)
            if blocked_reason:
                logger.info("studio 下拉已屏蔽不可用工作流 %s：%s", file.name, blocked_reason)
                continue
            resolved = str(file.resolve(strict=False))
            if resolved in seen:
                continue
            seen.add(resolved)
            mtime, caps, params, media_kind = _load_meta(file)
            if media_kind == "video" and not include_video:
                continue
            slots, ready = _studio_slots(file)
            if scope == "studio" and not ready:
                continue
            results.append({
                "path": str(file),
                "name": file.name,
                "rel_path": file.relative_to(settings.library_root).as_posix()
                if file.is_relative_to(settings.library_root) else file.name,
                "source": _path_source(file),
                "mtime": mtime,
                "caps": caps,
                "params": params,
                "media_kind": media_kind,
                "image_slots": slots,
                "studio_ready": ready,
                "recommended": file.name in _RECOMMENDED_STUDIO_NAMES,
            })
    return results
