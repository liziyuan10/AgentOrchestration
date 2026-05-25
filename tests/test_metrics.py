import pytest
from src.common.metrics import MetricsCollector


class TestMetricsCollector:
    def setup_method(self):
        self.metrics = MetricsCollector()

    def test_increment(self):
        self.metrics.increment("requests.total")
        self.metrics.increment("requests.total")
        snapshot = self.metrics.snapshot()
        assert snapshot["counters"]["requests.total"] == 2

    def test_gauge(self):
        self.metrics.gauge("memory.usage", 85.5)
        snapshot = self.metrics.snapshot()
        assert snapshot["gauges"]["memory.usage"] == 85.5

    def test_observe(self):
        self.metrics.observe("response.time", 0.5)
        self.metrics.observe("response.time", 1.5)
        snapshot = self.metrics.snapshot()
        assert snapshot["histograms"]["response.time"]["count"] == 2
        assert snapshot["histograms"]["response.time"]["avg"] == 1.0

    def test_timer(self):
        self.metrics.start_timer("operation")
        import time
        time.sleep(0.01)
        duration = self.metrics.stop_timer("operation")
        assert duration > 0.005

    def test_max_counter_allows_normal_increments(self):
        m = MetricsCollector(max_counter=100)
        m.increment("requests", 50)
        m.increment("requests", 30)
        snapshot = m.snapshot()
        assert snapshot["counters"]["requests"] == 80
        assert "warnings" not in snapshot

    def test_max_counter_raises_on_exceed(self):
        m = MetricsCollector(max_counter=100)
        m.increment("requests", 90)
        with pytest.raises(ValueError, match="would exceed max limit"):
            m.increment("requests", 20)

    def test_max_counter_records_warning_in_snapshot(self):
        m = MetricsCollector(max_counter=100)
        with pytest.raises(ValueError):
            m.increment("requests", 200)
        snapshot = m.snapshot()
        assert "warnings" in snapshot
        assert "requests" in snapshot["warnings"]["counter_limit_reached"]
        assert snapshot["warnings"]["max_counter"] == 100

    def test_max_counter_none_by_default(self):
        MetricsCollector()

    def test_multiple_counters_independent_limits(self):
        m = MetricsCollector(max_counter=100)
        m.increment("a", 50)
        with pytest.raises(ValueError):
            m.increment("b", 150)
        m.increment("a", 50)  # This is fine: a=100
        snapshot = m.snapshot()
        assert snapshot["counters"]["a"] == 100
        assert "warnings" in snapshot
        assert "b" in snapshot["warnings"]["counter_limit_reached"]
        assert "a" not in snapshot["warnings"]["counter_limit_reached"]
