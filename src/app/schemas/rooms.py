"""Schemas for rooms, their current lease and facility tags."""

from datetime import date
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from app.schemas.base import ApiModel

DIMENSION_DESCRIPTION = (
    "In metres, with at most 2 decimals. Give both lengthM and widthM, or neither."
)


class Occupancy(StrEnum):
    """Whether a room currently has an active lease."""

    OCCUPIED = "occupied"
    VACANT = "vacant"


class RoomInput(ApiModel):
    """Fields set when adding or editing a room."""

    number: str = Field(min_length=1, description="Must be unique within the property.")
    base_rate: int = Field(gt=0, description="Per month, in rupiah.")
    length_m: float | None = Field(
        default=None, gt=0, le=20, description=DIMENSION_DESCRIPTION
    )
    width_m: float | None = Field(
        default=None, gt=0, le=20, description=DIMENSION_DESCRIPTION
    )
    facilities: list[str] = Field(
        default=[],
        description=(
            "Free-form tags. On save each tag is trimmed, lowercased and has "
            "repeated spaces collapsed, and duplicates are dropped. At most 30 "
            "characters per tag and 15 tags per room."
        ),
    )


class RoomLease(ApiModel):
    """The active lease of an occupied room."""

    tenant_id: UUID
    tenant_name: str
    tenant_phone: str
    start_date: date | None
    end_date: date | None
    rent: int = Field(description="In rupiah.")


class Room(ApiModel):
    """A room with its occupancy and, if occupied, its active lease."""

    id: UUID
    property_id: UUID
    number: str
    base_rate: int = Field(description="Per month, in rupiah.")
    occupancy: Occupancy
    length_m: float | None = Field(description="In metres.")
    width_m: float | None = Field(description="In metres.")
    facilities: list[str]
    lease: RoomLease | None


class RoomList(ApiModel):
    """Rooms of a property."""

    items: list[Room]


class FacilitySuggestionList(ApiModel):
    """Distinct facility tags already used on rooms of the same Owner."""

    items: list[str]
