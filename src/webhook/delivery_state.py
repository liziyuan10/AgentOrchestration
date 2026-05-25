"""Webhook Delivery State — Endpoint state verification and delivery control.

Prevents disabled, revoked, or expired endpoints from receiving queued events.
Ensures idempotent retries and workspace isolation for delivery records.
"""

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional


class EndpointStatus(Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    REVOKED = "revoked"
    EXPIRED = "expired"


class DeliveryStatus(Enum):
    PENDING = "pending"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    FAILED = "failed"
    REJECTED = "rejected"


class DeliveryRecord:
    """A single delivery attempt for a webhook event."""

    def __init__(self, event_id: str, endpoint_id: str, workspace_id: str):
        self.delivery_id = str(uuid.uuid4())
        self.event_id = event_id
        self.endpoint_id = endpoint_id
        self.workspace_id = workspace_id
        self.status = DeliveryStatus.PENDING
        self.attempts = 0
        self.created_at = time.time()
        self.last_attempt_at: Optional[float] = None
        self.error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "delivery_id": self.delivery_id,
            "event_id": self.event_id,
            "endpoint_id": self.endpoint_id,
            "workspace_id": self.workspace_id,
            "status": self.status.value,
            "attempts": self.attempts,
            "created_at": self.created_at,
            "last_attempt_at": self.last_attempt_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeliveryRecord":
        record = cls(data["event_id"], data["endpoint_id"], data["workspace_id"])
        record.delivery_id = data["delivery_id"]
        record.status = DeliveryStatus(data["status"])
        record.attempts = data["attempts"]
        record.created_at = data["created_at"]
        record.last_attempt_at = data.get("last_attempt_at")
        record.error = data.get("error")
        return record


class WebhookDeliveryState:
    """Manages endpoint state and delivery verification for webhook events.

    Features:
    - Endpoint registration with status lifecycle (active -> disabled/revoked/expired)
    - Pre-delivery state verification (rejects disabled/revoked/expired endpoints)
    - Idempotent delivery retry detection
    - Workspace-isolated endpoint and delivery management
    - Lease renewal tracking for long-running deliveries
    - Audit counters for diagnostics
    """

    def __init__(self):
        self._endpoints: Dict[str, Dict[str, Any]] = {}
        self._deliveries: Dict[str, DeliveryRecord] = {}
        self._workspace_endpoints: Dict[str, List[str]] = {}
        self._lease_renewals: Dict[str, int] = {}
        # Audit counters
        self._audit_deliveries_rejected = 0
        self._audit_deliveries_completed = 0
        self._audit_deliveries_failed = 0
        self._audit_lease_renewals = 0
        self._audit_idempotent_skips = 0

    # ---- Endpoint management ----

    def register_endpoint(
        self,
        endpoint_id: str,
        workspace_id: str,
        url: str,
        ttl: float = 86400.0,  # 24h default TTL
    ) -> Dict[str, Any]:
        """Register a webhook endpoint. Returns the endpoint record."""
        now = time.time()
        endpoint = {
            "endpoint_id": endpoint_id,
            "workspace_id": workspace_id,
            "url": url,
            "status": EndpointStatus.ACTIVE.value,
            "created_at": now,
            "updated_at": now,
            "expires_at": now + ttl,
            "secret_rotated_at": None,
        }
        self._endpoints[endpoint_id] = endpoint

        if workspace_id not in self._workspace_endpoints:
            self._workspace_endpoints[workspace_id] = []
        self._workspace_endpoints[workspace_id].append(endpoint_id)

        return endpoint

    def get_endpoint(self, endpoint_id: str) -> Optional[Dict[str, Any]]:
        return self._endpoints.get(endpoint_id)

    def update_endpoint_status(self, endpoint_id: str, status: EndpointStatus) -> bool:
        """Update endpoint status. Returns False if endpoint doesn't exist."""
        endpoint = self._endpoints.get(endpoint_id)
        if not endpoint:
            return False
        endpoint["status"] = status.value
        endpoint["updated_at"] = time.time()
        if status == EndpointStatus.REVOKED:
            endpoint["secret_rotated_at"] = time.time()
        return True

    def list_workspace_endpoints(self, workspace_id: str) -> List[Dict[str, Any]]:
        """List endpoints for a workspace."""
        endpoint_ids = self._workspace_endpoints.get(workspace_id, [])
        return [self._endpoints[eid] for eid in endpoint_ids if eid in self._endpoints]

    def list_active_endpoints(self, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List only active (non-disabled/revoked/expired) endpoints."""
        endpoints = self._endpoints.values()
        if workspace_id:
            endpoint_ids = self._workspace_endpoints.get(workspace_id, [])
            endpoints = [e for e in endpoints if e["endpoint_id"] in endpoint_ids]

        now = time.time()
        return [
            e for e in endpoints
            if e["status"] == EndpointStatus.ACTIVE.value
            and e["expires_at"] > now
        ]

    # ---- Delivery state verification ----

    def validate_endpoint(self, endpoint_id: str) -> Optional[str]:
        """Validate endpoint state before delivery.

        Returns None if valid, or an error message string if delivery should be rejected.
        """
        endpoint = self._endpoints.get(endpoint_id)
        if not endpoint:
            return "endpoint not found"

        if endpoint["status"] != EndpointStatus.ACTIVE.value:
            return f"endpoint is {endpoint['status']}"

        if time.time() >= endpoint["expires_at"]:
            return "endpoint has expired"

        return None

    # ---- Delivery management ----

    def create_delivery(self, event_id: str, endpoint_id: str, workspace_id: str) -> DeliveryRecord:
        """Create a delivery record. Checks idempotency first."""
        # Idempotency check: if an existing delivery for this event+endpoint is
        # already delivered, skip duplicate.
        for record in self._deliveries.values():
            if record.event_id == event_id and record.endpoint_id == endpoint_id:
                if record.status == DeliveryStatus.DELIVERED:
                    self._audit_idempotent_skips += 1
                    return record
                if record.status == DeliveryStatus.REJECTED:
                    self._audit_idempotent_skips += 1
                    return record

        record = DeliveryRecord(event_id, endpoint_id, workspace_id)
        self._deliveries[record.delivery_id] = record
        return record

    def attempt_delivery(self, delivery_id: str) -> bool:
        """Mark a delivery as delivering. Returns False if already delivered/rejected."""
        record = self._deliveries.get(delivery_id)
        if not record:
            return False
        if record.status in (DeliveryStatus.DELIVERED, DeliveryStatus.REJECTED):
            return False
        record.status = DeliveryStatus.DELIVERING
        record.attempts += 1
        record.last_attempt_at = time.time()
        return True

    def complete_delivery(self, delivery_id: str) -> bool:
        """Mark delivery as successfully delivered."""
        record = self._deliveries.get(delivery_id)
        if not record:
            return False
        record.status = DeliveryStatus.DELIVERED
        self._audit_deliveries_completed += 1
        return True

    def fail_delivery(self, delivery_id: str, error: Optional[str] = None, max_retries: int = 3) -> bool:
        """Mark delivery as failed. Rejects if max retries exceeded."""
        record = self._deliveries.get(delivery_id)
        if not record:
            return False
        record.error = error
        if record.attempts >= max_retries:
            record.status = DeliveryStatus.FAILED
            self._audit_deliveries_failed += 1
        else:
            record.status = DeliveryStatus.PENDING  # Will be retried
        return True

    def reject_delivery(self, delivery_id: str, reason: str) -> bool:
        """Reject a delivery (e.g., endpoint is disabled)."""
        record = self._deliveries.get(delivery_id)
        if not record:
            return False
        record.status = DeliveryStatus.REJECTED
        record.error = reason
        self._audit_deliveries_rejected += 1
        return True

    def get_delivery(self, delivery_id: str) -> Optional[DeliveryRecord]:
        return self._deliveries.get(delivery_id)

    # ---- Lease renewal ----

    def renew_lease(self, endpoint_id: str, extension: float = 300.0) -> bool:
        """Extend the endpoint lease TTL during long-running operations (e.g., artifact upload)."""
        endpoint = self._endpoints.get(endpoint_id)
        if not endpoint:
            return False
        endpoint["expires_at"] = time.time() + extension
        endpoint["updated_at"] = time.time()
        self._lease_renewals[endpoint_id] = self._lease_renewals.get(endpoint_id, 0) + 1
        self._audit_lease_renewals += 1
        return True

    def renew_lease_count(self, endpoint_id: str) -> int:
        return self._lease_renewals.get(endpoint_id, 0)

    # ---- Audit ----

    def audit(self) -> Dict[str, int]:
        return {
            "deliveries_rejected": self._audit_deliveries_rejected,
            "deliveries_completed": self._audit_deliveries_completed,
            "deliveries_failed": self._audit_deliveries_failed,
            "lease_renewals": self._audit_lease_renewals,
            "idempotent_skips": self._audit_idempotent_skips,
            "endpoints_registered": len(self._endpoints),
            "deliveries_in_flight": sum(
                1 for r in self._deliveries.values()
                if r.status in (DeliveryStatus.PENDING, DeliveryStatus.DELIVERING)
            ),
        }
