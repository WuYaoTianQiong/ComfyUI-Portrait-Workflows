"""组合结果的语法操作 —— `【类型】` 文本的解析 / 渲染 / 批量替换。

命名规范 §9：`【类型】` 语法只有**一个**实现（`services/fragment_syntax.py`）。
前端曾自带一份等价的正则（`utils/segmentation.ts`），两份实现各改各的，
一旦格式演进就会一半页面认、一半不认。现在页面的预览与批量替换都打这里。

与 `routers/composer.py` 的分工：composer 是"组合创作"这个功能（碎片池 + 跑图），
composition 是"组合结果"这段文本的语法操作 —— 不碰数据库、不跑图。
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.fragment_syntax import (
    parse,
    render,
    replace_type,
    split_marked,
    types_in,
    validate,
)

router = APIRouter(tags=["组合结果"])


class Fragment(BaseModel):
    type: str
    content: str = ""


class ParseRequest(BaseModel):
    text: str = ""


class ParseResponse(BaseModel):
    fragments: list[Fragment] = Field(default_factory=list)
    types: list[str] = Field(default_factory=list)
    #: 未被 `【类型】` 标记的正文（"智能分段"只对它动手）
    leftover: str = ""
    problems: list[str] = Field(default_factory=list)


class RenderRequest(BaseModel):
    #: 每组碎片单独渲染成一段文本；批量传进来只为省掉 N 次往返
    items: list[list[Fragment]] = Field(default_factory=list)


class RenderResponse(BaseModel):
    texts: list[str] = Field(default_factory=list)


class ReplaceText(BaseModel):
    id: int
    text: str = ""


class BatchReplaceRequest(BaseModel):
    texts: list[ReplaceText] = Field(default_factory=list)
    type: str
    content: str = ""


class ReplaceResult(BaseModel):
    id: int
    #: 替换前该类型的正文（没有这一片时为空串）
    old_content: str = ""
    #: 替换后全文；该类型不存在时为 None（调用方据此跳过）
    replaced: str | None = None


class BatchReplaceResponse(BaseModel):
    items: list[ReplaceResult] = Field(default_factory=list)
    skipped: int = 0


@router.post("/composition/parse", response_model=ParseResponse)
def parse_composition(req: ParseRequest):
    """解析一段提示词：已标记碎片 + 未标记残留 + 语法问题。"""
    fragments, leftover = split_marked(req.text)
    return {
        "fragments": fragments,
        "types": types_in(req.text),
        "leftover": leftover,
        "problems": validate(req.text),
    }


@router.post("/composition/render", response_model=RenderResponse)
def render_composition(req: RenderRequest):
    """把碎片列表渲染回 `【类型】` 标准文本（空内容自动跳过）。"""
    return {"texts": [render([fragment.model_dump() for fragment in group]) for group in req.items]}


@router.post("/composition/batch_replace", response_model=BatchReplaceResponse)
def batch_replace_composition(req: BatchReplaceRequest):
    """批量替换指定类型的正文，返回替换前内容与替换后全文。"""
    results: list[ReplaceResult] = []
    skipped = 0
    for item in req.texts:
        replaced = replace_type(item.text, req.type, req.content)
        if replaced is None:
            skipped += 1
            results.append({"id": item.id, "old_content": "", "replaced": None})
            continue
        old = next(
            (f["content"] for f in parse(item.text) if f["type"] == req.type),
            "",
        )
        results.append({"id": item.id, "old_content": old, "replaced": replaced})
    return {"items": results, "skipped": skipped}
