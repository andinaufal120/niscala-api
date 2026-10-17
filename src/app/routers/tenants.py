"""Tenant and tenant-invitation endpoints. Declared in the contract; not implemented yet."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Response, status

from app.schemas.tenants import (
    NewTenantInput,
    Tenant,
    TenantInput,
    TenantInvitation,
    TenantList,
)

router = APIRouter(tags=["tenants"])

PropertyId = Annotated[UUID, Path(alias="propertyId")]
TenantId = Annotated[UUID, Path(alias="tenantId")]


@router.post("/properties/{propertyId}/tenants", status_code=status.HTTP_201_CREATED)
def create_tenant(property_id: PropertyId, body: NewTenantInput) -> Tenant:
    """Add a tenant to a vacant room of a property and create their invitation."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("/properties/{propertyId}/tenants")
def list_tenants(property_id: PropertyId) -> TenantList:
    """List a property's tenants."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("/tenants/{tenantId}")
def get_tenant(tenant_id: TenantId) -> Tenant:
    """Return a tenant's detail."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.put("/tenants/{tenantId}")
def update_tenant(tenant_id: TenantId, body: TenantInput) -> Tenant:
    """Replace a tenant's fields. The room cannot be changed."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.delete(
    "/tenants/{tenantId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_tenant(tenant_id: TenantId) -> None:
    """End a tenant's lease, revoke their access and free the room; history is kept."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/tenants/{tenantId}/invitation", status_code=status.HTTP_201_CREATED)
def regenerate_tenant_invitation(tenant_id: TenantId) -> TenantInvitation:
    """Create a new invitation link for a tenant, invalidating the old one."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
