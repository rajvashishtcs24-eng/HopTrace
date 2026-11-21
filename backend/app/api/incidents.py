"""
Incident retrieval, affected-subscriber, and business-impact endpoints.

Implements:
- GET /api/v1/incidents/latest
- GET /api/v1/incidents/{incident_id}
- GET /api/v1/incidents/{incident_id}/affected-subscribers
- GET /api/v1/incidents/{incident_id}/business-impact

Follows docs/api-contract.md Sections 4, 5, and 6.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import sqlite3
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

logger = logging.getLogger(__name__)

from app.config import settings
from app.db.connection import get_db
from app.db.repository import (
    get_incident,
    get_latest_incident,
    get_latest_open_incident,
    get_subscribers_by_ids,
    get_subscribers_sent_outage,
    list_notification_deliveries,
)
from app.engine.facade import get_incident_details, get_latest_incident as get_engine_latest_incident
from app.providers.dependencies import (
    DependencyAnalysisAdapter,
    GraphEngineUnavailableError,
)
from app.providers.explanations import (
    ExplanationProviderUnavailableError,
)
from app.providers.notifications import (
    NotificationProviderUnavailableError,
)
from app.providers.registry import (
    get_dependency_adapter,
    get_explanation_provider,
    get_notification_provider,
)
from app.schemas.incident import (
    AffectedSubscriberItem,
    AffectedSubscribersResponse,
    BusinessImpactResponse,
    BusinessImpactSubscriber,
    IncidentResponse,
)
from app.schemas.notification import (
    NotificationDeliveriesListResponse,
    NotificationDeliveryItem,
    NotificationPreviewItem,
    NotificationPreviewResponse,
    NotificationSendRequest,
    NotificationSendResponse,
)
from app.services.outage_notifier import (
    dispatch_outage_notifications,
    generate_notification_previews,
    mask_phone,
)

router = APIRouter(tags=["incidents"])

AP_TO_VILLAGE: dict[str, str] = {
    "AP1": "Rampur",
    "AP2": "Rampur",
    "AP3": "Bhatpur",
    "AP4": "Bhatpur",
    "AP5": "Daulatpur",
    "AP6": "Daulatpur",
}


@router.get(
    "/incidents/latest",
    response_model=Optional[IncidentResponse],
    summary="Get latest diagnostic incident",
    description=(
        "Returns the most recent diagnostic incident, or null if no incident has been created."
    ),
)
def get_latest(
    db: sqlite3.Connection = Depends(get_db),
) -> Optional[IncidentResponse]:
    """Retrieve the most recent open incident (status != 'closed') or return null."""
    # 1. Query only open incidents from operational storage
    incident = get_latest_open_incident(db)
    if incident is None:
        return None

    # 2. Enrich with engine diagnostic details if available in memory
    try:
        engine_incident = get_incident_details(incident["id"])
        if engine_incident is not None:
            if engine_incident.status == "closed":
                return None
            return IncidentResponse.model_validate(engine_incident.model_dump())
    except Exception:
        pass

    if incident.get("status") == "closed":
        return None

    return IncidentResponse(**incident)


@router.get(
    "/incidents/{incident_id}",
    response_model=IncidentResponse,
    summary="Get incident details",
    description="Returns detailed diagnostic information for a specific incident.",
)
def get_by_id(
    incident_id: str,
    db: sqlite3.Connection = Depends(get_db),
) -> IncidentResponse:
    """Retrieve an incident by ID or return 404 Not Found."""
    # 1. Query the engine facade for the incident details
    try:
        engine_incident = get_incident_details(incident_id)
        if engine_incident is not None:
            return IncidentResponse.model_validate(engine_incident.model_dump())
    except Exception:
        pass

    # 2. Fall back to operational storage
    incident = get_incident(db, incident_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found",
        )
    return IncidentResponse(**incident)


@router.get(
    "/incidents/{incident_id}/affected-subscribers",
    response_model=AffectedSubscribersResponse,
    summary="Get affected subscribers for an incident",
    description=(
        "Determines affected subscribers using network dependencies. "
        "Returns 503 if Member 1's graph dependency engine is not integrated or available."
    ),
)
def get_affected_subscribers(
    incident_id: str,
    db: sqlite3.Connection = Depends(get_db),
    adapter: DependencyAnalysisAdapter = Depends(get_dependency_adapter),
) -> AffectedSubscribersResponse:
    """
    Determine affected subscribers based on graph dependencies.

    - 200: Affected subscribers successfully determined.
    - 404: Incident ID not found.
    - 503: Graph dependency engine is unavailable.
    """
    # 1. Verify incident exists
    incident = get_incident(db, incident_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found",
        )

    # 2. Invoke dependency analysis adapter
    try:
        subscribers = adapter.get_affected_subscribers(
            incident_id=incident_id,
            suspected_component_id=incident.get("suspected_component_id"),
            suspected_component_type=incident.get("suspected_component_type"),
            db_conn=db,
        )
    except GraphEngineUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return AffectedSubscribersResponse(
        count=len(subscribers),
        subscribers=[AffectedSubscriberItem(**s) for s in subscribers],
    )


@router.get(
    "/incidents/{incident_id}/business-impact",
    response_model=BusinessImpactResponse,
    summary="Get business impact and SLA credits for an incident",
    description=(
        "Returns affected subscribers, monthly revenue at risk, outage duration, "
        "and estimated SLA credit owed."
    ),
)
def get_business_impact(
    incident_id: str,
    db: sqlite3.Connection = Depends(get_db),
    adapter: DependencyAnalysisAdapter = Depends(get_dependency_adapter),
) -> BusinessImpactResponse:
    """
    Calculate commercial and business impact for an incident.

    - 200: Business impact computed successfully.
    - 404: Incident ID not found.
    - 503: Graph dependency engine is unavailable.
    """
    # 1. Check if incident exists (engine memory or SQLite)
    incident = None
    try:
        engine_incident = get_incident_details(incident_id)
        if engine_incident is not None:
            incident = engine_incident.model_dump()
    except Exception:
        pass

    if incident is None:
        incident = get_incident(db, incident_id)

    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found",
        )

    # 2. Invoke dependency analysis adapter to determine affected subscribers
    try:
        raw_subs = adapter.get_affected_subscribers(
            incident_id=incident_id,
            suspected_component_id=incident.get("suspected_component_id"),
            suspected_component_type=incident.get("suspected_component_type"),
            db_conn=db,
        )
    except GraphEngineUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    # 3. Compute outage duration so far
    created_at_str = incident.get("created_at") or datetime.now(timezone.utc).isoformat()
    try:
        start_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        now_dt = datetime.now(timezone.utc)
        duration_seconds = max(0.0, (now_dt - start_dt).total_seconds())
    except Exception:
        duration_seconds = 0.0

    duration_minutes = round(duration_seconds / 60.0, 1)
    mins = int(duration_seconds // 60)
    hours = mins // 60
    rem_mins = mins % 60
    formatted_duration = f"{hours}h {rem_mins}m" if hours > 0 else f"{mins}m"

    # 4. Enrich affected subscribers with plan prices and villages
    enriched_subs: list[BusinessImpactSubscriber] = []
    households_by_village: dict[str, int] = {}
    total_revenue_at_risk = 0.0

    plan_defaults = {"Basic": 399.0, "Enterprise": 999.0, "Community": 0.0}

    for s in raw_subs:
        ap_id = s.get("access_point_id", "")
        village = AP_TO_VILLAGE.get(ap_id, "Unknown")
        plan = s.get("plan") or "Basic"
        raw_price = s.get("plan_price")
        price = float(raw_price) if raw_price is not None else plan_defaults.get(plan, 399.0)
        total_revenue_at_risk += price
        households_by_village[village] = households_by_village.get(village, 0) + 1

        enriched_subs.append(
            BusinessImpactSubscriber(
                id=s["id"],
                display_name=s.get("display_name", s["id"]),
                plan=plan,
                plan_price=price,
                access_point_id=ap_id,
                village=village,
                status=s.get("status", "active"),
                payment_status=s.get("payment_status", "paid"),
                due_date=s.get("due_date"),
            )
        )

    # 5. Calculate SLA credit owed (configurable rate per hour * duration in hours * revenue at risk)
    duration_hours = duration_seconds / 3600.0
    rate = settings.sla_credit_rate_per_hour
    sla_credit = round(total_revenue_at_risk * rate * duration_hours, 2)
    total_revenue_at_risk = round(total_revenue_at_risk, 2)

    return BusinessImpactResponse(
        incident_id=incident_id,
        status=incident.get("status", "open"),
        suspected_component_id=incident.get("suspected_component_id"),
        affected_count=len(enriched_subs),
        monthly_revenue_at_risk=total_revenue_at_risk,
        revenue_at_risk=total_revenue_at_risk,
        outage_duration_seconds=round(duration_seconds, 1),
        outage_duration_minutes=duration_minutes,
        outage_duration_formatted=formatted_duration,
        sla_credit_rate_per_hour=rate,
        estimated_sla_credit_owed=sla_credit,
        sla_credits_owed=sla_credit,
        households_by_village=households_by_village,
        affected_subscribers=enriched_subs,
    )


def reconcile_notify_recipients(
    db: sqlite3.Connection,
    raw_subs: list[dict[str, Any]],
    suspected_component_id: str | None = None,
) -> list[dict[str, Any]]:
    """Two-way reconciliation between graph dependency analysis and SQLite subscribers table.

    1. Forward reconciliation: verifies each graph subscriber exists in SQLite.
       Logs warning for phantom/missing IDs and discards them.
    2. Reverse reconciliation: computes SQLite subscribers under affected access points
       or villages, compares them with the graph result, logs any mismatch,
       and includes the extra subscribers in the send list.
    """
    graph_sub_ids = {s["id"] for s in raw_subs if "id" in s}
    affected_aps = {
        s.get("access_point_id") for s in raw_subs if s.get("access_point_id")
    }
    if suspected_component_id and suspected_component_id.startswith("AP"):
        affected_aps.add(suspected_component_id)

    # 1. Fetch SQLite subscribers for all graph-identified IDs
    sqlite_subs_by_id = {s["id"]: s for s in get_subscribers_by_ids(db, list(graph_sub_ids))}

    # 2. Fetch SQLite subscribers for all affected access points
    sqlite_ap_subs: list[dict[str, Any]] = []
    if affected_aps:
        placeholders = ",".join("?" for _ in affected_aps)
        cursor = db.execute(
            f"""
            SELECT id, display_name, plan, plan_price, phone, preferred_language,
                   access_point_id, status, payment_status, due_date
            FROM subscribers
            WHERE access_point_id IN ({placeholders})
            ORDER BY id ASC;
            """,
            list(affected_aps),
        )
        sqlite_ap_subs = [dict(r) for r in cursor.fetchall()]

    all_sqlite_subs = dict(sqlite_subs_by_id)
    for s in sqlite_ap_subs:
        all_sqlite_subs[s["id"]] = s

    # Forward check: graph ID not in SQLite
    for s in raw_subs:
        sid = s.get("id")
        if sid and sid not in all_sqlite_subs:
            logger.warning(
                "Subscriber ID %s from graph not found in SQLite subscribers table", sid
            )

    # Base list from confirmed graph subscribers
    enriched_subs = [all_sqlite_subs[s["id"]] for s in raw_subs if s.get("id") in all_sqlite_subs]
    seen_ids = {s["id"] for s in enriched_subs}

    # Reverse check: SQLite subscriber in affected AP missed by graph
    for s in sqlite_ap_subs:
        sid = s["id"]
        if sid not in graph_sub_ids:
            logger.warning(
                "Subscriber ID %s in SQLite under affected AP %s not returned by graph dependency query; reconciling into recipient list",
                sid,
                s.get("access_point_id"),
            )
            if sid not in seen_ids:
                enriched_subs.append(s)
                seen_ids.add(sid)

    return enriched_subs


@router.get(
    "/incidents/{incident_id}/notifications/preview",
    response_model=NotificationPreviewResponse,
    summary="Preview outage notifications for affected subscribers",
    description=(
        "Builds localized notification messages for affected subscribers in their "
        "preferred languages using deterministic templates and optional Sarvam translation. "
        "Works when provider is unconfigured (returns HTTP 200 with provider_available=False)."
    ),
)
def preview_incident_notifications(
    incident_id: str,
    channel: str = "sms",
    kind: Optional[str] = Query(None, description="Alert kind: outage or restoration"),
    message_kind: Optional[str] = Query(None, description="Alert kind: outage or restoration"),
    db: sqlite3.Connection = Depends(get_db),
    adapter: DependencyAnalysisAdapter = Depends(get_dependency_adapter),
) -> NotificationPreviewResponse:
    # 1. Verify incident exists
    incident = get_incident(db, incident_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found",
        )

    target_kind = (kind or message_kind or "outage").lower()
    if target_kind not in ("outage", "restoration"):
        target_kind = "outage"

    # 2. Check notification provider (preview works even when unconfigured)
    notif_provider_name = "unavailable"
    provider_available = False
    try:
        notif_provider = get_notification_provider()
        notif_provider_name = notif_provider.provider_name
        provider_available = (notif_provider_name != "unavailable")
    except Exception:
        pass

    # 3. Check explanation provider (optional, falls back gracefully to hi/en deterministic templates)
    explanation_provider = None
    try:
        expl_candidate = get_explanation_provider()
        if expl_candidate.provider_name != "unavailable":
            explanation_provider = expl_candidate
    except Exception:
        pass

    # 4. Determine affected subscribers & perform two-way reconciliation with SQLite
    try:
        raw_subs = adapter.get_affected_subscribers(
            incident_id=incident_id,
            suspected_component_id=incident.get("suspected_component_id"),
            suspected_component_type=incident.get("suspected_component_type"),
            db_conn=db,
        )
    except GraphEngineUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    enriched_subs = reconcile_notify_recipients(
        db=db,
        raw_subs=raw_subs,
        suspected_component_id=incident.get("suspected_component_id"),
    )

    # 5. Restoration messages default to subscribers whose outage message was sent
    if target_kind == "restoration":
        sent_outage_subs = get_subscribers_sent_outage(db, incident_id)
        enriched_subs = [s for s in enriched_subs if s.get("id") in sent_outage_subs]

    # 6. Generate previews
    previews_data = generate_notification_previews(
        incident=incident,
        subscribers=enriched_subs,
        explanation_provider=explanation_provider,
        channel=channel,
        message_kind=target_kind,
    )

    return NotificationPreviewResponse(
        incident_id=incident_id,
        channel=channel,
        message_kind=target_kind,
        provider=notif_provider_name,
        provider_available=provider_available,
        affected_subscribers_count=len(previews_data),
        previews=[NotificationPreviewItem(**p) for p in previews_data],
    )


@router.get(
    "/notifications/status",
    summary="Check outage notification provider status",
    description="Returns current notification provider availability and configuration detail.",
)
def get_notification_provider_status() -> dict[str, Any]:
    try:
        notif_provider = get_notification_provider()
        if notif_provider.provider_name == "unavailable":
            return {
                "available": False,
                "provider": notif_provider.provider_name,
                "reason": "Outage notification provider is not configured. Set NOTIFICATION_PROVIDER=console or twilio.",
            }
        return {
            "available": True,
            "provider": notif_provider.provider_name,
            "reason": None,
        }
    except Exception as exc:
        return {
            "available": False,
            "provider": "unavailable",
            "reason": str(exc),
        }


@router.post(
    "/incidents/{incident_id}/notify",
    response_model=NotificationSendResponse,
    summary="Send outage notifications to affected subscribers",
    description=(
        "Dispatches localized outage alert notifications to affected subscribers "
        "via the configured notification provider (Console or Twilio). "
        "Returns HTTP 503 if notification provider is unavailable."
    ),
)
def send_incident_notifications(
    incident_id: str,
    payload: Optional[NotificationSendRequest] = None,
    db: sqlite3.Connection = Depends(get_db),
    adapter: DependencyAnalysisAdapter = Depends(get_dependency_adapter),
) -> NotificationSendResponse:
    # 1. Verify incident exists
    incident = get_incident(db, incident_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found",
        )

    # 2. Check notification provider (must be configured to send)
    try:
        notif_provider = get_notification_provider()
        if notif_provider.provider_name == "unavailable":
            raise NotificationProviderUnavailableError(
                "Outage notification provider is not configured. Set NOTIFICATION_PROVIDER=console or twilio."
            )
    except NotificationProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    # 3. Check explanation provider (optional, fallback to deterministic templates)
    explanation_provider = None
    try:
        expl_candidate = get_explanation_provider()
        if expl_candidate.provider_name != "unavailable":
            explanation_provider = expl_candidate
    except Exception:
        pass

    target_kind = (payload.message_kind if payload and payload.message_kind else "outage").lower()
    if target_kind not in ("outage", "restoration"):
        target_kind = "outage"

    # 4. Determine affected subscribers
    try:
        raw_subs = adapter.get_affected_subscribers(
            incident_id=incident_id,
            suspected_component_id=incident.get("suspected_component_id"),
            suspected_component_type=incident.get("suspected_component_type"),
            db_conn=db,
        )
    except GraphEngineUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    channel = (payload.channel if payload else "sms") or "sms"

    # Reconcile graph subscriber analysis with SQLite in both directions
    enriched_subs = reconcile_notify_recipients(
        db=db,
        raw_subs=raw_subs,
        suspected_component_id=incident.get("suspected_component_id"),
    )

    # Restoration messages default to subscribers whose outage message was sent
    if target_kind == "restoration" and not (payload and payload.subscriber_ids):
        sent_outage_subs = get_subscribers_sent_outage(db, incident_id)
        enriched_subs = [s for s in enriched_subs if s.get("id") in sent_outage_subs]

    if payload and payload.subscriber_ids:
        target_ids = set(payload.subscriber_ids)
        enriched_subs = [s for s in enriched_subs if s.get("id") in target_ids]

    # 5. Dispatch notifications with atomic SQLite claim & idempotency
    try:
        dispatch_res = dispatch_outage_notifications(
            incident=incident,
            subscribers=enriched_subs,
            notification_provider=notif_provider,
            db_conn=db,
            explanation_provider=explanation_provider,
            channel=channel,
            message_kind=target_kind,
        )
    except NotificationProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return NotificationSendResponse(
        incident_id=incident_id,
        provider=dispatch_res["provider"],
        channel=dispatch_res["channel"],
        message_kind=target_kind,
        total_targeted=dispatch_res["total_targeted"],
        sent_count=dispatch_res["sent_count"],
        failed_count=dispatch_res["failed_count"],
        skipped_count=dispatch_res.get("skipped_count", 0),
        deliveries=[NotificationDeliveryItem(**d) for d in dispatch_res["deliveries"]],
    )


@router.get(
    "/incidents/{incident_id}/notifications",
    response_model=NotificationDeliveriesListResponse,
    summary="Get delivery history of notifications for an incident",
    description="Returns persisted delivery records for an incident with masked phone numbers for privacy audit.",
)
def get_incident_notifications(
    incident_id: str,
    kind: Optional[str] = Query(None, description="Filter by outage or restoration"),
    message_kind: Optional[str] = Query(None, description="Filter by outage or restoration"),
    db: sqlite3.Connection = Depends(get_db),
) -> NotificationDeliveriesListResponse:
    incident = get_incident(db, incident_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found",
        )

    target_kind = kind or message_kind
    records = list_notification_deliveries(db, incident_id, message_kind=target_kind)
    deliveries = []
    sent_count = 0
    failed_count = 0
    skipped_count = 0

    for r in records:
        st = r["status"]
        if st in ("sent", "simulated"):
            sent_count += 1
        elif st == "failed":
            failed_count += 1
        elif st == "skipped":
            skipped_count += 1

        prov = r.get("provider") or "console"
        human_status = (
            "simulated (not delivered)"
            if prov == "console" and st in ("sent", "simulated")
            else (f"skipped ({r.get('skip_reason')})" if st == "skipped" else st)
        )
        deliveries.append(
            NotificationDeliveryItem(
                subscriber_id=r["subscriber_id"],
                recipient=mask_phone(r.get("recipient")),
                status=st,
                delivery_status=human_status,
                skip_reason=r.get("skip_reason"),
                message_id=r.get("message_id"),
                message_kind=r.get("message_kind") or "outage",
                channel=r.get("channel") or "sms",
                provider=prov,
                message=r.get("message") or "",
                error=r.get("skip_reason") if st == "failed" else None,
                created_at=r.get("created_at"),
            )
        )

    return NotificationDeliveriesListResponse(
        incident_id=incident_id,
        total_count=len(deliveries),
        sent_count=sent_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
        deliveries=deliveries,
    )
