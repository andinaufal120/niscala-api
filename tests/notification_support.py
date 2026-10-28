"""Helpers shared by the notification, notification-settings and push tests."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from rent_bill_support import png
from sqlalchemy import text
from sqlalchemy.orm import Session

NOTIFICATIONS = "/notifications"
READ_ALL = "/notifications/read-all"
SETTINGS = "/me/notification-settings"
PUSH_TOKEN = "/me/push-token"
COMPLAINTS = "/complaints"
ACTIVATION = "/invitations/activations/password"
ACCEPTANCES = "/invitations/acceptances"
DESCRIPTION = "The air conditioner does not cool."

NOTIFICATION_FIELDS = {
    "id",
    "type",
    "createdAt",
    "read",
    "rentBill",
    "complaint",
    "tenant",
    "room",
    "property",
    "actorName",
}
RENT_BILL_FIELDS = {
    "rentBillId",
    "periodStart",
    "periodEnd",
    "dueDate",
    "amount",
    "paymentStatus",
    "paymentMethod",
    "reason",
    "daysOverdue",
}
COMPLAINT_FIELDS = {
    "complaintId",
    "description",
    "status",
    "category",
    "urgency",
    "handlingNote",
}

CATEGORIES_BY_ROLE = {
    "tenant": ["billing", "paymentStatus", "complaintProgress"],
    "owner": ["newComplaint", "receiptUpload", "overdueBill", "accountActivity"],
    "manager": ["newComplaint", "receiptUpload", "overdueBill", "accountActivity"],
}
ALL_CATEGORIES = [
    "billing",
    "paymentStatus",
    "complaintProgress",
    "newComplaint",
    "receiptUpload",
    "overdueBill",
    "accountActivity",
]


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


def assert_error(response, status: int, code: str, field: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["field"] == field
    assert body["message"]


def assert_not_found(response) -> None:
    assert_error(response, 404, "NOTIFICATION_NOT_FOUND")


def dump(notification) -> dict:
    """A pushed `Notification` as the JSON an API client would receive."""
    return notification.model_dump(mode="json", by_alias=True)


# Reading through the API


def list_all(client, signed_in) -> dict:
    response = client.get(NOTIFICATIONS, headers=signed_in.headers)
    assert response.status_code == 200, response.text
    return response.json()


def items(client, signed_in) -> list[dict]:
    return list_all(client, signed_in)["items"]


def of_type(client, signed_in, type_: str) -> list[dict]:
    return [item for item in items(client, signed_in) if item["type"] == type_]


def types(client, signed_in) -> list[str]:
    return [item["type"] for item in items(client, signed_in)]


def only(client, signed_in, type_: str) -> dict:
    found = of_type(client, signed_in, type_)
    assert len(found) == 1, found
    return found[0]


def mark_read(client, signed_in, notification_id):
    return client.post(
        f"{NOTIFICATIONS}/{notification_id}/read", headers=signed_in.headers
    )


def read_all(client, signed_in):
    return client.post(READ_ALL, headers=signed_in.headers)


# Stored notifications (the table is read and shifted in time through SQL only)


def stored_rows(database) -> list[dict]:
    with Session(database) as db:
        result = db.execute(
            text(
                "SELECT id, recipient_id, type, property_id, created_at, read_at "
                "FROM notifications ORDER BY created_at, id"
            )
        )
        return [dict(row) for row in result.mappings()]


def stored_for(database, user) -> list[dict]:
    return [row for row in stored_rows(database) if row["recipient_id"] == user.id]


def stored_row(database, notification_id) -> dict:
    (row,) = [r for r in stored_rows(database) if str(r["id"]) == str(notification_id)]
    return row


def set_created_at(database, notification_id, when: datetime) -> None:
    with Session(database) as db:
        db.execute(
            text("UPDATE notifications SET created_at = :when WHERE id = :id"),
            {"when": when, "id": UUID(str(notification_id))},
        )
        db.commit()


def minutes_ago(minutes: int) -> datetime:
    from datetime import timedelta

    return datetime.now(UTC) - timedelta(minutes=minutes)


def unassign(database, manager, property_) -> None:
    from app.models import ManagerAssignment

    with Session(database) as db:
        db.delete(db.get(ManagerAssignment, (manager.id, property_.id)))
        db.commit()


def edit_session(database, session_id, **columns) -> None:
    from app.models import UserSession

    with Session(database) as db:
        row = db.get(UserSession, session_id)
        for name, value in columns.items():
            setattr(row, name, value)
        db.commit()


def revoke_session(database, session_id) -> None:
    edit_session(database, session_id, revoked_at=datetime.now(UTC))


# Settings and push tokens


def default_items(role_name: str) -> list[dict]:
    return [
        {
            "category": category,
            "pushEnabled": True,
            "urgencyScope": "allUrgencies" if category == "newComplaint" else None,
        }
        for category in CATEGORIES_BY_ROLE[role_name]
    ]


def settings_items(
    role_name: str, off: tuple[str, ...] = (), scope: str = "allUrgencies"
) -> list[dict]:
    """A full settings body: the categories in `off` are switched off."""
    return [
        {
            **item,
            "pushEnabled": item["category"] not in off,
            "urgencyScope": scope if item["category"] == "newComplaint" else None,
        }
        for item in default_items(role_name)
    ]


def put_settings(client, signed_in, items_: list[dict]):
    return client.put(SETTINGS, json={"items": items_}, headers=signed_in.headers)


def save_settings(
    client, signed_in, role_name: str, off: tuple[str, ...] = (), scope="allUrgencies"
) -> None:
    response = put_settings(client, signed_in, settings_items(role_name, off, scope))
    assert response.status_code == 200, response.text


def register_token(client, signed_in, token: str) -> None:
    response = client.put(PUSH_TOKEN, json={"token": token}, headers=signed_in.headers)
    assert response.status_code == 204, response.text


# Rent bill events


def upload_receipt(client, headers, bill, content: bytes | None = None):
    return client.put(
        f"/rent-bills/{bill.id}/receipt",
        files={
            "file": ("receipt.png", png() if content is None else content, "image/png")
        },
        headers=headers,
    )


def verify(client, headers, bill):
    return client.post(f"/rent-bills/{bill.id}/verification", headers=headers)


def reject(client, headers, bill, reason: str = "The receipt is unreadable."):
    return client.post(
        f"/rent-bills/{bill.id}/rejection", json={"reason": reason}, headers=headers
    )


def pay_cash(client, headers, bill, received_on=None):
    from rent_bill_support import today

    body = {"receivedOn": (received_on or today()).isoformat()}
    return client.post(
        f"/rent-bills/{bill.id}/cash-payment", json=body, headers=headers
    )


def change_status(client, headers, bill, **body):
    return client.post(
        f"/rent-bills/{bill.id}/status-changes", json=body, headers=headers
    )


def awaiting_bill(make_rent_bill, lease, **options):
    """A bill whose receipt is waiting for management."""
    return make_rent_bill(
        lease,
        status="awaitingVerification",
        receipt=(png(), "image/png", datetime.now(UTC)),
        **options,
    )


def rent_bill_facts(
    bill,
    status: str,
    *,
    method: str | None = None,
    reason: str | None = None,
    days_overdue: int = 0,
) -> dict:
    return {
        "rentBillId": str(bill.id),
        "periodStart": bill.period_start.isoformat(),
        "periodEnd": bill.period_end.isoformat(),
        "dueDate": bill.due_date.isoformat(),
        "amount": bill.amount,
        "paymentStatus": status,
        "paymentMethod": method,
        "reason": reason,
        "daysOverdue": days_overdue,
    }


def room_ref(room) -> dict:
    return {"id": str(room.id), "number": room.number}


def property_ref(prop) -> dict:
    return {"id": str(prop.id), "name": prop.name}


def tenant_ref(user, name: str | None = None) -> dict:
    return {"id": str(user.id), "name": name or user.name}


# Complaint events


def submit_complaint(client, headers, description: str = DESCRIPTION):
    return client.post(COMPLAINTS, json={"description": description}, headers=headers)


def change_complaint(client, headers, complaint_id, status="inProgress", **extra):
    return client.post(
        f"{COMPLAINTS}/{complaint_id}/status-changes",
        json={"status": status, **extra},
        headers=headers,
    )


def classify_manually(client, headers, complaint_id, category="Air", urgency="low"):
    return client.put(
        f"{COMPLAINTS}/{complaint_id}/classification",
        json={"category": category, "urgency": urgency},
        headers=headers,
    )


def complaint_facts(
    complaint_id,
    status: str,
    *,
    description: str = DESCRIPTION,
    category: str | None = None,
    urgency: str | None = None,
    handling_note: str | None = None,
) -> dict:
    return {
        "complaintId": str(complaint_id),
        "description": description,
        "status": status,
        "category": category,
        "urgency": urgency,
        "handlingNote": handling_note,
    }


def assert_item(item: dict, type_: str, **expected: Any) -> None:
    """Check the fields of a notification; fields not given must be null."""
    assert set(item) == NOTIFICATION_FIELDS
    assert item["type"] == type_
    assert item["read"] is False
    for field in ("rentBill", "complaint", "tenant", "room", "property", "actorName"):
        assert item[field] == expected.get(field), field
