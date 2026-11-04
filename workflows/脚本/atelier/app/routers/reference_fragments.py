"""AI 参考图库 · 单条转提示词（M4）。

把一条参考写成 `prompts` 表里的一条结构化提示词：

    【人物服饰】
    象牙白针织衫

约定（融合计划 §4 M4）：
- **只做单条**，不做批量：批量会把个人提示词库稀释成参考库镜像；
- 正文 `f"【{类型}】\\n{内容}"`，与 `_migrate_v4_fragments_to_prompts` 同格式；
- `note = ref:{library}/{id}` 作为来源标记，可按它精确清理；
- `tags` 带库名，方便在提示词页按来源筛选；
- 按正文精确匹配去重（`prompts` 没有唯一约束），重复转换返回已有 id；
- 外链服装只转文字描述，不下载、不复制图片。

端点：
- POST /api/reference/fragments
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models import Prompt, auto_classify_prompt, db
from app.services import reference_library
from app.services.tagging import sync_prompt_tags

router = APIRouter(tags=["参考图库转提示词"])

#: 参考库 → 提示词碎片类型。
#: 计划文档写的是「服装与配饰」，但项目标准 8 类是「人物服饰」
#: （`fragment_syntax.FRAGMENT_TYPES`）。写入非标准类型会让提示词页的类型筛选
#: 与组合器都认不出来，所以按标准类型落地（决策见融合计划 §9）。
FRAGMENT_TYPE_BY_LIBRARY: dict[str, str] = {
    "pose": "姿态动作",
    "costume": "人物服饰",
    "portrait": "人物面部",
    "costume-anime": "人物服饰",
}

#: 与 `recipe_prompt.BASE_HAIR_NAME` 一致：这个发型名等于「没有特殊发型」。
BASE_HAIR_NAME = "标准基础款"


class ReferenceFragmentRequest(BaseModel):
    library: str = Field(..., description="pose / costume / portrait / costume-anime")
    item_id: str = Field(..., description="参考条目 id（上游 JSON 的 id）")


class ReferenceFragmentResponse(BaseModel):
    success: bool = True
    id: int
    dedup: bool = False
    prompt: str
    note: str
    tags: str
    fragment_type: str


@router.get("/reference/ping")
def ping_reference_fragments():
    return {"ok": True, "router": "reference_fragments"}


def _append(parts: list[str], value: str | None) -> None:
    text = (value or "").strip()
    if text:
        parts.append(text)


def _content_for(library: str, item: dict) -> str:
    """从参考 DTO 拼一句可进随机池的中文描述。

    不拼姿势编号（P001）之类的索引信息：编号对出图没有语义价值，
    写进随机池只会让提示词变成元数据。只保留名称与可感知的属性
    （姿势角度、发型/发长、外链服装的日文名）。服装名称本身通常已是
    整套搭配描述，不再叠分类/标签，否则正文会变成元数据堆。
    """
    name = (item.get("name") or "").strip() or item["id"]
    parts = [name]

    if library == "pose":
        _append(parts, item.get("angle"))
    elif library == "portrait":
        hair_name = (item.get("subtitle") or "").strip()
        if hair_name and hair_name != BASE_HAIR_NAME and hair_name not in name:
            _append(parts, hair_name)
        facet = (item.get("facet") or "").strip()
        if facet and facet not in name:
            _append(parts, facet)
    elif library == "costume-anime":
        _append(parts, item.get("subtitle"))

    # 去重并保持顺序（角度/发型名可能与名称重复）
    seen: set[str] = set()
    unique: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.add(part)
            unique.append(part)
    return "，".join(unique)


@router.post("/reference/fragments", response_model=ReferenceFragmentResponse)
def create_reference_fragment(req: ReferenceFragmentRequest):
    """把单条参考转成提示词；重复转换返回已有条目（`dedup=true`）。"""
    if req.library not in reference_library.LIBRARY_FILES:
        raise HTTPException(404, f"未知参考库：{req.library}")
    item_id = (req.item_id or "").strip()
    if not item_id:
        raise HTTPException(400, "缺少参考条目 id")

    # `get_item` 已套用 NSFW 可见性：总闸关闭时敏感条目返回 None → 404，
    # 不能靠转提示词绕过过滤。
    item = reference_library.get_item(req.library, item_id)
    if item is None:
        raise HTTPException(404, "参考条目不存在或不可见")

    fragment_type = FRAGMENT_TYPE_BY_LIBRARY[req.library]
    content = _content_for(req.library, item)
    prompt_text = f"【{fragment_type}】\n{content}"

    existing = Prompt.get_or_none(Prompt.prompt == prompt_text)
    if existing is not None:
        return {
            "success": True,
            "id": existing.id,
            "dedup": True,
            "prompt": prompt_text,
            "note": existing.note or f"ref:{req.library}/{item_id}",
            "tags": existing.tags or "",
            "fragment_type": fragment_type,
        }

    note = f"ref:{req.library}/{item_id}"
    tags = f"参考库,{reference_library.LIBRARY_LABELS[req.library]}"
    with db.atomic():
        prompt = Prompt.create(
            name=item.get("name") or item_id,
            prompt=prompt_text,
            negative_prompt="",
            tags=tags,
            note=note,
        )
        # 与 prompts 路由的单条创建保持一致：自动归入 组合/单项/零散，
        # 并把标签文本同步到 entity_tags（标签筛选以关联表为准）。
        auto_classify_prompt(prompt.id)
        sync_prompt_tags(prompt.id, tags)

    return {
        "success": True,
        "id": prompt.id,
        "dedup": False,
        "prompt": prompt_text,
        "note": note,
        "tags": tags,
        "fragment_type": fragment_type,
    }