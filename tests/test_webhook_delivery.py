"""Tests for WebhookDeliveryState — endpoint state, delivery verification, and idempotency."""

import sys, os, importlib.util
_src = os.path.join(os.path.dirname(__file__), "..", "src")
_dspath = os.path.join(_src, "webhook", "delivery_state.py")
_spec = importlib.util.spec_from_file_location("_webhook_mod", _dspath, submodule_search_locations=[])
_webhook_mod = importlib.util.module_from_spec(_spec)
sys.modules["_webhook_mod"] = _webhook_mod
_spec.loader.exec_module(_webhook_mod)
WebhookDeliveryState = _webhook_mod.WebhookDeliveryState
EndpointStatus = _webhook_mod.EndpointStatus


class TestWebhookDeliveryState:
    def setup_method(self):
        self.state = WebhookDeliveryState()

    def test_register_endpoint(self):
        ep = self.state.register_endpoint("ep-1", "ws-1", "https://example.com/hook")
        assert ep["endpoint_id"] == "ep-1"
        assert ep["status"] == "active"

    def test_get_endpoint(self):
        self.state.register_endpoint("ep-1", "ws-1", "https://example.com/hook")
        ep = self.state.get_endpoint("ep-1")
        assert ep is not None
        assert ep["url"] == "https://example.com/hook"

    def test_get_nonexistent_endpoint(self):
        assert self.state.get_endpoint("nonexistent") is None

    def test_update_endpoint_status(self):
        self.state.register_endpoint("ep-1", "ws-1", "https://example.com/hook")
        assert self.state.update_endpoint_status("ep-1", EndpointStatus.DISABLED)
        ep = self.state.get_endpoint("ep-1")
        assert ep["status"] == "disabled"

    def test_list_workspace_endpoints(self):
        self.state.register_endpoint("ep-1", "ws-1", "https://a.com")
        self.state.register_endpoint("ep-2", "ws-1", "https://b.com")
        self.state.register_endpoint("ep-3", "ws-2", "https://c.com")
        assert len(self.state.list_workspace_endpoints("ws-1")) == 2
        assert len(self.state.list_workspace_endpoints("ws-2")) == 1

    def test_active_endpoints_exclude_disabled(self):
        self.state.register_endpoint("ep-1", "ws-1", "https://a.com")
        self.state.register_endpoint("ep-2", "ws-1", "https://b.com")
        self.state.update_endpoint_status("ep-2", EndpointStatus.DISABLED)
        active = self.state.list_active_endpoints("ws-1")
        assert len(active) == 1
        assert active[0]["endpoint_id"] == "ep-1"

    def test_active_endpoints_exclude_expired(self):
        self.state.register_endpoint("ep-1", "ws-1", "https://a.com", ttl=-1)
        active = self.state.list_active_endpoints("ws-1")
        assert len(active) == 0

    def test_validate_active_endpoint_returns_none(self):
        self.state.register_endpoint("ep-1", "ws-1", "https://a.com")
        assert self.state.validate_endpoint("ep-1") is None

    def test_validate_disabled_endpoint_returns_error(self):
        self.state.register_endpoint("ep-1", "ws-1", "https://a.com")
        self.state.update_endpoint_status("ep-1", EndpointStatus.DISABLED)
        err = self.state.validate_endpoint("ep-1")
        assert err is not None
        assert "disabled" in err

    def test_validate_revoked_endpoint_returns_error(self):
        self.state.register_endpoint("ep-1", "ws-1", "https://a.com")
        self.state.update_endpoint_status("ep-1", EndpointStatus.REVOKED)
        err = self.state.validate_endpoint("ep-1")
        assert err is not None
        assert "revoked" in err

    def test_validate_nonexistent_endpoint(self):
        err = self.state.validate_endpoint("nonexistent")
        assert err is not None
        assert "not found" in err

    def test_validate_expired_endpoint(self):
        self.state.register_endpoint("ep-1", "ws-1", "https://a.com", ttl=-1)
        err = self.state.validate_endpoint("ep-1")
        assert err is not None
        assert "expired" in err

    def test_create_delivery(self):
        self.state.register_endpoint("ep-1", "ws-1", "https://a.com")
        record = self.state.create_delivery("evt-1", "ep-1", "ws-1")
        assert record.event_id == "evt-1"
        assert record.status.value == "pending"

    def test_complete_delivery(self):
        self.state.register_endpoint("ep-1", "ws-1", "https://a.com")
        record = self.state.create_delivery("evt-1", "ep-1", "ws-1")
        self.state.attempt_delivery(record.delivery_id)
        assert self.state.complete_delivery(record.delivery_id)
        assert record.status.value == "delivered"

    def test_reject_delivery(self):
        self.state.register_endpoint("ep-1", "ws-1", "https://a.com")
        record = self.state.create_delivery("evt-1", "ep-1", "ws-1")
        assert self.state.reject_delivery(record.delivery_id, "endpoint disabled")
        assert record.status.value == "rejected"

    def test_idempotent_delivery_skip(self):
        self.state.register_endpoint("ep-1", "ws-1", "https://a.com")
        r1 = self.state.create_delivery("evt-1", "ep-1", "ws-1")
        self.state.attempt_delivery(r1.delivery_id)
        self.state.complete_delivery(r1.delivery_id)
        r2 = self.state.create_delivery("evt-1", "ep-1", "ws-1")
        assert r2.delivery_id == r1.delivery_id
        audit = self.state.audit()
        assert audit["idempotent_skips"] == 1

    def test_delivery_retry_exhausted(self):
        self.state.register_endpoint("ep-1", "ws-1", "https://a.com")
        record = self.state.create_delivery("evt-1", "ep-1", "ws-1")
        for _ in range(3):
            self.state.attempt_delivery(record.delivery_id)
            self.state.fail_delivery(record.delivery_id, "timeout", max_retries=3)
        self.state.attempt_delivery(record.delivery_id)
        self.state.fail_delivery(record.delivery_id, "final", max_retries=3)
        assert record.status.value == "failed"

    def test_lease_renewal(self):
        self.state.register_endpoint("ep-1", "ws-1", "https://a.com", ttl=1)
        assert self.state.renew_lease("ep-1", extension=3600)
        assert self.state.renew_lease_count("ep-1") == 1
        assert self.state.validate_endpoint("ep-1") is None

    def test_workspace_isolation(self):
        self.state.register_endpoint("ep-1", "ws-1", "https://a.com")
        self.state.register_endpoint("ep-2", "ws-2", "https://b.com")
        self.state.update_endpoint_status("ep-2", EndpointStatus.DISABLED)
        ws1_active = self.state.list_active_endpoints("ws-1")
        assert len(ws1_active) == 1
        assert ws1_active[0]["endpoint_id"] == "ep-1"

    def test_audit_counters(self):
        self.state.register_endpoint("ep-1", "ws-1", "https://a.com")
        self.state.register_endpoint("ep-2", "ws-1", "https://b.com")
        r1 = self.state.create_delivery("evt-1", "ep-1", "ws-1")
        self.state.attempt_delivery(r1.delivery_id)
        self.state.complete_delivery(r1.delivery_id)
        r2 = self.state.create_delivery("evt-2", "ep-2", "ws-1")
        self.state.reject_delivery(r2.delivery_id, "disabled")
        self.state.renew_lease("ep-1", 3600)
        a = self.state.audit()
        assert a["deliveries_completed"] == 1
        assert a["deliveries_rejected"] == 1
        assert a["lease_renewals"] == 1
        assert a["endpoints_registered"] == 2
