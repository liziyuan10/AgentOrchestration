"""Task Scheduler — Priority-based task queuing and dispatch with catch-up protection."""

import asyncio
import heapq
import logging
import time
from typing import Any, Dict, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class PriorityQueue:
    def __init__(self):
        self._queue = []
        self._counter = 0

    def push(self, item: Any, priority: int = 0) -> None:
        heapq.heappush(self._queue, (-priority, self._counter, item))
        self._counter += 1

    def pop(self) -> Optional[Any]:
        if self._queue:
            return heapq.heappop(self._queue)[2]
        return None

    def peek(self) -> Optional[Any]:
        if self._queue:
            return self._queue[0][2]
        return None

    def __len__(self) -> int:
        return len(self._queue)


class TaskScheduler:
    def __init__(self, retention_window: float = 86400.0):  # 24h default
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, tuple] = {}  # task_id -> (timestamp, task_dict)
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3
        self._retention_window = retention_window
        self._last_active_at = time.time()
        # Audit counters
        self._audit_catch_up_deferred = 0
        self._audit_catch_up_stale = 0

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["_scheduled_at"] = time.time()
        self._scheduled[task_id] = (time.time() + delay, task)
        return task_id

    def catch_up_audit(self) -> Dict[str, int]:
        """Return catch-up audit counters for diagnostics."""
        return {
            "deferred": self._audit_catch_up_deferred,
            "stale": self._audit_catch_up_stale,
        }

    async def dequeue(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        now = time.time()

        # --- Catch-up protection ---
        inactivity = now - self._last_active_at
        if inactivity >= self._retention_window:
            self._audit_catch_up_deferred += 1

            deferred_scheduled = 0
            expired = [(tid, t[0], t[1]) for tid, t in self._scheduled.items() if t[0] <= now]
            for tid, _, task in expired:
                self._scheduled.pop(tid, None)
                self._audit_catch_up_stale += 1
                deferred_scheduled += 1

            if deferred_scheduled > 0 or self._audit_catch_up_deferred == 1:
                logger.warning(
                    "catch-up deferred: inactivity=%.1fs, retention=%.1f, stale=%d",
                    inactivity, self._retention_window, deferred_scheduled,
                )

            # Reset to avoid repeated logging
            self._last_active_at = now
            return None
        # --- End catch-up protection ---

        expired = [(tid, t[0], t[1]) for tid, t in self._scheduled.items() if t[0] <= now]
        for tid, _, task in expired:
            self._scheduled.pop(tid, None)
            if task:
                self.enqueue(task, queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                self._in_flight[task["id"]] = task
                self._last_active_at = now
                return task
        return None

    def complete(self, task_id: str) -> bool:
        return self._in_flight.pop(task_id, None) is not None

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False
