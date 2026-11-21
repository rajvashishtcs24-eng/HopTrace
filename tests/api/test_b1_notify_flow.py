"""
Tests for Track B1: Outage and restoration notification flow.

Verifies:
1. Parallel sends and atomic idempotency claims (no double dispatch, UNIQUE constraint safe).
2. Failed-send retry (failed row is re-claimed and updated to sent).
3. Resend after phone correction (skipped invalid_e164_phone re-claimed and sent).
4. Provider error mid-batch (sub 1 sent, sub 2 failed, sub 3 sent; batch does not abort).
5. Simulated incident with Twilio configured (Twilio call blocked, skipped with simulated_incident_twilio_blocked).
6. Allowlist enforcement (NOTIFY_ALLOWLIST allows listed numbers, skips others with not_in_allowlist).
7. Phone masking in all GET responses (/preview and /notifications).
8. Preview when unconfigured (returns HTTP 200, only POST /notify returns HTTP 503).
9. Restoration default recipient filtering (defaults to subscribers sent outage message).
10. Max recipients cap enforcement.
"""
from __future__ import annotations

import sqlite3
import threading
from typing import Any, Dict, List
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.init import DEMO_INCIDENTS
from app.db.repository import (
    claim_notification_delivery,
    create_incident,
    get_incident,
    get_subscribers_sent_outage,
    list_notification_deliveries,
    update_notification_delivery,
)
from app.main import app
from app.providers.notifications import (
    ConsoleNotificationProvider,
    NotificationProvider,
)
from app.services.outage_notifier import (
    dispatch_outage_notifications,
    generate_notification_previews,
    generate_subscriber_message,
    is_valid_e164,
    mask_phone,
)

DEMO_INCIDENT_ID = DEMO_INCIDENTS[0]["id"]


class MockFailingProvider(NotificationProvider):
    """Fails delivery for specific phone numbers or subscribers."""
    def __init__(self, failing_subscribers: set[str]) -> None:
        self.failing_subscribers = failing_subscribers
        self.sent_messages: List[Dict[str, Any]] = []

    @property
    def provider_name(self) -> str:
        return "mock_failing"

    def send_notification(
        self,
        recipient: str,
        message: str,
        channel: str = "sms",
        subscriber_id: str | None = None,
    ) -> Dict[str, Any]:
        if subscriber_id in self.failing_subscribers:
            raise RuntimeError(f"Carrier network error dispatching to {subscriber_id}")
        record = {
            "recipient": recipient,
            "message": message,
            "channel": channel,
            "subscriber_id": subscriber_id,
        }
        self.sent_messages.append(record)
        return {
            "status": "sent",
            "provider": "mock_failing",
            "message_id": f"msg-{len(self.sent_messages)}",
            "recipient": recipient,
            "channel": channel,
        }


# ── Test 1: Parallel sends (atomic claim race condition) ─────────────────────

def test_parallel_sends_atomic_idempotency_claim(isolated_db: str) -> None:
    """Parallel dispatch requests for the same incident and subscriber do not double-send."""
    conn = sqlite3.connect(isolated_db)
    conn.row_factory = sqlite3.Row
    incident = get_incident(conn, DEMO_INCIDENT_ID)
    assert incident is not None

    subscribers = [
        {"id": "SUB201", "phone": "+919876543201", "preferred_language": "hi", "village": "Rampur"},
        {"id": "SUB202", "phone": "+919876543202", "preferred_language": "hi", "village": "Rampur"},
    ]

    provider = ConsoleNotificationProvider()

    # Run dispatch in two concurrent threads
    results = [None, None]

    def worker(idx: int) -> None:
        t_conn = sqlite3.connect(isolated_db)
        t_conn.row_factory = sqlite3.Row
        res = dispatch_outage_notifications(
            incident=incident,
            subscribers=subscribers,
            notification_provider=provider,
            db_conn=t_conn,
            message_kind="outage",
        )
        results[idx] = res
        t_conn.close()

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    res1, res2 = results[0], results[1]
    assert res1 is not None and res2 is not None

    total_sent = res1["sent_count"] + res2["sent_count"]
    total_skipped = res1["skipped_count"] + res2["skipped_count"]

    # Exactly 2 messages sent in total across both threads, and 2 skipped
    assert total_sent == 2
    assert total_skipped == 2

    # Verify database has exactly 2 records with UNIQUE(incident_id, subscriber_id, message_kind)
    records = list_notification_deliveries(conn, DEMO_INCIDENT_ID, message_kind="outage")
    assert len(records) == 2
    for r in records:
        assert r["status"] == "sent"

    conn.close()


