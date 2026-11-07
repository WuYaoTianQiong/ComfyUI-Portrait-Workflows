"""配置管理 —— pydantic-settings 统一加载"""
import os
from pathlib import Path
from pydantic import model_validator
from pydantic_settings import BaseSettings


def _is_inside(base: Path, candidate: Path) -> bool:
    """词法包含校验（不访问磁盘），避免 Windows junction 上的 exists/resolve 异常。"""
    try:
        root = os.path.abspath(os.path.normcase(str(base)))
        target = os.path.abspath(os.path.normcase(str(candidate)))
        return os.path.commonpath([root, target]) == root
    except (OSError, ValueError):
        return False


def _validate_reference_cache_dir(
    cache_dir: Path,
    app_root: Path,
    library_root: Path,
    reference_root: Path | None,
) -> Path:
    """校验外链图片缓存根目录的落点（C-REMOTE-CACHE@1）。

    硬约束：必须在 app_root 下；不得与 reference_root 互相包含；不得落在
    data/ 或 dist/ 内。缓存只存储本机参考素材，禁止随发布物扩散。
    """
    cache_dir = Path(cache_dir)
    if not cache_dir.is_absolute():
        cache_dir = app_root / cache_dir

    if not _is_inside(app_root, cache_dir):
        raise ValueError(f"ATELIER_REFERENCE_CACHE_DIR 必须位于 app_root 下：{cache_dir}")
    if reference_root is not None and (
        _is_inside(reference_root, cache_dir) or _is_inside(cache_dir, reference_root)
    ):
        raise ValueError(
            f"ATELIER_REFERENCE_CACHE_DIR 不得与 reference_root 互相包含：{cache_dir}"
        )
    forbidden = (
        app_root / "data",
        library_root / "data",
        app_root / "dist",
        library_root / "dist",
    )
    for directory in forbidden:
        if _is_inside(directory, cache_dir):
            raise ValueError(
                f"ATELIER_REFERENCE_CACHE_DIR 不得位于 data/ 或 dist/ 内：{cache_dir}"
            )
    return cache_dir


def _resolve_library_root(app_root: Path) -> Path:
    """ComfyUI 工作流库根：只放工作流与文档；运行数据在 `data_dir`（默认 `脚本/atelier/data`）。

    atelier 通常放在 <库>/脚本/ 下，需要跳过一层「脚本」；若直接放在 <库>/ 下则上一层即是。
    """
    if app_root.parent.name == "脚本":
        return app_root.parent.parent
    return app_root.parent


def _resolve_pose_extra_dir(library_root: Path, explicit: Path | None) -> Path | None:
    """第二姿势来源（pose-studio-lite）根目录。

    显式 `ATELIER_POSE_EXTRA_DIR` 优先；未配置时按常见落点自动探测，
    都没有则返回 None（只加载上游，行为与合并前一致）。
    只认带 `meta.json` 的目录，避免把空目录/半成品当来源。
    """
    if explicit is not None:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            path = library_root / path
        return path.absolute()

    candidates = (
        library_root.parent / "reference-assets" / "pose-studio-lite",
        library_root.parent.parent / "reference-assets" / "pose-studio-lite",
        library_root / "reference-assets" / "pose-studio-lite",
    )
    for path in candidates:
        try:
            if (path / "meta.json").is_file():
                return path.absolute()
        except OSError:
            continue
    return None


def _resolve_costume_character_dir(
    library_root: Path, explicit: Path | None
) -> Path | None:
    """角色创作库精选服装来源（60 件本地只读包）。

    显式 `ATELIER_COSTUME_CHARACTER_DIR` 优先；未配置时按 `reference-assets/
    character-ref-costume-60` 常见落点自动探测；都没有则只加载上游服装库。
    """
    if explicit is not None:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            path = library_root / path
        return path.absolute()

    candidates = (
        library_root.parent / "reference-assets" / "character-ref-costume-60",
        library_root.parent.parent / "reference-assets" / "character-ref-costume-60",
        library_root / "reference-assets" / "character-ref-costume-60",
    )
    for path in candidates:
        try:
            if (path / "meta.json").is_file():
                return path.absolute()
        except OSError:
            continue
    return None


