"""Endpoints under /rooms. Declared in the contract; not implemented yet."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Response, status

from app.schemas.rooms import Room, RoomInput

router = APIRouter(prefix="/rooms", tags=["rooms"])

RoomId = Annotated[UUID, Path(alias="roomId")]


@router.get("/{roomId}")
def get_room(room_id: RoomId) -> Room:
    """Return a room's detail."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.put("/{roomId}")
def update_room(room_id: RoomId, body: RoomInput) -> Room:
    """Replace a room's fields."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.delete(
    "/{roomId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_room(room_id: RoomId) -> None:
    """Delete a room."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