# ── Test 2: Failed-send retry ────────────────────────────────────────────────

def test_failed_send_retry(isolated_db: str) -> None:
    """A failed notification delivery can be reclaimed and successfully retried."""
    conn = sqlite3.connect(isolated_db)
    conn.row_factory = sqlite3.Row
    incident = get_incident(conn, DEMO_INCIDENT_ID)
    assert incident is not None

    subscribers = [
        {"id": "SUB201", "phone": "+919876543201", "preferred_language": "hi", "village": "Rampur"},
    ]

    # Attempt 1: provider fails
    failing_prov = MockFailingProvider(failing_subscribers={"SUB201"})
    res1 = dispatch_outage_notifications(
        incident=incident,
        subscribers=subscribers,
        notification_provider=failing_prov,
        db_conn=conn,
        message_kind="outage",
    )
    assert res1["sent_count"] == 0
    assert res1["failed_count"] == 1

    # Verify DB recorded failed status
    records = list_notification_deliveries(conn, DEMO_INCIDENT_ID, message_kind="outage")
    assert len(records) == 1
    assert records[0]["status"] == "failed"
    assert "Carrier network error" in (records[0]["skip_reason"] or "")

    # Attempt 2: retry with healthy provider
    healthy_prov = ConsoleNotificationProvider()
    res2 = dispatch_outage_notifications(
        incident=incident,
        subscribers=subscribers,
        notification_provider=healthy_prov,
        db_conn=conn,
        message_kind="outage",
    )
    assert res2["sent_count"] == 1
    assert res2["failed_count"] == 0

    # Verify DB updated to sent
    records2 = list_notification_deliveries(conn, DEMO_INCIDENT_ID, message_kind="outage")
    assert len(records2) == 1
    assert records2[0]["status"] == "sent"
    assert records2[0]["skip_reason"] is None

    conn.close()


# ── Test 3: Resend after phone correction ────────────────────────────────────

def test_resend_after_phone_correction(isolated_db: str) -> None:
    """An invalid E.164 phone number is skipped, and can be retried and sent after correction."""
    conn = sqlite3.connect(isolated_db)
    conn.row_factory = sqlite3.Row
    incident = get_incident(conn, DEMO_INCIDENT_ID)
    assert incident is not None

    # Step 1: Initial dispatch with invalid phone
    bad_sub = [{"id": "SUB201", "phone": "9876543201", "preferred_language": "hi", "village": "Rampur"}]
    prov = ConsoleNotificationProvider()

    res1 = dispatch_outage_notifications(
        incident=incident,
        subscribers=bad_sub,
        notification_provider=prov,
        db_conn=conn,
        message_kind="outage",
    )
    assert res1["sent_count"] == 0
    assert res1["skipped_count"] == 1
    assert res1["deliveries"][0]["skip_reason"] == "invalid_e164_phone"

    records = list_notification_deliveries(conn, DEMO_INCIDENT_ID, message_kind="outage")
    assert len(records) == 1
    assert records[0]["status"] == "skipped"
    assert records[0]["skip_reason"] == "invalid_e164_phone"

    # Step 2: Correct phone to valid E.164 and retry
    corrected_sub = [{"id": "SUB201", "phone": "+919876543201", "preferred_language": "hi", "village": "Rampur"}]
    res2 = dispatch_outage_notifications(
        incident=incident,
        subscribers=corrected_sub,
        notification_provider=prov,
        db_conn=conn,
        message_kind="outage",
    )
    assert res2["sent_count"] == 1
    assert res2["skipped_count"] == 0

    records2 = list_notification_deliveries(conn, DEMO_INCIDENT_ID, message_kind="outage")
    assert len(records2) == 1
    assert records2[0]["status"] == "sent"
    assert records2[0]["skip_reason"] is None
    assert records2[0]["recipient"] == "+919876543201"

    conn.close()