def _safe_is_dir(p: Path) -> bool:
    """容错 is_dir：junction/符号链接在 Windows 上可能抛 WinError 448，视为不存在。

    用 os.readlink 解析单层重解析点（junction）得到真实目标后再判目录，与
    services.paths._resolve_if_reparse 一致；避免 os.path.realpath/exists 在
    不受信任的装入点上抛 WinError 448 而被误判为不存在。
    """

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


def _split_csv(raw: str) -> frozenset[str]:
    """把逗号分隔的名单拆成集合；兼容全角逗号与首尾空白。"""
    parts = (raw or "").replace("，", ",").split(",")
    return frozenset(p.strip() for p in parts if p.strip())


def _resolve_comfyui_root(library_root: Path, env_override: str | None = None) -> Path:
    """自适应 ComfyUI 安装目录：从 library_root 向上逐级查找首个含 output 子目录的根。

    覆盖项目位于 <库>/脚本/atelier 等深层目录、而 ComfyUI 根在更上层的情况
    （如 ComfyUI-aki-v3/ComfyUI）。旧逻辑仅检查固定两层，会误选不存在的目录，导致
    get_image_metadata / 缩略图 / 模型提取全部定位失败。
    """
    if env_override:
        p = Path(env_override)
        if _safe_is_dir(p):
            return p

    cur = library_root
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
    return library_root.parent / "ComfyUI"


