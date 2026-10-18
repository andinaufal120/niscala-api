"""Endpoints under /occupancy-dashboard. Declared in the contract; not implemented yet."""

from fastapi import APIRouter, HTTPException, status

from app.schemas.dashboard import OccupancyDashboard

router = APIRouter(prefix="/occupancy-dashboard", tags=["dashboard"])


@router.get("")
def get_occupancy_dashboard() -> OccupancyDashboard:
    """Show occupancy figures for each accessible property and a summary across them."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