# ── Test 4: Provider error mid-batch ─────────────────────────────────────────

def test_provider_error_mid_batch_does_not_abort(isolated_db: str) -> None:
    """When a provider throws mid-batch, successful recipients are recorded and remaining proceed."""
    conn = sqlite3.connect(isolated_db)
    conn.row_factory = sqlite3.Row
    incident = get_incident(conn, DEMO_INCIDENT_ID)
    assert incident is not None

    subscribers = [
        {"id": "SUB201", "phone": "+919876543201", "preferred_language": "hi", "village": "Rampur"},
        {"id": "SUB202", "phone": "+919876543202", "preferred_language": "hi", "village": "Rampur"},
        {"id": "SUB203", "phone": "+919876543203", "preferred_language": "hi", "village": "Rampur"},
    ]

    # SUB202 will fail, SUB201 and SUB203 will succeed
    failing_prov = MockFailingProvider(failing_subscribers={"SUB202"})

    res = dispatch_outage_notifications(
        incident=incident,
        subscribers=subscribers,
        notification_provider=failing_prov,
        db_conn=conn,
        message_kind="outage",
    )
    assert res["total_targeted"] == 3
    assert res["sent_count"] == 2
    assert res["failed_count"] == 1
    assert res["skipped_count"] == 0

    deliveries_map = {d["subscriber_id"]: d for d in res["deliveries"]}
    assert deliveries_map["SUB201"]["status"] == "sent"
    assert deliveries_map["SUB202"]["status"] == "failed"
    assert deliveries_map["SUB203"]["status"] == "sent"

    # DB persistence check
    records = list_notification_deliveries(conn, DEMO_INCIDENT_ID, message_kind="outage")
    rec_map = {r["subscriber_id"]: r for r in records}
    assert rec_map["SUB201"]["status"] == "sent"
    assert rec_map["SUB202"]["status"] == "failed"
    assert rec_map["SUB203"]["status"] == "sent"

    conn.close()


# ── Test 5: Simulated incident with Twilio configured ────────────────────────

