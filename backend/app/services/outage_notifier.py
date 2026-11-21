"""
Outage and restoration notification service.

Provides:
- Deterministic HopTrace message templates in Hindi and English (no internal cause, no ETA, zero GramNet branding).
- Sarvam translation slot with fallback to hi/en.
- E.164 phone number validation.
- Phone number masking helper for audit and privacy.
- Two-way SQLite persistence and atomic idempotency claims.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.db.repository import (
    claim_notification_delivery,
    update_notification_delivery,
)
from app.engine.topology import classify_essential
from app.providers.notifications import NotificationProvider

logger = logging.getLogger(__name__)

# Strict E.164 format: + followed by 10 to 15 digits
E164_REGEX = re.compile(r"^\+[1-9]\d{9,14}$")


def is_valid_e164(phone: Optional[str]) -> bool:
    """Validates whether a phone number strictly complies with E.164 format."""
    if not phone or not isinstance(phone, str):
        return False
    return bool(E164_REGEX.match(phone.strip()))


def mask_phone(phone: Optional[str]) -> str:
    """Masks a phone number, preserving the country prefix and last 2 digits.

    Example: '+919876543200' -> '+91*****00'
    """
    if not phone:
        return "—"
    clean = str(phone).strip()
    if clean.startswith("+") and len(clean) >= 6:
        prefix = clean[:3]
        suffix = clean[-2:]
        masked_len = max(3, len(clean) - 5)
        return f"{prefix}{'*' * masked_len}{suffix}"
    if len(clean) > 4:
        return f"{clean[:1]}{'*' * (len(clean) - 3)}{clean[-2:]}"
    return "****"


def generate_subscriber_message(
    subscriber: Dict[str, Any],
    village: Optional[str] = None,
    message_kind: str = "outage",
    explanation_provider: Optional[Any] = None,
) -> Tuple[str, str]:
    """Builds a deterministic, friendly subscriber alert message.

    Rule: No internal diagnostic cause codes and no unverified ETAs.
    Branding: HopTrace (zero GramNet occurrences).

    Returns:
        (message_text, translation_source)
    """
    lang = (subscriber.get("preferred_language") or "hi").lower().strip()
    sub_name = subscriber.get("display_name") or subscriber.get("id") or "Subscriber"
    village_name = (village or subscriber.get("village") or "your village").capitalize()

    # Outage deterministic templates
    if message_kind == "outage":
        if lang.startswith("hi"):
            msg = (
                f"नमस्ते {sub_name}, हॉपट्रेस सूचना: आपके क्षेत्र ({village_name}) में "
                "नेटवर्क सेवा बाधित है। हमारी फील्ड टीम बहाली कार्य कर रही है।"
            )
            return msg, "template_hi"
        elif lang.startswith("en"):
            msg = (
                f"Dear {sub_name}, HopTrace Alert: Network service disruption detected in "
                f"your area ({village_name}). Field restoration is in progress."
            )
            return msg, "template_en"
        else:
            # Sarvam translation slot for regional languages (e.g. ta, mr, te, kn, bn)
            if (
                explanation_provider
                and getattr(explanation_provider, "provider_name", None) == "sarvam"
                and hasattr(explanation_provider, "translate")
            ):
                try:
                    base_en = (
                        f"Dear {sub_name}, HopTrace Alert: Network service disruption detected in "
                        f"your area ({village_name}). Field restoration is in progress."
                    )
                    translated = explanation_provider.translate(base_en, target_language=lang)
                    if translated and isinstance(translated, str) and len(translated.strip()) > 5:
                        return translated.strip(), "sarvam"
                except Exception as exc:
                    logger.warning("Sarvam translation failed for %s, falling back to Hindi: %s", lang, exc)

            # Guaranteed fallback to Hindi
            msg = (
                f"नमस्ते {sub_name}, हॉपट्रेस सूचना: आपके क्षेत्र ({village_name}) में "
                "नेटवर्क सेवा बाधित है। हमारी फील्ड टीम बहाली कार्य कर रही है।"
            )
            return msg, "fallback_hi"

    # Restoration deterministic templates
    else:
        if lang.startswith("hi"):
            msg = (
                f"नमस्ते {sub_name}, हॉपट्रेस सूचना: आपके क्षेत्र ({village_name}) में "
                "नेटवर्क सेवा पूरी तरह बहाल कर दी गई है। असुविधा के लिए खेद है।"
            )
            return msg, "template_hi"
        elif lang.startswith("en"):
            msg = (
                f"Dear {sub_name}, HopTrace Alert: Network service in your area ({village_name}) "
                "has been fully restored. Thank you for your patience."
            )
            return msg, "template_en"
        else:
            if (
                explanation_provider
                and getattr(explanation_provider, "provider_name", None) == "sarvam"
                and hasattr(explanation_provider, "translate")
            ):
                try:
                    base_en = (
                        f"Dear {sub_name}, HopTrace Alert: Network service in your area ({village_name}) "
                        "has been fully restored. Thank you for your patience."
                    )
                    translated = explanation_provider.translate(base_en, target_language=lang)
                    if translated and isinstance(translated, str) and len(translated.strip()) > 5:
                        return translated.strip(), "sarvam"
                except Exception as exc:
                    logger.warning("Sarvam restoration translation failed for %s, falling back: %s", lang, exc)

            msg = (
                f"नमस्ते {sub_name}, हॉपट्रेस सूचना: आपके क्षेत्र ({village_name}) में "
                "नेटवर्क सेवा पूरी तरह बहाल कर दी गई है। असुविधा के लिए खेद है।"
            )
            return msg, "fallback_hi"


def generate_notification_previews(
    incident: Dict[str, Any],
    subscribers: List[Dict[str, Any]],
    explanation_provider: Optional[Any] = None,
    channel: str = "sms",
    message_kind: str = "outage",
) -> List[Dict[str, Any]]:
    """Builds preview items for all target subscribers, sorted essential services first."""
    previews = []

    for sub in subscribers:
        raw_phone = sub.get("phone") or ""
        valid_e164 = is_valid_e164(raw_phone)
        val_reason = None if valid_e164 else "invalid_e164_format"
        masked = mask_phone(raw_phone)
        lang = (sub.get("preferred_language") or "hi").strip()
        village = sub.get("village") or "Unknown"

        sub_name = sub.get("display_name") or sub.get("id")
        is_ess = classify_essential(sub_name)

        msg, source = generate_subscriber_message(
            subscriber=sub,
            village=village,
            message_kind=message_kind,
            explanation_provider=explanation_provider,
        )

        previews.append({
            "subscriber_id": sub.get("id"),
            "subscriber_name": sub_name,
            "phone": masked,
            "phone_valid": valid_e164,
            "phone_validation_reason": val_reason,
            "village": village.lower(),
            "is_essential": is_ess,
            "preferred_language": lang,
            "translation_source": source,
            "message_kind": message_kind,
            "channel": channel.lower(),
            "message": msg,
        })

    # Essential public services first, then alphabetical by ID
    previews.sort(key=lambda p: (not p["is_essential"], p["subscriber_id"]))
    return previews


def dispatch_outage_notifications(
    incident: Dict[str, Any],
    subscribers: List[Dict[str, Any]],
    notification_provider: NotificationProvider,
    db_conn: sqlite3.Connection,
    explanation_provider: Optional[Any] = None,
    channel: str = "sms",
    message_kind: str = "outage",
) -> Dict[str, Any]:
    """Generates, claims, and dispatches outage or restoration notifications.

    Guarantees:
    - Atomically claims rows in SQLite (ON CONFLICT DO NOTHING as 'queued').
    - Only 'sent' and recent 'queued' rows block resends (double-click safe).
    - Failed or skipped rows can be retried and updated.
    - Stale queued rows (>= 5 minutes old) are retryable.
    - Already-notified rows return 'already_notified' to caller without overwriting DB record.
    - Validates E.164: invalid numbers marked 'skipped' ('invalid_e164_phone'), never sent.
    - Live-only Twilio enforcement: simulated incidents skip Twilio sending ('simulated_incident_twilio_blocked').
    - Allowlist enforcement for Twilio: non-allowlisted numbers marked 'skipped' ('not_in_allowlist').
    - Max recipients cap per dispatch.
    - Console results labeled 'simulated (not delivered)'.
    - Returns masked recipient strings in response for privacy.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    prov_name = notification_provider.provider_name
    is_live_incident = (incident.get("data_source") == "live")

    allowlist_str = settings.notify_allowlist
    allowlist = {n.strip() for n in allowlist_str.split(",") if n.strip()} if allowlist_str else set()
    max_recipients = settings.notify_max_recipients

    deliveries = []
    sent_count = 0
    failed_count = 0
    skipped_count = 0

    for sub in subscribers:
        sub_id = sub["id"]
        raw_phone = sub.get("phone") or ""
        village = sub.get("village") or "Unknown"
        lang = (sub.get("preferred_language") or "hi").strip()
        msg, _ = generate_subscriber_message(
            subscriber=sub,
            village=village,
            message_kind=message_kind,
            explanation_provider=explanation_provider,
        )

        # 1. Atomic SQLite claim
        delivery_id, owned, existing_rec = claim_notification_delivery(
            conn=db_conn,
            incident_id=incident["id"],
            subscriber_id=sub_id,
            message_kind=message_kind,
            channel=channel,
            recipient=raw_phone,
            language=lang,
            message=msg,
            provider=prov_name,
            now_iso=now_iso,
        )

        if not owned and existing_rec:
            # Already sent or in-flight: do NOT overwrite SQLite row
            skip_reason = "already_notified" if existing_rec.get("status") == "sent" else "already_queued"
            skipped_count += 1
            deliveries.append({
                "subscriber_id": sub_id,
                "recipient": mask_phone(existing_rec.get("recipient") or raw_phone),
                "status": "skipped",
                "delivery_status": f"skipped ({skip_reason})",
                "skip_reason": skip_reason,
                "message_id": existing_rec.get("message_id"),
                "message_kind": message_kind,
                "channel": channel.lower(),
                "provider": existing_rec.get("provider") or prov_name,
                "message": existing_rec.get("message") or msg,
                "error": None,
                "created_at": existing_rec.get("created_at") or now_iso,
            })
            continue

        # We own the claim (status is 'queued' in DB). Now validate and dispatch:

        # Check A: E.164 phone validation
        if not is_valid_e164(raw_phone):
            update_notification_delivery(
                conn=db_conn,
                delivery_id=delivery_id,
                status="skipped",
                skip_reason="invalid_e164_phone",
                now_iso=now_iso,
            )
            skipped_count += 1
            deliveries.append({
                "subscriber_id": sub_id,
                "recipient": mask_phone(raw_phone),
                "status": "skipped",
                "delivery_status": "skipped (invalid E.164 phone)",
                "skip_reason": "invalid_e164_phone",
                "message_id": None,
                "message_kind": message_kind,
                "channel": channel.lower(),
                "provider": prov_name,
                "message": msg,
                "error": None,
                "created_at": now_iso,
            })
            continue

        # Check B: Real Twilio sends permitted ONLY for live incidents
        if prov_name == "twilio" and not is_live_incident:
            update_notification_delivery(
                conn=db_conn,
                delivery_id=delivery_id,
                status="skipped",
                skip_reason="simulated_incident_twilio_blocked",
                now_iso=now_iso,
            )
            skipped_count += 1
            deliveries.append({
                "subscriber_id": sub_id,
                "recipient": mask_phone(raw_phone),
                "status": "skipped",
                "delivery_status": "skipped (Twilio dispatch disabled for simulated incidents)",
                "skip_reason": "simulated_incident_twilio_blocked",
                "message_id": None,
                "message_kind": message_kind,
                "channel": channel.lower(),
                "provider": prov_name,
                "message": msg,
                "error": None,
                "created_at": now_iso,
            })
            continue

        # Check C: Allowlist enforcement for Twilio
        if prov_name == "twilio" and allowlist and raw_phone not in allowlist:
            update_notification_delivery(
                conn=db_conn,
                delivery_id=delivery_id,
                status="skipped",
                skip_reason="not_in_allowlist",
                now_iso=now_iso,
            )
            skipped_count += 1
            deliveries.append({
                "subscriber_id": sub_id,
                "recipient": mask_phone(raw_phone),
                "status": "skipped",
                "delivery_status": "skipped (not in allowlist)",
                "skip_reason": "not_in_allowlist",
                "message_id": None,
                "message_kind": message_kind,
                "channel": channel.lower(),
                "provider": prov_name,
                "message": msg,
                "error": None,
                "created_at": now_iso,
            })
            continue

        # Check D: Max recipients cap
        if sent_count >= max_recipients:
            update_notification_delivery(
                conn=db_conn,
                delivery_id=delivery_id,
                status="skipped",
                skip_reason="max_recipients_exceeded",
                now_iso=now_iso,
            )
            skipped_count += 1
            deliveries.append({
                "subscriber_id": sub_id,
                "recipient": mask_phone(raw_phone),
                "status": "skipped",
                "delivery_status": "skipped (max recipients cap reached)",
                "skip_reason": "max_recipients_exceeded",
                "message_id": None,
                "message_kind": message_kind,
                "channel": channel.lower(),
                "provider": prov_name,
                "message": msg,
                "error": None,
                "created_at": now_iso,
            })
            continue

        # Dispatch via active provider
        try:
            res = notification_provider.send_notification(
                recipient=raw_phone,
                message=msg,
                channel=channel,
                subscriber_id=sub_id,
            )
            msg_id = res.get("message_id")
            update_notification_delivery(
                conn=db_conn,
                delivery_id=delivery_id,
                status="sent",
                provider_message_id=msg_id,
                now_iso=now_iso,
            )
            sent_count += 1
            human_status = "simulated (not delivered)" if prov_name == "console" else "sent"
            deliveries.append({
                "subscriber_id": sub_id,
                "recipient": mask_phone(raw_phone),
                "status": "sent",
                "delivery_status": human_status,
                "skip_reason": None,
                "message_id": msg_id,
                "message_kind": message_kind,
                "channel": channel.lower(),
                "provider": prov_name,
                "message": msg,
                "error": None,
                "created_at": now_iso,
            })
        except Exception as exc:
            logger.error("Failed to deliver notification to %s (%s): %s", sub_id, mask_phone(raw_phone), exc)
            update_notification_delivery(
                conn=db_conn,
                delivery_id=delivery_id,
                status="failed",
                skip_reason=str(exc),
                now_iso=now_iso,
            )
            failed_count += 1
            deliveries.append({
                "subscriber_id": sub_id,
                "recipient": mask_phone(raw_phone),
                "status": "failed",
                "delivery_status": "failed",
                "skip_reason": None,
                "message_id": None,
                "message_kind": message_kind,
                "channel": channel.lower(),
                "provider": prov_name,
                "message": msg,
                "error": str(exc),
                "created_at": now_iso,
            })

    return {
        "provider": prov_name,
        "channel": channel.lower(),
        "message_kind": message_kind,
        "total_targeted": len(subscribers),
        "sent_count": sent_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "deliveries": deliveries,
    }
