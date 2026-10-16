"""Room and facility-suggestion endpoints. Declared in the contract; not implemented yet."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Response, status

from app.schemas.rooms import FacilitySuggestionList, Room, RoomInput, RoomList

router = APIRouter(tags=["rooms"])

PropertyId = Annotated[UUID, Path(alias="propertyId")]
RoomId = Annotated[UUID, Path(alias="roomId")]


@router.post("/properties/{propertyId}/rooms", status_code=status.HTTP_201_CREATED)
def create_room(property_id: PropertyId, body: RoomInput) -> Room:
    """Add a room to a property."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("/properties/{propertyId}/rooms")
def list_rooms(property_id: PropertyId) -> RoomList:
    """List a property's rooms."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("/properties/{propertyId}/facility-suggestions")
def list_facility_suggestions(property_id: PropertyId) -> FacilitySuggestionList:
    """List the distinct facility tags already used on rooms of the property's Owner."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("/rooms/{roomId}")
def get_room(room_id: RoomId) -> Room:
    """Return a room's detail."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.put("/rooms/{roomId}")
def update_room(room_id: RoomId, body: RoomInput) -> Room:
    """Replace a room's fields."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.delete(
    "/rooms/{roomId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_room(room_id: RoomId) -> None:
    """Delete a room."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