def test_simulated_incident_with_twilio_configured_is_blocked(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Twilio dispatch is blocked for simulated incidents to prevent accidental real cellular SMS."""
    conn = sqlite3.connect(isolated_db)
    conn.row_factory = sqlite3.Row

    # Incident with data_source = 'simulated'
    incident = get_incident(conn, DEMO_INCIDENT_ID)
    assert incident["data_source"] == "simulated"

    subscribers = [
        {"id": "SUB201", "phone": "+919876543201", "preferred_language": "hi", "village": "Rampur"},
    ]

    class FakeTwilioProvider(NotificationProvider):
        provider_name = "twilio"
        def send_notification(self, recipient: str, message: str, channel: str = "sms", subscriber_id: str | None = None) -> NotificationResult:
            raise AssertionError("Twilio send_notification should NOT be called for simulated incident!")

    fake_twilio = FakeTwilioProvider()
    res = dispatch_outage_notifications(
        incident=incident,
        subscribers=subscribers,
        notification_provider=fake_twilio,
        db_conn=conn,
        message_kind="outage",
    )
    assert res["sent_count"] == 0
    assert res["skipped_count"] == 1
    assert res["deliveries"][0]["skip_reason"] == "simulated_incident_twilio_blocked"

    conn.close()


# ── Test 6: Allowlist enforcement ────────────────────────────────────────────

def test_twilio_allowlist_enforcement(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Twilio only dispatches to numbers in NOTIFY_ALLOWLIST; non-allowlisted numbers are skipped."""
    conn = sqlite3.connect(isolated_db)
    conn.row_factory = sqlite3.Row

    # Create a live incident
    live_inc = {
        "id": "incident-live-test-01",
        "run_id": "run-live-01",
        "status": "open",
        "suspected_component_id": "AP2",
        "suspected_component_type": "access_point",
        "summary": "Live fiber break",
        "confidence_score": 0.95,
        "evidence": "[]",
        "uncertainty_note": None,
        "data_source": "live",
        "created_at": "2026-11-20T10:00:00Z",
    }
    create_incident(conn, live_inc)

    monkeypatch.setattr(settings, "notify_allowlist", "+919876543201")

    subscribers = [
        {"id": "SUB201", "phone": "+919876543201", "preferred_language": "hi", "village": "Rampur"},
        {"id": "SUB202", "phone": "+919876543202", "preferred_language": "hi", "village": "Rampur"},
    ]

    twilio_dispatched = []
    class FakeTwilioProvider(NotificationProvider):
        provider_name = "twilio"
        def send_notification(self, recipient: str, message: str, channel: str = "sms", subscriber_id: str | None = None) -> NotificationResult:
            twilio_dispatched.append(recipient)
            return {"status": "sent", "provider": "twilio", "message_id": "SM123", "recipient": recipient, "channel": channel}

    fake_twilio = FakeTwilioProvider()
    res = dispatch_outage_notifications(
        incident=live_inc,
        subscribers=subscribers,
        notification_provider=fake_twilio,
        db_conn=conn,
        message_kind="outage",
    )
    assert res["sent_count"] == 1
    assert res["skipped_count"] == 1
    assert twilio_dispatched == ["+919876543201"]

    deliveries_map = {d["subscriber_id"]: d for d in res["deliveries"]}
    assert deliveries_map["SUB201"]["status"] == "sent"
    assert deliveries_map["SUB202"]["status"] == "skipped"
    assert deliveries_map["SUB202"]["skip_reason"] == "not_in_allowlist"

    conn.close()


# ── Test 7: Phone masking in all GET responses ───────────────────────────────

def test_phone_masking_in_preview_and_history(
    client: TestClient, isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phone numbers are masked (+91*****00) in /preview and /notifications GET responses."""
    monkeypatch.setattr(settings, "notification_provider", "console")
    monkeypatch.setattr(settings, "explanation_provider", "simulated")

    # 1. Check GET /preview
    prev_res = client.get(f"/api/v1/incidents/{DEMO_INCIDENT_ID}/notifications/preview")
    assert prev_res.status_code == 200
    prev_data = prev_res.json()
    assert len(prev_data["previews"]) > 0
    for item in prev_data["previews"]:
        assert "*" in item["phone"]
        assert not item["phone"].endswith("SUB101")
        assert len(item["phone"]) >= 7

    # 2. Dispatch a notification
    send_res = client.post(
        f"/api/v1/incidents/{DEMO_INCIDENT_ID}/notify",
        json={"channel": "sms"},
    )
    assert send_res.status_code == 200

    # 3. Check GET /notifications history
    hist_res = client.get(f"/api/v1/incidents/{DEMO_INCIDENT_ID}/notifications")
    assert hist_res.status_code == 200
    hist_data = hist_res.json()
    assert hist_data["total_count"] > 0
    for d in hist_data["deliveries"]:
        assert "*" in d["recipient"]
        assert len(d["recipient"]) >= 7


# ── Test 8: Preview when unconfigured ────────────────────────────────────────

def test_preview_works_when_unconfigured_while_send_returns_503(
    client: TestClient, isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preview returns HTTP 200 when provider is unconfigured; only POST /notify returns 503."""
    monkeypatch.setattr(settings, "notification_provider", "unavailable")
    monkeypatch.setattr(settings, "explanation_provider", "unavailable")

    # Preview works (HTTP 200)
    prev_res = client.get(f"/api/v1/incidents/{DEMO_INCIDENT_ID}/notifications/preview")
    assert prev_res.status_code == 200
    data = prev_res.json()
    assert data["provider"] == "unavailable"
    assert data["provider_available"] is False
    assert len(data["previews"]) > 0

    # Messages use deterministic templates, no cause codes, no GramNet
    for p in data["previews"]:
        assert "HopTrace" in p["message"] or "हॉपट्रेस" in p["message"]
        assert "GramNet" not in p["message"]
        assert "gramnet" not in p["message"].lower()
        assert "rf_degradation" not in p["message"]
        assert "Fibre cut" not in p["message"]

    # Dispatch fails honestly (HTTP 503)
    notify_res = client.post(
        f"/api/v1/incidents/{DEMO_INCIDENT_ID}/notify",
        json={"channel": "sms"},
    )
    assert notify_res.status_code == 503
    assert "not configured" in notify_res.json()["detail"].lower()


# ── Test 9: Restoration default recipient filtering ──────────────────────────

def test_restoration_defaults_to_subscribers_sent_outage(
    client: TestClient, isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Restoration preview and send default strictly to subscribers whose outage alert was sent."""
    monkeypatch.setattr(settings, "notification_provider", "console")
    monkeypatch.setattr(settings, "explanation_provider", "simulated")

    # Step A: Before any outage alert is sent, restoration preview has 0 recipients
    res_prev0 = client.get(f"/api/v1/incidents/{DEMO_INCIDENT_ID}/notifications/preview?kind=restoration")
    assert res_prev0.status_code == 200
    assert res_prev0.json()["affected_subscribers_count"] == 0

    # Step B: Send outage alert to only SUB101
    send_outage = client.post(
        f"/api/v1/incidents/{DEMO_INCIDENT_ID}/notify",
        json={"channel": "sms", "message_kind": "outage", "subscriber_ids": ["SUB101"]},
    )
    assert send_outage.status_code == 200
    assert send_outage.json()["sent_count"] == 1

    # Step C: Restoration preview now targets only SUB101
    res_prev1 = client.get(f"/api/v1/incidents/{DEMO_INCIDENT_ID}/notifications/preview?kind=restoration")
    assert res_prev1.status_code == 200
    rdata = res_prev1.json()
    assert rdata["affected_subscribers_count"] == 1
    assert rdata["previews"][0]["subscriber_id"] == "SUB101"
    assert "restored" in rdata["previews"][0]["message"].lower() or "बहाल" in rdata["previews"][0]["message"]

    # Step D: Dispatch restoration alert
    send_resto = client.post(
        f"/api/v1/incidents/{DEMO_INCIDENT_ID}/notify",
        json={"channel": "sms", "message_kind": "restoration"},
    )
    assert send_resto.status_code == 200
    assert send_resto.json()["sent_count"] == 1
    assert send_resto.json()["deliveries"][0]["subscriber_id"] == "SUB101"


# ── Test 10: Max recipients cap enforcement ──────────────────────────────────

def test_max_recipients_cap(isolated_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dispatches beyond NOTIFY_MAX_RECIPIENTS are skipped with max_recipients_exceeded."""
    conn = sqlite3.connect(isolated_db)
    conn.row_factory = sqlite3.Row
    incident = get_incident(conn, DEMO_INCIDENT_ID)
    assert incident is not None

    monkeypatch.setattr(settings, "notify_max_recipients", 2)

    subscribers = [
        {"id": "SUB201", "phone": "+919876543201", "preferred_language": "hi", "village": "Rampur"},
        {"id": "SUB202", "phone": "+919876543202", "preferred_language": "hi", "village": "Rampur"},
        {"id": "SUB203", "phone": "+919876543203", "preferred_language": "hi", "village": "Rampur"},
    ]

    prov = ConsoleNotificationProvider()
    res = dispatch_outage_notifications(
        incident=incident,
        subscribers=subscribers,
        notification_provider=prov,
        db_conn=conn,
        message_kind="outage",
    )
    assert res["sent_count"] == 2
    assert res["skipped_count"] == 1
    assert res["deliveries"][2]["skip_reason"] == "max_recipients_exceeded"

    conn.close()
