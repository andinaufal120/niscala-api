"""Endpoints under /me."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.access import require_roles
from app.db import SessionDep
from app.schemas.auth import UserRole
from app.schemas.tenants import CurrentLeaseResult
from app.security import CurrentUser
from app.services import tenants

router = APIRouter(prefix="/me", tags=["tenants"])

Db = SessionDep
TenantOnly = Annotated[CurrentUser, Depends(require_roles(UserRole.TENANT))]


@router.get("/lease")
def get_my_lease(caller: TenantOnly, db: Db) -> CurrentLeaseResult:
    """Return the calling tenant's active lease, or null when it has ended."""
    return tenants.get_current_lease(db, caller.user)
