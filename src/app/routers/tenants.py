"""Endpoints under /tenants. Declared in the contract; not implemented yet."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Response, status

from app.schemas.tenants import Tenant, TenantInput, TenantInvitation

router = APIRouter(prefix="/tenants", tags=["tenants"])

TenantId = Annotated[UUID, Path(alias="tenantId")]


@router.get("/{tenantId}")
def get_tenant(tenant_id: TenantId) -> Tenant:
    """Return a tenant's detail."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.put("/{tenantId}")
def update_tenant(tenant_id: TenantId, body: TenantInput) -> Tenant:
    """Replace a tenant's fields. The room cannot be changed."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.delete(
    "/{tenantId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_tenant(tenant_id: TenantId) -> None:
    """End a tenant's lease, revoke their access and free the room; history is kept."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/{tenantId}/invitation", status_code=status.HTTP_201_CREATED)
def regenerate_tenant_invitation(tenant_id: TenantId) -> TenantInvitation:
    """Create a new invitation link for a tenant, invalidating the old one."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
