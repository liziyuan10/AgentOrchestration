"""Tests for TaskScheduler — includes catch-up protection tests."""

import sys, os
# Import scheduler directly to bypass __init__.py import chain on Windows
_src = os.path.join(os.path.dirname(__file__), "..", "src")
_sched_path = os.path.join(_src, "orchestrator", "scheduler.py")
import importlib.util
_spec = importlib.util.spec_from_file_location("_scheduler_mod", _sched_path, submodule_search_locations=[])
_scheduler_mod = importlib.util.module_from_spec(_spec)
sys.modules["_scheduler_mod"] = _scheduler_mod
_spec.loader.exec_module(_scheduler_mod)
TaskScheduler = _scheduler_mod.TaskScheduler


class TestTaskScheduler:
    def setup_method(self):
        self.scheduler = TaskScheduler()

    def test_enqueue_task(self):
        task_id = self.scheduler.enqueue({"type": "test", "payload": {}})
        assert task_id is not None

    def test_dequeue_task(self):
        self.scheduler.enqueue({"type": "test", "payload": {"data": 1}})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert task["type"] == "test"

    def test_enqueue_multiple_priorities(self):
        self.scheduler.enqueue({"type": "low"}, priority=1)
        self.scheduler.enqueue({"type": "high"}, priority=10)
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task["type"] == "high"

    def test_complete_task(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.complete(task["id"])

    def test_fail_task_with_retry(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.fail(task["id"])

    # ---- Catch-up protection tests ----

    def test_catch_up_normal_dequeue_succeeds(self):
        """Normal dequeue within retention window works unchanged."""
        import asyncio
        self.scheduler.enqueue({"type": "normal"})
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert task["type"] == "normal"
        audit = self.scheduler.catch_up_audit()
        assert audit["deferred"] == 0

    def test_catch_up_deferred_when_beyond_retention(self):
        """Dequeue returns None when inactivity exceeds retention window."""
        import time, asyncio
        short_window = TaskScheduler(retention_window=0.001)
        short_window._last_active_at = time.time() - 10
        short_window.enqueue({"type": "stale"})
        task = asyncio.run(short_window.dequeue())
        assert task is None, "Should refuse dequeue past retention window"
        audit = short_window.catch_up_audit()
        assert audit["deferred"] == 1

    def test_catch_up_stale_tasks_audited(self):
        """Scheduled tasks that expired during downtime are counted as stale."""
        import time, asyncio
        short_window = TaskScheduler(retention_window=0.001)
        short_window._last_active_at = time.time() - 10
        short_window.schedule({"type": "past"}, delay=-9999)
        task = asyncio.run(short_window.dequeue())
        assert task is None
        audit = short_window.catch_up_audit()
        assert audit["stale"] > 0, "Scheduled past tasks should be counted as stale"

    def test_catch_up_resumes_after_recovery(self):
        """After recovery (reset _last_active_at), dequeue works again."""
        import time, asyncio
        short_window = TaskScheduler(retention_window=0.001)
        short_window._last_active_at = time.time() - 10
        short_window.enqueue({"type": "first"})
        first = asyncio.run(short_window.dequeue())
        assert first is None

        recovered = TaskScheduler(retention_window=3600.0)
        recovered._last_active_at = time.time()
        recovered.enqueue({"type": "recovered"})
        r = asyncio.run(recovered.dequeue())
        assert r is not None
        assert r["type"] == "recovered"

    def test_catch_up_configurable_retention_window(self):
        """retention_window parameter is respected."""
        import asyncio, time
        long_window = TaskScheduler(retention_window=3600.0)
        long_window.enqueue({"type": "ok"})
        task = asyncio.run(long_window.dequeue())
        assert task is not None
