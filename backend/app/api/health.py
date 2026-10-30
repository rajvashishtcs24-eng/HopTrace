"""
GET /api/v1/health

Returns a fixed status/version payload.  No external dependencies.
"""
from fastapi import APIRouter

from app.config import settings
from app.schemas.health import HealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns the API status and version.  Always 200 when the server is running.",
)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=settings.app_version)
