"""Endpoints under /managers. Declared in the contract; not implemented yet."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query, Response, status

from app.schemas.managers import (
    Manager,
    ManagerInput,
    ManagerInvitation,
    ManagerList,
)

router = APIRouter(prefix="/managers", tags=["managers"])

ManagerId = Annotated[UUID, Path(alias="managerId")]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_manager(body: ManagerInput) -> Manager:
    """Add a manager to properties of the Owner and return them with an invitation."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("")
def list_managers(
    property_id: Annotated[UUID | None, Query(alias="propertyId")] = None,
) -> ManagerList:
    """List the Owner's managers, optionally only those assigned to one property."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("/{managerId}")
def get_manager(manager_id: ManagerId) -> Manager:
    """Return a manager's detail, with the invitation while not activated."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.put("/{managerId}")
def update_manager(manager_id: ManagerId, body: ManagerInput) -> Manager:
    """Replace a manager's fields; access to removed properties is revoked."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.delete(
    "/{managerId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_manager(manager_id: ManagerId) -> None:
    """Revoke the manager's assignments to the Owner's properties; history is kept."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/{managerId}/invitation", status_code=status.HTTP_201_CREATED)
def regenerate_manager_invitation(manager_id: ManagerId) -> ManagerInvitation:
    """Create a new invitation link for a manager, invalidating the old one."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
