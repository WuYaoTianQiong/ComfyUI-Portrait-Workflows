"""遍历合成台工作流，算出「每个工作流在 1/2/3/4 图下哪些角色组合可提交」。

产物 `studio_matrix_catalog.json` 是 `tools/studio_matrix.py` 的输入：
组合清单必须与后端同一套可裁剪判定（`_resolve_trim_plan`）算出，
否则实测会跑一堆本来就会 400 的组合。

用法（在项目根）：
    python tools/studio_matrix_catalog.py
"""
from __future__ import annotations

import itertools
import json
import sys
from collections import Counter
from pathlib import Path

# 脚本在 tools/ 下，项目根（app/ 所在）要手动塞进 sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers.reference_library import (  # noqa: E402
    SLOT_ROLES,
    _resolve_trim_plan,
    _role_nodes,
    _role_support_error,
)
from app.services.workflow_catalog import list_valid_workflows
from app.services.workflow_parser import find_loadimage_nodes, load_workflow

all_items = list_valid_workflows(scope="all")
studio_items = list_valid_workflows(scope="studio")

rows = []
for item in studio_items:
    path = Path(item["path"])
    api_wf = load_workflow(str(path))
    role_nodes = _role_nodes(api_wf)
    input_count = len(find_loadimage_nodes(api_wf))
    combos = []
    for size in range(1, len(SLOT_ROLES) + 1):
        for combo in itertools.combinations(SLOT_ROLES, size):
            filled = {role: role in combo for role in SLOT_ROLES}
            reason = _role_support_error(role_nodes, filled, path.name)
            if not reason:
                _, _, reason = _resolve_trim_plan(api_wf, filled)
            if not reason:
                combos.append("+".join(combo))
    rows.append(
        {
            "name": path.name,
            "input_count": input_count,
            "roles": [role for role in SLOT_ROLES if role in role_nodes],
            "submittable": combos,
        }
    )

report = {
    "all_count": len(all_items),
    "all_sources": dict(Counter(item.get("source") for item in all_items)),
    "all_slots": dict(Counter(str(item.get("image_slots")) for item in all_items)),
    "studio_count": len(studio_items),
    "studio_ready": sum(1 for item in all_items if item.get("studio_ready")),
    "studio": rows,
    "total_submittable_combos": sum(len(row["submittable"]) for row in rows),
}
out = Path(__file__).resolve().parent / "studio_matrix_catalog.json"
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"all={report['all_count']} studio={report['studio_count']} combos={report['total_submittable_combos']}")
