"""
Automated tests for Incident Explanation endpoint (Milestone 6).

Tests:
1. POST /api/v1/incidents/{incident_id}/explain returns 404 for unknown incident.
2. POST /api/v1/incidents/{incident_id}/explain returns 422 for invalid request body (empty/blank language).
3. POST /api/v1/incidents/{incident_id}/explain returns 503 when explanation provider is unavailable.
4. POST /api/v1/incidents/{incident_id}/explain returns 200 with grounded explanation when provider succeeds.
5. Provider registry selection for unavailable, sarvam, and invalid settings.
6. SarvamExplanationProvider initialization guards (rejects blank model, non-positive timeout).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.providers.explanations import (
    ExplanationProvider,
    ExplanationProviderUnavailableError,
    SarvamExplanationProvider,
    UnavailableExplanationProvider,
)
from app.providers.registry import get_explanation_provider


class MockWorkingExplanationProvider(ExplanationProvider):
    """Test double provider returning verified grounded explanation."""

    @property
    def provider_name(self) -> str:
        return "mock_provider"

    def explain_incident(self, incident: dict[str, Any], language: str) -> str:
        return f"Incident {incident['id']} occurred on {incident['suspected_component_id']} in language {language}"


def test_explain_unknown_incident_returns_404(client: TestClient, isolated_db: str) -> None:
    """Non-existent incident ID must return 404 Not Found."""
    resp = client.post(
        "/api/v1/incidents/unknown-incident-9999/explain",
        json={"language": "hi"},
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_explain_empty_language_returns_422(client: TestClient, isolated_db: str) -> None:
    """Empty or whitespace-only language must return 422 Unprocessable Entity."""
    # Empty string
    r1 = client.post(
        "/api/v1/incidents/incident-001/explain",
        json={"language": ""},
    )
    assert r1.status_code == 422

    # Whitespace only
    r2 = client.post(
        "/api/v1/incidents/incident-001/explain",
        json={"language": "   "},
    )
    assert r2.status_code == 422

    # Missing field
    r3 = client.post(
        "/api/v1/incidents/incident-001/explain",
        json={},
    )
    assert r3.status_code == 422


def test_explain_provider_unavailable_returns_503(client: TestClient, isolated_db: str) -> None:
    """When the default unavailable provider is active, explain endpoint returns 503."""
    resp = client.post(
        "/api/v1/incidents/incident-001/explain",
        json={"language": "hi"},
    )
    assert resp.status_code == 503
    assert "not currently available" in resp.json()["detail"].lower()


def test_explain_success_with_provider(client: TestClient, isolated_db: str) -> None:
    """When a provider successfully returns an explanation, returns 200 with correct schema."""
    app.dependency_overrides[get_explanation_provider] = lambda: MockWorkingExplanationProvider()
    try:
        resp = client.post(
            "/api/v1/incidents/incident-001/explain",
            json={"language": "hi"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["incident_id"] == "incident-001"
        assert data["language"] == "hi"
        assert "incident-001" in data["explanation"]
        assert data["provider"] == "mock_provider"
    finally:
        app.dependency_overrides.pop(get_explanation_provider, None)


def test_registry_explanation_provider_selection(monkeypatch) -> None:
    """Registry correctly selects UnavailableExplanationProvider or SarvamExplanationProvider."""
    # 1. unavailable
    monkeypatch.setattr(settings, "explanation_provider", "unavailable")
    p1 = get_explanation_provider()
    assert isinstance(p1, UnavailableExplanationProvider)
    assert p1.provider_name == "unavailable"

    # 2. sarvam
    monkeypatch.setattr(settings, "explanation_provider", "sarvam")
    monkeypatch.setattr(settings, "sarvam_api_key", "test-key")
    monkeypatch.setattr(settings, "sarvam_model", "sarvam-105b")
    monkeypatch.setattr(settings, "sarvam_timeout_seconds", 30.0)
    p2 = get_explanation_provider()
    assert isinstance(p2, SarvamExplanationProvider)
    assert p2.provider_name == "sarvam"

    # 3. invalid
    monkeypatch.setattr(settings, "explanation_provider", "unsupported_provider")
    with pytest.raises(ValueError) as exc:
        get_explanation_provider()
    assert "Unknown EXPLANATION_PROVIDER='unsupported_provider'" in str(exc.value)


def test_sarvam_provider_init_guards() -> None:
    """SarvamExplanationProvider rejects invalid constructor parameters."""
    # Blank model
    with pytest.raises(ValueError) as exc1:
        SarvamExplanationProvider(api_key="key", model="", timeout_seconds=10.0)
    assert "non-blank" in str(exc1.value)

    with pytest.raises(ValueError) as exc2:
        SarvamExplanationProvider(api_key="key", model="   ", timeout_seconds=10.0)
    assert "non-blank" in str(exc2.value)

    # Non-positive timeout
    with pytest.raises(ValueError) as exc3:
        SarvamExplanationProvider(api_key="key", model="sarvam-105b", timeout_seconds=0.0)
    assert "greater than zero" in str(exc3.value)

    with pytest.raises(ValueError) as exc4:
        SarvamExplanationProvider(api_key="key", model="sarvam-105b", timeout_seconds=-5.0)
    assert "greater than zero" in str(exc4.value)


def test_sarvam_provider_missing_key_raises_unavailable() -> None:
    """SarvamExplanationProvider raises ExplanationProviderUnavailableError if key is missing."""
    provider = SarvamExplanationProvider(api_key="", model="sarvam-105b", timeout_seconds=30.0)
    with pytest.raises(ExplanationProviderUnavailableError) as exc:
        provider.explain_incident({"id": "inc-1"}, "hi")
    assert "not configured" in str(exc.value).lower()
