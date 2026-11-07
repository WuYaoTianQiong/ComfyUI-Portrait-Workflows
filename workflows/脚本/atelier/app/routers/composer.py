"""组合创作 API —— 碎片解析 + 碎片跑图"""
import json
import traceback
import random
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from app.models import Prompt, Category, Tag, PromptCategory, EntityTag, db
from app.services.prompt_compiler import compile_prompt
from app.services.workflow_parser import (
    RatioNotSupported, detect_workflow_caps, load_workflow, inject_prompt, resolve_seed,
)
from app.services.generation import submit_generation
from app.services.idempotency import (
    SCOPE_COMPOSER_BATCH,
    SCOPE_COMPOSER_SINGLE,
    request_key,
)
from app.services.output_location import (
    OutputLocationError,
    expand_subfolder,
)
from app.routers.jobs import (
    build_job_extra,
    find_job_by_idempotency,
)
from app.config import settings
from app.services.fragment_syntax import (
    FRAGMENT_TYPES, contains_nsfw_keyword, parse, strip_headers,
)
from app.services import atomic_pilot
from app.services.costume_policy import (
    costume_covers_lower, costume_coverage_warning, has_explicit_content,
)
from app.services.tagging import (
    RANDOM_EXCLUDE_TAG, RANDOM_EXCLUDE_WARNING, split_tags,
)

router = APIRouter(tags=["组合创作"])


def _get_fragment_data(
    search="", category_id=None, tag_ids=None, fragment_type="", safe_mode=False,
):
    """获取碎片数据，按类型分组，供随机组合 / 批量替换使用。

    α 之后碎片统一从 prompts 解析（单块 prompt 就是碎片），不再读 fragments 表。

    `safe_mode=True` 时跳过 tags / note 命中 NSFW_KEYWORDS 的提示词：
    只做启发式过滤（无法保证全覆盖），且**不检查正文**，避免正常描述被误伤。
    """
    query = Prompt.select()

    if search:
        query = query.where(
            Prompt.prompt.contains(search)
            | Prompt.name.contains(search)
            | Prompt.tags.contains(search)
            | Prompt.note.contains(search)
        )

    if category_id is not None:
        query = query.join(PromptCategory).where(
            PromptCategory.category == category_id
        )

    if tag_ids:
        tag_id_list = [int(t.strip()) for t in tag_ids.split(",") if t.strip()]
        if tag_id_list:
            query = query.where(
                Prompt.id
                << EntityTag.select(EntityTag.entity_id).where(
                    (EntityTag.entity_type == "prompt")
                    & (EntityTag.tag.in_(tag_id_list))
                )
            )

    rows = list(query.order_by(Prompt.id.desc()))
    keyword = (search or "").strip().lower()

    only = fragment_type if fragment_type in FRAGMENT_TYPES else ""
    grouped = {only: []} if only else {t: [] for t in FRAGMENT_TYPES}
    seen_content = {}

    def content_key(ftype, content):
        return f"{ftype}||{content}"

    for r in rows:
        # 安全模式：整条提示词隐藏（其下所有碎片一起消失），只按 tags/note 判定。
        if safe_mode and contains_nsfw_keyword(r.tags, r.note):
            continue
        excluded = RANDOM_EXCLUDE_TAG in split_tags(r.tags)
        fragments = parse(r.prompt)
        costume_text = next(
            (f["content"] for f in fragments if f["type"] == "人物服饰"), "",
        )
        coverage_warning = costume_coverage_warning(costume_text)
        warnings = []
        if excluded:
            warnings.append(RANDOM_EXCLUDE_WARNING)
        if coverage_warning:
            warnings.append(coverage_warning)
        warning = "；".join(warnings)
        for f in fragments:
            ftype = f["type"]
            if ftype not in grouped:
                continue
            if keyword and keyword not in (f["content"] or "").lower():
                continue
            ck = content_key(ftype, f["content"])
            if ck in seen_content:
                entry = seen_content[ck]
                entry["dup_count"] = (entry.get("dup_count") or 1) + 1
                src = f"{r.name or ''} (ID:{r.id})"
                if src not in entry.get("source_names", []):
                    entry.setdefault("source_names", []).append(src)
                # 同一内容只要还有一个「未排除且服装完整」的来源，就清掉警告。
                if not excluded and not coverage_warning:
                    entry["warning"] = ""
            else:
                entry = {
                    "prompt_id": r.id,
                    "prompt_name": r.name or "",
                    "type": ftype,
                    "content": f["content"],
                    "tags": r.tags or "",
                    "source_preview": (r.prompt or "")[:60],
                    "source": "prompt",
                    "dup_count": 1,
                    "source_names": [f"{r.name or ''} (ID:{r.id})"],
                    "warning": warning,
                }
                seen_content[ck] = entry
                grouped[ftype].append(entry)

    return grouped


