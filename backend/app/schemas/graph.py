"""
Pydantic schemas for graph status and intelligence endpoints.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class GraphStatusResponse(BaseModel):
    backend: str
    fallback: bool
    latency_ms: Optional[float] = None
    last_error: Optional[str] = None
    reason: Optional[str] = None
