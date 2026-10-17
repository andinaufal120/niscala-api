"""Schemas for the occupancy dashboard."""

from uuid import UUID

from pydantic import Field

from app.schemas.base import ApiModel
from app.schemas.rooms import Occupancy

PERCENTAGE_DESCRIPTION = (
    "Occupied rooms as a whole-number percentage of all rooms, halves rounded up; "
    "0 when there are no rooms."
)


class OccupancyRoom(ApiModel):
    """A room's number and whether it has an active lease."""

    id: UUID
    number: str
    occupancy: Occupancy


class OccupancySummary(ApiModel):
    """Occupancy totals across the caller's accessible properties."""

    property_count: int = Field(ge=0)
    room_count: int = Field(ge=0)
    occupied_room_count: int = Field(ge=0)
    vacant_room_count: int = Field(ge=0)
    occupancy_percentage: int = Field(ge=0, le=100, description=PERCENTAGE_DESCRIPTION)


class PropertyOccupancy(ApiModel):
    """Occupancy figures and room statuses of one property."""

    id: UUID
    name: str
    room_count: int = Field(ge=0)
    occupied_room_count: int = Field(ge=0)
    vacant_room_count: int = Field(ge=0)
    occupancy_percentage: int = Field(ge=0, le=100, description=PERCENTAGE_DESCRIPTION)
    rooms: list[OccupancyRoom]


class OccupancyDashboard(ApiModel):
    """Occupancy of the caller's accessible properties."""

    summary: OccupancySummary
    items: list[PropertyOccupancy]
