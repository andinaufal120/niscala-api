"""Endpoints under /me."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.access import require_roles
from app.db import SessionDep
from app.schemas.auth import UserRole
from app.schemas.tenants import CurrentLeaseList
from app.security import CurrentUser, get_verified_user
from app.services import tenants, user_accounts

router = APIRouter(prefix="/me", tags=["tenants"])

Db = SessionDep
Verified = Annotated[CurrentUser, Depends(get_verified_user)]
TenantOnly = Annotated[CurrentUser, Depends(require_roles(UserRole.TENANT))]


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_my_account(caller: Verified, db: Db) -> None:
    """Delete the caller's own account and erase its personal data."""
    user_accounts.delete_own_account(db, caller)


@router.get("/leases")
def get_my_leases(caller: TenantOnly, db: Db) -> CurrentLeaseList:
    """Return the calling tenant's active leases, possibly none."""
    return tenants.get_current_leases(db, caller.user)
