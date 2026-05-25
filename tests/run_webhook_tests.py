"""Standalone test runner for webhook delivery state module - works on Windows."""

import sys, os, importlib.util

test_dir = os.path.dirname(__file__)
src_dir = os.path.join(test_dir, "..", "src")

# Load delivery_state.py directly
dspath = os.path.join(src_dir, "webhook", "delivery_state.py")
spec = importlib.util.spec_from_file_location("webhook_direct", dspath, submodule_search_locations=[])
mod = importlib.util.module_from_spec(spec)
sys.modules["webhook_direct"] = mod
spec.loader.exec_module(mod)

WebhookDeliveryState = mod.WebhookDeliveryState
EndpointStatus = mod.EndpointStatus


def test_register_endpoint():
    s = WebhookDeliveryState()
    ep = s.register_endpoint("ep-1", "ws-1", "https://example.com/hook")
    assert ep["endpoint_id"] == "ep-1"
    assert ep["status"] == "active"


def test_get_endpoint():
    s = WebhookDeliveryState()
    s.register_endpoint("ep-1", "ws-1", "https://example.com/hook")
    ep = s.get_endpoint("ep-1")
    assert ep is not None
    assert ep["url"] == "https://example.com/hook"


def test_get_nonexistent_endpoint():
    s = WebhookDeliveryState()
    assert s.get_endpoint("nonexistent") is None


def test_update_endpoint_status():
    s = WebhookDeliveryState()
    s.register_endpoint("ep-1", "ws-1", "https://example.com/hook")
    assert s.update_endpoint_status("ep-1", EndpointStatus.DISABLED)
    ep = s.get_endpoint("ep-1")
    assert ep["status"] == "disabled"


def test_list_workspace_endpoints():
    s = WebhookDeliveryState()
    s.register_endpoint("ep-1", "ws-1", "https://a.com")
    s.register_endpoint("ep-2", "ws-1", "https://b.com")
    s.register_endpoint("ep-3", "ws-2", "https://c.com")
    assert len(s.list_workspace_endpoints("ws-1")) == 2
    assert len(s.list_workspace_endpoints("ws-2")) == 1


def test_active_endpoints_exclude_disabled():
    s = WebhookDeliveryState()
    s.register_endpoint("ep-1", "ws-1", "https://a.com")
    s.register_endpoint("ep-2", "ws-1", "https://b.com")
    s.update_endpoint_status("ep-2", EndpointStatus.DISABLED)
    active = s.list_active_endpoints("ws-1")
    assert len(active) == 1
    assert active[0]["endpoint_id"] == "ep-1"


def test_active_endpoints_exclude_expired():
    s = WebhookDeliveryState()
    s.register_endpoint("ep-1", "ws-1", "https://a.com", ttl=-1)  # expired immediately
    active = s.list_active_endpoints("ws-1")
    assert len(active) == 0


def test_validate_active_endpoint_returns_none():
    s = WebhookDeliveryState()
    s.register_endpoint("ep-1", "ws-1", "https://a.com")
    err = s.validate_endpoint("ep-1")
    assert err is None, "Active endpoint should be valid"


def test_validate_disabled_endpoint_returns_error():
    s = WebhookDeliveryState()
    s.register_endpoint("ep-1", "ws-1", "https://a.com")
    s.update_endpoint_status("ep-1", EndpointStatus.DISABLED)
    err = s.validate_endpoint("ep-1")
    assert err is not None
    assert "disabled" in err


def test_validate_revoked_endpoint_returns_error():
    s = WebhookDeliveryState()
    s.register_endpoint("ep-1", "ws-1", "https://a.com")
    s.update_endpoint_status("ep-1", EndpointStatus.REVOKED)
    err = s.validate_endpoint("ep-1")
    assert err is not None
    assert "revoked" in err


def test_validate_nonexistent_endpoint():
    s = WebhookDeliveryState()
    err = s.validate_endpoint("nonexistent")
    assert err is not None
    assert "not found" in err


def test_validate_expired_endpoint():
    s = WebhookDeliveryState()
    s.register_endpoint("ep-1", "ws-1", "https://a.com", ttl=-1)
    err = s.validate_endpoint("ep-1")
    assert err is not None
    assert "expired" in err