def _resolve_reference_root(
    library_root: Path,
    comfyui_root: Path,
    explicit: Path | None,
) -> Path:
    """解析上游 AI 参考图库（ai-pose-gallery-zh）的根目录。

    上游项目固定位于 `<comfyui_root>/custom_nodes/`，不在工作流库内；
    `workflows/` 下不再需要 Junction。优先级（从高到低）：

    1. 显式传入 / 环境变量 `ATELIER_REFERENCE_ROOT`（尊重用户意图，不做存在性校验）；
    2. `<comfyui_root>/custom_nodes/ai-pose-gallery-zh`（唯一规范位置，存在即用）；
    3. `<library_root>/ai-pose-gallery-zh`（旧布局兼容回退，存在才用）；
    4. 都不存在 → 仍返回第 2 项，让下游给出明确报错，而不是静默指向旧布局。

    存在性探测走 `_safe_is_dir`（即 `Path.is_dir()` + 重解析点容错），
    权限不足等探测失败一律按不存在处理，不抛异常。
    """
    if explicit is not None:
        return Path(explicit)

    canonical = Path(comfyui_root) / "custom_nodes" / "ai-pose-gallery-zh"
    if _safe_is_dir(canonical):
        return canonical

    legacy = Path(library_root) / "ai-pose-gallery-zh"
    if _safe_is_dir(legacy):
        return legacy

    return canonical


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8656
    no_browser: bool = False  # ATELIER_NO_BROWSER=1：启动时不自动开浏览器（冒烟/测试用）
    comfyui_api: str = "http://127.0.0.1:8188"
    comfyui_root_env: str | None = None  # 手动覆盖用
    # 独立指定 ComfyUI 的出图根（ComfyUI 用 --output-directory 或 output 挂到别的盘时）
    comfyui_output_dir: Path | None = None

    # 路径（两个根，语义不同，别再混用）
    package_dir: Path = Path(__file__).absolute().parent        # <库>/脚本/atelier/app
    app_root: Path = package_dir.parent                        # <库>/脚本/atelier  ← 代码项目根
    library_root: Path = _resolve_library_root(app_root)       # <库>                ← 工作流库根
    # 应用运行数据根（DB / 缩略图 / 上传 / 备份）：与 ComfyUI 工作流库分离
    # ATELIER_DATA_DIR 覆盖；默认 app_root/"data"
    data_dir: Path | None = None
    # 由 model_validator 在 env 解析后计算；不能把 _resolve_comfyui_root(...) 写在这里，
    # 否则读到的永远是类默认的 comfyui_root_env（None），ATELIER_COMFYUI_ROOT_ENV 形同虚设。
    comfyui_root: Path = Path()
    # 缩略图目录（2026-11-06 归一：由 model_validator 派生到 data_dir/thumbnails）；
    # 不能写成 `library_root / "thumbnails"`，否则会固化成模块加载时的类默认值
    # （与 reference_root 当初的坑同源）。
    thumbnail_dir: Path = Path()
    # 入库后后台预热 600px 缩略图；测试/极慢磁盘可用 ATELIER_THUMBNAIL_PREWARM=0 关闭
    thumbnail_prewarm: bool = True

    # AI 参考图库（只读素材层，上游 ai-pose-gallery-zh）
    reference_enabled: bool = True
    # 由 model_validator 在 env 解析后计算（见 `_resolve_reference_root`）：
    # 上游项目固定位于 `<comfyui_root>/custom_nodes/` 下，不在工作流库内，
    # `workflows/` 下不再需要 Junction。显式传入 ATELIER_REFERENCE_ROOT 时优先。
    # 不要写成 library_root / "..."，否则会固化成模块加载时的类默认值，
    # ATELIER_LIBRARY_ROOT / ATELIER_COMFYUI_ROOT_ENV 覆盖后不会跟着变。
    reference_root: Path | None = None
    #: 第二姿势来源（pose-studio-lite）根；None = 禁用。
    #: `ATELIER_POSE_EXTRA_DIR` 显式覆盖；未配置时按 reference-assets 常见落点自动探测。
    pose_extra_dir: Path | None = None
    #: 角色创作库精选服装（60 件）根；None = 禁用。
    #: `ATELIER_COSTUME_CHARACTER_DIR` 显式覆盖；未配置时自动探测。
    costume_character_dir: Path | None = None
    reference_allow_nsfw: bool = False

    reference_page_size: int = 60
    reference_nsfw_pose_systems: str = "全身单人・性感系,双人缠绵"
    reference_nsfw_costume_categories: str = "内衣・睡衣,性感穿搭"

    # 外链图片缓存（CharaDB 素材仅本机参考、禁止再分发；目录不得入库/进发布物）
    #: 缓存根；默认 `<app_root>/.cache/reference-remote`，由 model_validator 归一与校验
    reference_cache_dir: Path = app_root / ".cache" / "reference-remote"
    #: 允许下载的外链域名白名单（逗号分隔）；只读集合见 `reference_remote_host_set`
    reference_remote_hosts: str = "charadb-2fi.pages.dev"
    #: 单次下载总超时（秒）
    reference_remote_timeout_sec: float = 20.0
    #: 进程内同时下载上限（asyncio 信号量）
    reference_remote_max_concurrency: int = 8
    #: 失败重试次数（不含首次）
    reference_remote_retry: int = 2
    #: 单文件上限；超出按下载失败处理
    reference_remote_max_bytes: int = 20 * 1024 * 1024

    @model_validator(mode="after")
    def _resolve_comfyui_root_field(self):
        self.comfyui_root = _resolve_comfyui_root(self.library_root, self.comfyui_root_env)
        # 运行数据根：与 ComfyUI 工作流库分离。
        # 必须在 validator 里重新派生 db_path / thumbnail_dir —— 它们若写成类属性
        # `library_root / ...`，会固化成模块加载时的类默认值（reference_root 踩过的坑）。
        # 例外：显式 ATELIER_DB_PATH / ATELIER_THUMBNAIL_DIR 优先（tests/conftest.py、
        # tools/smoke.py、tests/e2e 靠它们把库与缩略图隔离到临时目录）。
        if self.data_dir is None:
            self.data_dir = self.app_root / "data"
        self.data_dir = Path(self.data_dir).expanduser().absolute()
        if "db_path" not in self.model_fields_set:
            self.db_path = self.data_dir / "prompts.db"
        if "thumbnail_dir" not in self.model_fields_set:
            self.thumbnail_dir = self.data_dir / "thumbnails"
        # 三级解析：显式/env > comfyui_root/custom_nodes > library_root 旧布局兼容回退。
        # 依赖上面的 comfyui_root，顺序不能颠倒。
        self.reference_root = _resolve_reference_root(
            self.library_root, self.comfyui_root, self.reference_root
        )
        self.pose_extra_dir = _resolve_pose_extra_dir(self.library_root, self.pose_extra_dir)
        self.costume_character_dir = _resolve_costume_character_dir(
            self.library_root, self.costume_character_dir
        )
        self.reference_cache_dir = _validate_reference_cache_dir(
            self.reference_cache_dir,
            self.app_root,
            self.library_root,
            self.reference_root,
        )
        return self

    @property
    def reference_dir(self) -> Path:
        """参考库根（只读）：指向上游 ai-pose-gallery-zh。

        上游项目固定位于 `<comfyui_root>/custom_nodes/` 下，不在工作流库内，
        `workflows/` 下不再需要 Junction。解析统一在 `_resolve_reference_root`
        完成（validator 保证非 None），这里不再做第二处回退，避免两处逻辑漂移。
        """
        return self.reference_root

    @property
    def nsfw_pose_systems(self) -> frozenset[str]:
        return _split_csv(self.reference_nsfw_pose_systems)

    @property
    def nsfw_costume_categories(self) -> frozenset[str]:
        return _split_csv(self.reference_nsfw_costume_categories)

    @property
    def reference_remote_host_set(self) -> frozenset[str]:
        """外链域名白名单（只读集合）；比较前统一小写，避免大小写绕过。"""
        return frozenset(host.lower() for host in _split_csv(self.reference_remote_hosts))

    @property
    def output_dir(self) -> Path:
        """出图根：显式配置优先，否则沿用 <comfyui_root>/output。"""
        return self.comfyui_output_dir or (self.comfyui_root / "output")

    @property
    def input_dir(self) -> Path:
        return self.comfyui_root / "input"

    @property
    def temp_dir(self) -> Path:
        return self.comfyui_root / "temp"

    # 数据库（2026-11-06 归一：由 validator 派生到 data_dir/prompts.db，
    # 不再是 library_root/文档/提示词收藏.db；显式 ATELIER_DB_PATH 仍优先）
    db_path: Path = Path()

    # 前端构建产物目录（vite build 输出，需含 index.html 与 assets/）
    web_dir: Path = app_root / "web"

    model_config = {"env_prefix": "ATELIER_", "extra": "ignore"}


settings = Settings()
# 运行数据根必须先建：upload 落盘、备份目录都直接在它下面派生
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.thumbnail_dir.mkdir(parents=True, exist_ok=True)

# 启动时打印确认
print(f"[config] comfyui_root = {settings.comfyui_root}")
print(f"[config]   output dir = {settings.output_dir}")
print(f"[config]   output dir exists = {_safe_is_dir(settings.output_dir)}")
print(f"[config]   data_dir = {settings.data_dir}")
print(f"[config]   thumbnail_dir = {settings.thumbnail_dir}")
print(f"[config]   db_path = {settings.db_path}")
print(f"[config]   reference_root = {settings.reference_root} (enabled={settings.reference_enabled})")
print(f"[config]   pose_extra_dir = {settings.pose_extra_dir}")
print(f"[config]   costume_character_dir = {settings.costume_character_dir}")
print(f"[config]   reference_cache_dir = {settings.reference_cache_dir}")
