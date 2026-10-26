"""Endpoints for the caller's sessions and password change under /me.

Covers listing and ending sessions and replacing the password.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response, status

from app.db import SessionDep
from app.schemas.sessions import (
    PasswordChangeInput,
    PasswordChangeResult,
    SessionList,
)
from app.security import CurrentUser, get_verified_user
from app.services import sessions as session_service
from app.services.reauthentication import change_password

router = APIRouter(prefix="/me")

VerifiedUser = Annotated[CurrentUser, Depends(get_verified_user)]


@router.get("/sessions", tags=["sessions"])
def list_my_sessions(db: SessionDep, current: VerifiedUser) -> SessionList:
    """List the caller's signed-in devices."""
    return session_service.list_sessions(db, current)


@router.delete(
    "/sessions/{sessionId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["sessions"],
)
def end_my_session(
    session_id: Annotated[UUID, Path(alias="sessionId")],
    db: SessionDep,
    current: VerifiedUser,
) -> None:
    """Sign one of the caller's devices out."""
    session_service.end_other_session(db, current, session_id)


@router.delete(
    "/sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["sessions"],
)
def end_my_other_sessions(db: SessionDep, current: VerifiedUser) -> None:
    """Sign out every device of the caller except the current one."""
    session_service.end_other_sessions(db, current)


@router.post("/password-changes", tags=["account"])
def change_my_password(
    body: PasswordChangeInput, db: SessionDep, current: VerifiedUser
) -> PasswordChangeResult:
    """Replace the caller's password after checking the current one."""
    return change_password(db, current, body.current_password, body.new_password)
