"""Endpoints under /managers, available to Owners."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.access import require_roles
from app.db import SessionDep
from app.schemas.auth import UserRole
from app.schemas.managers import (
    Manager,
    ManagerInput,
    ManagerInvitation,
    ManagerList,
)
from app.security import CurrentUser
from app.services import managers

router = APIRouter(prefix="/managers", tags=["managers"])

ManagerId = Annotated[UUID, Path(alias="managerId")]
Db = SessionDep
Owner = Annotated[CurrentUser, Depends(require_roles(UserRole.OWNER))]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_manager(body: ManagerInput, caller: Owner, db: Db) -> Manager:
    """Add a manager to properties of the Owner and return them with an invitation."""
    return managers.create_manager(db, caller.user, body)


@router.get("")
def list_managers(
    caller: Owner,
    db: Db,
    property_id: Annotated[UUID | None, Query(alias="propertyId")] = None,
) -> ManagerList:
    """List the Owner's managers, optionally only those assigned to one property."""
    return managers.list_managers(db, caller.user, property_id)


@router.get("/{managerId}")
def get_manager(manager_id: ManagerId, caller: Owner, db: Db) -> Manager:
    """Return a manager's detail, with the invitation while not activated."""
    return managers.get_manager(db, caller.user, manager_id)


@router.put("/{managerId}")
def update_manager(
    manager_id: ManagerId, body: ManagerInput, caller: Owner, db: Db
) -> Manager:
    """Replace a manager's fields; access to removed properties is revoked."""
    return managers.update_manager(db, caller.user, manager_id, body)


@router.delete(
    "/{managerId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_manager(manager_id: ManagerId, caller: Owner, db: Db) -> None:
    """Revoke the manager's assignments to the Owner's properties; history is kept."""
    managers.delete_manager(db, caller.user, manager_id)


@router.post("/{managerId}/invitation", status_code=status.HTTP_201_CREATED)
def regenerate_manager_invitation(
    manager_id: ManagerId, caller: Owner, db: Db
) -> ManagerInvitation:
    """Create a new invitation link for a manager, invalidating the old one."""
    return managers.regenerate_invitation(db, caller.user, manager_id)
