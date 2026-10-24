"""Endpoints under /tenants."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response, status

from app.access import require_roles
from app.db import SessionDep
from app.schemas.auth import UserRole
from app.schemas.tenants import Tenant, TenantInput, TenantInvitation
from app.security import CurrentUser
from app.services import tenants

router = APIRouter(prefix="/tenants", tags=["tenants"])

TenantId = Annotated[UUID, Path(alias="tenantId")]
Db = SessionDep
OwnerOrManager = Annotated[
    CurrentUser, Depends(require_roles(UserRole.OWNER, UserRole.MANAGER))
]


@router.get("/{tenantId}")
def get_tenant(tenant_id: TenantId, caller: OwnerOrManager, db: Db) -> Tenant:
    """Return a tenant's detail."""
    return tenants.get_tenant(db, caller.user, tenant_id)


@router.put("/{tenantId}")
def update_tenant(
    tenant_id: TenantId, body: TenantInput, caller: OwnerOrManager, db: Db
) -> Tenant:
    """Replace a tenant's fields. The room cannot be changed."""
    return tenants.update_tenant(db, caller.user, tenant_id, body)


@router.delete(
    "/{tenantId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_tenant(tenant_id: TenantId, caller: OwnerOrManager, db: Db) -> None:
    """End a tenant's lease, revoke their access and free the room; history is kept."""
    tenants.delete_tenant(db, caller.user, tenant_id)


@router.post("/{tenantId}/invitation", status_code=status.HTTP_201_CREATED)
def regenerate_tenant_invitation(
    tenant_id: TenantId, caller: OwnerOrManager, db: Db
) -> TenantInvitation:
    """Create a new invitation link for a tenant, invalidating the old one."""
    return tenants.regenerate_invitation(db, caller.user, tenant_id)
