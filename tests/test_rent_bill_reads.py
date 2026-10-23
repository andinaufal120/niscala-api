"""Listing rent bills, reading one and downloading its receipt."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from conftest import BANK_ACCOUNT
from rent_bill_support import (
    CHANGE_FIELDS,
    DETAIL_FIELDS,
    PAYMENT_FIELDS,
    RENT_BILLS,
    SUMMARY_FIELDS,
    assert_error,
    assert_not_found,
    assert_receipt_not_found,
    bill_url,
    clear_bank_account,
    days_ago,
    days_ahead,
    delete_property,
    jpeg,
    parse_time,
    png,
    today,
)


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


def ids(response) -> set[str]:
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()["items"]}


@pytest.fixture
def lease(scene):
    return scene.tenant.lease


@pytest.fixture
def bill(make_rent_bill, lease):
    return make_rent_bill(lease)


@pytest.fixture
def admin_in(make_user, sign_in):
    return sign_in(make_user(name="Ade Admin", role=role("admin")))


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


# Authentication and roles

REQUESTS = [
    pytest.param("get", RENT_BILLS, id="list"),
    pytest.param("get", f"{RENT_BILLS}/{uuid4()}", id="get"),
    pytest.param("get", f"{RENT_BILLS}/{uuid4()}/receipt", id="receipt"),
]


@pytest.mark.parametrize(("method", "url"), REQUESTS)
def test_a_request_without_a_token_is_rejected(client, database, method, url):
    assert_error(client.request(method, url), 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize(("method", "url"), REQUESTS)
def test_a_request_with_a_garbage_token_is_rejected(client, database, method, url):
    response = client.request(method, url, headers={"Authorization": "Bearer garbage"})
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize("name", ["tenant", "owner", "manager"])
@pytest.mark.parametrize(("method", "url"), REQUESTS)
def test_a_request_from_an_unverified_account_is_rejected(
    client, database, make_user, sign_in, name, method, url
):
    session = sign_in(make_user(role=role(name), email_verified=False))
    response = client.request(method, url, headers=session.headers)
    assert_error(response, 403, "EMAIL_NOT_VERIFIED")


def test_admins_cannot_list_rent_bills(client, admin_in):
    assert_error(client.get(RENT_BILLS, headers=admin_in.headers), 403, "FORBIDDEN")


def test_admins_cannot_read_a_rent_bill(client, admin_in, bill):
    response = client.get(bill_url(bill), headers=admin_in.headers)
    assert_error(response, 403, "FORBIDDEN")


def test_admins_cannot_download_a_receipt(client, admin_in, lease, make_rent_bill):
    bill = make_rent_bill(lease, receipt=(png(), "image/png", datetime.now(UTC)))
    response = client.get(bill_url(bill, "/receipt"), headers=admin_in.headers)
    assert_error(response, 403, "FORBIDDEN")


# List

ALL_ROLES = ["tenant_in", "owner_in", "manager_in"]


@pytest.mark.parametrize("who", ALL_ROLES)
def test_an_empty_list_is_a_successful_response(client, scene, who):
    response = client.get(RENT_BILLS, headers=getattr(scene, who).headers)
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_a_tenant_sees_the_bills_of_their_own_lease(client, scene, bill):
    assert ids(client.get(RENT_BILLS, headers=scene.tenant_in.headers)) == {
        str(bill.id)
    }


def test_a_tenant_sees_all_their_own_bills(client, scene, lease, make_rent_bill):
    first = make_rent_bill(lease, period_start=days_ago(65))
    second = make_rent_bill(lease, period_start=days_ago(35))
    third = make_rent_bill(lease)
    result = ids(client.get(RENT_BILLS, headers=scene.tenant_in.headers))
    assert result == {str(first.id), str(second.id), str(third.id)}


def test_a_tenant_does_not_see_the_bills_of_another_tenant(
    client, scene, bill, stranger, make_room, make_verified_tenant, make_rent_bill
):
    neighbour = make_verified_tenant(make_room(scene.prop, number="A2"))
    make_rent_bill(neighbour.lease)
    assert ids(client.get(RENT_BILLS, headers=scene.tenant_in.headers)) == {
        str(bill.id)
    }


def test_an_owner_sees_the_bills_of_all_their_properties(
    client, scene, bill, make_property, make_room, make_verified_tenant, make_rent_bill
):
    second_prop = make_property(scene.owner, name="Kos Kenanga")
    other = make_verified_tenant(make_room(second_prop, number="C1"))
    other_bill = make_rent_bill(other.lease)
    result = ids(client.get(RENT_BILLS, headers=scene.owner_in.headers))
    assert result == {str(bill.id), str(other_bill.id)}


def test_an_owner_does_not_see_the_bills_of_another_owner(
    client, scene, bill, stranger
):
    result = ids(client.get(RENT_BILLS, headers=scene.owner_in.headers))
    assert result == {str(bill.id)}


def test_a_manager_sees_only_bills_of_assigned_properties(
    client, scene, bill, make_property, make_room, make_verified_tenant, make_rent_bill
):
    unassigned = make_property(scene.owner, name="Kos Kenanga")
    other = make_verified_tenant(make_room(unassigned, number="C1"))
    make_rent_bill(other.lease)
    result = ids(client.get(RENT_BILLS, headers=scene.manager_in.headers))
    assert result == {str(bill.id)}


def test_a_manager_without_assignments_sees_nothing(client, bill, make_user, sign_in):
    session = sign_in(make_user(role=role("manager")))
    response = client.get(RENT_BILLS, headers=session.headers)
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_bills_of_a_deleted_property_are_not_listed(client, database, scene, bill):
    delete_property(database, scene.prop)
    for who in ("owner_in", "manager_in"):
        response = client.get(RENT_BILLS, headers=getattr(scene, who).headers)
        assert response.json() == {"items": []}


def test_a_list_item_has_the_summary_fields(client, scene, lease, make_rent_bill):
    bill = make_rent_bill(
        lease,
        period_start=days_ago(5),
        period_end=days_ahead(24),
        due_date=days_ahead(10),
        amount=1250000,
    )
    (item,) = client.get(RENT_BILLS, headers=scene.owner_in.headers).json()["items"]
    assert set(item) == SUMMARY_FIELDS
    assert item["id"] == str(bill.id)
    assert item["tenant"] == {"id": str(scene.tenant.id), "name": "Budi Tenant"}
    assert item["room"] == {"id": str(scene.room.id), "number": "A1"}
    assert item["periodStart"] == days_ago(5).isoformat()
    assert item["periodEnd"] == days_ahead(24).isoformat()
    assert item["dueDate"] == days_ahead(10).isoformat()
    assert item["amount"] == 1250000
    assert item["daysOverdue"] == 0
    assert item["property"] == {"id": str(scene.prop.id), "name": "Kos Melati"}
    assert item["isCurrent"] is True
    assert item["canUploadReceipt"] is True
    assert set(item["payment"]) == PAYMENT_FIELDS
    assert item["payment"] == {
        "status": "unpaid",
        "method": None,
        "paidOn": None,
        "hasReceipt": False,
        "rejectionReason": None,
    }


def test_a_list_item_shows_a_paid_bill_with_method_and_date(
    client, scene, lease, make_rent_bill
):
    make_rent_bill(lease, status="paid", method="cash", paid_on=days_ago(2))
    (item,) = client.get(RENT_BILLS, headers=scene.tenant_in.headers).json()["items"]
    assert item["payment"]["status"] == "paid"
    assert item["payment"]["method"] == "cash"
    assert item["payment"]["paidOn"] == days_ago(2).isoformat()


def test_a_list_item_shows_the_rejection_reason(client, scene, lease, make_rent_bill):
    make_rent_bill(lease, status="rejected", rejection_reason="Blurry photo.")
    (item,) = client.get(RENT_BILLS, headers=scene.tenant_in.headers).json()["items"]
    assert item["payment"]["status"] == "rejected"
    assert item["payment"]["rejectionReason"] == "Blurry photo."


def test_a_list_item_reports_whether_a_receipt_is_attached(
    client, scene, lease, make_rent_bill
):
    with_receipt = make_rent_bill(
        lease,
        period_start=days_ago(40),
        status="awaitingVerification",
        receipt=(png(), "image/png", datetime.now(UTC)),
    )
    without = make_rent_bill(lease)
    items = client.get(RENT_BILLS, headers=scene.owner_in.headers).json()["items"]
    flags = {i["id"]: i["payment"]["hasReceipt"] for i in items}
    assert flags == {str(with_receipt.id): True, str(without.id): False}


# Filters


def test_the_tenant_filter_limits_management_to_one_tenant(
    client, scene, bill, make_room, make_verified_tenant, make_rent_bill
):
    other = make_verified_tenant(make_room(scene.prop, number="A2"))
    other_bill = make_rent_bill(other.lease)
    url = f"{RENT_BILLS}?tenantId={other.id}"
    assert ids(client.get(url, headers=scene.owner_in.headers)) == {str(other_bill.id)}
    url = f"{RENT_BILLS}?tenantId={scene.tenant.id}"
    assert ids(client.get(url, headers=scene.manager_in.headers)) == {str(bill.id)}


def test_the_tenant_filter_with_an_unknown_tenant_gives_an_empty_list(
    client, scene, bill
):
    response = client.get(
        f"{RENT_BILLS}?tenantId={uuid4()}", headers=scene.owner_in.headers
    )
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_the_tenant_filter_cannot_reach_a_tenant_outside_access(
    client, scene, bill, stranger
):
    url = f"{RENT_BILLS}?tenantId={stranger.tenant.id}"
    assert client.get(url, headers=scene.owner_in.headers).json() == {"items": []}
    assert client.get(url, headers=scene.manager_in.headers).json() == {"items": []}


def test_a_tenant_cannot_use_the_tenant_filter_to_see_another_tenant(
    client, scene, bill, stranger
):
    url = f"{RENT_BILLS}?tenantId={stranger.tenant.id}"
    assert client.get(url, headers=scene.tenant_in.headers).json() == {"items": []}


def test_a_tenant_may_filter_by_their_own_id(client, scene, bill):
    url = f"{RENT_BILLS}?tenantId={scene.tenant.id}"
    assert ids(client.get(url, headers=scene.tenant_in.headers)) == {str(bill.id)}


@pytest.mark.parametrize(
    "status", ["unpaid", "awaitingVerification", "paid", "rejected"]
)
def test_the_status_filter_returns_only_bills_in_that_status(
    client, scene, lease, make_rent_bill, status
):
    bills = {
        s: make_rent_bill(lease, period_start=days_ago(30 * (i + 1)), status=s)
        for i, s in enumerate(["unpaid", "awaitingVerification", "paid", "rejected"])
    }
    url = f"{RENT_BILLS}?paymentStatus={status}"
    assert ids(client.get(url, headers=scene.owner_in.headers)) == {
        str(bills[status].id)
    }
    assert ids(client.get(url, headers=scene.tenant_in.headers)) == {
        str(bills[status].id)
    }


def test_the_filters_combine(
    client, scene, bill, make_room, make_verified_tenant, make_rent_bill
):
    other = make_verified_tenant(make_room(scene.prop, number="A2"))
    make_rent_bill(other.lease)
    paid = make_rent_bill(other.lease, period_start=days_ago(40), status="paid")
    url = f"{RENT_BILLS}?tenantId={other.id}&paymentStatus=paid"
    assert ids(client.get(url, headers=scene.owner_in.headers)) == {str(paid.id)}


def test_a_filter_with_no_match_gives_an_empty_list(client, scene, bill):
    response = client.get(
        f"{RENT_BILLS}?paymentStatus=paid", headers=scene.owner_in.headers
    )
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_an_unknown_status_filter_is_a_validation_error(client, scene):
    response = client.get(
        f"{RENT_BILLS}?paymentStatus=late", headers=scene.owner_in.headers
    )
    assert_error(response, 422, "VALIDATION_FAILED", "paymentStatus")


def test_a_malformed_tenant_filter_is_a_validation_error(client, scene):
    response = client.get(f"{RENT_BILLS}?tenantId=nope", headers=scene.owner_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", "tenantId")


@pytest.fixture
def second_property(
    scene, make_property, make_room, make_verified_tenant, make_rent_bill
):
    """A second property of the same owner, not assigned to the manager."""
    prop = make_property(scene.owner, name="Kos Kenanga")
    tenant = make_verified_tenant(make_room(prop, number="C1"), name="Sari Tenant")
    return type(
        "Second",
        (),
        {"prop": prop, "tenant": tenant, "bill": make_rent_bill(tenant.lease)},
    )


def test_the_property_filter_limits_the_list_to_one_property(
    client, scene, bill, second_property
):
    url = f"{RENT_BILLS}?propertyId={second_property.prop.id}"
    assert ids(client.get(url, headers=scene.owner_in.headers)) == {
        str(second_property.bill.id)
    }
    url = f"{RENT_BILLS}?propertyId={scene.prop.id}"
    assert ids(client.get(url, headers=scene.owner_in.headers)) == {str(bill.id)}


def test_the_property_filter_cannot_reach_a_property_outside_access(
    client, scene, bill, second_property, stranger
):
    other = f"{RENT_BILLS}?propertyId={stranger.prop.id}"
    assert client.get(other, headers=scene.owner_in.headers).json() == {"items": []}
    unassigned = f"{RENT_BILLS}?propertyId={second_property.prop.id}"
    response = client.get(unassigned, headers=scene.manager_in.headers)
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_the_property_filter_with_an_unknown_property_gives_an_empty_list(
    client, scene, bill
):
    response = client.get(
        f"{RENT_BILLS}?propertyId={uuid4()}", headers=scene.owner_in.headers
    )
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_a_malformed_property_filter_is_a_validation_error(client, scene):
    response = client.get(
        f"{RENT_BILLS}?propertyId=nope", headers=scene.owner_in.headers
    )
    assert_error(response, 422, "VALIDATION_FAILED", "propertyId")


def test_the_property_and_status_filters_combine(
    client, scene, bill, second_property, make_rent_bill
):
    paid = make_rent_bill(
        second_property.tenant.lease, period_start=days_ago(40), status="paid"
    )
    url = f"{RENT_BILLS}?propertyId={second_property.prop.id}&paymentStatus=paid"
    assert ids(client.get(url, headers=scene.owner_in.headers)) == {str(paid.id)}


def test_the_payment_status_filter_may_be_repeated(
    client, scene, lease, make_rent_bill
):
    bills = {
        s: make_rent_bill(lease, period_start=days_ago(30 * (i + 1)), status=s)
        for i, s in enumerate(["unpaid", "awaitingVerification", "paid", "rejected"])
    }
    url = f"{RENT_BILLS}?paymentStatus=unpaid&paymentStatus=rejected"
    expected = {str(bills["unpaid"].id), str(bills["rejected"].id)}
    assert ids(client.get(url, headers=scene.owner_in.headers)) == expected
    assert ids(client.get(url, headers=scene.tenant_in.headers)) == expected


def test_a_repeated_status_filter_with_an_unknown_value_is_a_validation_error(
    client, scene
):
    url = f"{RENT_BILLS}?paymentStatus=unpaid&paymentStatus=late"
    response = client.get(url, headers=scene.owner_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", "paymentStatus")


def test_a_tenant_without_an_active_lease_gets_an_empty_list(
    client, scene, make_room, make_verified_tenant, make_rent_bill, sign_in
):
    former = make_verified_tenant(make_room(scene.prop, number="A9"), lease_ended=True)
    make_rent_bill(former.lease)
    response = client.get(RENT_BILLS, headers=sign_in(former.user).headers)
    assert response.status_code == 200
    assert response.json() == {"items": []}


# Order


def test_bills_are_listed_newest_period_first(client, scene, lease, make_rent_bill):
    oldest = make_rent_bill(lease, period_start=days_ago(70))
    newest = make_rent_bill(lease, period_start=days_ago(5))
    middle = make_rent_bill(lease, period_start=days_ago(35))
    for who in ("tenant_in", "owner_in", "manager_in"):
        items = client.get(RENT_BILLS, headers=getattr(scene, who).headers).json()[
            "items"
        ]
        assert [i["id"] for i in items] == [
            str(newest.id),
            str(middle.id),
            str(oldest.id),
        ]


def test_bills_of_the_same_period_start_are_ordered_by_id(
    client, scene, make_room, make_verified_tenant, make_rent_bill, lease
):
    bills = [make_rent_bill(lease)]
    for number in ("A2", "A3", "A4"):
        other = make_verified_tenant(make_room(scene.prop, number=number))
        bills.append(make_rent_bill(other.lease))
    older = make_rent_bill(lease, period_start=days_ago(40))
    items = client.get(RENT_BILLS, headers=scene.owner_in.headers).json()["items"]
    got = [i["id"] for i in items]
    assert got == sorted(str(b.id) for b in bills) + [str(older.id)]


# Current period and upload flag


@pytest.mark.parametrize(
    ("start", "end", "current"),
    [
        (days_ago(5), days_ahead(24), True),
        (today(), days_ahead(29), True),
        (days_ago(29), today(), True),
        (today(), today(), True),
        (days_ago(30), days_ago(1), False),
        (days_ahead(1), days_ahead(30), False),
        (days_ago(90), days_ago(61), False),
    ],
    ids=[
        "middle",
        "starts_today",
        "ends_today",
        "single_day",
        "ended",
        "future",
        "old",
    ],
)
def test_a_bill_is_current_when_its_period_contains_today(
    client, scene, lease, make_rent_bill, start, end, current
):
    make_rent_bill(lease, period_start=start, period_end=end)
    (item,) = client.get(RENT_BILLS, headers=scene.tenant_in.headers).json()["items"]
    assert item["isCurrent"] is current


def test_current_is_decided_by_the_date_in_jakarta(
    client, scene, lease, make_rent_bill, monkeypatch
):
    from datetime import date

    monkeypatch.setattr(
        "app.services.rent_bills.today_jakarta", lambda: date(2031, 3, 1)
    )
    make_rent_bill(lease, period_start=date(2031, 3, 1), period_end=date(2031, 3, 31))
    (item,) = client.get(RENT_BILLS, headers=scene.tenant_in.headers).json()["items"]
    assert item["isCurrent"] is True
    assert item["canUploadReceipt"] is True


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("unpaid", True),
        ("rejected", True),
        ("awaitingVerification", False),
        ("paid", False),
    ],
)
def test_a_receipt_can_be_uploaded_while_unpaid_or_rejected(
    client, scene, lease, make_rent_bill, status, expected
):
    make_rent_bill(lease, status=status)
    for who in ("tenant_in", "owner_in", "manager_in"):
        (item,) = client.get(RENT_BILLS, headers=getattr(scene, who).headers).json()[
            "items"
        ]
        assert item["canUploadReceipt"] is expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("unpaid", True),
        ("rejected", True),
        ("awaitingVerification", False),
        ("paid", False),
    ],
)
def test_a_receipt_can_be_uploaded_for_a_past_bill_only_while_unpaid_or_rejected(
    client, scene, lease, make_rent_bill, status, expected
):
    make_rent_bill(
        lease, period_start=days_ago(60), period_end=days_ago(31), status=status
    )
    for who in ("tenant_in", "owner_in", "manager_in"):
        (item,) = client.get(RENT_BILLS, headers=getattr(scene, who).headers).json()[
            "items"
        ]
        assert item["isCurrent"] is False
        assert item["canUploadReceipt"] is expected


def test_a_receipt_can_be_uploaded_for_a_bill_of_a_future_period(
    client, scene, lease, make_rent_bill
):
    make_rent_bill(lease, period_start=days_ahead(1), period_end=days_ahead(30))
    (item,) = client.get(RENT_BILLS, headers=scene.tenant_in.headers).json()["items"]
    assert item["isCurrent"] is False
    assert item["canUploadReceipt"] is True


def test_a_receipt_cannot_be_uploaded_for_a_past_bill_without_a_bank_account(
    client, database, scene, lease, make_rent_bill
):
    make_rent_bill(lease, period_start=days_ago(60), period_end=days_ago(31))
    clear_bank_account(database, scene.prop)
    (item,) = client.get(RENT_BILLS, headers=scene.tenant_in.headers).json()["items"]
    assert item["isCurrent"] is False
    assert item["canUploadReceipt"] is False


def test_a_receipt_cannot_be_uploaded_when_the_property_has_no_bank_account(
    client, database, scene, bill
):
    clear_bank_account(database, scene.prop)
    (item,) = client.get(RENT_BILLS, headers=scene.tenant_in.headers).json()["items"]
    assert item["isCurrent"] is True
    assert item["canUploadReceipt"] is False


def test_the_detail_carries_the_same_flags_as_the_list(
    client, scene, lease, make_rent_bill
):
    current = make_rent_bill(lease)
    old = make_rent_bill(lease, period_start=days_ago(60), period_end=days_ago(31))
    for who in ("tenant_in", "owner_in"):
        headers = getattr(scene, who).headers
        body = client.get(bill_url(current), headers=headers).json()
        assert (body["isCurrent"], body["canUploadReceipt"]) == (True, True)
        body = client.get(bill_url(old), headers=headers).json()
        assert (body["isCurrent"], body["canUploadReceipt"]) == (False, True)


# Days overdue


@pytest.mark.parametrize(
    ("status", "due", "expected"),
    [
        ("unpaid", days_ago(3), 3),
        ("unpaid", days_ago(1), 1),
        ("unpaid", days_ago(120), 120),
        ("unpaid", today(), 0),
        ("unpaid", days_ahead(4), 0),
        ("rejected", days_ago(7), 7),
        ("rejected", today(), 0),
        ("rejected", days_ahead(2), 0),
        ("awaitingVerification", days_ago(9), 0),
        ("awaitingVerification", days_ahead(2), 0),
        ("paid", days_ago(9), 0),
        ("paid", days_ahead(2), 0),
    ],
)
def test_days_overdue_counts_days_past_due_only_while_unpaid_or_rejected(
    client, scene, lease, make_rent_bill, status, due, expected
):
    make_rent_bill(lease, status=status, due_date=due)
    (item,) = client.get(RENT_BILLS, headers=scene.tenant_in.headers).json()["items"]
    assert item["daysOverdue"] == expected


def test_detail_carries_the_same_days_overdue_as_the_list(
    client, scene, lease, make_rent_bill
):
    bill = make_rent_bill(lease, due_date=days_ago(4))
    response = client.get(bill_url(bill), headers=scene.owner_in.headers)
    assert response.json()["daysOverdue"] == 4


# Detail


@pytest.mark.parametrize("who", ALL_ROLES)
def test_those_with_access_can_read_a_bill(client, scene, bill, who):
    response = client.get(bill_url(bill), headers=getattr(scene, who).headers)
    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(bill.id)


def test_detail_has_the_summary_and_the_detail_fields(client, scene, bill):
    body = client.get(bill_url(bill), headers=scene.tenant_in.headers).json()
    assert set(body) == DETAIL_FIELDS
    assert body["property"] == {"id": str(scene.prop.id), "name": "Kos Melati"}
    assert body["tenant"] == {"id": str(scene.tenant.id), "name": "Budi Tenant"}
    assert body["room"] == {"id": str(scene.room.id), "number": "A1"}
    UUID(body["id"])


def test_detail_includes_the_bank_account_of_the_property(client, scene, bill):
    for who in ALL_ROLES:
        body = client.get(bill_url(bill), headers=getattr(scene, who).headers).json()
        assert body["bankAccount"] == BANK_ACCOUNT


def test_detail_has_no_bank_account_when_the_property_has_none(
    client, database, scene, bill
):
    clear_bank_account(database, scene.prop)
    body = client.get(bill_url(bill), headers=scene.tenant_in.headers).json()
    assert body["bankAccount"] is None


def test_the_history_of_a_new_bill_is_its_creation(client, scene, bill):
    body = client.get(bill_url(bill), headers=scene.tenant_in.headers).json()
    (change,) = body["statusChanges"]
    assert set(change) == CHANGE_FIELDS
    assert change["status"] == "unpaid"
    assert change["method"] is None
    assert change["reason"] is None
    assert change["manual"] is False
    assert change["actorName"] is None
    parse_time(change["changedAt"])


def test_the_history_is_listed_oldest_first(client, scene, lease, make_rent_bill):
    now = datetime.now(UTC)
    owner = scene.owner.id
    bill = make_rent_bill(
        lease,
        status="paid",
        method="cash",
        paid_on=days_ago(1),
        changes=[
            ("paid", "cash", None, False, owner, now - timedelta(hours=1)),
            ("unpaid", None, None, False, None, now - timedelta(days=3)),
            (
                "rejected",
                None,
                "Wrong amount.",
                False,
                scene.manager.id,
                now - timedelta(days=2),
            ),
        ],
    )
    body = client.get(bill_url(bill), headers=scene.owner_in.headers).json()
    assert [c["status"] for c in body["statusChanges"]] == [
        "unpaid",
        "rejected",
        "paid",
    ]
    times = [parse_time(c["changedAt"]) for c in body["statusChanges"]]
    assert times == sorted(times)


def test_each_history_entry_carries_actor_reason_method_and_manual_flag(
    client, scene, lease, make_rent_bill
):
    now = datetime.now(UTC)
    bill = make_rent_bill(
        lease,
        status="paid",
        method="transfer",
        paid_on=days_ago(1),
        changes=[
            ("unpaid", None, None, False, None, now - timedelta(days=4)),
            (
                "rejected",
                None,
                "Wrong amount.",
                False,
                scene.manager.id,
                now - timedelta(days=3),
            ),
            (
                "paid",
                "transfer",
                "Checked the bank statement.",
                True,
                scene.owner.id,
                now - timedelta(days=2),
            ),
        ],
    )
    body = client.get(bill_url(bill), headers=scene.tenant_in.headers).json()
    created, rejected, paid = body["statusChanges"]
    assert created["actorName"] is None
    assert created["manual"] is False
    assert rejected["actorName"] == "Mira Manager"
    assert rejected["reason"] == "Wrong amount."
    assert rejected["manual"] is False
    assert rejected["method"] is None
    assert paid["actorName"] == "Rina Owner"
    assert paid["reason"] == "Checked the bank statement."
    assert paid["method"] == "transfer"
    assert paid["manual"] is True


def test_a_tenant_actor_is_named_in_the_history(client, scene, lease, make_rent_bill):
    now = datetime.now(UTC)
    bill = make_rent_bill(
        lease,
        status="awaitingVerification",
        changes=[
            ("unpaid", None, None, False, None, now - timedelta(days=1)),
            ("awaitingVerification", None, None, False, scene.tenant.id, now),
        ],
    )
    body = client.get(bill_url(bill), headers=scene.owner_in.headers).json()
    assert body["statusChanges"][-1]["actorName"] == "Budi Tenant"


def test_detail_shows_payment_state_of_a_bill_awaiting_verification(
    client, scene, lease, make_rent_bill
):
    bill = make_rent_bill(
        lease,
        status="awaitingVerification",
        receipt=(png(), "image/png", datetime.now(UTC)),
    )
    body = client.get(bill_url(bill), headers=scene.owner_in.headers).json()
    assert body["payment"]["status"] == "awaitingVerification"
    assert body["payment"]["hasReceipt"] is True
    assert body["daysOverdue"] == 0


# Access to a single bill


def test_a_tenant_cannot_read_the_bill_of_another_tenant(
    client, scene, stranger, make_room, make_verified_tenant, make_rent_bill
):
    neighbour = make_verified_tenant(make_room(scene.prop, number="A2"))
    neighbour_bill = make_rent_bill(neighbour.lease)
    for other in (stranger.bill, neighbour_bill):
        response = client.get(bill_url(other), headers=scene.tenant_in.headers)
        assert_not_found(response)


def test_an_owner_cannot_read_the_bill_of_another_owner(client, scene, stranger):
    response = client.get(bill_url(stranger.bill), headers=scene.owner_in.headers)
    assert_not_found(response)


def test_a_manager_cannot_read_a_bill_of_an_unassigned_property(
    client, scene, make_property, make_room, make_verified_tenant, make_rent_bill
):
    unassigned = make_property(scene.owner, name="Kos Kenanga")
    other = make_verified_tenant(make_room(unassigned, number="C1"))
    other_bill = make_rent_bill(other.lease)
    response = client.get(bill_url(other_bill), headers=scene.manager_in.headers)
    assert_not_found(response)
    response = client.get(bill_url(other_bill), headers=scene.owner_in.headers)
    assert response.status_code == 200


def test_a_bill_of_a_deleted_property_is_not_found(client, database, scene, bill):
    delete_property(database, scene.prop)
    for who in ("owner_in", "manager_in"):
        response = client.get(bill_url(bill), headers=getattr(scene, who).headers)
        assert_not_found(response)


def test_an_unknown_bill_is_not_found(client, scene):
    for who in ALL_ROLES:
        response = client.get(
            f"{RENT_BILLS}/{uuid4()}", headers=getattr(scene, who).headers
        )
        assert_not_found(response)


def test_a_malformed_bill_id_is_a_validation_error(client, scene):
    response = client.get(f"{RENT_BILLS}/not-a-uuid", headers=scene.owner_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", "rentBillId")


def test_a_not_found_response_does_not_differ_between_missing_and_foreign_bills(
    client, scene, stranger
):
    foreign = client.get(bill_url(stranger.bill), headers=scene.owner_in.headers)
    missing = client.get(f"{RENT_BILLS}/{uuid4()}", headers=scene.owner_in.headers)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["code"] == missing.json()["code"]


# Receipt download


@pytest.mark.parametrize(
    ("content", "content_type"),
    [(png(2000), "image/png"), (jpeg(2000), "image/jpeg")],
    ids=["png", "jpeg"],
)
@pytest.mark.parametrize("who", ALL_ROLES)
def test_the_receipt_is_returned_with_its_content_type(
    client, scene, lease, make_rent_bill, who, content, content_type
):
    bill = make_rent_bill(
        lease,
        status="awaitingVerification",
        receipt=(content, content_type, datetime.now(UTC)),
    )
    response = client.get(
        bill_url(bill, "/receipt"), headers=getattr(scene, who).headers
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].split(";")[0] == content_type
    assert response.content == content


def test_a_bill_without_a_receipt_has_no_receipt_to_download(client, scene, bill):
    for who in ALL_ROLES:
        response = client.get(
            bill_url(bill, "/receipt"), headers=getattr(scene, who).headers
        )
        assert_receipt_not_found(response)


def test_the_receipt_is_hidden_from_a_tenant_who_does_not_own_the_bill(
    client, scene, make_rent_bill, make_room, make_verified_tenant, stranger
):
    other = make_rent_bill(
        stranger.tenant.lease,
        period_start=days_ago(40),
        status="awaitingVerification",
        receipt=(png(), "image/png", datetime.now(UTC)),
    )
    neighbour = make_verified_tenant(make_room(scene.prop, number="A2"))
    neighbour_bill = make_rent_bill(
        neighbour.lease,
        status="awaitingVerification",
        receipt=(png(), "image/png", datetime.now(UTC)),
    )
    for hidden in (other, neighbour_bill):
        response = client.get(
            bill_url(hidden, "/receipt"), headers=scene.tenant_in.headers
        )
        assert_not_found(response)


def test_the_receipt_is_hidden_from_management_outside_access(
    client, scene, make_rent_bill, stranger
):
    other = make_rent_bill(
        stranger.tenant.lease,
        period_start=days_ago(40),
        status="awaitingVerification",
        receipt=(png(), "image/png", datetime.now(UTC)),
    )
    for who in ("owner_in", "manager_in"):
        response = client.get(
            bill_url(other, "/receipt"), headers=getattr(scene, who).headers
        )
        assert_not_found(response)


def test_an_unassigned_manager_cannot_download_a_receipt(
    client, scene, make_property, make_room, make_verified_tenant, make_rent_bill
):
    unassigned = make_property(scene.owner, name="Kos Kenanga")
    other = make_verified_tenant(make_room(unassigned, number="C1"))
    bill = make_rent_bill(
        other.lease,
        status="awaitingVerification",
        receipt=(png(), "image/png", datetime.now(UTC)),
    )
    assert_not_found(
        client.get(bill_url(bill, "/receipt"), headers=scene.manager_in.headers)
    )
    assert (
        client.get(
            bill_url(bill, "/receipt"), headers=scene.owner_in.headers
        ).status_code
        == 200
    )


def test_an_unknown_bill_has_no_receipt(client, scene):
    response = client.get(
        f"{RENT_BILLS}/{uuid4()}/receipt", headers=scene.owner_in.headers
    )
    assert_not_found(response)
