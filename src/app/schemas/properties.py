"""Schemas for properties and their bank accounts."""

from uuid import UUID

from pydantic import Field

from app.schemas.base import ApiModel


class BankAccount(ApiModel):
    """Bank account that receives rent transfers for a property."""

    bank_name: str = Field(min_length=1)
    account_number: str = Field(min_length=1)
    account_holder_name: str = Field(min_length=1)


class PropertyInput(ApiModel):
    """Fields an Owner sets when adding or editing a property."""

    name: str = Field(
        min_length=1, description="Must be unique within the Owner's account."
    )
    address: str = Field(min_length=1)
    bank_account: BankAccount | None = Field(
        default=None,
        description="Optional; when given, all of its fields are required.",
    )


class ManagerRef(ApiModel):
    """A Manager assigned to a property."""

    id: UUID
    name: str


class Property(ApiModel):
    """A property with its room counts and assigned managers."""

    id: UUID
    name: str
    address: str
    bank_account: BankAccount | None
    room_count: int
    occupied_room_count: int
    vacant_room_count: int
    managers: list[ManagerRef]
    editable: bool = Field(description="False while the property is view-only.")


class PropertySummary(ApiModel):
    """A property as shown in the property list."""

    id: UUID
    name: str
    address: str
    room_count: int
    occupied_room_count: int
    managers: list[ManagerRef]
    editable: bool = Field(description="False while the property is view-only.")


class PropertyList(ApiModel):
    """Properties the caller may access."""

    items: list[PropertySummary]
