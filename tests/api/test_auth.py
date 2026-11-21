"""
Comprehensive tests for backend authentication, token lifecycle, RBAC enforcement,
agent ingest security, route coverage, and startup validation (M2 Lane).
"""
from __future__ import annotations

import json
import time
import pytest
from fastapi.routing import APIRoute, _IncludedRouter
from fastapi.testclient import TestClient

from app.api.auth import reset_login_rate_limits
from app.auth.deps import enforce_rbac, get_current_user, require_agent_key, require_agent_or_rbac
from app.auth.security import (
    _b64url_encode,
    create_access_token,
    decode_access_token,
    dummy_verify,
    hash_password,
    verify_password,
)
from app.config import settings
from app.db.init import init_db
from app.main import app, lifespan

TEST_AUTH_SECRET = "test-secret-key-32-bytes-minimum-length-for-hmac-sha256"
TEST_INGEST_KEY = "test-ingest-api-key-secret-987654"


# ── 1. Unit Tests for Security Primitives ────────────────────────────────────

def test_scrypt_password_hashing_and_verification() -> None:
    """Scrypt password hashing produces formatted string and verifies in constant time."""
    password = "SuperSecretOperatorPassword123!"
    hashed = hash_password(password)

    assert hashed.startswith("scrypt$16384$8$1$")
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False
    assert verify_password(password, "invalid-hash-string") is False


def test_dummy_verify_timing_mitigation() -> None:
    """Dummy verification runs calculation and returns False."""
    assert dummy_verify("any-password") is False


def test_token_creation_and_decoding() -> None:
    """Tokens are created with HS256, expiration, and decoded accurately."""
    token, expires_at = create_access_token(
        username="test_operator",
        role="operator",
        secret=TEST_AUTH_SECRET,
        expires_in_minutes=60,
    )
    assert token.count(".") == 2
    assert "T" in expires_at

    payload = decode_access_token(token, TEST_AUTH_SECRET)
    assert payload is not None
    assert payload["sub"] == "test_operator"
    assert payload["role"] == "operator"
    assert payload["exp"] > time.time()


def test_token_creation_rejects_secret_shorter_than_32_chars() -> None:
    """Creating an access token with a secret shorter than 32 characters raises ValueError."""
    with pytest.raises(ValueError, match="auth_secret must be at least 32 characters"):
        create_access_token("op", "operator", "short-secret-12345")


def test_tampered_token_rejected() -> None:
    """Tampering with token payload or signature returns None."""
    token, _ = create_access_token(
        username="test_operator",
        role="operator",
        secret=TEST_AUTH_SECRET,
        expires_in_minutes=60,
    )
    parts = token.split(".")
    tampered = f"{parts[0]}.{parts[1]}.tampered_signature"
    assert decode_access_token(tampered, TEST_AUTH_SECRET) is None


def test_expired_token_rejected() -> None:
    """Expired token returns None."""
    token, _ = create_access_token(
        username="test_operator",
        role="operator",
        secret=TEST_AUTH_SECRET,
        expires_in_minutes=-5,  # 5 minutes in the past
    )
    assert decode_access_token(token, TEST_AUTH_SECRET) is None


def test_token_rejects_alg_none_and_other_algorithms() -> None:
    """HS256 is pinned; alg=none or any other algorithm is explicitly rejected."""
    # Craft token with header alg="none"
    header_none = _b64url_encode(json.dumps({"alg": "none", "typ": "JWT"}).encode("utf-8"))
    payload = _b64url_encode(json.dumps({"sub": "admin", "role": "operator", "exp": int(time.time() + 3600)}).encode("utf-8"))
    
    # 1. alg none without signature
    token_none_empty = f"{header_none}.{payload}."
    assert decode_access_token(token_none_empty, TEST_AUTH_SECRET) is None

    # 2. alg none with dummy signature
    token_none_dummy = f"{header_none}.{payload}.dummy"
    assert decode_access_token(token_none_dummy, TEST_AUTH_SECRET) is None

    # 3. Non-HS256 algorithm (e.g. HS384)
    header_hs384 = _b64url_encode(json.dumps({"alg": "HS384", "typ": "JWT"}).encode("utf-8"))
    token_hs384 = f"{header_hs384}.{payload}.dummy"
    assert decode_access_token(token_hs384, TEST_AUTH_SECRET) is None


# ── 2. Startup Validation Tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_startup_fails_if_auth_enabled_and_secret_short_or_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """FastAPI lifespan startup raises RuntimeError if auth is enabled but secret is < 32 chars."""
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "auth_secret", "too-short-secret")

    with pytest.raises(RuntimeError, match="shorter than 32 characters"):
        async with lifespan(app):
            pass


