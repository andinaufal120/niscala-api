"""Endpoints under /properties: properties and their rooms, facility suggestions, tenants, payment overview and payment patterns.

The property, room and facility-suggestion endpoints are implemented; the
others are declared in the contract and answer 501.
"""

import datetime as dt
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.access import has_recent_reauthentication, require_roles
from app.db import get_session
from app.schemas.auth import UserRole
from app.schemas.payments import PaymentOverview, PaymentPatternList
from app.schemas.properties import Property, PropertyInput, PropertyList
from app.schemas.rooms import FacilitySuggestionList, Room, RoomInput, RoomList
from app.schemas.tenants import NewTenantInput, Tenant, TenantList
from app.security import CurrentUser
from app.services import properties, rooms

router = APIRouter(prefix="/properties")

PropertyId = Annotated[UUID, Path(alias="propertyId")]
Db = Annotated[Session, Depends(get_session)]
OwnerOnly = Annotated[CurrentUser, Depends(require_roles(UserRole.OWNER))]
OwnerOrManager = Annotated[
    CurrentUser, Depends(require_roles(UserRole.OWNER, UserRole.MANAGER))
]


@router.post("", status_code=status.HTTP_201_CREATED, tags=["properties"])
def create_property(body: PropertyInput, owner: OwnerOnly, db: Db) -> Property:
    """Add a property to the Owner's account."""
    return properties.create_property(db, owner.user, body)


@router.get("", tags=["properties"])
def list_properties(caller: OwnerOrManager, db: Db) -> PropertyList:
    """List the properties the caller may access."""
    return PropertyList(items=properties.list_properties(db, caller.user))


@router.get("/{propertyId}", tags=["properties"])
def get_property(property_id: PropertyId, caller: OwnerOrManager, db: Db) -> Property:
    """Return a property's detail."""
    return properties.get_property(db, caller.user, property_id)


@router.put("/{propertyId}", tags=["properties"])
def update_property(
    property_id: PropertyId, body: PropertyInput, owner: OwnerOnly, db: Db
) -> Property:
    """Replace a property's name, address and bank account."""
    return properties.update_property(
        db,
        owner.user,
        property_id,
        body,
        reauthenticated=has_recent_reauthentication(owner.session),
    )


@router.delete(
    "/{propertyId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["properties"],
)
def delete_property(property_id: PropertyId, owner: OwnerOnly, db: Db) -> None:
    """Delete a property together with its rooms and manager assignments."""
    properties.delete_property(db, owner.user, property_id)


@router.post("/{propertyId}/rooms", status_code=status.HTTP_201_CREATED, tags=["rooms"])
def create_room(
    property_id: PropertyId, body: RoomInput, caller: OwnerOrManager, db: Db
) -> Room:
    """Add a room to a property."""
    return rooms.create_room(db, caller.user, property_id, body)


@router.get("/{propertyId}/rooms", tags=["rooms"])
def list_rooms(property_id: PropertyId, caller: OwnerOrManager, db: Db) -> RoomList:
    """List a property's rooms."""
    return rooms.list_rooms(db, caller.user, property_id)


@router.get("/{propertyId}/facility-suggestions", tags=["rooms"])
def list_facility_suggestions(
    property_id: PropertyId, caller: OwnerOrManager, db: Db
) -> FacilitySuggestionList:
    """List the distinct facility tags already used on rooms of the property's Owner."""
    return rooms.list_facility_suggestions(db, caller.user, property_id)


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


@router.get("/{propertyId}/payment-patterns", tags=["rent-bills"])
def get_payment_patterns(property_id: PropertyId) -> PaymentPatternList:
    """Show each tenant's payment pattern over their most recent bills."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
