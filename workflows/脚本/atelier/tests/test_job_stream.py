"""任务事件流：单调序号 + 断线后按 since 重放。"""
import queue

import pytest


def test_publish_assigns_monotonic_seq_and_replays_since(api):
    from app.services import job_state

    live = job_state.subscribe()
    replay = None
    try:
        job_state.publish({"id": 1, "status": "running"})
        first = live.get(timeout=1)
        job_state.publish({"id": 1, "status": "done"})
        second = live.get(timeout=1)

        assert second["seq"] > first["seq"]

        replay = job_state.subscribe(since=first["seq"])
        replayed = replay.get(timeout=1)
        assert replayed["job"]["status"] == "done"
        assert replayed["seq"] == second["seq"]
    finally:
        job_state.unsubscribe(live)
        if replay is not None:
            job_state.unsubscribe(replay)


def test_subscribe_without_since_only_receives_new_events(api):
    from app.services import job_state

    q = job_state.subscribe()
    try:
        with pytest.raises(queue.Empty):
            q.get_nowait()
    finally:
        job_state.unsubscribe(q)
