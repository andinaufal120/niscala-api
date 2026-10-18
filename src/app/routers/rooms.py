"""Endpoints under /rooms."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response, status
from sqlalchemy.orm import Session

from app.access import require_roles
from app.db import get_session
from app.schemas.auth import UserRole
from app.schemas.rooms import Room, RoomInput
from app.security import CurrentUser
from app.services import rooms

router = APIRouter(prefix="/rooms", tags=["rooms"])

RoomId = Annotated[UUID, Path(alias="roomId")]
Db = Annotated[Session, Depends(get_session)]
OwnerOrManager = Annotated[
    CurrentUser, Depends(require_roles(UserRole.OWNER, UserRole.MANAGER))
]


@router.get("/{roomId}")
def get_room(room_id: RoomId, caller: OwnerOrManager, db: Db) -> Room:
    """Return a room's detail."""
    return rooms.get_room(db, caller.user, room_id)


@router.put("/{roomId}")
def update_room(
    room_id: RoomId, body: RoomInput, caller: OwnerOrManager, db: Db
) -> Room:
    """Replace a room's fields."""
    return rooms.update_room(db, caller.user, room_id, body)


@router.delete(
    "/{roomId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_room(room_id: RoomId, caller: OwnerOrManager, db: Db) -> None:
    """Delete a room."""
    rooms.delete_room(db, caller.user, room_id)
