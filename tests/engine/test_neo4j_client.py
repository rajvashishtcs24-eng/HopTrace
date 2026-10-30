"""Automated tests for Neo4j client connection handling, Aura configuration, and security."""

import pytest
from backend.app.engine import Neo4jClient, check_neo4j_health


def test_neo4j_client_reads_environment_variables(monkeypatch):
    """Validates that Neo4j client reads URI, username, and password from environment."""
    monkeypatch.setenv("NEO4J_URI", "bolt://192.168.1.100:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "custom_admin")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret123")

    client = Neo4jClient()
    assert client.uri == "bolt://192.168.1.100:7687"
    assert client.username == "custom_admin"
    assert client.password == "secret123"
    assert client.is_configured is True


def test_neo4j_client_default_parameters(monkeypatch):
    """Validates parameters when environment variables are unset without hardcoding localhost."""
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_USERNAME", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

    client = Neo4jClient()
    assert client.uri is None
    assert client.username == "neo4j"
    assert client.password == ""
    assert client.is_configured is False


def test_neo4j_client_aura_configuration():
    """Validates Aura configuration detection and credential masking."""
    client = Neo4jClient(
        uri="neo4j+s://abc12345.databases.neo4j.io",
        username="neo4j",
        password="supersecretpassword",
    )
    assert client.is_aura is True
    assert client.is_configured is True
    assert "supersecretpassword" not in client.sanitized_uri


def test_neo4j_client_missing_credentials_reasons(monkeypatch):
    """Validates missing credential detection and clear explanation."""
    monkeypatch.delenv("NEO4J_URI", raising=False)
    client = Neo4jClient()
    is_missing, reason = client.has_missing_credentials()
    assert is_missing is True
    assert "NEO4J_URI" in reason

    # Aura URI without password
    client_aura = Neo4jClient(uri="neo4j+s://my-db.databases.neo4j.io", password="")
    is_missing, reason = client_aura.has_missing_credentials()
    assert is_missing is True
    assert "NEO4J_PASSWORD" in reason


def test_neo4j_client_never_prints_password_in_errors():
    """Validates that passwords are never included in error messages."""
    client = Neo4jClient(
        uri="bolt://127.0.0.1:9999",
        username="neo4j",
        password="super_sensitive_password_xyz",
    )
    res = client.check_connection()
    assert res["connected"] is False
    assert "super_sensitive_password_xyz" not in str(res)


def test_neo4j_check_connection_graceful_offline_handling():
    """Validates that check_connection returns structured status without crashing when offline."""
    client = Neo4jClient(uri="bolt://127.0.0.1:9999", username="neo4j", password="bad")
    result = client.check_connection()

    assert isinstance(result, dict)
    assert result["connected"] is False
    assert result["error"] is not None
    assert "9999" in result["error"] or "unavailable" in result["error"].lower()


def test_neo4j_driver_lifecycle():
    """Validates driver initialization and safe cleanup."""
    client = Neo4jClient(uri="bolt://localhost:7687")
    client.close()
    assert client._driver is None


def test_facade_check_neo4j_health():
    """Validates check_neo4j_health facade function."""
    health = check_neo4j_health()
    assert isinstance(health, dict)
    assert "connected" in health
    assert "uri" in health
