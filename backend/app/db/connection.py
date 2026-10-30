"""
SQLite database connection management.

Uses Python's standard library sqlite3 with:
- PRAGMA foreign_keys = ON enforced for relational integrity.
- sqlite3.Row row_factory for column-name access.
- FastAPI dependency injection via get_db().
"""
from __future__ import annotations

import sqlite3
from typing import Generator

from app.config import settings


def get_db_connection(db_path: str | None = None) -> sqlite3.Connection:
    """
    Open and configure a SQLite connection.

    Always enables foreign keys and sets row_factory to sqlite3.Row.
    """
    path = db_path if db_path is not None else settings.sqlite_db_path
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """
    FastAPI dependency yielding an open database connection.

    Ensures the connection is safely closed after the request finishes.
    In tests, this dependency can be overridden using app.dependency_overrides[get_db].
    """
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()
