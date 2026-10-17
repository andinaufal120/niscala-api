"""Endpoints under /properties: properties and their rooms, facility suggestions and tenants.

Declared in the contract; not implemented yet.
"""

import datetime as dt
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query, Response, status

from app.schemas.payments import PaymentOverview
from app.schemas.properties import Property, PropertyInput, PropertyList
from app.schemas.rooms import FacilitySuggestionList, Room, RoomInput, RoomList
from app.schemas.tenants import NewTenantInput, Tenant, TenantList

router = APIRouter(prefix="/properties")

PropertyId = Annotated[UUID, Path(alias="propertyId")]


@router.post("", status_code=status.HTTP_201_CREATED, tags=["properties"])
def create_property(body: PropertyInput) -> Property:
    """Add a property to the Owner's account."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("", tags=["properties"])
def list_properties() -> PropertyList:
    """List the properties the caller may access."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("/{propertyId}", tags=["properties"])
def get_property(property_id: PropertyId) -> Property:
    """Return a property's detail."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.put("/{propertyId}", tags=["properties"])
def update_property(property_id: PropertyId, body: PropertyInput) -> Property:
    """Replace a property's name, address and bank account."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.delete(
    "/{propertyId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["properties"],
)
def delete_property(property_id: PropertyId) -> None:
    """Delete a property together with its rooms and manager assignments."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/{propertyId}/rooms", status_code=status.HTTP_201_CREATED, tags=["rooms"])
def create_room(property_id: PropertyId, body: RoomInput) -> Room:
    """Add a room to a property."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("/{propertyId}/rooms", tags=["rooms"])
def list_rooms(property_id: PropertyId) -> RoomList:
    """List a property's rooms."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("/{propertyId}/facility-suggestions", tags=["rooms"])
def list_facility_suggestions(property_id: PropertyId) -> FacilitySuggestionList:
    """List the distinct facility tags already used on rooms of the property's Owner."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post(
    "/{propertyId}/tenants", status_code=status.HTTP_201_CREATED, tags=["tenants"]
)
def create_tenant(property_id: PropertyId, body: NewTenantInput) -> Tenant:
    """Add a tenant to a vacant room of a property and create their invitation."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("/{propertyId}/tenants", tags=["tenants"])
def list_tenants(property_id: PropertyId) -> TenantList:
    """List a property's tenants."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("/{propertyId}/payment-overview", tags=["rent-bills"])
def get_payment_overview(
    property_id: PropertyId,
    date: Annotated[dt.date | None, Query()] = None,
) -> PaymentOverview:
    """Show each tenant's bill covering a date, defaulting to today."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
