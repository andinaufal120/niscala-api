"""Helpers shared by the Manager invitation tests."""

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

PREVIEW_URL = "/invitations/previews"
ACTIVATION_URL = "/invitations/activations/password"
ACCEPTANCE_PREVIEW_URL = "/invitations/acceptance-previews"
ACCEPTANCE_URL = "/invitations/acceptances"
HOOK = "app.services.activation.notify_manager_activated"

PREVIEW_FIELDS = {
    "status",
    "role",
    "inviterName",
    "properties",
    "roomNumber",
    "expiresAt",
    "name",
    "emergencyContactsRequired",
}


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def preview(client, token: str, **kwargs):
    return client.post(PREVIEW_URL, json={"token": token}, **kwargs)


def preview_status(client, token: str) -> str:
    response = preview(client, token)
    assert response.status_code == 200, response.text
    return response.json()["status"]


def edit_invitation(database, token: str, **columns) -> None:
    from app.models import Invitation

    with Session(database) as db:
        row = db.scalars(
            select(Invitation).where(Invitation.token_hash == sha256(token))
        ).one()
        for name, value in columns.items():
            setattr(row, name, value)
        db.commit()


def rename_user(database, user_id, name: str) -> None:
    from app.models import UserAccount

    with Session(database) as db:
        db.get(UserAccount, user_id).name = name
        db.commit()


def stored_user(database, user_id):
    from app.models import UserAccount

    with Session(database, expire_on_commit=False) as db:
        return db.get(UserAccount, user_id)


def stored_record(database, record_id):
    from app.models import Manager

    with Session(database, expire_on_commit=False) as db:
        return db.get(Manager, record_id)


def code_count(database) -> int:
    from app.models import EmailVerificationCode

    with Session(database) as db:
        return len(list(db.scalars(select(EmailVerificationCode))))


def assignments_of(database, user_id) -> set:
    from app.models import ManagerAssignment

    with Session(database) as db:
        rows = db.scalars(
            select(ManagerAssignment).where(ManagerAssignment.manager_id == user_id)
        )
        return {row.property_id for row in rows}


class HookCalls:
    """Records the calls of the replaced Manager activation hook."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.records: list = []
        self.error = error

    def __call__(self, *args, **kwargs) -> None:
        self.records.append(args[0] if args else kwargs["record"])
        if self.error is not None:
            raise self.error

    @property
    def record_ids(self) -> list:
        return [record.id for record in self.records]


def install_hook(monkeypatch, error: BaseException | None = None) -> HookCalls:
    """Replace the activation hook with a recorder; fails if the hook is missing."""
    calls = HookCalls(error)
    monkeypatch.setattr(HOOK, calls)
    return calls
