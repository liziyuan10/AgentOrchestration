"""Run scheduler tests directly (bypasses import chain issues on Windows)."""
import sys
import time
import asyncio

sys.path.insert(0, "D:/AI/AgentOrchestration")

import importlib.util
spec = importlib.util.spec_from_file_location(
    "scheduler", "D:/AI/AgentOrchestration/src/orchestrator/scheduler.py"
)
sched = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sched)

TaskScheduler = sched.TaskScheduler

passed = 0
failed = 0

def test(name, ok):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name}")

print("=== Scheduler Reclaim Tests ===\n")

s = TaskScheduler()

# Test reclaim returns 0 when no in-flight jobs
test("reclaim empty returns 0", s.reclaim_abandoned() == 0)

# Test reclaim with timeout=0 reclaims expired job
short = TaskScheduler(reclaim_timeout=0)
short.enqueue({"type": "test"})
task = asyncio.run(short.dequeue())
test("dequeued task has _reserved_at", "_reserved_at" in task)
time.sleep(0.001)
reclaimed = short.reclaim_abandoned()
test("reclaim returns 1 for expired job", reclaimed == 1)

# Test reclaimed job is re-enqueued
short2 = TaskScheduler(reclaim_timeout=0)
short2.enqueue({"type": "test2"})
asyncio.run(short2.dequeue())
time.sleep(0.001)
short2.reclaim_abandoned()
retask = asyncio.run(short2.dequeue())
test("reclaimed job is available again", retask is not None)
test("reclaimed job has _reclaim_count=1", retask and retask["_reclaim_count"] == 1)

# Test completed job is not reclaimed
short3 = TaskScheduler(reclaim_timeout=0)
short3.enqueue({"type": "test3"})
t3 = asyncio.run(short3.dequeue())
short3.complete(t3["id"])
time.sleep(0.001)
test("completed job not reclaimed", short3.reclaim_abandoned() == 0)

print(f"\n=== Results: {passed} passed, {failed} failed ===")
sys.exit(0 if failed == 0 else 1)
