"""Occupancy figures across the properties a user may access."""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import accessible_properties
from app.models import Lease, Room, UserAccount
from app.schemas.dashboard import (
    OccupancyDashboard,
    OccupancyRoom,
    OccupancySummary,
    PropertyOccupancy,
)
from app.schemas.rooms import Occupancy
from app.services.rooms import natural_number_key


def _percentage(occupied: int, rooms: int) -> int:
    """Occupied share of all rooms as a whole percentage, halves rounded up."""
    if rooms == 0:
        return 0
    return (200 * occupied + rooms) // (2 * rooms)


def get_occupancy_dashboard(db: Session, user: UserAccount) -> OccupancyDashboard:
    """Report occupancy for each accessible property and across all of them.

    Properties are ordered by name and rooms by natural number order. View-only
    properties are included.
    """
    properties = db.scalars(accessible_properties(user)).all()
    room_rows = db.scalars(
        select(Room).where(
            Room.property_id.in_([row.id for row in properties]),
            Room.deleted_at.is_(None),
        )
    ).all()
    occupied_ids: set[UUID] = set(
        db.scalars(
            select(Lease.room_id).where(
                Lease.room_id.in_([row.id for row in room_rows]),
                Lease.ended_at.is_(None),
            )
        )
    )
    rooms_by_property: dict[UUID, list[Room]] = defaultdict(list)
    for room in sorted(room_rows, key=lambda r: (natural_number_key(r.number), r.id)):
        rooms_by_property[room.property_id].append(room)

    items = []
    for row in properties:
        rooms = rooms_by_property[row.id]
        occupied = sum(room.id in occupied_ids for room in rooms)
        items.append(
            PropertyOccupancy(
                id=row.id,
                name=row.name,
                room_count=len(rooms),
                occupied_room_count=occupied,
                vacant_room_count=len(rooms) - occupied,
                occupancy_percentage=_percentage(occupied, len(rooms)),
                rooms=[
                    OccupancyRoom(
                        id=room.id,
                        number=room.number,
                        occupancy=(
                            Occupancy.OCCUPIED
                            if room.id in occupied_ids
                            else Occupancy.VACANT
                        ),
                    )
                    for room in rooms
                ],
            )
        )
    total = sum(item.room_count for item in items)
    occupied_total = sum(item.occupied_room_count for item in items)
    return OccupancyDashboard(
        summary=OccupancySummary(
            property_count=len(items),
            room_count=total,
            occupied_room_count=occupied_total,
            vacant_room_count=total - occupied_total,
            occupancy_percentage=_percentage(occupied_total, total),
        ),
        items=items,
    )
