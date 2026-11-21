"""
Pydantic schemas for outage and restoration notification preview, dispatch, and delivery tracking.
"""
from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field

ChannelType = Literal["sms", "whatsapp"]
MessageKindType = Literal["outage", "restoration"]


class NotificationPreviewItem(BaseModel):
    subscriber_id: str = Field(..., description="Unique subscriber ID (e.g. SUB101)")
    subscriber_name: str = Field(..., description="Subscriber display name")
    phone: str = Field(..., description="Masked destination phone number (e.g. +91*****00)")
    phone_valid: bool = Field(True, description="Whether phone matches E.164 format")
    phone_validation_reason: Optional[str] = Field(None, description="Reason if phone number failed E.164 validation")
    village: Optional[str] = Field(None, description="Village location")
    is_essential: bool = Field(False, description="Whether subscriber is an essential public service")
    preferred_language: str = Field(..., description="Subscriber preferred language code (e.g. 'hi', 'en')")
    translation_source: str = Field(
        "template_hi",
        description="Source of rendered message (e.g. 'template_hi', 'template_en', 'sarvam', 'fallback_hi')",
    )
    message_kind: MessageKindType = Field("outage", description="Type of alert ('outage' or 'restoration')")
    channel: str = Field("sms", description="Delivery channel ('sms' or 'whatsapp')")
    message: str = Field(..., description="Rendered alert message in preferred language")


class NotificationPreviewResponse(BaseModel):
    incident_id: str = Field(..., description="Incident ID")
    channel: str = Field("sms", description="Target delivery channel")
    message_kind: MessageKindType = Field("outage", description="Type of alert ('outage' or 'restoration')")
    provider: str = Field("unavailable", description="Configured notification provider ('console', 'twilio', 'unavailable')")
    provider_available: bool = Field(False, description="Whether notification provider is currently available to send")
    affected_subscribers_count: int = Field(..., description="Count of affected subscribers")
    previews: List[NotificationPreviewItem] = Field(..., description="Preview items per subscriber")


class NotificationSendRequest(BaseModel):
    channel: ChannelType = Field("sms", description="Delivery channel: 'sms' or 'whatsapp'")
    message_kind: MessageKindType = Field("outage", description="Type of alert: 'outage' or 'restoration'")
    subscriber_ids: Optional[List[str]] = Field(
        None,
        description="Optional list of subscriber IDs to target. If omitted, sends to all eligible subscribers.",
    )


class NotificationDeliveryItem(BaseModel):
    subscriber_id: str = Field(..., description="Target subscriber ID")
    recipient: str = Field(..., description="Masked recipient phone number")
    status: str = Field(..., description="Delivery status ('sent', 'failed', 'skipped', 'queued')")
    delivery_status: Optional[str] = Field(None, description="Human-readable delivery status (e.g. 'simulated (not delivered)')")
    skip_reason: Optional[str] = Field(None, description="Reason if skipped (e.g. 'already_notified', 'invalid_e164_phone', 'not_in_allowlist')")
    message_id: Optional[str] = Field(None, description="External or internal message tracking ID")
    message_kind: MessageKindType = Field("outage", description="Alert kind ('outage' or 'restoration')")
    channel: str = Field(..., description="Channel used ('sms' or 'whatsapp')")
    provider: str = Field(..., description="Provider used ('console', 'twilio')")
    message: str = Field(..., description="Message text delivered")
    error: Optional[str] = Field(None, description="Error detail if delivery failed")
    created_at: Optional[str] = Field(None, description="ISO-8601 UTC delivery creation timestamp")


class NotificationSendResponse(BaseModel):
    incident_id: str = Field(..., description="Incident ID")
    provider: str = Field(..., description="Provider used ('console', 'twilio')")
    channel: str = Field(..., description="Delivery channel ('sms', 'whatsapp')")
    message_kind: MessageKindType = Field("outage", description="Alert kind ('outage' or 'restoration')")
    total_targeted: int = Field(..., description="Total target subscriber count")
    sent_count: int = Field(..., description="Successfully dispatched count")
    failed_count: int = Field(..., description="Failed dispatch count")
    skipped_count: int = Field(0, description="Skipped count")
    deliveries: List[NotificationDeliveryItem] = Field(..., description="Detailed delivery results")


class NotificationDeliveriesListResponse(BaseModel):
    incident_id: str = Field(..., description="Incident ID")
    total_count: int = Field(..., description="Total persisted delivery count")
    sent_count: int = Field(..., description="Count of sent/delivered records")
    failed_count: int = Field(..., description="Count of failed records")
    skipped_count: int = Field(..., description="Count of skipped records")
    deliveries: List[NotificationDeliveryItem] = Field(..., description="List of persisted delivery records")
