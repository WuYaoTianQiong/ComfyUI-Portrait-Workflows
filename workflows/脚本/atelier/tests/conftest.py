"""契约测试基础设施 —— 与生产库完全隔离。

三条硬规则：
1. 必须在 import 任何项目模块之前设置 PB_* 环境变量，让 `config.settings` 指向临时库；
2. 不进入 `TestClient` 的 with 块（那会触发 lifespan，启动后台监控循环并访问 ComfyUI）；
3. 每个用例前清空全部业务表，保证用例顺序无关。

跑法（项目解释器）：
    python -m pytest -q
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="atelier_contract_"))
os.environ["ATELIER_DB_PATH"] = str(_TMP / "contract.db")
os.environ["ATELIER_THUMBNAIL_DIR"] = str(_TMP / "thumbs")
# 隔离 ComfyUI 根目录：否则 get_image_metadata 会去读本机真实 output，
# 测试结果就取决于磁盘上恰好存在哪些文件（缺文件判定尤其敏感）
_COMFY_ROOT = _TMP / "comfyui"
(_COMFY_ROOT / "output").mkdir(parents=True, exist_ok=True)
os.environ["ATELIER_COMFYUI_ROOT_ENV"] = str(_COMFY_ROOT)
# 测试里创建的假图（b"x"）会被预热线程短暂打开，随后用例 unlink 在 Windows 上
# 会撞到共享冲突；预热只是优化项，测试环境统一关闭。
os.environ["ATELIER_THUMBNAIL_PREWARM"] = "0"
# 指向一个必然拒绝连接的端口：任何意外外呼都会立刻失败，不会挂住测试
os.environ["ATELIER_COMFYUI_API"] = "http://127.0.0.1:9"

import pytest  # noqa: E402

from app.config import settings  # noqa: E402
from app.models import db, init_db  # noqa: E402

# 硬断言：库必须落在临时目录里，否则立即中止，避免测试写坏生产库
assert str(settings.db_path).startswith(str(_TMP)), f"测试库未隔离: {settings.db_path}"

init_db()

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

# raise_server_exceptions=False：让 500 以响应形式返回，便于契约测试断言状态码
client = TestClient(app, raise_server_exceptions=False)

_TABLES = [
    # 顺序 = 先删子表再删父表，否则外键约束会拦住（template_fragments → prompts/templates）
    "prompt_categories",
    "prompt_tags",
    "entity_tags",
    "image_categories",
    "image_tags",
    "template_fragments",
    "gen_history",
    "gen_jobs",
    "templates",
    "prompts",
    "categories",
    "tags",
]


def _assert_schema_ready():
    """新库必须自带部分唯一索引，否则所有 ON CONFLICT 写入都会静默失败。"""
    row = db.execute_sql(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name='gen_history_filename_subfolder_img_type'"
    ).fetchone()
    assert row, "gen_history 部分唯一索引缺失，init_db 的迁移顺序有问题"


_assert_schema_ready()


@pytest.fixture()
def api():
    """每个用例前清空业务表，返回 HTTP 客户端。"""
    for table in _TABLES:
        db.execute_sql(f"DELETE FROM {table}")
    return client


@pytest.fixture()
def seed_prompt():
    from app.models import Prompt

    def _make(**kw):
        kw.setdefault("name", "测试提示词")
        kw.setdefault("prompt", "【人物面部】测试面部")
        return Prompt.create(**kw)

    return _make


@pytest.fixture()
def seed_history():
    from app.models import Image

    def _make(**kw):
        kw.setdefault("filename", "test_00001_.png")
        kw.setdefault("subfolder", "")
        kw.setdefault("img_type", "output")
        kw.setdefault("source", "local")
        return Image.create(**kw)

    return _make


@pytest.fixture()
def seed_taxonomy():
    from app.models import Category, Tag

    def _make():
        cat = Category.create(name="测试分类", color="#123456")
        tag = Tag.create(name="测试标签")
        return cat, tag

    return _make
