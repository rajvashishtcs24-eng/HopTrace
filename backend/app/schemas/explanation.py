"""
Pydantic schemas for incident natural language explanation endpoint.

Follows docs/api-contract.md Section 10.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class IncidentExplanationRequest(BaseModel):
    language: str = Field(
        ...,
        description="Target language code for the explanation (e.g. 'hi' for Hindi, 'en' for English)",
        examples=["hi"],
    )

    @field_validator("language")
    @classmethod
    def validate_language_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("language must not be empty or whitespace")
        return v.strip()


class IncidentExplanationResponse(BaseModel):
    incident_id: str = Field(
        ...,
        description="Unique identifier of the explained incident (e.g. incident-001)",
        examples=["incident-001"],
    )
    language: str = Field(
        ...,
        description="Language code of the explanation (e.g. hi, en)",
        examples=["hi"],
    )
    explanation: str = Field(
        ...,
        description="Natural language diagnostic explanation grounded in verified incident data",
        examples=["Hindi explanation based on verified incident data"],
    )
    provider: str = Field(
        ...,
        description="Explanation provider identifier (e.g. sarvam, template, simulated)",
        examples=["sarvam"],
    )
