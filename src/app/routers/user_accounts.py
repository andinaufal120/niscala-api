"""Endpoints under /user-accounts, available to Admins."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response, status
from pydantic import StringConstraints

from app.access import require_roles
from app.db import SessionDep
from app.email import EmailSender, get_email_sender
from app.schemas.auth import UserRole
from app.schemas.user_accounts import UserAccount, UserAccountInput, UserAccountList
from app.security import CurrentUser
from app.services import user_accounts

router = APIRouter(prefix="/user-accounts", tags=["user-accounts"])

UserAccountId = Annotated[UUID, Path(alias="userAccountId")]
Admin = Annotated[CurrentUser, Depends(require_roles(UserRole.ADMIN))]


@router.get("")
def list_user_accounts(
    caller: Admin,
    db: SessionDep,
    email: Annotated[
        str | None,
        Query(
            min_length=1,
            description="Case-insensitive match on any part of the current email.",
        ),
        StringConstraints(strip_whitespace=True, min_length=1),
    ] = None,
    role: UserRole | None = None,
    include_deleted: Annotated[
        bool, Query(alias="includeDeleted", description="Include deleted accounts.")
    ] = False,
) -> UserAccountList:
    """List user accounts of every role; deleted ones only on request."""
    return user_accounts.list_user_accounts(db, email, role, include_deleted)


@router.get("/{userAccountId}")
def get_user_account(
    user_account_id: UserAccountId, caller: Admin, db: SessionDep
) -> UserAccount:
    """Return one user account with its login details and links."""
    return user_accounts.get_user_account(db, user_account_id)


def _find_account(
    user_account_id: UserAccountId, caller: Admin, db: SessionDep
) -> user_accounts.Found:
    """Look the account up as a dependency, so a missing one answers 404 before the body is validated."""
    return user_accounts.find_user_account(db, user_account_id)


@router.put("/{userAccountId}")
def update_user_account(
    found: Annotated[user_accounts.Found, Depends(_find_account)],
    body: UserAccountInput,
    caller: Admin,
    db: SessionDep,
    sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> UserAccount:
    """Change name, email and status; a new email stays pending until verified."""
    return user_accounts.update_user_account(db, caller.user, found, body, sender)


@router.delete(
    "/{userAccountId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_user_account(
    user_account_id: UserAccountId, caller: Admin, db: SessionDep
) -> None:
    """Soft-delete an account and end its sessions."""
    user_accounts.delete_user_account(db, caller.user, user_account_id)
