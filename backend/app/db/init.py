"""
Database initialization and demo data seeding.

Creates required SQLite tables with relational constraints and seeds
clearly labeled demo subscribers and incidents without duplicating or overwriting on repeated runs.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from app.db.connection import get_db_connection

# ── DDL ──────────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS subscribers (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    plan TEXT NOT NULL,
    access_point_id TEXT NOT NULL,
    status TEXT NOT NULL,
    payment_status TEXT NOT NULL,
    due_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payment_reminders (
    id TEXT PRIMARY KEY,
    subscriber_id TEXT NOT NULL,
    language TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    delivery_status TEXT NOT NULL,
    FOREIGN KEY (subscriber_id) REFERENCES subscribers (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    run_id TEXT,
    status TEXT NOT NULL,
    suspected_component_id TEXT,
    suspected_component_type TEXT,
    summary TEXT NOT NULL,
    confidence_score REAL,
    evidence TEXT NOT NULL DEFAULT '[]',
    uncertainty_note TEXT,
    data_source TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

# ── Clearly Labeled Demo Data ────────────────────────────────────────────────

DEMO_SUBSCRIBERS: list[dict[str, Any]] = [
    {
        "id": "SUB101",
        "display_name": "Demo Subscriber 101",
        "plan": "Basic",
        "access_point_id": "AP1",
        "status": "active",
        "payment_status": "paid",
        "due_date": "2026-11-01",
    },
    {
        "id": "SUB102",
        "display_name": "Demo Subscriber 102",
        "plan": "Standard",
        "access_point_id": "AP1",
        "status": "active",
        "payment_status": "overdue",
        "due_date": "2026-10-25",
    },
    {
        "id": "SUB201",
        "display_name": "Demo Subscriber 201",
        "plan": "Premium",
        "access_point_id": "AP2",
        "status": "active",
        "payment_status": "pending",
        "due_date": "2026-11-05",
    },
    {
        "id": "SUB202",
        "display_name": "Demo Subscriber 202",
        "plan": "Basic",
        "access_point_id": "AP2",
        "status": "active",
        "payment_status": "overdue",
        "due_date": "2026-10-20",
    },
]

DEMO_INCIDENTS: list[dict[str, Any]] = [
    {
        "id": "incident-001",
        "run_id": "run-001",
        "status": "open",
        "suspected_component_id": "L2",
        "suspected_component_type": "link",
        "summary": "Potential intermediate-link degradation",
        "confidence_score": None,
        "evidence": "[]",
        "uncertainty_note": None,
        "data_source": "simulated",
        "created_at": "2026-10-29T10:00:00Z",
    }
]


def init_db(
    db_path: str | None = None,
    seed_demo: bool = True,
    seed_incidents: bool = True,
) -> None:
    """
    Initialize SQLite schema safely.

    - Creates tables if they do not exist.
    - If seed_demo is True, inserts DEMO_SUBSCRIBERS using ON CONFLICT DO NOTHING.
    - If seed_incidents is True and seed_demo is True, inserts DEMO_INCIDENTS using ON CONFLICT DO NOTHING.
    - Preserves all existing records and guarantees zero duplicates on repeated runs.
    """
    conn = get_db_connection(db_path)
    try:
        conn.executescript(SCHEMA_SQL)

        if seed_demo:
            conn.executemany(
                """
                INSERT INTO subscribers (
                    id, display_name, plan, access_point_id, status, payment_status, due_date
                ) VALUES (
                    :id, :display_name, :plan, :access_point_id, :status, :payment_status, :due_date
                )
                ON CONFLICT(id) DO NOTHING;
                """,
                DEMO_SUBSCRIBERS,
            )

            if seed_incidents:
                conn.executemany(
                    """
                    INSERT INTO incidents (
                        id, run_id, status, suspected_component_id, suspected_component_type,
                        summary, confidence_score, evidence, uncertainty_note, data_source, created_at
                    ) VALUES (
                        :id, :run_id, :status, :suspected_component_id, :suspected_component_type,
                        :summary, :confidence_score, :evidence, :uncertainty_note, :data_source, :created_at
                    )
                    ON CONFLICT(id) DO NOTHING;
                    """,
                    DEMO_INCIDENTS,
                )

            conn.commit()
    finally:
        conn.close()
