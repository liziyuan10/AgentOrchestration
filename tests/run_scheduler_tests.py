"""Standalone test runner for scheduler module - works on Windows without pytest resource module.

Loads scheduler.py directly by file path to bypass __init__.py import chain.
"""

import sys
import os
import importlib.util

test_dir = os.path.dirname(__file__)
src_dir = os.path.join(test_dir, "..", "src")

# Load scheduler.py directly, bypassing all __init__.py
scheduler_path = os.path.join(src_dir, "orchestrator", "scheduler.py")
spec = importlib.util.spec_from_file_location(
    "scheduler_direct", scheduler_path,
    submodule_search_locations=[],
)
scheduler_mod = importlib.util.module_from_spec(spec)
sys.modules["scheduler_direct"] = scheduler_mod
spec.loader.exec_module(scheduler_mod)
TaskScheduler = scheduler_mod.TaskScheduler


def test_enqueue_task():
    s = TaskScheduler()
    task_id = s.enqueue({"type": "test", "payload": {}})
    assert task_id is not None


def test_dequeue_task():
    import asyncio
    s = TaskScheduler()
    s.enqueue({"type": "test", "payload": {"data": 1}})
    task = asyncio.run(s.dequeue())
    assert task is not None
    assert task["type"] == "test"


def test_enqueue_multiple_priorities():
    import asyncio
    s = TaskScheduler()
    s.enqueue({"type": "low"}, priority=1)
    s.enqueue({"type": "high"}, priority=10)
    task = asyncio.run(s.dequeue())
    assert task["type"] == "high"


def test_complete_task():
    import asyncio
    s = TaskScheduler()
    s.enqueue({"type": "test"})
    task = asyncio.run(s.dequeue())
    assert s.complete(task["id"])


def test_fail_task_with_retry():
    import asyncio
    s = TaskScheduler()
    s.enqueue({"type": "test"})
    task = asyncio.run(s.dequeue())
    assert s.fail(task["id"])


def test_catch_up_normal_dequeue_succeeds():
    """Normal dequeue within retention window works unchanged."""
    import asyncio
    s = TaskScheduler()
    s.enqueue({"type": "normal"})
    task = asyncio.run(s.dequeue())
    assert task is not None
    assert task["type"] == "normal"
    audit = s.catch_up_audit()
    assert audit["deferred"] == 0


def test_catch_up_deferred_when_beyond_retention():
    """Dequeue returns None when inactivity exceeds retention window."""
    import time, asyncio
    s = TaskScheduler(retention_window=0.001)
    s._last_active_at = time.time() - 10
    s.enqueue({"type": "stale"})
    task = asyncio.run(s.dequeue())
    assert task is None, "Should refuse dequeue past retention window"
    audit = s.catch_up_audit()
    assert audit["deferred"] == 1


def test_catch_up_stale_tasks_audited():
    """Scheduled tasks that expired during downtime are counted as stale."""
    import time, asyncio
    s = TaskScheduler(retention_window=0.001)
    s._last_active_at = time.time() - 10
    s.schedule({"type": "past"}, delay=-9999)
    task = asyncio.run(s.dequeue())
    assert task is None
    audit = s.catch_up_audit()
    assert audit["stale"] > 0


def test_catch_up_resumes_after_recovery():
    """After recovery (reset _last_active_at), dequeue works again."""
    import time, asyncio
    s = TaskScheduler(retention_window=0.001)
    s._last_active_at = time.time() - 10
    s.enqueue({"type": "first"})
    first = asyncio.run(s.dequeue())
    assert first is None

    recovered = TaskScheduler(retention_window=3600.0)
    recovered._last_active_at = time.time()
    recovered.enqueue({"type": "recovered"})
    r = asyncio.run(recovered.dequeue())
    assert r is not None
    assert r["type"] == "recovered"


def test_catch_up_configurable_retention_window():
    """retention_window parameter is respected."""
    import asyncio, time
    s = TaskScheduler(retention_window=3600.0)
    s.enqueue({"type": "ok"})
    task = asyncio.run(s.dequeue())
    assert task is not None


if __name__ == "__main__":
    passed = 0
    failed = 0
    errors = []

    test_methods = [name for name in dir() if name.startswith("test") and callable(globals()[name])]

    print("=== Scheduler All Tests ===\n")
    for name in sorted(test_methods):
        try:
            fn = globals()[name]
            fn()
            print(f"  ✅ {name}")
            passed += 1
        except Exception as e:
            import traceback
            print(f"  ❌ {name}: {e}")
            traceback.print_exc()
            failed += 1
            errors.append(f"{name}: {e}")

    print(f"\n=== Results: {passed} passed, {failed} failed ===")
    if errors:
        print("\nError details:")
        for e in errors:
            print(f"  • {e}")
    sys.exit(0 if failed == 0 else 1)
