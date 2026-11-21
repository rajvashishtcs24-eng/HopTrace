"""
Shared pytest fixtures for the HopTrace test suite.

Ensures:
- Tests run against isolated temporary SQLite databases.
- The developer's real database is never touched.
- Dependency overrides are safely scoped and cleaned up.
- AUTH_DISABLED=true defaults across all test runs so existing test suite remains green.
- Clean defaults (GRAPH_BACKEND=memory, NOTIFICATION_PROVIDER=unavailable, EXPLANATION_PROVIDER=unavailable)
  so a local .env cannot change test results.
"""
from __future__ import annotations

import os

os.environ["AUTH_DISABLED"] = "true"
os.environ["GRAPH_BACKEND"] = "memory"
os.environ["NOTIFICATION_PROVIDER"] = "unavailable"
os.environ["EXPLANATION_PROVIDER"] = "unavailable"

from typing import Generator
import pytest
from fastapi.testclient import TestClient

from app.config import settings
settings.auth_disabled = True
settings.graph_backend = "memory"
settings.notification_provider = "unavailable"
settings.explanation_provider = "unavailable"

from app.db.connection import get_db, get_db_connection
from app.db.init import init_db
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def configure_session_test_db(tmp_path_factory) -> str:
    """Redirect default settings.sqlite_db_path to a temp file and ensure memory backend."""
    temp_dir = tmp_path_factory.mktemp("session_db")
    test_db_file = str(temp_dir / "hoptrace_test_session.db")
    settings.sqlite_db_path = test_db_file
    settings.auth_disabled = True
    settings.graph_backend = "memory"
    settings.notification_provider = "unavailable"
    settings.explanation_provider = "unavailable"
    os.environ["GRAPH_BACKEND"] = "memory"
    os.environ["NOTIFICATION_PROVIDER"] = "unavailable"
    os.environ["EXPLANATION_PROVIDER"] = "unavailable"
    init_db(test_db_file, seed_demo=True)
    return test_db_file


@pytest.fixture(autouse=True)
def ensure_clean_test_defaults() -> Generator[None, None, None]:
    """Ensure clean test defaults (auth, graph, notification, explanation) for each test."""
    orig_auth = settings.auth_disabled
    orig_graph = settings.graph_backend
    orig_notif = settings.notification_provider
    orig_expl = settings.explanation_provider
    settings.auth_disabled = True
    settings.graph_backend = "memory"
    settings.notification_provider = "unavailable"
    settings.explanation_provider = "unavailable"
    yield
    settings.auth_disabled = orig_auth
    settings.graph_backend = orig_graph
    settings.notification_provider = orig_notif
    settings.explanation_provider = orig_expl


@pytest.fixture
def client() -> TestClient:
    """TestClient wrapping FastAPI app."""
    return TestClient(app)


@pytest.fixture
def isolated_db(tmp_path) -> Generator[str, None, None]:
    """
    Creates a fresh temporary database with demo subscribers seeded.
    Overrides the get_db dependency for the duration of the test.
    """
    db_file = str(tmp_path / "test_isolated.db")
    init_db(db_file, seed_demo=True)

    def _override_get_db():
        conn = get_db_connection(db_file)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield db_file
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def empty_db(tmp_path) -> Generator[str, None, None]:
    """
    Creates a fresh temporary database with schema only (no subscribers seeded).
    Overrides the get_db dependency for the duration of the test.
    """
    db_file = str(tmp_path / "test_empty.db")
    init_db(db_file, seed_demo=False)

    def _override_get_db():
        conn = get_db_connection(db_file)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield db_file
    finally:
        app.dependency_overrides.pop(get_db, None)
