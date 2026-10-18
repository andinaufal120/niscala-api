"""Endpoints for the caller's sessions and password change under /me. Declared in the contract; not implemented yet."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Response, status

from app.schemas.sessions import (
    PasswordChangeInput,
    PasswordChangeResult,
    SessionList,
)

router = APIRouter(prefix="/me")


@router.get("/sessions", tags=["sessions"])
def list_my_sessions() -> SessionList:
    """List the caller's signed-in devices."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.delete(
    "/sessions/{sessionId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["sessions"],
)
def end_my_session(session_id: Annotated[UUID, Path(alias="sessionId")]) -> None:
    """Sign one of the caller's devices out."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.delete(
    "/sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["sessions"],
)
def end_my_other_sessions() -> None:
    """Sign out every device of the caller except the current one."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/password-changes", tags=["account"])
def change_my_password(body: PasswordChangeInput) -> PasswordChangeResult:
    """Replace the caller's password after checking the current one."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
