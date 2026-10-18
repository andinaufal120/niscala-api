"""Adding, listing, editing and deleting rooms, and facility suggestions."""

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.access import accessible_properties, get_accessible_property
from app.errors import ApiError
from app.models import Lease, Property, Tenant, UserAccount
from app.models import Room as RoomRow
from app.schemas.rooms import (
    FacilitySuggestionList,
    Occupancy,
    Room,
    RoomInput,
    RoomLease,
    RoomLeaseSummary,
    RoomList,
    RoomSummary,
)
from app.services.subscriptions import plan_limits

MAX_FACILITY_LENGTH = 30
MAX_FACILITIES = 15


class _Fields:
    """A validated room body, ready to store."""

    def __init__(self, data: RoomInput):
        self.number = data.number.strip()
        if not self.number:
            raise ApiError(422, "VALIDATION_FAILED", field="number")
        if (data.length_m is None) != (data.width_m is None):
            missing = "width_m" if data.width_m is None else "length_m"
            raise ApiError(422, "VALIDATION_FAILED", field=_camel(missing))
        self.length_m = _dimension(data.length_m, "lengthM")
        self.width_m = _dimension(data.width_m, "widthM")
        self.base_rate = data.base_rate
        self.facilities = _facilities(data.facilities)


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.capitalize() for part in rest)


def _dimension(value: float | None, field: str) -> Decimal | None:
    if value is None:
        return None
    decimal = Decimal(str(value))
    if decimal.as_tuple().exponent < -2:
        raise ApiError(422, "VALIDATION_FAILED", field=field)
    return decimal


def _facilities(tags: list[str]) -> list[str]:
    normalized = list(dict.fromkeys(" ".join(tag.lower().split()) for tag in tags))
    kept = [tag for tag in normalized if tag]
    if len(kept) > MAX_FACILITIES or any(len(t) > MAX_FACILITY_LENGTH for t in kept):
        raise ApiError(422, "VALIDATION_FAILED", field="facilities")
    return kept