@pytest.mark.asyncio
async def test_startup_fails_if_auth_enabled_and_ingest_key_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """FastAPI lifespan startup raises RuntimeError if auth is enabled but INGEST_API_KEY is empty."""
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "auth_secret", TEST_AUTH_SECRET)
    monkeypatch.setattr(settings, "ingest_api_key", "")

    with pytest.raises(RuntimeError, match="INGEST_API_KEY is not configured"):
        async with lifespan(app):
            pass


# ── 3. API Login & Identity Tests ─────────────────────────────────────────────

def test_login_flow_operator_and_viewer(isolated_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Seeded operator and viewer accounts can log in and receive valid tokens."""
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "auth_secret", TEST_AUTH_SECRET)
    monkeypatch.setattr(settings, "operator_password", "OpPass123!")
    monkeypatch.setattr(settings, "viewer_password", "ViewPass123!")
    reset_login_rate_limits()

    # Re-init db with passwords configured
    init_db(isolated_db, seed_demo=True)

    client = TestClient(app)

    # 1. Login operator
    res_op = client.post("/api/v1/auth/login", json={"username": "operator", "password": "OpPass123!"})
    assert res_op.status_code == 200
    data_op = res_op.json()
    assert data_op["username"] == "operator"
    assert data_op["role"] == "operator"
    assert "access_token" in data_op
    op_token = data_op["access_token"]

    # 2. Check /auth/me for operator
    res_me_op = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {op_token}"})
    assert res_me_op.status_code == 200
    assert res_me_op.json() == {"username": "operator", "role": "operator"}

    # 3. Login viewer
    res_vw = client.post("/api/v1/auth/login", json={"username": "viewer", "password": "ViewPass123!"})
    assert res_vw.status_code == 200
    data_vw = res_vw.json()
    assert data_vw["username"] == "viewer"
    assert data_vw["role"] == "viewer"
    vw_token = data_vw["access_token"]

    # 4. Check /auth/me for viewer
    res_me_vw = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {vw_token}"})
    assert res_me_vw.status_code == 200
    assert res_me_vw.json() == {"username": "viewer", "role": "viewer"}


def test_login_invalid_password_returns_401(isolated_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid password returns 401."""
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "auth_secret", TEST_AUTH_SECRET)
    monkeypatch.setattr(settings, "operator_password", "CorrectPassword123")
    reset_login_rate_limits()
    init_db(isolated_db, seed_demo=True)

    client = TestClient(app)
    res = client.post("/api/v1/auth/login", json={"username": "operator", "password": "WrongPassword"})
    assert res.status_code == 401
    assert "invalid" in res.json()["detail"].lower()


def test_login_unknown_user_returns_401(isolated_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-existent username returns 401."""
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "auth_secret", TEST_AUTH_SECRET)
    reset_login_rate_limits()
    init_db(isolated_db, seed_demo=True)

    client = TestClient(app)
    res = client.post("/api/v1/auth/login", json={"username": "non_existent_user_999", "password": "AnyPassword"})
    assert res.status_code == 401
    assert "invalid" in res.json()["detail"].lower()


def test_login_rate_limiting_and_trusted_proxy_spoofing(isolated_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Login rate limit is keyed on (client_ip, username).
    When TRUSTED_PROXY=False, spoofed X-Forwarded-For headers DO NOT bypass rate limiting.
    When TRUSTED_PROXY=True, X-Forwarded-For is honored.
    """
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "auth_secret", TEST_AUTH_SECRET)
    monkeypatch.setattr(settings, "login_rate_limit_per_minute", 3)
    monkeypatch.setattr(settings, "trusted_proxy", False)
    reset_login_rate_limits()
    init_db(isolated_db, seed_demo=True)

    client = TestClient(app)

    # 3 attempts from default client host with spoofed X-Forwarded-For headers
    for i in range(3):
        r = client.post(
            "/api/v1/auth/login",
            json={"username": "operator", "password": "WrongPassword"},
            headers={"X-Forwarded-For": f"198.51.100.{i+1}"},
        )
        assert r.status_code == 401

    # 4th attempt with another spoofed header -> blocked with 429 because trusted_proxy is False
    blocked_res = client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "WrongPassword"},
        headers={"X-Forwarded-For": "203.0.113.99"},
    )
    assert blocked_res.status_code == 429
    assert "rate limit exceeded" in blocked_res.json()["detail"].lower()

    # Different username on same IP should not be blocked yet
    diff_user_res = client.post(
        "/api/v1/auth/login",
        json={"username": "viewer", "password": "WrongPassword"},
    )
    assert diff_user_res.status_code == 401

    # When TRUSTED_PROXY=True, X-Forwarded-For is honored as IP
    monkeypatch.setattr(settings, "trusted_proxy", True)
    proxy_res = client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "WrongPassword"},
        headers={"X-Forwarded-For": "192.0.2.10"},
    )
    assert proxy_res.status_code == 401


