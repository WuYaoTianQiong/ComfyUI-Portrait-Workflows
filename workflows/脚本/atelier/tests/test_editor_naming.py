"""派生文件名（拷进 ComfyUI input 目录的那批）的前缀回归锁。

这些名字不是"随便起的临时名"：它们是注入给 LoadImage 的图名，ComfyUI 的缓存键
包含文件名，所以既有「同一素材必须得到同一个名字」的稳定性要求，也有
「一眼能看出是 atelier 生成的」的命名要求（历史遗留的老前缀 `pb_` 已废弃）。
"""
from app.routers.editor import _dest_name, output_prefix


def test_dest_name_has_atelier_prefix():
    name = _dest_name({"path": r"F:\pics\A.png", "name": "A.png"})
    assert name.startswith("atelier_fs_")
    assert name.endswith("_A.png")


def test_dest_name_is_stable_for_same_source():
    """同一路径（大小写差异不算不同素材）必须得到同一个名字，否则 input 目录会被刷爆。"""
    first = _dest_name({"path": r"F:\pics\A.png", "name": "A.png"})
    second = _dest_name({"path": r"f:\PICS\a.png", "name": "A.png"})
    assert first == second


def test_dest_name_differs_for_different_source():
    first = _dest_name({"path": r"F:\pics\A.png", "name": "A.png"})
    second = _dest_name({"path": r"F:\pics\B.png", "name": "B.png"})
    assert first != second


def test_output_prefix_keeps_label_readable():
    assert output_prefix(7, ["目标A", "参考B"]) == "fs7_目标A_参考B"
    assert output_prefix(7, []) == "fs7"
    # 标签截断：文件名过长会撞 Windows 260 字符路径上限
    assert len(output_prefix(1, ["x" * 80])) == len("fs1_") + 24