@router.get("/composer/fragments")
def get_fragments(
    search: str = Query(""),
    category_id: Optional[int] = Query(None),
    tag_ids: Optional[str] = Query(None),
    fragment_type: str = Query(""),
    safe_mode: bool = Query(False),
):
    """获取当前筛选提示词范围内的碎片列表，按类型分组。

    `safe_mode=1`：跳过 tags / note 命中 NSFW 关键词的提示词（启发式，无法保证全覆盖）。
    """
    grouped = _get_fragment_data(search, category_id, tag_ids, fragment_type, safe_mode)
    total_fragments = sum(len(v) for v in grouped.values())
    return {
        "grouped": grouped,
        "total_prompts": 0,  # 不再需要，保留兼容
        "fragment_count": total_fragments,
    }


class RandomRecipeFragment(BaseModel):
    type: str
    content: str


class RandomRecipeResponse(BaseModel):
    prompt_id: int
    name: str
    fragments: list[RandomRecipeFragment]
    tags: str = ""
    source: str = "prompt"
    recipe_count: int


class AtomicRecipeResponse(BaseModel):
    bank_version: int
    combo_id: str
    fragments: list[RandomRecipeFragment]
    pose_facet: str
    labels: dict[str, str] = {}
    warning: str = "跨源实验：建议人工复核"


@router.get("/composer/recipes/random", response_model=RandomRecipeResponse)
def get_random_recipe(
    exclude_id: Optional[int] = Query(None, description="避免连续抽到同一套"),
    safe_mode: bool = Query(False),
):
    """随机返回一套完整 8 类配方（同源整套随机）。

    只接受「恰好 8 个标准类、无重复、无残留标题/字面量换行」的提示词；
    `随机排除` 标签与安全模式在这里过滤。`exclude_id` 用于避免连续重复，
    若排除后为空则回退到完整候选集，保证不会因为只有一套而 404。
    """
    candidates: list[tuple[Prompt, dict[str, str]]] = []
    for row in Prompt.select().order_by(Prompt.id.desc()):
        if safe_mode and contains_nsfw_keyword(row.tags, row.note):
            continue
        if safe_mode and has_explicit_content(row.prompt):
            continue
        if RANDOM_EXCLUDE_TAG in split_tags(row.tags):
            continue
        fragments = parse(row.prompt)
        if len(fragments) != len(FRAGMENT_TYPES):
            continue
        types = [f["type"] for f in fragments]
        if len(set(types)) != len(types) or set(types) != set(FRAGMENT_TYPES):
            continue
        by_type = {f["type"]: f["content"] for f in fragments}
        # P4 safety：服装只描述上衣 / 通用「服装」的配方可能补出裸露，随机池跳过。
        if not costume_covers_lower(by_type.get("人物服饰", "")):
            continue
        if any("【" in content or "\\n" in content for content in by_type.values()):
            continue
        candidates.append((row, by_type))

    if exclude_id is not None:
        filtered = [item for item in candidates if item[0].id != exclude_id]
        if filtered:
            candidates = filtered
    if not candidates:
        raise HTTPException(404, "没有可用的完整 8 类配方")

    row, by_type = random.choice(candidates)
    return RandomRecipeResponse(
        prompt_id=row.id,
        name=row.name or "",
        fragments=[
            RandomRecipeFragment(type=ftype, content=by_type[ftype])
            for ftype in FRAGMENT_TYPES
        ],
        tags=row.tags or "",
        recipe_count=len(candidates),
    )


@router.get("/composer/recipes/atomic", response_model=AtomicRecipeResponse)
def get_atomic_recipe(seed: Optional[int] = Query(None, description="固定随机种子，便于复现")):
    """跨源实验：从原子碎片库抽一套兼容组合（不写数据库、不进生产随机池）。"""
    try:
        combo = atomic_pilot.sample_combo(seed)
    except atomic_pilot.AtomicPilotUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    return AtomicRecipeResponse(**combo)


class ComposerRunRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    workflow_path: str = ""
    workflow_content: str | None = None
    orientation: str = "portrait"
    quality: str = "4K"
    aspect_ratio: str = ""
    output_subfolder: str = ""
    idempotency_key: str = ""


