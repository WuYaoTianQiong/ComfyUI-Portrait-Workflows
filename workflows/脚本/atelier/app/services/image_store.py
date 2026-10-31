"""gen_history 的唯一写入入口：把「部分唯一索引 + ON CONFLICT」的方言细节收在一处。

gen_history 的唯一约束是 `(filename, subfolder, img_type) WHERE is_deleted = 0`
（部分索引），所以每次 upsert 都必须满足两个条件：

1. `conflict_target` 与索引列完全一致；
2. `conflict_where` 必须是 **SQL 字面量** —— 写成 peewee 表达式会生成带引号的
   `"is_deleted" = 0`，SQLite 不认，抛出
   "ON CONFLICT clause does not match any PRIMARY KEY or UNIQUE constraint"。

这个坑已经踩过两次：先是 v4.1 用了 3.x 的 `on_conflict_do_update(set_=...)` 抛
AttributeError，修好写入后又是 conflict_where 不匹配。两次都被外层的
`except Exception: pass` 吞掉，表现为"同步永远写不进库，画廊永远没有新图"。

因此统一收到这里：调用方只描述"插什么、冲突时更新什么"，不用再记方言细节。
"""

from __future__ import annotations

from peewee import SQL

from app.models import Image

# 与 models._migrate_genhistory_unique_constraint 创建的部分唯一索引一一对应
LIVE_ONLY_FILTER = SQL("is_deleted=0")
CONFLICT_TARGET = (Image.filename, Image.subfolder, Image.img_type)


def upsert_image(
    insert_values: dict,
    update_values: dict,
    only_when_job_null: bool = False,
) -> None:
    """按 (filename, subfolder, img_type) 插入或更新一条出图记录。

    only_when_job_null=True 时只更新 `job_id IS NULL` 的行：已被任务写入的行带着
    `source=composer/faceswap` 这类富参数（含组合来源、节点映射、种子），同步只能从
    ComfyUI history 反推出较弱的数据，覆盖即丢信息。
    """
    conflict_kwargs = {
        "conflict_target": list(CONFLICT_TARGET),
        "conflict_where": LIVE_ONLY_FILTER,
        "update": update_values,
    }
    if only_when_job_null:
        conflict_kwargs["where"] = Image.job_id.is_null()
    Image.insert(**insert_values).on_conflict(**conflict_kwargs).execute()