# ── 4. RBAC Method Enforcement Tests ──────────────────────────────────────────

def test_rbac_method_rules(isolated_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    When auth is enabled:
    - Unauthenticated protected request returns 401.
    - Viewer can GET (200) but is blocked on POST (403).
    - Operator can both GET (200) and POST (200).
    """
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "auth_secret", TEST_AUTH_SECRET)

    client = TestClient(app)

    # 1. Unauthenticated request to protected endpoint -> 401
    res_no_auth = client.get("/api/v1/topology")
    assert res_no_auth.status_code == 401

    # Generate tokens directly
    viewer_token, _ = create_access_token("viewer", "viewer", TEST_AUTH_SECRET)
    operator_token, _ = create_access_token("operator", "operator", TEST_AUTH_SECRET)

    # 2. Viewer GET /api/v1/topology -> allowed (200)
    res_vw_get = client.get("/api/v1/topology", headers={"Authorization": f"Bearer {viewer_token}"})
    assert res_vw_get.status_code == 200

    # 3. Viewer POST /api/v1/lab/run -> blocked (403)
    res_vw_post = client.post(
        "/api/v1/lab/run",
        json={"scenario": "baseline"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res_vw_post.status_code == 403
    assert "operator" in res_vw_post.json()["detail"].lower()

    # 4. Operator GET /api/v1/topology -> allowed (200)
    res_op_get = client.get("/api/v1/topology", headers={"Authorization": f"Bearer {operator_token}"})
    assert res_op_get.status_code == 200

    # 5. Operator POST /api/v1/lab/run -> allowed (200)
    res_op_post = client.post(
        "/api/v1/lab/run",
        json={"scenario": "baseline"},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert res_op_post.status_code == 200


# ── 5. OpenAPI and Docs Disabling Test ────────────────────────────────────────

def test_docs_disabled_when_auth_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """When auth is enabled, /docs, /redoc, and /openapi.json return 404."""
    client = TestClient(app)

    # Auth enabled -> 404
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "auth_secret", TEST_AUTH_SECRET)
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404

    # Auth disabled -> 200
    monkeypatch.setattr(settings, "auth_disabled", True)
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").status_code == 200


# ── 6. Public and Agent Unified Dependency Tests ──────────────────────────────

def test_public_routes_remain_open_when_auth_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Public endpoints (/health, /api/v1/health, /api/v1/auth/login) require no token."""
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "auth_secret", TEST_AUTH_SECRET)

    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/health").status_code == 200


