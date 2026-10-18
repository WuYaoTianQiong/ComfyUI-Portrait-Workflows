"""跨模块共享常量和工具函数 —— 消除 router/services 间的重复定义"""

# 结构化提示词的解析统一在 services.composition，这里只做兼容导出
from services.composition import (  # noqa: F401
    FRAGMENT_TYPES,
    extract,
    parse,
)

# 支持的画像级别
QUALITY_MAP = {
    "2K":  (2160, 3840),
    "4K":  (2560, 4096),
    "6K":  (3200, 5120),
    "8K":  (3840, 6400),
    "12K": (5120, 8192),
}


# ========== 兼容旧函数名（调用方不需要改）==========

def parse_prompt_fragments(prompt_text: str) -> list[dict]:
    """解析 【类型】... 格式的提示词为碎片列表。见 services.composition.parse。"""
    return parse(prompt_text)


def extract_fragment(prompt_text: str, fragment_type: str) -> str:
    """从 prompt 文本中提取指定类型的碎片内容。见 services.composition.extract。"""
    return extract(prompt_text, fragment_type)
