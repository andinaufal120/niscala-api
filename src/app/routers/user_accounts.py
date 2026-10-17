"""Endpoints under /user-accounts. Declared in the contract; not implemented yet."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query, Response, status

from app.schemas.auth import UserRole
from app.schemas.user_accounts import UserAccount, UserAccountInput, UserAccountList

router = APIRouter(prefix="/user-accounts", tags=["user-accounts"])

UserAccountId = Annotated[UUID, Path(alias="userAccountId")]


@router.get("")
def list_user_accounts(
    email: Annotated[
        str | None,
        Query(
            min_length=1,
            description="Case-insensitive match on any part of the current email.",
        ),
    ] = None,
    role: UserRole | None = None,
    include_deleted: Annotated[
        bool, Query(alias="includeDeleted", description="Include deleted accounts.")
    ] = False,
) -> UserAccountList:
    """List user accounts of every role; deleted ones only on request."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("/{userAccountId}")
def get_user_account(user_account_id: UserAccountId) -> UserAccount:
    """Return one user account with its login details and links."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.put("/{userAccountId}")
def update_user_account(
    user_account_id: UserAccountId, body: UserAccountInput
) -> UserAccount:
    """Change name, email and status; a new email stays pending until verified."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.delete(
    "/{userAccountId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_user_account(user_account_id: UserAccountId) -> None:
    """Soft-delete an account and end its sessions."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