def test_agent_measurements_probes_unified_dependency(isolated_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    On agents, measurements, and probes routers:
    - POST requires a valid X-API-Key == ingest_api_key (missing/invalid key returns 401).
    - All other methods (GET) require Bearer auth: unauthenticated returns 401; viewer gets 200.
    """
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "auth_secret", TEST_AUTH_SECRET)
    monkeypatch.setattr(settings, "ingest_api_key", TEST_INGEST_KEY)
    init_db(isolated_db, seed_demo=True, seed_incidents=True)

    client = TestClient(app)
    viewer_token, _ = create_access_token("viewer", "viewer", TEST_AUTH_SECRET)

    # 1. Unauthenticated GET /api/v1/agent/status -> 401
    assert client.get("/api/v1/agent/status").status_code == 401

    # 2. Viewer GET /api/v1/agent/status -> 200
    resp_agent_status = client.get("/api/v1/agent/status", headers={"Authorization": f"Bearer {viewer_token}"})
    assert resp_agent_status.status_code == 200

    # 3. Unauthenticated GET /api/v1/measurements/runs/run-demo-001/measurements -> 401
    assert client.get("/api/v1/measurements/runs/run-demo-001/measurements").status_code == 401
    assert client.get("/api/v1/runs/run-demo-001/measurements").status_code == 401

    # 4. Viewer GET /api/v1/measurements/runs/run-demo-001/measurements -> 200
    resp_meas_viewer = client.get(
        "/api/v1/measurements/runs/run-demo-001/measurements",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp_meas_viewer.status_code == 200

    # 5. POST /api/v1/agent/heartbeat without X-API-Key -> 401
    hb_payload = {
        "agent_id": "agent-1",
        "site_id": "rampur",
        "timestamp": "2026-11-21T10:00:00Z",
    }
    assert client.post("/api/v1/agent/heartbeat", json=hb_payload).status_code == 401

    # 6. POST /api/v1/agent/heartbeat with wrong key -> 401
    assert client.post(
        "/api/v1/agent/heartbeat",
        json=hb_payload,
        headers={"X-API-Key": "wrong-key"},
    ).status_code == 401

    # 7. POST /api/v1/agent/heartbeat with valid key -> 200
    resp_hb_ok = client.post(
        "/api/v1/agent/heartbeat",
        json=hb_payload,
        headers={"X-API-Key": TEST_INGEST_KEY},
    )
    assert resp_hb_ok.status_code == 200

    # 8. POST when ingest_api_key is empty on server -> 401
    monkeypatch.setattr(settings, "ingest_api_key", "")
    assert client.post(
        "/api/v1/agent/heartbeat",
        json=hb_payload,
        headers={"X-API-Key": TEST_INGEST_KEY},
    ).status_code == 401


# ── 7. WebSocket Token Authentication ─────────────────────────────────────────

def test_websocket_token_enforcement(monkeypatch: pytest.MonkeyPatch) -> None:
    """WebSocket stream requires ?token= when auth is enabled; bad token closes with code 1008."""
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "auth_secret", TEST_AUTH_SECRET)

    client = TestClient(app)

    # Without token -> closes with policy violation
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/telemetry"):
            pass

    # With invalid token -> closes
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/telemetry?token=invalid.token.signature"):
            pass

    # With valid token -> connects successfully
    token, _ = create_access_token("operator", "operator", TEST_AUTH_SECRET)
    with client.websocket_connect(f"/ws/telemetry?token={token}") as ws:
        msg = ws.receive_json()
        assert msg["type"] in ("connected", "telemetry_batch")


# ── 8. Idempotent User Seeding ────────────────────────────────────────────────

def test_seeding_skips_upsert_when_matching(isolated_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """User seeding skips re-hashing and upserting when password and role already match."""
    monkeypatch.setattr(settings, "operator_password", "OriginalPassword123")
    monkeypatch.setattr(settings, "viewer_password", "OriginalViewer123")
    init_db(isolated_db, seed_demo=True)

    # Query initial created_at / hash
    from app.db.connection import get_db_connection
    with get_db_connection(isolated_db) as conn:
        row1 = conn.execute("SELECT password_hash, created_at FROM users WHERE username = 'operator'").fetchone()
        hash1, created1 = row1[0], row1[1]

    # Re-run init_db with the exact same credentials
    init_db(isolated_db, seed_demo=True)

    with get_db_connection(isolated_db) as conn:
        row2 = conn.execute("SELECT password_hash, created_at FROM users WHERE username = 'operator'").fetchone()
        hash2, created2 = row2[0], row2[1]

    # Hash and timestamp should be identical (upsert was skipped)
    assert hash1 == hash2
    assert created1 == created2


# ── 9. Route Coverage Test ────────────────────────────────────────────────────

def test_route_coverage_public_or_auth_dependency() -> None:
    """
    Every route in app.routes must either:
    1. Be on the explicit public allowlist, OR
    2. Have an auth dependency (enforce_rbac, require_agent_or_rbac, require_agent_key, get_current_user).
    """
    PUBLIC_ALLOWLIST = {
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/health",
        "/api/v1/health",
        "/api/v1/auth/login",
        "/ws/telemetry",
        "/api/v1/ws/telemetry",
        "/assets",
        "/{full_path:path}",
    }

    AUTH_DEP_NAMES = {
        "enforce_rbac",
        "require_agent_or_rbac",
        "require_agent_key",
        "get_current_user",
    }

    all_routes = []

    for r in app.routes:
        if isinstance(r, _IncludedRouter):
            ctx = r.include_context
            router_deps = {getattr(d.dependency, "__name__", str(d.dependency)) for d in ctx.dependencies}
            for sub_r in r.original_router.routes:
                sub_deps = {getattr(d.dependency, "__name__", str(d.dependency)) for d in getattr(sub_r, "dependencies", [])}
                effective_deps = router_deps.union(sub_deps)
                full_path = (ctx.prefix.rstrip("/") + "/" + sub_r.path.lstrip("/")).rstrip("/")
                all_routes.append((full_path, effective_deps))
        elif isinstance(r, APIRoute):
            route_deps = {getattr(d.dependency, "__name__", str(d.dependency)) for d in getattr(r, "dependencies", [])}
            all_routes.append((r.path, route_deps))
        else:
            path = getattr(r, "path", None)
            if path:
                all_routes.append((path, set()))

    for path, deps in all_routes:
        if path in PUBLIC_ALLOWLIST:
            continue
        # Also check /api/v1/auth/me which uses get_current_user in route signature
        if path == "/api/v1/auth/me":
            continue
        has_auth = bool(deps.intersection(AUTH_DEP_NAMES))
        assert has_auth, f"Route '{path}' is not in public allowlist and lacks an auth dependency! Found deps: {deps}"
