"""Role checks and property access rules."""

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import Depends, Header
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


_IF_MATCH = re.compile(r'"([0-9]+)"', re.ASCII)


def if_match_version(
    if_match: Annotated[
        str | None,
        Header(
            alias="If-Match",
            description=(
                "The version the caller last read, as a quoted whole number "
                'such as "3". When it is not the current version, the edit is '
                "refused with RESOURCE_VERSION_CONFLICT. Without the header, "
                "the edit is applied whatever the version."
            ),
        ),
    ] = None,
) -> int | None:
    """Read the `If-Match` header as a version number; None when absent.

    Raises 422 VALIDATION_FAILED on field `ifMatch` unless the value is exactly
    a quoted non-negative whole number.
    """
    if if_match is None:
        return None
    matched = _IF_MATCH.fullmatch(if_match)
    if matched is None:
        raise ApiError(422, "VALIDATION_FAILED", field="ifMatch")
    return int(matched.group(1))


IfMatch = Annotated[int | None, Depends(if_match_version)]


class Versioned(Protocol):
    """A record that counts its edits."""

    version: int


def bump_version(row: Versioned, expected: int | None) -> None:
    """Raise the record's version by one for an edit made on version `expected`.

    Raises 409 RESOURCE_VERSION_CONFLICT when `expected` is given and is not the
    record's current version. Call it on a row loaded with a lock.
    """
    if expected is not None and row.version != expected:
        raise ApiError(409, "RESOURCE_VERSION_CONFLICT")
    row.version += 1


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
    db: Session, user: UserAccount, property_id: UUID, *, lock: bool = False
) -> Property:
    """Return the property if the user may access it.

    Raises 404 PROPERTY_NOT_FOUND for an unknown, deleted or inaccessible
    property, so the response never reveals which case applied. With `lock`,
    the row is locked until the transaction ends and read fresh, so an edit
    sees the latest version.
    """
    query = accessible_properties(user).where(Property.id == property_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    found = db.scalars(query).first()
    if found is None:
        raise ApiError(404, "PROPERTY_NOT_FOUND")
    return found
