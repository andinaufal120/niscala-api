"""Payment status of all tenants of a property on a date."""

from uuid import uuid4

import pytest
from rent_bill_support import (
    SUMMARY_FIELDS,
    assert_error,
    days_ago,
    days_ahead,
    delete_property,
    snapshot,
    today,
)

ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


def overview_url(prop, query: str = "") -> str:
    return f"/properties/{prop.id}/payment-overview{query}"


def at(prop, day) -> str:
    return overview_url(prop, f"?date={day.isoformat()}")


def assert_property_not_found(response) -> None:
    assert_error(response, 404, "PROPERTY_NOT_FOUND")


@pytest.fixture
def admin_in(make_user, sign_in):
    return sign_in(make_user(name="Ade Admin", role=role("admin")))


@pytest.fixture
def lease(scene):
    return scene.tenant.lease


@pytest.fixture
def stranger(make_user, make_property, make_room, make_verified_tenant, make_rent_bill):
    """An owner of another property whose tenant has a bill."""
    owner = make_user(name="Other Owner")
    prop = make_property(owner, name="Kos Mawar")
    room = make_room(prop, number="Z1")
    tenant = make_verified_tenant(room, name="Dewi Tenant")
    return type(
        "Stranger",
        (),
        {
            "owner": owner,
            "prop": prop,
            "tenant": tenant,
            "bill": make_rent_bill(tenant.lease),
        },
    )


