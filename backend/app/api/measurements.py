"""
Test run measurements retrieval endpoint.

Implements:
- GET /api/v1/runs/{run_id}/measurements

Follows docs/api-contract.md Section 7.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.engine.facade import get_run_measurements
from app.schemas.measurements import RunMeasurementsResponse

router = APIRouter(tags=["measurements"])


@router.get(
    "/runs/{run_id}/measurements",
    response_model=RunMeasurementsResponse,
    summary="Get run measurements",
    description="Retrieves all simulated or measured telemetry observations captured for a specific test run.",
)
def get_measurements_by_run_id(run_id: str) -> RunMeasurementsResponse:
    """
    Retrieve telemetry measurements for a run by run_id or return 404 Not Found.

    - 200: Measurements retrieved successfully.
    - 404: Run ID not found.
    """
    run_data = get_run_measurements(run_id)
    if run_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )
    return RunMeasurementsResponse.model_validate(run_data.model_dump())