def natural_number_key(number: str) -> list[int | str]:
    """Sort key ordering room numbers naturally: "A2" before "A10", ignoring case."""
    parts = re.split(r"(\d+)", number.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def _number_order(row: RoomRow) -> tuple[list[int | str], UUID]:
    return natural_number_key(row.number), row.id


def _editable(row: RoomRow, parent: Property) -> bool:
    return not (row.view_only or parent.view_only)


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _active_leases(
    db: Session, room_ids: Iterable[UUID]
) -> dict[UUID, tuple[Lease, str, str]]:
    """Map each room id to its active lease, tenant name and tenant phone."""
    rows = db.execute(
        select(Lease, UserAccount.name, Tenant.phone)
        .join(Tenant, Tenant.user_id == Lease.tenant_id)
        .join(UserAccount, UserAccount.id == Tenant.user_id)
        .where(Lease.room_id.in_(list(room_ids)), Lease.ended_at.is_(None))
    )
    return {lease.room_id: (lease, name, phone) for lease, name, phone in rows}


def _detail(
    row: RoomRow, parent: Property, active: tuple[Lease, str, str] | None
) -> Room:
    lease = None
    if active is not None:
        found, name, phone = active
        lease = RoomLease(
            tenant_id=found.tenant_id,
            tenant_name=name,
            tenant_phone=phone,
            start_date=found.start_date,
            end_date=found.end_date,
            rent=found.rent,
        )
    return Room(
        id=row.id,
        property_id=row.property_id,
        number=row.number,
        base_rate=row.base_rate,
        occupancy=Occupancy.VACANT if active is None else Occupancy.OCCUPIED,
        length_m=_float(row.length_m),
        width_m=_float(row.width_m),
        facilities=row.facilities,
        lease=lease,
        editable=_editable(row, parent),
    )


def _summary(
    row: RoomRow, parent: Property, active: tuple[Lease, str, str] | None
) -> RoomSummary:
    lease = None
    if active is not None:
        found, name, _ = active
        lease = RoomLeaseSummary(tenant_name=name, end_date=found.end_date)
    return RoomSummary(
        id=row.id,
        number=row.number,
        base_rate=row.base_rate,
        occupancy=Occupancy.VACANT if active is None else Occupancy.OCCUPIED,
        length_m=_float(row.length_m),
        width_m=_float(row.width_m),
        facilities=row.facilities,
        lease=lease,
        editable=_editable(row, parent),
    )


def _ensure_number_free(
    db: Session, property_id: UUID, number: str, excluding: UUID | None = None
) -> None:
    taken = select(RoomRow.id).where(
        RoomRow.property_id == property_id,
        RoomRow.deleted_at.is_(None),
        func.lower(RoomRow.number) == number.lower(),
    )
    if excluding is not None:
        taken = taken.where(RoomRow.id != excluding)
    if db.scalars(taken.limit(1)).first() is not None:
        raise ApiError(409, "ROOM_NUMBER_TAKEN", field="number")


def _accessible_room(
    db: Session, user: UserAccount, room_id: UUID
) -> tuple[RoomRow, Property]:
    """Return a live room and its property, or raise 404 ROOM_NOT_FOUND."""
    row = db.scalars(
        select(RoomRow).where(
            RoomRow.id == room_id,
            RoomRow.deleted_at.is_(None),
            RoomRow.property_id.in_(
                accessible_properties(user).with_only_columns(Property.id)
            ),
        )
    ).first()
    if row is None:
        raise ApiError(404, "ROOM_NOT_FOUND")
    return row, db.get_one(Property, row.property_id)


def create_room(
    db: Session, user: UserAccount, property_id: UUID, data: RoomInput
) -> Room:
    """Add a room to a property the user may access.

    Checks in order: access (404 PROPERTY_NOT_FOUND), view-only (403
    PROPERTY_READ_ONLY), field rules (422 VALIDATION_FAILED), a number used by
    a live room of the property (409 ROOM_NUMBER_TAKEN), the property owner's
    plan limit (403 ROOM_LIMIT_REACHED). View-only rooms count towards the limit.
    """
    parent = get_accessible_property(db, user, property_id)
    if parent.view_only:
        raise ApiError(403, "PROPERTY_READ_ONLY")
    fields = _Fields(data)
    _ensure_number_free(db, parent.id, fields.number)
    limit = plan_limits(db, parent.owner_id).max_rooms_per_property
    held = db.scalar(
        select(func.count())
        .select_from(RoomRow)
        .where(RoomRow.property_id == parent.id, RoomRow.deleted_at.is_(None))
    )
    if limit is not None and (held or 0) >= limit:
        raise ApiError(403, "ROOM_LIMIT_REACHED")
    row = RoomRow(property_id=parent.id, **vars(fields))
    db.add(row)
    db.flush()
    return _detail(row, parent, None)


def list_rooms(db: Session, user: UserAccount, property_id: UUID) -> RoomList:
    """List a property's live rooms in natural order of their number."""
    parent = get_accessible_property(db, user, property_id)
    rows = db.scalars(
        select(RoomRow).where(
            RoomRow.property_id == parent.id, RoomRow.deleted_at.is_(None)
        )
    ).all()
    active = _active_leases(db, [row.id for row in rows])
    return RoomList(
        items=[
            _summary(row, parent, active.get(row.id))
            for row in sorted(rows, key=_number_order)
        ]
    )


def list_facility_suggestions(
    db: Session, user: UserAccount, property_id: UUID
) -> FacilitySuggestionList:
    """List the distinct tags on live rooms of all live properties of the owner."""
    parent = get_accessible_property(db, user, property_id)
    tag_lists = db.scalars(
        select(RoomRow.facilities)
        .join(Property, Property.id == RoomRow.property_id)
        .where(
            Property.owner_id == parent.owner_id,
            Property.deleted_at.is_(None),
            RoomRow.deleted_at.is_(None),
        )
    )
    return FacilitySuggestionList(items=sorted({t for tags in tag_lists for t in tags}))


def get_room(db: Session, user: UserAccount, room_id: UUID) -> Room:
    """Return a live room of a property the user may access."""
    row, parent = _accessible_room(db, user, room_id)
    return _detail(row, parent, _active_leases(db, [row.id]).get(row.id))


def update_room(db: Session, user: UserAccount, room_id: UUID, data: RoomInput) -> Room:
    """Replace a room's fields.

    Checks in order: access (404 ROOM_NOT_FOUND), view-only property (403
    PROPERTY_READ_ONLY), view-only room (403 ROOM_READ_ONLY), field rules (422
    VALIDATION_FAILED), a number used by another live room of the property (409
    ROOM_NUMBER_TAKEN).
    """
    row, parent = _accessible_room(db, user, room_id)
    if parent.view_only:
        raise ApiError(403, "PROPERTY_READ_ONLY")
    if row.view_only:
        raise ApiError(403, "ROOM_READ_ONLY")
    fields = _Fields(data)
    _ensure_number_free(db, parent.id, fields.number, excluding=row.id)
    for name, value in vars(fields).items():
        setattr(row, name, value)
    db.flush()
    return _detail(row, parent, _active_leases(db, [row.id]).get(row.id))


def delete_room(db: Session, user: UserAccount, room_id: UUID) -> None:
    """Soft-delete a room, even a view-only one.

    Raises 404 ROOM_NOT_FOUND without access, then 409 ROOM_HAS_ACTIVE_LEASE
    while the room has an active lease.
    """
    row, _ = _accessible_room(db, user, room_id)
    if row.id in _active_leases(db, [row.id]):
        raise ApiError(409, "ROOM_HAS_ACTIVE_LEASE")
    row.deleted_at = datetime.now(UTC)
