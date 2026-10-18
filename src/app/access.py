"""Role checks and property access rules."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy import Select, false, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import ManagerAssignment, Property, UserAccount, UserSession
from app.schemas.auth import UserRole
from app.security import CurrentUser, get_verified_user
from app.services.reauthentication import REAUTHENTICATION_WINDOW


def require_roles(*roles: UserRole) -> Callable[..., CurrentUser]:
    """Build a dependency that admits verified callers holding one of `roles`.

    Raises 403 FORBIDDEN for any other role.
    """

    def dependency(
        current: Annotated[CurrentUser, Depends(get_verified_user)],
    ) -> CurrentUser:
        if current.user.role not in roles:
            raise ApiError(403, "FORBIDDEN")
        return current

    return dependency


def has_recent_reauthentication(session: UserSession) -> bool:
    """Return whether the session re-authenticated within the window."""
    at = session.reauthenticated_at
    return at is not None and datetime.now(UTC) - at < REAUTHENTICATION_WINDOW


def require_recent_reauthentication(
    current: Annotated[CurrentUser, Depends(get_verified_user)],
) -> CurrentUser:
    """Admit verified callers whose session re-authenticated within the window.

    Raises 403 REAUTHENTICATION_REQUIRED otherwise.
    """
    if not has_recent_reauthentication(current.session):
        raise ApiError(403, "REAUTHENTICATION_REQUIRED")
    return current


def accessible_properties(user: UserAccount) -> Select[tuple[Property]]:
    """Select the non-deleted properties the user may access, by name then id.

    Owners get their own properties, managers the ones they are assigned to,
    and other roles none.
    """
    query = select(Property).where(Property.deleted_at.is_(None))
    match user.role:
        case UserRole.OWNER:
            query = query.where(Property.owner_id == user.id)
        case UserRole.MANAGER:
            query = query.where(
                Property.id.in_(
                    select(ManagerAssignment.property_id).where(
                        ManagerAssignment.manager_id == user.id
                    )
                )
            )
        case _:
            query = query.where(false())
    return query.order_by(Property.name, Property.id)


def get_accessible_property(
    db: Session, user: UserAccount, property_id: UUID
) -> Property:
    """Return the property if the user may access it.

    Raises 404 PROPERTY_NOT_FOUND for an unknown, deleted or inaccessible
    property, so the response never reveals which case applied.
    """
    found = db.scalars(
        accessible_properties(user).where(Property.id == property_id)
    ).first()
    if found is None:
        raise ApiError(404, "PROPERTY_NOT_FOUND")
    return found
