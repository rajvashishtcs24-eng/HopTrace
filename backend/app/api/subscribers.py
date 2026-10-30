"""
Subscribers and payment reminder endpoints.

Implements:
- GET  /api/v1/subscribers
- POST /api/v1/subscribers/{subscriber_id}/remind
"""
from __future__ import annotations

import sqlite3
from fastapi import APIRouter, Depends, HTTPException, status

from app.db.connection import get_db
from app.db.repository import get_subscriber, list_subscribers, record_payment_reminder
from app.schemas.subscriber import (
    ReminderRequest,
    ReminderResponse,
    SubscriberListResponse,
)

router = APIRouter(tags=["subscribers"])


@router.get(
    "/subscribers",
    response_model=SubscriberListResponse,
    summary="List all subscribers",
    description=(
        "Returns all subscriber records from SQLite operational storage. "
        "Returns an empty list under the 'subscribers' key if no records exist."
    ),
)
def get_subscribers(
    db: sqlite3.Connection = Depends(get_db),
) -> SubscriberListResponse:
    """Read subscriber records from SQLite database."""
    items = list_subscribers(db)
    return SubscriberListResponse(subscribers=items)


@router.post(
    "/subscribers/{subscriber_id}/remind",
    response_model=ReminderResponse,
    status_code=status.HTTP_200_OK,
    summary="Record payment reminder action",
    description=(
        "Records a payment reminder request for a subscriber in the database. "
        "Returns delivery_status='not_sent' as no external messaging integration is configured."
    ),
)
def remind_subscriber(
    subscriber_id: str,
    payload: ReminderRequest,
    db: sqlite3.Connection = Depends(get_db),
) -> ReminderResponse:
    """
    Validate subscriber existence, record the reminder in SQLite, and return confirmation.

    - 200: Reminder action recorded in history.
    - 404: Unknown subscriber ID.
    - 422: Invalid request body or unsupported language.
    """
    # 1. Verify target subscriber exists
    subscriber = get_subscriber(db, subscriber_id)
    if subscriber is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subscriber '{subscriber_id}' not found",
        )

    # 2. Persist reminder in SQLite history
    try:
        result = record_payment_reminder(
            conn=db,
            subscriber_id=subscriber_id,
            language=payload.language,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record payment reminder: {exc}",
        ) from exc

    return ReminderResponse(**result)
