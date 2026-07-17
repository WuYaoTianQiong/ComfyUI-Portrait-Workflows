"""配置管理 —— pydantic-settings 统一加载"""
from pathlib import Path
from pydantic_settings import BaseSettings


def _resolve_project_root(script_dir: Path) -> Path:
    """自适应 project_root：无论 v4 放在 workflows/ 还是 workflows/脚本/ 下都能正确解析"""
    if script_dir.parent.name == "脚本":
        return script_dir.parent.parent  # workflows/脚本/prompt_browser_v4 → workflows/
    return script_dir.parent  # workflows/prompt_browser_v4 → workflows/


def _safe_is_dir(p: Path) -> bool:
    """容错 is_dir：junction/符号链接在 Windows 上可能抛 WinError 448，视为不存在。

    用 os.readlink 解析单层重解析点（junction）得到真实目标后再判目录，与
    services.helpers._resolve_if_reparse 一致；避免 os.path.realpath/exists 在
    不受信任的装入点上抛 WinError 448 而被误判为不存在。
    """
    import os
    try:
        try:
            target = os.readlink(p)
            if target:
                p = Path(target)
        except (OSError, ValueError):
            pass
        return os.path.isdir(p)
    except OSError:
        return False


def _resolve_comfyui_root(project_root: Path, env_override: str | None = None) -> Path:
    """自适应 ComfyUI 安装目录：从 project_root 向上逐级查找首个含 output 子目录的根。

    覆盖 v4 位于 workflows/脚本/prompt_browser_v4 等深层目录、而 ComfyUI 根在更上层的情况
    （如 ComfyUI-aki-v3/ComfyUI）。旧逻辑仅检查固定两层，会误选不存在的目录，导致
    get_image_metadata / 缩略图 / 模型提取全部定位失败。
    """
    if env_override:
        p = Path(env_override)
        if _safe_is_dir(p):
            return p

    cur = project_root
    for _ in range(8):
        # 当前层直接是 ComfyUI 根（含 output）
        if _safe_is_dir(cur / "output"):
            return cur
        # 当前层下有 ComfyUI 子目录（含 output）
        cand = cur / "ComfyUI"
        if _safe_is_dir(cand / "output"):
            return cand
        parent = cur.parent
        if parent == cur:  # 抵达盘符根，停止
            break
        cur = parent

    # 兜底：保持旧行为（即使不存在）
    return project_root.parent / "ComfyUI"


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8656
    comfyui_api: str = "http://127.0.0.1:8188"
    comfyui_root_env: str | None = None  # 手动覆盖用

    # 路径
    script_dir: Path = Path(__file__).absolute().parent
    project_root: Path = _resolve_project_root(script_dir)
    comfyui_root: Path = _resolve_comfyui_root(project_root, comfyui_root_env)
    thumbnail_dir: Path = project_root / "thumbnails"

    # 数据库
    db_path: Path = project_root / "文档" / "提示词收藏.db"

    # 静态文件
    static_dir: Path = script_dir / "static"

    model_config = {"env_prefix": "PB_", "extra": "ignore"}


settings = Settings()
settings.thumbnail_dir.mkdir(parents=True, exist_ok=True)

# 启动时打印确认
print(f"[config] comfyui_root = {settings.comfyui_root}")
print(f"[config]   output dir exists = {_safe_is_dir(settings.comfyui_root / 'output')}")
print(f"[config]   thumbnail_dir = {settings.thumbnail_dir}")
