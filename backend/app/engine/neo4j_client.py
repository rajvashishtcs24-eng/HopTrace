"""Neo4j client management for HopTrace.

Reads connection credentials strictly from environment variables:
- NEO4J_URI (e.g. neo4j+s://<dbid>.databases.neo4j.io for Neo4j Aura)
- NEO4J_USERNAME (default: neo4j)
- NEO4J_PASSWORD (required for authenticated databases like Neo4j Aura)

Security:
- Never hardcodes, logs, or prints credentials.
- Sanitizes URIs and error messages to prevent credential leakage.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from neo4j import GraphDatabase, Driver
from neo4j.exceptions import ServiceUnavailable, AuthError, Neo4jError


def _load_env() -> None:
    """Attempts to load .env from project root or backend folder if dotenv is available."""
    try:
        from dotenv import load_dotenv

        current_file = Path(__file__).resolve()
        # backend/app/engine/neo4j_client.py -> 4 parents to project root
        root_dir = current_file.parent.parent.parent.parent
        root_env = root_dir / ".env"
        if root_env.is_file():
            load_dotenv(root_env, override=False)

        backend_env = root_dir / "backend" / ".env"
        if backend_env.is_file():
            load_dotenv(backend_env, override=False)

        load_dotenv(override=False)
    except Exception:
        pass


# Automatically load env when module is imported
_load_env()


def sanitize_uri(uri: Optional[str]) -> str:
    """Masks embedded passwords in a connection URI.

    Example: 'neo4j+s://neo4j:secret@abc.databases.neo4j.io' ->
             'neo4j+s://neo4j:***@abc.databases.neo4j.io'
    """
    if not uri:
        return ""
    return re.sub(r"://([^:@]+):([^@]+)@", r"://\1:***@", uri)


def sanitize_error(error: Any, password: Optional[str] = None) -> str:
    """Strips passwords and sensitive tokens from error messages."""
    msg = str(error)
    if password and password in msg:
        msg = msg.replace(password, "***")
    msg = re.sub(r"://([^:@]+):([^@]+)@", r"://\1:***@", msg)
    return msg


class Neo4jClient:
    """Encapsulates Neo4j driver connection and query execution for HopTrace."""

    def __init__(
        self,
        uri: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        _load_env()
        raw_uri = uri if uri is not None else os.getenv("NEO4J_URI")
        self.uri: Optional[str] = raw_uri.strip() if raw_uri else None
        raw_user = username if username is not None else os.getenv("NEO4J_USERNAME", "neo4j")
        self.username: str = raw_user.strip() if raw_user else "neo4j"
        raw_pw = password if password is not None else os.getenv("NEO4J_PASSWORD", "")
        self.password: str = raw_pw.strip() if raw_pw else ""
        self._driver: Optional[Driver] = None

    @property
    def is_aura(self) -> bool:
        """Returns True if the target database is Neo4j Aura (cloud-hosted)."""
        if not self.uri:
            return False
        uri_lower = self.uri.lower()
        return "databases.neo4j.io" in uri_lower or any(
            uri_lower.startswith(p)
            for p in ("neo4j+s://", "neo4j+ssc://", "bolt+s://", "bolt+ssc://")
        )

    @property
    def sanitized_uri(self) -> str:
        """Returns the URI with credentials safely masked."""
        return sanitize_uri(self.uri)

    @property
    def is_configured(self) -> bool:
        """Returns True if a connection URI and necessary credentials are provided."""
        is_missing, _ = self.has_missing_credentials()
        return not is_missing

    def has_missing_credentials(self) -> Tuple[bool, Optional[str]]:
        """Checks for missing connection configuration.

        Returns:
            Tuple of (is_missing: bool, reason: Optional[str])
        """
        if not self.uri:
            return True, "NEO4J_URI environment variable is not configured."

        if not self.username:
            return True, "NEO4J_USERNAME environment variable is not configured."

        if self.is_aura and not self.password:
            return (
                True,
                f"NEO4J_PASSWORD environment variable is not configured for Neo4j Aura ({self.sanitized_uri}).",
            )

        return False, None

    def get_driver(self) -> Driver:
        """Lazily initializes and returns the Neo4j driver."""
        if self._driver is None:
            if not self.uri:
                raise ValueError("NEO4J_URI is not configured.")
            auth = (self.username, self.password) if self.password else None
            self._driver = GraphDatabase.driver(self.uri, auth=auth)
        return self._driver

    def check_connection(self) -> Dict[str, Any]:
        """Performs a lightweight connectivity check.

        Never includes sensitive credentials in return values or error messages.
        """
        is_missing, reason = self.has_missing_credentials()
        if is_missing:
            return {
                "connected": False,
                "uri": self.sanitized_uri,
                "error": reason,
            }

        try:
            driver = self.get_driver()
            driver.verify_connectivity()
            server_info = driver.get_server_info()
            return {
                "connected": True,
                "uri": self.sanitized_uri,
                "agent": server_info.agent,
                "protocol_version": str(server_info.protocol_version),
                "error": None,
            }
        except ServiceUnavailable as exc:
            clean_error = sanitize_error(exc, self.password)
            return {
                "connected": False,
                "uri": self.sanitized_uri,
                "error": f"Neo4j service unavailable at {self.sanitized_uri}: {clean_error}",
            }
        except AuthError as exc:
            clean_error = sanitize_error(exc, self.password)
            return {
                "connected": False,
                "uri": self.sanitized_uri,
                "error": f"Neo4j authentication failed for user '{self.username}': {clean_error}",
            }
        except Exception as exc:
            clean_error = sanitize_error(exc, self.password)
            return {
                "connected": False,
                "uri": self.sanitized_uri,
                "error": f"Neo4j connection error: {clean_error}",
            }

    def execute_query(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Executes a parameterized Cypher query and returns records as dictionaries."""
        driver = self.get_driver()
        params = parameters or {}
        try:
            with driver.session(database=database) as session:
                result = session.run(query, params)
                return [record.data() for record in result]
        except (Neo4jError, ServiceUnavailable, AuthError) as exc:
            clean_err = sanitize_error(exc, self.password)
            raise RuntimeError(f"Cypher execution failed: {clean_err}") from exc

    def execute_write(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Executes a write query within an explicit write transaction."""
        driver = self.get_driver()
        params = parameters or {}

        def _work(tx):
            res = tx.run(query, params)
            return [record.data() for record in res]

        try:
            with driver.session(database=database) as session:
                return session.execute_write(_work)
        except (Neo4jError, ServiceUnavailable, AuthError) as exc:
            clean_err = sanitize_error(exc, self.password)
            raise RuntimeError(f"Cypher write transaction failed: {clean_err}") from exc

    def close(self) -> None:
        """Closes the underlying Neo4j driver connection pool."""
        if self._driver is not None:
            self._driver.close()
            self._driver = None


# Global singleton instance for engine reuse
_default_client: Optional[Neo4jClient] = None


def get_neo4j_client() -> Neo4jClient:
    """Returns the shared Neo4jClient instance."""
    global _default_client
    if _default_client is None:
        _default_client = Neo4jClient()
    return _default_client
