"""跨模块共享常量和工具函数 —— 消除 router/services 间的重复定义"""

import re
from pathlib import Path
from fastapi.templating import Jinja2Templates

# 碎片类型（在 composer / templates / fragments 等模块中共享）
FRAGMENT_TYPES = [
    "人物面部", "人物身材", "人物服饰", "姿态动作",
    "拍摄视角", "场景环境", "光影色调", "画风技术",
]

# 支持的画像级别
QUALITY_MAP = {
    "2K":  (2160, 3840),
    "4K":  (2560, 4096),
    "6K":  (3200, 5120),
    "8K":  (3840, 6400),
    "12K": (5120, 8192),
}

# Jinja2 模板引擎（供 HTMX 路由使用）
_TEMPLATES_DIR = Path(__file__).absolute().parent / "static" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ========== 碎片解析工具（composer / templates 共享）==========

def parse_prompt_fragments(prompt_text: str) -> list[dict]:
    """解析 【类型】... 格式的提示词为碎片列表（找出所有类型和内容）"""
    if not prompt_text:
        return []
    fragments = []
    pattern = r'【([^】]+)】\s*(.*?)(?=\n【|$)'
    for m in re.finditer(pattern, prompt_text, re.DOTALL):
        name = m.group(1).strip()
        content = m.group(2).strip()
        if content:
            fragments.append({"type": name, "content": content})
    return fragments


def extract_fragment(prompt_text: str, fragment_type: str) -> str:
    """从 prompt 文本中提取指定类型的碎片内容"""
    if not prompt_text:
        return ""
    pattern = r'【' + re.escape(fragment_type) + r'】\s*(.*?)(?=\n【|$)'
    m = re.search(pattern, prompt_text, re.DOTALL)
    return m.group(1).strip() if m else ""
