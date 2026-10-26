"""Endpoints under /occupancy-dashboard."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.access import require_roles
from app.db import SessionDep
from app.schemas.auth import UserRole
from app.schemas.dashboard import OccupancyDashboard
from app.security import CurrentUser
from app.services import dashboard

router = APIRouter(prefix="/occupancy-dashboard", tags=["dashboard"])

Staff = Annotated[CurrentUser, Depends(require_roles(UserRole.OWNER, UserRole.MANAGER))]


@router.get("")
def get_occupancy_dashboard(caller: Staff, db: SessionDep) -> OccupancyDashboard:
    """Show occupancy figures for each accessible property and a summary across them."""
    return dashboard.get_occupancy_dashboard(db, caller.user)