@router.post("/composer/run")
def composer_run(
    req: ComposerRunRequest,
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
):
    """组合提示词直接跑图（不保存到提示词库）"""
    key = request_key(x_idempotency_key, req.idempotency_key)
    existing = find_job_by_idempotency(key, SCOPE_COMPOSER_SINGLE) if key else None
    if existing is not None:
        return {
            "success": True, "job_id": existing["id"], "result": {}, "idempotent": True,
        }

    workflow_path = req.workflow_path or ""
    if not workflow_path:
        raise HTTPException(400, "缺少工作流路径")

    try:
        expand_subfolder(
            req.output_subfolder, workflow_path=workflow_path, job_id=0,
            quality=req.quality, orientation=req.orientation,
        )
        api_wf = load_workflow(workflow_path, req.workflow_content)
        # 与 comfyui.py 的各出图入口保持一致：【类型】标题只用于组合器里给人看，
        # 不能作为正文注入 CLIP（否则会多出 8 段中文标签文本）。
        prompt_data = {
            "prompt": strip_headers(req.prompt),
            "negative_prompt": req.negative_prompt,
            "orientation": req.orientation,
            "quality": req.quality,
            "aspect_ratio": req.aspect_ratio,
        }
        inject_prompt(api_wf, prompt_data)
        seed_effective = int(prompt_data["seed_effective"])

        import json
        items = [{
            "prompt_id": 0,
            "seed": seed_effective,
            "prompt_preview": (req.prompt or "")[:120],
            "prompt_params": json.dumps({
                "prompt": req.prompt,
                "negative_prompt": req.negative_prompt,
                "aspect_ratio": req.aspect_ratio,
                "source": "composer",
                "seed": seed_effective,
                "compiled": prompt_data.get("compiled"),
            }, ensure_ascii=False),
        }]
        extra = build_job_extra(
            workflow_path, req.workflow_content, req.output_subfolder,
            aspect_ratio=req.aspect_ratio,
        )
        if key:
            extra.update({"idempotency_key": key, "idempotency_scope": SCOPE_COMPOSER_SINGLE})
        outcome = submit_generation(
            job_type="single", title="组合创作", items=items,
            workflow_path=workflow_path, workflow_content=req.workflow_content,
            orientation=req.orientation, quality=req.quality,
            aspect_ratio=req.aspect_ratio, output_subfolder=req.output_subfolder,
            prepare=lambda _index, _ctx: api_wf, extra=extra,
        )
        return {
            "success": True, "job_id": outcome["job_id"],
            "result": outcome["result"], "seed": seed_effective,
        }
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    except OutputLocationError as e:
        raise HTTPException(400, str(e))
    except RatioNotSupported:
        raise
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"{type(e).__name__}: {e}")


class BatchRandomRunRequest(BaseModel):
    count: int = 1  # 随机组数（1~10）
    workflow_path: str = ""
    workflow_content: str | None = None
    orientation: str = "portrait"
    quality: str = "4K"
    aspect_ratio: str = ""
    negative_prompt: str = ""
    search: str = ""  # 碎片筛选条件
    category_id: int | None = None
    tag_ids: str | None = None
    fixed_fragments: dict | None = None  # {类型名: 碎片内容, ...} 固定碎片，不参与随机
    composed_prompts: list[str] | None = None  # 前端预览确认后的组合文本；有则按原样提交
    output_subfolder: str = ""
    idempotency_key: str = ""