def numbers(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [item["room"]["number"] for item in response.json()["items"]]


def tenant_ids(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [item["tenant"]["id"] for item in response.json()["items"]]


# Authentication and roles


def test_a_request_without_a_token_is_rejected(client, scene):
    response = client.get(overview_url(scene.prop))
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


def test_a_request_with_a_garbage_token_is_rejected(client, scene):
    response = client.get(
        overview_url(scene.prop), headers={"Authorization": "Bearer garbage"}
    )
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize("name", ["owner", "manager"])
def test_a_request_from_an_unverified_account_is_rejected(
    client, scene, make_user, sign_in, name
):
    session = sign_in(make_user(role=role(name), email_verified=False))
    response = client.get(overview_url(scene.prop), headers=session.headers)
    assert_error(response, 403, "EMAIL_NOT_VERIFIED")


def test_a_tenant_cannot_read_the_overview(client, scene):
    response = client.get(overview_url(scene.prop), headers=scene.tenant_in.headers)
    assert_error(response, 403, "FORBIDDEN")


def test_a_tenant_of_the_property_cannot_read_the_overview_on_a_date(client, scene):
    response = client.get(at(scene.prop, today()), headers=scene.tenant_in.headers)
    assert_error(response, 403, "FORBIDDEN")


def test_an_admin_cannot_read_the_overview(client, scene, admin_in):
    response = client.get(overview_url(scene.prop), headers=admin_in.headers)
    assert_error(response, 403, "FORBIDDEN")


def test_a_forbidden_role_is_refused_before_the_property_is_looked_up(
    client, scene, admin_in
):
    response = client.get(
        f"/properties/{uuid4()}/payment-overview", headers=admin_in.headers
    )
    assert_error(response, 403, "FORBIDDEN")


@pytest.mark.parametrize("who", ["owner_in", "manager_in"])
def test_management_can_read_the_overview(client, scene, who):
    response = client.get(overview_url(scene.prop), headers=getattr(scene, who).headers)
    assert response.status_code == 200, response.text


# Access to the property


def test_an_unknown_property_is_not_found(client, scene):
    for who in ("owner_in", "manager_in"):
        response = client.get(
            f"/properties/{uuid4()}/payment-overview",
            headers=getattr(scene, who).headers,
        )
        assert_property_not_found(response)


def test_a_deleted_property_is_not_found(client, database, scene, bill_for_scene):
    delete_property(database, scene.prop)
    for who in ("owner_in", "manager_in"):
        response = client.get(
            overview_url(scene.prop), headers=getattr(scene, who).headers
        )
        assert_property_not_found(response)


def test_the_property_of_another_owner_is_not_found(client, scene, stranger):
    response = client.get(overview_url(stranger.prop), headers=scene.owner_in.headers)
    assert_property_not_found(response)


def test_an_unassigned_manager_gets_property_not_found(
    client, scene, make_property, make_room, make_verified_tenant
):
    unassigned = make_property(scene.owner, name="Kos Kenanga")
    make_verified_tenant(make_room(unassigned, number="C1"))
    response = client.get(overview_url(unassigned), headers=scene.manager_in.headers)
    assert_property_not_found(response)
    response = client.get(overview_url(unassigned), headers=scene.owner_in.headers)
    assert response.status_code == 200


def test_a_manager_whose_assignment_was_removed_loses_access(client, database, scene):
    from sqlalchemy import delete
    from sqlalchemy.orm import Session

    from app.models import ManagerAssignment

    before = client.get(overview_url(scene.prop), headers=scene.manager_in.headers)
    assert before.status_code == 200
    with Session(database) as db:
        db.execute(
            delete(ManagerAssignment).where(
                ManagerAssignment.manager_id == scene.manager.id
            )
        )
        db.commit()
    after = client.get(overview_url(scene.prop), headers=scene.manager_in.headers)
    assert_property_not_found(after)
    owner = client.get(overview_url(scene.prop), headers=scene.owner_in.headers)
    assert owner.status_code == 200


def test_a_not_found_response_does_not_differ_between_missing_and_foreign_properties(
    client, scene, stranger
):
    foreign = client.get(overview_url(stranger.prop), headers=scene.owner_in.headers)
    missing = client.get(
        f"/properties/{uuid4()}/payment-overview", headers=scene.owner_in.headers
    )
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["code"] == missing.json()["code"]


def test_a_malformed_property_id_is_a_validation_error(client, scene):
    response = client.get(
        "/properties/not-a-uuid/payment-overview", headers=scene.owner_in.headers
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


@pytest.fixture
def bill_for_scene(make_rent_bill, lease):
    return make_rent_bill(lease)


# The date


@pytest.mark.parametrize(
    "value",
    ["garbage", "2026-13-01", "2026-02-30", "23-10-2026", "2026/10/23", "2026-10"],
)
def test_an_invalid_date_is_a_validation_error(client, scene, value):
    response = client.get(
        overview_url(scene.prop, f"?date={value}"), headers=scene.owner_in.headers
    )
    assert_error(response, 422, "VALIDATION_FAILED", "date")


def test_an_invalid_date_is_a_validation_error_for_a_manager(client, scene):
    response = client.get(
        overview_url(scene.prop, "?date=nope"), headers=scene.manager_in.headers
    )
    assert_error(response, 422, "VALIDATION_FAILED", "date")


def test_the_date_defaults_to_today_in_jakarta(client, scene):
    body = client.get(overview_url(scene.prop), headers=scene.owner_in.headers).json()
    assert body["date"] == today().isoformat()


def test_the_default_date_follows_the_jakarta_clock(client, scene, monkeypatch):
    from datetime import date

    monkeypatch.setattr(
        "app.services.rent_bills.today_jakarta", lambda: date(2031, 3, 1)
    )
    body = client.get(overview_url(scene.prop), headers=scene.owner_in.headers).json()
    assert body["date"] == "2031-03-01"


def test_a_requested_date_is_echoed(client, scene):
    for day in (days_ago(40), today(), days_ahead(100)):
        body = client.get(at(scene.prop, day), headers=scene.owner_in.headers).json()
        assert body["date"] == day.isoformat()


def test_the_default_date_selects_the_bill_covering_today(
    client, scene, lease, make_rent_bill
):
    older = make_rent_bill(lease, period_start=days_ago(40), period_end=days_ago(11))
    current = make_rent_bill(lease)
    (item,) = client.get(
        overview_url(scene.prop), headers=scene.owner_in.headers
    ).json()["items"]
    assert item["bill"]["id"] == str(current.id)
    assert item["bill"]["id"] != str(older.id)


def test_an_overview_has_only_date_and_items(client, scene):
    body = client.get(overview_url(scene.prop), headers=scene.owner_in.headers).json()
    assert set(body) == {"date", "items"}


# Items


def test_an_item_has_tenant_room_and_bill(client, scene, bill_for_scene):
    (item,) = client.get(
        overview_url(scene.prop), headers=scene.owner_in.headers
    ).json()["items"]
    assert set(item) == {"tenant", "room", "bill"}
    assert item["tenant"] == {"id": str(scene.tenant.id), "name": "Budi Tenant"}
    assert item["room"] == {"id": str(scene.room.id), "number": "A1"}
    assert item["bill"]["id"] == str(bill_for_scene.id)


def test_an_item_bill_is_a_rent_bill_summary(client, scene, lease, make_rent_bill):
    bill = make_rent_bill(
        lease,
        period_start=days_ago(5),
        period_end=days_ahead(24),
        due_date=days_ahead(10),
        amount=1250000,
    )
    (item,) = client.get(
        overview_url(scene.prop), headers=scene.manager_in.headers
    ).json()["items"]
    summary = item["bill"]
    assert set(summary) == SUMMARY_FIELDS
    assert summary["id"] == str(bill.id)
    assert summary["tenant"] == {"id": str(scene.tenant.id), "name": "Budi Tenant"}
    assert summary["room"] == {"id": str(scene.room.id), "number": "A1"}
    assert summary["property"] == {"id": str(scene.prop.id), "name": "Kos Melati"}
    assert summary["periodStart"] == days_ago(5).isoformat()
    assert summary["periodEnd"] == days_ahead(24).isoformat()
    assert summary["dueDate"] == days_ahead(10).isoformat()
    assert summary["amount"] == 1250000
    assert summary["daysOverdue"] == 0
    assert summary["isCurrent"] is True
    assert summary["canUploadReceipt"] is True
    assert summary["payment"] == {
        "status": "unpaid",
        "method": None,
        "paidOn": None,
        "hasReceipt": False,
        "rejectionReason": None,
    }


def test_an_item_bill_shows_a_paid_payment(client, scene, lease, make_rent_bill):
    make_rent_bill(lease, status="paid", method="cash", paid_on=days_ago(2))
    (item,) = client.get(
        overview_url(scene.prop), headers=scene.owner_in.headers
    ).json()["items"]
    payment = item["bill"]["payment"]
    assert payment["status"] == "paid"
    assert payment["method"] == "cash"
    assert payment["paidOn"] == days_ago(2).isoformat()
    assert item["bill"]["canUploadReceipt"] is False


def test_an_item_bill_shows_a_rejection_reason(client, scene, lease, make_rent_bill):
    make_rent_bill(lease, status="rejected", rejection_reason="Blurry photo.")
    (item,) = client.get(
        overview_url(scene.prop), headers=scene.owner_in.headers
    ).json()["items"]
    assert item["bill"]["payment"]["status"] == "rejected"
    assert item["bill"]["payment"]["rejectionReason"] == "Blurry photo."


@pytest.mark.parametrize(
    "status", ["unpaid", "awaitingVerification", "paid", "rejected"]
)
def test_an_item_bill_carries_every_payment_status(
    client, scene, lease, make_rent_bill, status
):
    make_rent_bill(lease, status=status)
    (item,) = client.get(
        overview_url(scene.prop), headers=scene.owner_in.headers
    ).json()["items"]
    assert item["bill"]["payment"]["status"] == status


def test_an_item_bill_reports_whether_a_receipt_is_attached(
    client, scene, lease, make_rent_bill
):
    from datetime import UTC, datetime

    from rent_bill_support import png

    make_rent_bill(
        lease,
        status="awaitingVerification",
        receipt=(png(), "image/png", datetime.now(UTC)),
    )
    (item,) = client.get(
        overview_url(scene.prop), headers=scene.owner_in.headers
    ).json()["items"]
    assert item["bill"]["payment"]["hasReceipt"] is True


def test_a_tenant_without_bills_has_no_bill(client, scene):
    (item,) = client.get(
        overview_url(scene.prop), headers=scene.owner_in.headers
    ).json()["items"]
    assert item["tenant"]["id"] == str(scene.tenant.id)
    assert item["bill"] is None


def test_a_tenant_whose_bills_do_not_cover_the_date_has_no_bill(
    client, scene, lease, make_rent_bill
):
    make_rent_bill(lease, period_start=days_ago(90), period_end=days_ago(61))
    make_rent_bill(lease, period_start=days_ahead(30), period_end=days_ahead(59))
    (item,) = client.get(
        overview_url(scene.prop), headers=scene.owner_in.headers
    ).json()["items"]
    assert item["bill"] is None


def test_an_empty_property_gives_no_items(client, scene, make_property):
    empty = make_property(scene.owner, name="Kos Kenanga")
    response = client.get(overview_url(empty), headers=scene.owner_in.headers)
    assert response.status_code == 200
    assert response.json() == {"date": today().isoformat(), "items": []}


def test_a_manager_sees_an_empty_assigned_property_as_empty(
    client, scene, make_property, assign_manager
):
    empty = make_property(scene.owner, name="Kos Kenanga")
    assign_manager(scene.manager, empty)
    response = client.get(overview_url(empty), headers=scene.manager_in.headers)
    assert response.status_code == 200
    assert response.json()["items"] == []


# Which bill is shown


def test_the_first_day_of_the_period_selects_the_bill(
    client, scene, lease, make_rent_bill
):
    bill = make_rent_bill(lease, period_start=days_ago(10), period_end=days_ahead(19))
    (item,) = client.get(
        at(scene.prop, days_ago(10)), headers=scene.owner_in.headers
    ).json()["items"]
    assert item["bill"]["id"] == str(bill.id)


def test_the_last_day_of_the_period_selects_the_bill(
    client, scene, lease, make_rent_bill
):
    bill = make_rent_bill(lease, period_start=days_ago(10), period_end=days_ahead(19))
    (item,) = client.get(
        at(scene.prop, days_ahead(19)), headers=scene.owner_in.headers
    ).json()["items"]
    assert item["bill"]["id"] == str(bill.id)


def test_the_day_before_and_after_the_period_select_nothing(
    client, scene, lease, make_rent_bill
):
    make_rent_bill(lease, period_start=days_ago(10), period_end=days_ahead(19))
    for day in (days_ago(11), days_ahead(20)):
        (item,) = client.get(
            at(scene.prop, day), headers=scene.owner_in.headers
        ).json()["items"]
        assert item["bill"] is None


def test_a_single_day_period_is_selected_only_on_that_day(
    client, scene, lease, make_rent_bill
):
    bill = make_rent_bill(lease, period_start=days_ago(3), period_end=days_ago(3))
    (item,) = client.get(
        at(scene.prop, days_ago(3)), headers=scene.owner_in.headers
    ).json()["items"]
    assert item["bill"]["id"] == str(bill.id)
    for day in (days_ago(4), days_ago(2)):
        (item,) = client.get(
            at(scene.prop, day), headers=scene.owner_in.headers
        ).json()["items"]
        assert item["bill"] is None


def test_consecutive_bills_are_told_apart_by_the_date(
    client, scene, lease, make_rent_bill
):
    first = make_rent_bill(lease, period_start=days_ago(60), period_end=days_ago(31))
    second = make_rent_bill(lease, period_start=days_ago(30), period_end=days_ago(1))
    third = make_rent_bill(lease, period_start=today(), period_end=days_ahead(29))
    expected = {
        days_ago(45): first,
        days_ago(31): first,
        days_ago(30): second,
        days_ago(1): second,
        today(): third,
    }
    for day, bill in expected.items():
        (item,) = client.get(
            at(scene.prop, day), headers=scene.owner_in.headers
        ).json()["items"]
        assert item["bill"]["id"] == str(bill.id), day


def test_a_past_date_shows_the_bill_of_that_period(
    client, scene, lease, make_rent_bill
):
    old = make_rent_bill(
        lease,
        period_start=days_ago(60),
        period_end=days_ago(31),
        due_date=days_ago(50),
        status="paid",
        method="transfer",
        paid_on=days_ago(52),
    )
    make_rent_bill(lease)
    (item,) = client.get(
        at(scene.prop, days_ago(45)), headers=scene.owner_in.headers
    ).json()["items"]
    assert item["bill"]["id"] == str(old.id)
    assert item["bill"]["payment"]["status"] == "paid"


def test_a_future_date_shows_the_bill_of_that_period(
    client, scene, lease, make_rent_bill
):
    make_rent_bill(lease)
    later = make_rent_bill(
        lease, period_start=days_ahead(25), period_end=days_ahead(54)
    )
    (item,) = client.get(
        at(scene.prop, days_ahead(30)), headers=scene.owner_in.headers
    ).json()["items"]
    assert item["bill"]["id"] == str(later.id)


def test_each_tenant_gets_the_bill_of_their_own_lease(
    client, scene, bill_for_scene, make_room, make_verified_tenant, make_rent_bill
):
    other = make_verified_tenant(make_room(scene.prop, number="A2"), name="Citra")
    other_bill = make_rent_bill(other.lease, amount=2500000)
    items = client.get(overview_url(scene.prop), headers=scene.owner_in.headers).json()[
        "items"
    ]
    shown = {i["tenant"]["id"]: i["bill"]["id"] for i in items}
    assert shown == {
        str(scene.tenant.id): str(bill_for_scene.id),
        str(other.id): str(other_bill.id),
    }


def test_only_the_tenants_with_a_covering_bill_have_one(
    client, scene, bill_for_scene, make_room, make_verified_tenant, make_rent_bill
):
    other = make_verified_tenant(make_room(scene.prop, number="A2"), name="Citra")
    make_rent_bill(other.lease, period_start=days_ago(90), period_end=days_ago(61))
    items = client.get(overview_url(scene.prop), headers=scene.owner_in.headers).json()[
        "items"
    ]
    shown = {i["tenant"]["id"]: i["bill"] for i in items}
    assert shown[str(scene.tenant.id)]["id"] == str(bill_for_scene.id)
    assert shown[str(other.id)] is None


# Overdue and current are decided by today, not by the requested date


def test_days_overdue_is_counted_against_today_not_the_requested_date(
    client, scene, lease, make_rent_bill
):
    make_rent_bill(
        lease,
        period_start=days_ago(40),
        period_end=days_ago(11),
        due_date=days_ago(30),
    )
    for day in (days_ago(40), days_ago(20), days_ago(11)):
        (item,) = client.get(
            at(scene.prop, day), headers=scene.owner_in.headers
        ).json()["items"]
        assert item["bill"]["daysOverdue"] == 30, day


def test_days_overdue_is_zero_for_a_bill_not_yet_due_today(
    client, scene, lease, make_rent_bill
):
    make_rent_bill(
        lease,
        period_start=days_ahead(10),
        period_end=days_ahead(39),
        due_date=days_ahead(12),
    )
    (item,) = client.get(
        at(scene.prop, days_ahead(30)), headers=scene.owner_in.headers
    ).json()["items"]
    assert item["bill"]["daysOverdue"] == 0


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("unpaid", 3),
        ("rejected", 3),
        ("awaitingVerification", 0),
        ("paid", 0),
    ],
)
def test_days_overdue_counts_only_while_unpaid_or_rejected(
    client, scene, lease, make_rent_bill, status, expected
):
    make_rent_bill(lease, status=status, due_date=days_ago(3))
    (item,) = client.get(
        overview_url(scene.prop), headers=scene.owner_in.headers
    ).json()["items"]
    assert item["bill"]["daysOverdue"] == expected


def test_is_current_is_decided_by_today_not_the_requested_date(
    client, scene, lease, make_rent_bill
):
    make_rent_bill(lease, period_start=days_ago(60), period_end=days_ago(31))
    (item,) = client.get(
        at(scene.prop, days_ago(45)), headers=scene.owner_in.headers
    ).json()["items"]
    assert item["bill"] is not None
    assert item["bill"]["isCurrent"] is False


def test_a_current_bill_is_current_when_asked_for_another_day_of_its_period(
    client, scene, lease, make_rent_bill
):
    make_rent_bill(lease, period_start=days_ago(5), period_end=days_ahead(24))
    (item,) = client.get(
        at(scene.prop, days_ahead(20)), headers=scene.owner_in.headers
    ).json()["items"]
    assert item["bill"]["isCurrent"] is True


def test_a_future_bill_is_not_current(client, scene, lease, make_rent_bill):
    make_rent_bill(lease, period_start=days_ahead(1), period_end=days_ahead(30))
    (item,) = client.get(
        at(scene.prop, days_ahead(15)), headers=scene.owner_in.headers
    ).json()["items"]
    assert item["bill"]["isCurrent"] is False


def test_is_current_follows_the_jakarta_clock(
    client, scene, lease, make_rent_bill, monkeypatch
):
    from datetime import date

    monkeypatch.setattr(
        "app.services.rent_bills.today_jakarta", lambda: date(2031, 3, 1)
    )
    make_rent_bill(lease, period_start=date(2031, 3, 1), period_end=date(2031, 3, 31))
    (item,) = client.get(
        overview_url(scene.prop), headers=scene.owner_in.headers
    ).json()["items"]
    assert item["bill"]["isCurrent"] is True


def test_can_upload_receipt_is_false_without_a_bank_account(
    client, database, scene, bill_for_scene
):
    from rent_bill_support import clear_bank_account

    clear_bank_account(database, scene.prop)
    (item,) = client.get(
        overview_url(scene.prop), headers=scene.owner_in.headers
    ).json()["items"]
    assert item["bill"]["canUploadReceipt"] is False


def test_a_manager_and_an_owner_see_the_same_overview(
    client, scene, lease, make_rent_bill
):
    make_rent_bill(lease, status="rejected", rejection_reason="Wrong amount.")
    owner = client.get(overview_url(scene.prop), headers=scene.owner_in.headers)
    manager = client.get(overview_url(scene.prop), headers=scene.manager_in.headers)
    assert owner.status_code == manager.status_code == 200
    assert owner.json() == manager.json()
    assert owner.json()["items"][0]["bill"]["payment"]["status"] == "rejected"


# Which tenants are listed


def test_a_tenant_with_an_ended_lease_is_not_listed(
    client, scene, bill_for_scene, make_room, make_verified_tenant, make_rent_bill
):
    former = make_verified_tenant(
        make_room(scene.prop, number="A9"), name="Former", lease_ended=True
    )
    make_rent_bill(former.lease)
    result = tenant_ids(
        client.get(overview_url(scene.prop), headers=scene.owner_in.headers)
    )
    assert result == [str(scene.tenant.id)]


def test_a_tenant_who_moved_to_another_room_is_listed_once_for_the_active_lease(
    client, scene, make_room, make_verified_tenant, make_rent_bill
):
    old_room = make_room(scene.prop, number="A0")
    former = make_verified_tenant(old_room, name="Former", lease_ended=True)
    make_rent_bill(former.lease)
    result = numbers(
        client.get(overview_url(scene.prop), headers=scene.owner_in.headers)
    )
    assert result == ["A1"]


def test_a_deleted_tenant_is_not_listed(
    client, scene, bill_for_scene, make_room, make_verified_tenant, make_rent_bill
):
    gone = make_verified_tenant(
        make_room(scene.prop, number="A9"), name="Gone", deleted=True
    )
    make_rent_bill(gone.lease)
    result = tenant_ids(
        client.get(overview_url(scene.prop), headers=scene.owner_in.headers)
    )
    assert result == [str(scene.tenant.id)]


def test_a_tenant_who_has_not_activated_is_listed(
    client, scene, make_room, make_tenant, make_rent_bill
):
    pending = make_tenant(make_room(scene.prop, number="A2"), name="Pending")
    bill = make_rent_bill(pending.lease)
    items = client.get(overview_url(scene.prop), headers=scene.owner_in.headers).json()[
        "items"
    ]
    by_tenant = {i["tenant"]["id"]: i for i in items}
    assert by_tenant[str(pending.id)]["bill"]["id"] == str(bill.id)
    assert by_tenant[str(pending.id)]["tenant"]["name"] == "Pending"


def test_tenants_of_other_properties_are_not_listed(
    client, scene, stranger, make_property, make_room, make_verified_tenant
):
    sibling = make_property(scene.owner, name="Kos Kenanga")
    other = make_verified_tenant(make_room(sibling, number="C1"), name="Sari")
    for headers in (scene.owner_in.headers, scene.manager_in.headers):
        result = tenant_ids(client.get(overview_url(scene.prop), headers=headers))
        assert result == [str(scene.tenant.id)]
    result = tenant_ids(
        client.get(overview_url(sibling), headers=scene.owner_in.headers)
    )
    assert result == [str(other.id)]


def test_bills_of_other_properties_never_appear(
    client,
    scene,
    stranger,
    make_property,
    make_room,
    make_verified_tenant,
    make_rent_bill,
):
    sibling = make_property(scene.owner, name="Kos Kenanga")
    other = make_verified_tenant(make_room(sibling, number="C1"))
    other_bill = make_rent_bill(other.lease)
    response = client.get(overview_url(scene.prop), headers=scene.owner_in.headers)
    assert response.status_code == 200
    assert str(other_bill.id) not in response.text
    assert str(stranger.bill.id) not in response.text


def test_each_property_lists_its_own_tenants(
    client,
    scene,
    bill_for_scene,
    make_property,
    make_room,
    make_verified_tenant,
    make_rent_bill,
):
    sibling = make_property(scene.owner, name="Kos Kenanga")
    other = make_verified_tenant(make_room(sibling, number="C1"), name="Sari")
    other_bill = make_rent_bill(other.lease)
    (first,) = client.get(
        overview_url(scene.prop), headers=scene.owner_in.headers
    ).json()["items"]
    (second,) = client.get(
        overview_url(sibling), headers=scene.owner_in.headers
    ).json()["items"]
    assert first["bill"]["id"] == str(bill_for_scene.id)
    assert second["bill"]["id"] == str(other_bill.id)
    assert second["bill"]["property"] == {"id": str(sibling.id), "name": "Kos Kenanga"}


# Order


def test_items_are_in_natural_room_number_order(
    client, scene, make_room, make_verified_tenant
):
    for number in ("10", "2", "1", "B3", "B12"):
        make_verified_tenant(make_room(scene.prop, number=number), name=f"T{number}")
    result = numbers(
        client.get(overview_url(scene.prop), headers=scene.owner_in.headers)
    )
    assert result.index("2") < result.index("10")
    assert result.index("1") < result.index("2")
    assert result.index("B3") < result.index("B12")


def test_two_comes_before_ten(
    client, database, make_user, make_property, make_room, make_verified_tenant, sign_in
):
    owner = make_user(name="Order Owner")
    prop = make_property(owner, name="Kos Urut")
    make_verified_tenant(make_room(prop, number="10"), name="Ten")
    make_verified_tenant(make_room(prop, number="2"), name="Two")
    result = numbers(client.get(overview_url(prop), headers=sign_in(owner).headers))
    assert result == ["2", "10"]


def test_the_room_number_comes_before_the_tenant_name_in_the_order(
    client, scene, make_property, make_room, make_verified_tenant
):
    prop = make_property(scene.owner, name="Kos Nama")
    make_verified_tenant(make_room(prop, number="5"), name="Zaki")
    make_verified_tenant(make_room(prop, number="6"), name="Adi")
    items = client.get(overview_url(prop), headers=scene.owner_in.headers).json()[
        "items"
    ]
    assert [i["room"]["number"] for i in items] == ["5", "6"]
    assert [i["tenant"]["name"] for i in items] == ["Zaki", "Adi"]


def test_the_order_does_not_depend_on_the_bills(
    client, scene, make_property, make_room, make_verified_tenant, make_rent_bill
):
    prop = make_property(scene.owner, name="Kos Urut")
    late = make_verified_tenant(make_room(prop, number="3"), name="Late")
    early = make_verified_tenant(make_room(prop, number="11"), name="Early")
    make_rent_bill(early.lease)
    result = tenant_ids(client.get(overview_url(prop), headers=scene.owner_in.headers))
    assert result == [str(late.id), str(early.id)]


def test_the_order_is_the_same_for_every_date(
    client, scene, make_property, make_room, make_verified_tenant
):
    prop = make_property(scene.owner, name="Kos Urut")
    for number in ("20", "3", "100"):
        make_verified_tenant(make_room(prop, number=number))
    expected = ["3", "20", "100"]
    for day in (days_ago(90), today(), days_ahead(90)):
        result = numbers(client.get(at(prop, day), headers=scene.owner_in.headers))
        assert result == expected


# Reading changes nothing


def test_reading_the_overview_changes_no_stored_state(
    client, database, scene, lease, make_rent_bill
):
    from datetime import UTC, datetime

    from rent_bill_support import png

    bills = [
        make_rent_bill(lease, period_start=days_ago(60), period_end=days_ago(31)),
        make_rent_bill(
            lease,
            status="awaitingVerification",
            receipt=(png(), "image/png", datetime.now(UTC)),
        ),
    ]
    before = [snapshot(database, bill) for bill in bills]
    for headers in (scene.owner_in.headers, scene.manager_in.headers):
        for url in (
            overview_url(scene.prop),
            at(scene.prop, days_ago(45)),
            at(scene.prop, days_ahead(45)),
        ):
            assert client.get(url, headers=headers).status_code == 200
    assert [snapshot(database, bill) for bill in bills] == before
