"""图片文件完整性巡检。

背景：`gen_history` 里"记录还在、文件没了"是常态（手动删图、ComfyUI 清 output、
换盘符没挂上）。过去的处理方式是列表读到元数据为空就硬删记录，结果一次路径
误判就能清掉整库（见 models.py 的墓碑注释）。这里改成可自愈的派生状态：

- 只写 `missing_since` 派生列，**绝不删记录、绝不改 is_deleted**
- 文件回来后自动清空 `missing_since`，标签/收藏/分类一个都不丢
- 分批扫描 + 每批一次批量 UPDATE，避免逐行写库长时间占着 WAL 写锁
- 只做路径存在性判断，不走 PIL 解码（那是缩略图和详情页的事）

调用方：`services.job_state.writer_loop`，启动后立即跑一次，之后低频重复。
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.models import Image
from app.services.thumbnail import _get_image_path

logger = logging.getLogger("atelier.integrity")

_DEFAULT_BATCH = 500


def scan_missing(batch: int = _DEFAULT_BATCH) -> dict:
    """巡检所有未删除记录的图片文件存在性。

    返回 {"checked": 检查数, "marked": 新标记为缺失, "cleared": 恢复数}。
    """
    checked = marked = cleared = 0
    now = datetime.now()
    mark_ids: list[int] = []
    clear_ids: list[int] = []
    last_id = 0

    while True:
        rows = list(
            Image.select(Image.id, Image.filename, Image.subfolder, Image.img_type, Image.missing_since)
            .where((Image.is_deleted == False) & (Image.id > last_id))
            .order_by(Image.id)
            .limit(batch)
        )
        if not rows:
            break

        for r in rows:
            last_id = r.id
            checked += 1
            exists = _get_image_path(
                r.filename or "", r.subfolder or "", r.img_type or "output"
            ) is not None
            if not exists and r.missing_since is None:
                mark_ids.append(r.id)
            elif exists and r.missing_since is not None:
                clear_ids.append(r.id)

        # 每批落库一次：整库一次事务会在几千行时把写锁占住好几百毫秒
        if mark_ids:
            Image.update(missing_since=now).where(Image.id.in_(mark_ids)).execute()
            marked += len(mark_ids)
            mark_ids = []
        if clear_ids:
            Image.update(missing_since=None).where(Image.id.in_(clear_ids)).execute()
            cleared += len(clear_ids)
            clear_ids = []

    return {"checked": checked, "marked": marked, "cleared": cleared}
