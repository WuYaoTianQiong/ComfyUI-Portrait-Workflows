"""旧路径 308 别名（`routers/legacy.py`）的回归锁。

别名只活一个版本，但它活着的时候必须真的能用：
- 状态码必须是 308（保留方法与请求体，浏览器会自动重发）；
- Location 必须带 `/api` 前缀并带上原查询串（漏了 `/api` 会跳到 SPA catch-all，
  变成"旧 URL 返回 index.html 200"，看起来没坏、实际什么都没发生）；
- 子路径（`/api/history/{id}`）要跟着一起重定向。
"""
import pytest

from app.routers.legacy import _ALIASES, get_hit_counts, reset_hit_counts


@pytest.fixture()
def no_follow(api):
    reset_hit_counts()
    return api


@pytest.mark.parametrize("old,new,_subtree", _ALIASES)
def test_alias_redirects_with_api_prefix(no_follow, old, new, _subtree):
    resp = no_follow.get(f"/api{old}?probe=1", follow_redirects=False)
    assert resp.status_code == 308, f"/api{old} 未返回 308"
    location = resp.headers["location"]
    assert location.startswith(f"/api{new}"), f"/api{old} 跳到了 {location}"
    assert location.endswith("?probe=1"), f"/api{old} 丢了查询串: {location}"


@pytest.mark.parametrize(
    "old,new", [(o, n) for o, n, subtree in _ALIASES if subtree]
)
def test_alias_redirects_subpaths(no_follow, old, new):
    resp = no_follow.get(f"/api{old}/42/detail?x=y", follow_redirects=False)
    assert resp.status_code == 308
    assert resp.headers["location"] == f"/api{new}/42/detail?x=y"


def test_alias_hits_are_counted(no_follow):
    no_follow.get("/api/status", follow_redirects=False)
    no_follow.get("/api/status", follow_redirects=False)
    hits = get_hit_counts()
    assert hits["/api/status"] == 2
