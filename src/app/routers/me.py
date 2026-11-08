"""Endpoints under /me."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.access import require_roles
from app.db import SessionDep
from app.schemas.auth import UserRole
from app.schemas.tenants import CurrentLeaseList
from app.security import CurrentUser
from app.services import tenants

router = APIRouter(prefix="/me", tags=["tenants"])

Db = SessionDep
TenantOnly = Annotated[CurrentUser, Depends(require_roles(UserRole.TENANT))]


@router.get("/leases")
def get_my_leases(caller: TenantOnly, db: Db) -> CurrentLeaseList:
    """Return the calling tenant's active leases, possibly none."""
    return tenants.get_current_leases(db, caller.user)
