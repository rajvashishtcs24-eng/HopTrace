"""Pytest configuration and fixtures for engine tests."""

import os
import sys
from pathlib import Path

# Add project root to sys.path so backend package is discoverable
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load .env files if python-dotenv is available
try:
    from dotenv import load_dotenv

    # 1. Project root .env
    root_env = PROJECT_ROOT / ".env"
    if root_env.is_file():
        load_dotenv(root_env, override=False)

    # 2. backend/.env
    backend_env = PROJECT_ROOT / "backend" / ".env"
    if backend_env.is_file():
        load_dotenv(backend_env, override=False)

    load_dotenv(override=False)
except Exception:
    pass


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: mark test as requiring a live Neo4j database"
    )