@router.post("/composer/batch_random_run")
def composer_batch_random_run(
    req: BatchRandomRunRequest,
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
):
    """批量随机组合碎片并跑图"""
    idem_key = request_key(x_idempotency_key, req.idempotency_key)
    workflow_path = req.workflow_path or ""
    if not workflow_path:
        raise HTTPException(400, "缺少工作流路径")
    count = max(1, min(req.count, 10))  # 限制 1~10

    try:
        expand_subfolder(
            req.output_subfolder, workflow_path=workflow_path, job_id=0,
            quality=req.quality, orientation=req.orientation,
        )
        existing = find_job_by_idempotency(idem_key, SCOPE_COMPOSER_BATCH) if idem_key else None
        if existing is not None:
            return {
                "success": True, "job_id": existing["id"], "results": [],
                "idempotent": True, "async": True, "queued": 0, "total": existing["total"],
            }
        # 获取碎片数据
        grouped = _get_fragment_data(req.search, req.category_id, req.tag_ids)

        # 检查每个类型是否有碎片（仅后端随机时需要；前端已给组合文本则跳过）
        provided = [p.strip() for p in (req.composed_prompts or []) if p and p.strip()][:count]
        if not provided:
            for ft in FRAGMENT_TYPES:
                frags = grouped.get(ft, [])
                if not frags:
                    raise HTTPException(400, f"碎片类型「{ft}」没有可用碎片，请先添加")

        # 生成组合：前端预览确认过的直接按原样提交；否则后端随机
        fixed = req.fixed_fragments or {}
        job_items = []
        if provided:
            for composed_prompt in provided:
                task_seed = random.randint(0, 2**32 - 1)
                job_items.append({
                    "prompt_id": 0,
                    "seed": task_seed,
                    "prompt_preview": composed_prompt[:120],
                    "prompt_params": json.dumps({
                        "prompt": composed_prompt,
                        "negative_prompt": req.negative_prompt,
                        "source": "composer_random",
                        "selection": {},
                        "seed": task_seed,
                        "fixed_types": list(fixed.keys()),
                    }, ensure_ascii=False),
                })
        else:
            for i in range(count):
                # 从每个类型中随机选一个（固定类型直接用固定内容）
                selection = {}
                composed_parts = []
                for ft in FRAGMENT_TYPES:
                    if ft in fixed and fixed[ft]:
                        # 固定类型：直接使用固定内容
                        selection[ft] = fixed[ft]
                        composed_parts.append(f"【{ft}】\n{fixed[ft]}")
                    else:
                        # 随机类型：从碎片池中随机选
                        frags = grouped[ft]
                        pick = frags[random.randint(0, len(frags) - 1)]
                        selection[ft] = pick["content"]
                        composed_parts.append(f"【{ft}】\n{pick['content']}")

                composed_prompt = "\n\n".join(composed_parts)
                # 每个任务独立随机种子，避免批量时所有图用同一个种子
                task_seed = random.randint(0, 2**32 - 1)

                job_items.append({
                    "prompt_id": 0,
                    "seed": task_seed,
                    "prompt_preview": composed_prompt[:120],
                    "prompt_params": json.dumps({
                        "prompt": composed_prompt,
                        "negative_prompt": req.negative_prompt,
                        "source": "composer_random",
                        "selection": selection,
                        "seed": task_seed,
                        "fixed_types": list(fixed.keys()),
                    }, ensure_ascii=False),
                })

        # 创建任务；真正的 push 交给后台提交线程
        try:
            api_wf = load_workflow(workflow_path, req.workflow_content)
        except Exception as e:
            raise HTTPException(400, f"工作流加载失败: {e}")
        # 批量任务在入队时就编译一次，prompt_params 里留下实际提交的正/负向；
        # 后台 prepare 里的 inject_prompt 会再编译一次（幂等），不会改变结果。
        negative_effective = bool(detect_workflow_caps(api_wf).get("negative_effective"))
        for item in job_items:
            params = json.loads(item["prompt_params"])
            compiled = compile_prompt(
                strip_headers(params.get("prompt") or ""),
                params.get("negative_prompt") or "",
                negative_effective=negative_effective,
            )
            params["compiled"] = compiled.as_dict()
            item["prompt_params"] = json.dumps(params, ensure_ascii=False)
            item["status"] = "pending"
            item["submit_state"] = "queued"

        extra = build_job_extra(workflow_path, req.workflow_content, req.output_subfolder)
        if idem_key:
            extra["idempotency_key"] = idem_key
            extra["idempotency_scope"] = SCOPE_COMPOSER_BATCH
        def prepare(index: int, _ctx) -> dict:
            item = job_items[index]
            api_wf = load_workflow(workflow_path, req.workflow_content)
            task_seed = resolve_seed(item.get("seed"))
            prompt_data = {
                # 同一入口同样去掉【类型】标题；prompt_params 里仍保留原文
                "prompt": strip_headers(json.loads(item["prompt_params"])["prompt"]),
                "negative_prompt": req.negative_prompt,
                "seed": task_seed,
                "orientation": req.orientation,
                "quality": req.quality,
                "aspect_ratio": req.aspect_ratio,
            }
            inject_prompt(api_wf, prompt_data)
            return api_wf

        outcome = submit_generation(
            job_type="batch" if len(job_items) > 1 else "single",
            title=f"批量随机组合 ({len(job_items)} 组)",
            items=job_items,
            workflow_path=workflow_path, workflow_content=req.workflow_content,
            orientation=req.orientation, quality=req.quality,
            aspect_ratio=req.aspect_ratio, output_subfolder=req.output_subfolder,
            prepare=prepare, mode="queue",
            indexes=list(range(len(job_items))), extra=extra,
        )

        return {
            "success": True, "job_id": outcome["job_id"], "results": [],
            "total": len(job_items), "submitted": 0, "queued": len(job_items),
            "async": True,
        }
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    except OutputLocationError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"{type(e).__name__}: {e}")