def test_create_delivery():
    s = WebhookDeliveryState()
    s.register_endpoint("ep-1", "ws-1", "https://a.com")
    record = s.create_delivery("evt-1", "ep-1", "ws-1")
    assert record.event_id == "evt-1"
    assert record.status.value == "pending"


def test_complete_delivery():
    s = WebhookDeliveryState()
    s.register_endpoint("ep-1", "ws-1", "https://a.com")
    record = s.create_delivery("evt-1", "ep-1", "ws-1")
    s.attempt_delivery(record.delivery_id)
    assert s.complete_delivery(record.delivery_id)
    assert record.status.value == "delivered"


def test_reject_delivery():
    s = WebhookDeliveryState()
    s.register_endpoint("ep-1", "ws-1", "https://a.com")
    record = s.create_delivery("evt-1", "ep-1", "ws-1")
    assert s.reject_delivery(record.delivery_id, "endpoint disabled")
    assert record.status.value == "rejected"


def test_idempotent_delivery_skip():
    s = WebhookDeliveryState()
    s.register_endpoint("ep-1", "ws-1", "https://a.com")
    r1 = s.create_delivery("evt-1", "ep-1", "ws-1")
    s.attempt_delivery(r1.delivery_id)
    s.complete_delivery(r1.delivery_id)
    # Second create_delivery for same event+endpoint should return existing record
    r2 = s.create_delivery("evt-1", "ep-1", "ws-1")
    assert r2.delivery_id == r1.delivery_id
    audit = s.audit()
    assert audit["idempotent_skips"] == 1


def test_delivery_retry_max_attempts():
    s = WebhookDeliveryState()
    s.register_endpoint("ep-1", "ws-1", "https://a.com")
    record = s.create_delivery("evt-1", "ep-1", "ws-1")

    # Attempt 3 times (max_retries=3 in fail_delivery default)
    for i in range(3):
        s.attempt_delivery(record.delivery_id)
        s.fail_delivery(record.delivery_id, "timeout", max_retries=3)

    # 4th attempt should succeed but fail_delivery should mark as FAILED
    s.attempt_delivery(record.delivery_id)
    s.fail_delivery(record.delivery_id, "final timeout", max_retries=3)
    assert record.status.value == "failed"


def test_lease_renewal():
    import time
    s = WebhookDeliveryState()
    s.register_endpoint("ep-1", "ws-1", "https://a.com", ttl=1)
    # Renew lease
    assert s.renew_lease("ep-1", extension=3600)
    assert s.renew_lease_count("ep-1") == 1
    # Now endpoint should be valid (lease extended)
    err = s.validate_endpoint("ep-1")
    assert err is None


def test_workspace_isolation():
    s = WebhookDeliveryState()
    s.register_endpoint("ep-1", "ws-1", "https://a.com")
    s.register_endpoint("ep-2", "ws-2", "https://b.com")
    s.update_endpoint_status("ep-2", EndpointStatus.DISABLED)

    # ws-1 should not see ws-2's disabled endpoint
    ws1_active = s.list_active_endpoints("ws-1")
    assert len(ws1_active) == 1
    assert ws1_active[0]["endpoint_id"] == "ep-1"

    # Workspace isolation: delivery events from ws-1 should not affect ws-2
    s.create_delivery("evt-1", "ep-1", "ws-1")
    deliveries_ws1 = [r for r in s._deliveries.values() if r.workspace_id == "ws-1"]
    assert len(deliveries_ws1) == 1


def test_audit_counters():
    s = WebhookDeliveryState()
    s.register_endpoint("ep-1", "ws-1", "https://a.com")
    s.register_endpoint("ep-2", "ws-1", "https://b.com")

    record = s.create_delivery("evt-1", "ep-1", "ws-1")
    s.attempt_delivery(record.delivery_id)
    s.complete_delivery(record.delivery_id)

    record2 = s.create_delivery("evt-2", "ep-2", "ws-1")
    s.reject_delivery(record2.delivery_id, "disabled")

    s.renew_lease("ep-1", 3600)

    audit = s.audit()
    assert audit["deliveries_completed"] == 1
    assert audit["deliveries_rejected"] == 1
    assert audit["lease_renewals"] == 1
    assert audit["endpoints_registered"] == 2


if __name__ == "__main__":
    passed = 0
    failed = 0
    errors = []

    test_methods = [name for name in dir() if name.startswith("test") and callable(globals()[name])]

    print("=== Webhook Delivery State Tests ===\n")
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
