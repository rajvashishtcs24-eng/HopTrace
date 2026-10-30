"""
Tests for FastAPI application lifespan in app.main.

Verifies:
- SQLite initialization occurs on startup.
- Engine topology seeding is called once during startup when TOPOLOGY_PROVIDER=engine.
- Engine topology seeding is not called when TOPOLOGY_PROVIDER=simulated.
- Engine seeding failure raises a clear RuntimeError with the original exception chained.
- TestClient startup triggers lifespan correctly.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app, lifespan


@pytest.mark.asyncio
async def test_lifespan_engine_provider_seeds_topology(monkeypatch) -> None:
    """When TOPOLOGY_PROVIDER=engine, lifespan seeds SQLite and the graph engine."""
    monkeypatch.setattr(settings, "topology_provider", "engine")

    with patch("app.main.init_db") as mock_init_db, \
         patch("app.engine.facade.seed_topology") as mock_seed_topo:
        mock_seed_topo.return_value = {"status": "seeded"}

        async with lifespan(app):
            pass

        mock_init_db.assert_called_once_with(
            db_path=settings.sqlite_db_path,
            seed_demo=settings.seed_demo_subscribers,
            seed_incidents=settings.seed_demo_incidents,
        )
        mock_seed_topo.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_simulated_provider_skips_engine_seeding(monkeypatch) -> None:
    """When TOPOLOGY_PROVIDER=simulated, lifespan seeds SQLite but NOT the graph engine."""
    monkeypatch.setattr(settings, "topology_provider", "simulated")

    with patch("app.main.init_db") as mock_init_db, \
         patch("app.engine.facade.seed_topology") as mock_seed_topo:

        async with lifespan(app):
            pass

        mock_init_db.assert_called_once_with(
            db_path=settings.sqlite_db_path,
            seed_demo=settings.seed_demo_subscribers,
            seed_incidents=settings.seed_demo_incidents,
        )
        mock_seed_topo.assert_not_called()


@pytest.mark.asyncio
async def test_lifespan_engine_seed_failure_raises_runtime_error(monkeypatch) -> None:
    """Engine seeding errors during startup raise a clear RuntimeError with cause chained."""
    monkeypatch.setattr(settings, "topology_provider", "engine")

    cause = RuntimeError("Graph database unreachable")
    with patch("app.main.init_db"), \
         patch("app.engine.facade.seed_topology", side_effect=cause):

        with pytest.raises(RuntimeError) as exc_info:
            async with lifespan(app):
                pass

        assert "Failed to initialize graph engine topology during startup" in str(exc_info.value)
        assert exc_info.value.__cause__ is cause


def test_lifespan_with_test_client_engine(monkeypatch) -> None:
    """End-to-end lifespan startup via TestClient with engine provider."""
    monkeypatch.setattr(settings, "topology_provider", "engine")

    with patch("app.engine.facade.seed_topology") as mock_seed_topo:
        mock_seed_topo.return_value = {"status": "seeded"}

        with TestClient(app) as tc:
            res = tc.get("/api/v1/health")
            assert res.status_code == 200

        mock_seed_topo.assert_called_once()
