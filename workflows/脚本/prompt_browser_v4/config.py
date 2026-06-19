"""配置管理 —— pydantic-settings 统一加载"""
from pathlib import Path
from pydantic_settings import BaseSettings


def _resolve_project_root(script_dir: Path) -> Path:
    """自适应 project_root：无论 v4 放在 workflows/ 还是 workflows/脚本/ 下都能正确解析"""
    if script_dir.parent.name == "脚本":
        return script_dir.parent.parent  # workflows/脚本/prompt_browser_v4 → workflows/
    return script_dir.parent  # workflows/prompt_browser_v4 → workflows/


def _resolve_comfyui_root(project_root: Path, env_override: str | None = None) -> Path:
    """自适应 ComfyUI 安装目录，支持三种结构"""
    if env_override:
        p = Path(env_override)
        if p.exists():
            return p

    # 结构 A: ComfyUI-aki-v3/ComfyUI/  (D 盘 style)
    candidate_a = project_root.parent / "ComfyUI"
    if candidate_a.exists():
        return candidate_a

    # 结构 B: 再往上一级就是 ComfyUI 根目录 (F 盘 style: 根目录/output/)
    candidate_b = project_root.parent.parent
    if candidate_b.exists() and (candidate_b / "output").is_dir():
        return candidate_b

    # 兜底：返回默认路径（即使不存在）
    return candidate_a


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8654
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
print(f"[config]   output dir exists = {(settings.comfyui_root / 'output').is_dir()}")
print(f"[config]   thumbnail_dir = {settings.thumbnail_dir}")
