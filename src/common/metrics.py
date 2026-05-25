"""Metrics collection and reporting."""

import time
from collections import defaultdict
from typing import Dict, List, Optional
from threading import Lock


class MetricsCollector:
    """Thread-safe metrics collector with optional counter range validation.

    When `max_counter` is set, the collector validates that no counter exceeds
    the specified limit. This guards against downstream metrics systems that
    reject large integer values (e.g., Prometheus int64 overflow).

    Args:
        max_counter: Optional maximum allowed counter value. When set,
            `increment()` raises a `ValueError` if the counter would exceed
            this limit, and `snapshot()` includes a `"warnings"` key listing
            any counters that have reached the limit.
    """

    def __init__(self, max_counter: Optional[int] = None):
        self._lock = Lock()
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._timers: Dict[str, float] = {}
        self._max_counter = max_counter
        self._counter_warnings: Dict[str, bool] = defaultdict(bool)

    def increment(self, metric: str, value: int = 1) -> None:
        """Increment a counter metric.

        Raises:
            ValueError: If `max_counter` is configured and incrementing would
                push the counter above the limit.
        """
        with self._lock:
            new_value = self._counters[metric] + value
            if self._max_counter is not None and new_value > self._max_counter:
                self._counter_warnings[metric] = True
                raise ValueError(
                    f"Counter '{metric}' would exceed max limit of {self._max_counter} "
                    f"(current: {self._counters[metric]}, increment: {value})"
                )
            self._counters[metric] = new_value

    def gauge(self, metric: str, value: float) -> None:
        with self._lock:
            self._gauges[metric] = value

    def observe(self, metric: str, value: float) -> None:
        with self._lock:
            self._histograms[metric].append(value)

    def start_timer(self, metric: str) -> None:
        with self._lock:
            self._timers[metric] = time.time()

    def stop_timer(self, metric: str) -> float:
        with self._lock:
            if metric in self._timers:
                duration = time.time() - self._timers.pop(metric)
                self.observe(metric, duration)
                return duration
        return 0.0

    def snapshot(self) -> Dict:
        with self._lock:
            result: Dict = {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {k: {"count": len(v), "sum": sum(v), "avg": sum(v) / len(v) if v else 0}
                               for k, v in self._histograms.items()},
            }
            if self._max_counter is not None:
                warnings = [k for k, v in self._counter_warnings.items() if v]
                if warnings:
                    result["warnings"] = {
                        "counter_limit_reached": warnings,
                        "max_counter": self._max_counter,
                    }
            return result


metrics = MetricsCollector()
