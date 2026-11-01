"""Payment pattern facts of all tenants of a property."""

from datetime import timedelta
from uuid import uuid4

import pytest
from rent_bill_support import (
    assert_error,
    days_ago,
    delete_property,
    snapshot,
)

PATTERN_FIELDS = {
    "tenant",
    "room",
    "onTimeCount",
    "countedBillCount",
    "averageDaysLate",
    "arrears",
    "atRisk",
    "summary",
    "summaryWithheld",
}


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


def patterns_url(prop) -> str:
    return f"/properties/{prop.id}/payment-patterns"


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
    """An owner of another property whose tenant has an overdue bill."""
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
            "bill": make_rent_bill(
                tenant.lease,
                period_start=days_ago(40),
                period_end=days_ago(11),
                due_date=days_ago(20),
                amount=9999000,
            ),
        },
    )


@pytest.fixture
def add_bill(make_rent_bill):
    """Add a bill due `due_ago` days ago to a lease; periods never overlap.

    `slot` places the billing period: 0 is the latest, 1 the one before it.
    A paid bill is paid `late` days after its due date.
    """

    def add(lease, slot, due_ago, status="unpaid", *, late=0, amount=1000000):
        start = days_ago(30 * (slot + 1))
        due = days_ago(due_ago)
        extra = {}
        if status == "paid":
            extra = {"method": "transfer", "paid_on": due + timedelta(days=late)}
        if status == "rejected":
            extra = {"rejection_reason": "Blurry photo."}
        return make_rent_bill(
            lease,
            period_start=start,
            period_end=start + timedelta(days=29),
            due_date=due,
            amount=amount,
            status=status,
            **extra,
        )

    return add


def items(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return response.json()["items"]


def only_item(client, scene, headers=None) -> dict:
    response = client.get(
        patterns_url(scene.prop), headers=headers or scene.owner_in.headers
    )
    (item,) = items(response)
    return item


def numbers(response) -> list[str]:
    return [item["room"]["number"] for item in items(response)]


def tenant_ids(response) -> list[str]:
    return [item["tenant"]["id"] for item in items(response)]


def facts(item: dict) -> tuple:
    return (
        item["onTimeCount"],
        item["countedBillCount"],
        item["averageDaysLate"],
        item["arrears"],
        item["atRisk"],
    )


# Authentication and roles


def test_a_request_without_a_token_is_rejected(client, scene):
    response = client.get(patterns_url(scene.prop))
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


def test_a_request_with_a_garbage_token_is_rejected(client, scene):
    response = client.get(
        patterns_url(scene.prop), headers={"Authorization": "Bearer garbage"}
    )
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize("name", ["owner", "manager"])
def test_a_request_from_an_unverified_account_is_rejected(
    client, scene, make_user, sign_in, name
):
    session = sign_in(make_user(role=role(name), email_verified=False))
    response = client.get(patterns_url(scene.prop), headers=session.headers)
    assert_error(response, 403, "EMAIL_NOT_VERIFIED")


def test_a_tenant_cannot_read_the_patterns(client, scene):
    response = client.get(patterns_url(scene.prop), headers=scene.tenant_in.headers)
    assert_error(response, 403, "FORBIDDEN")


def test_an_admin_cannot_read_the_patterns(client, scene, admin_in):
    response = client.get(patterns_url(scene.prop), headers=admin_in.headers)
    assert_error(response, 403, "FORBIDDEN")


def test_a_forbidden_role_is_refused_before_the_property_is_looked_up(
    client, scene, admin_in
):
    response = client.get(
        f"/properties/{uuid4()}/payment-patterns", headers=admin_in.headers
    )
    assert_error(response, 403, "FORBIDDEN")


@pytest.mark.parametrize("who", ["owner_in", "manager_in"])
def test_management_can_read_the_patterns(client, scene, who):
    response = client.get(patterns_url(scene.prop), headers=getattr(scene, who).headers)
    assert response.status_code == 200, response.text


# Access to the property


def test_an_unknown_property_is_not_found(client, scene):
    for who in ("owner_in", "manager_in"):
        response = client.get(
            f"/properties/{uuid4()}/payment-patterns",
            headers=getattr(scene, who).headers,
        )
        assert_property_not_found(response)


def test_a_deleted_property_is_not_found(client, database, scene):
    delete_property(database, scene.prop)
    for who in ("owner_in", "manager_in"):
        response = client.get(
            patterns_url(scene.prop), headers=getattr(scene, who).headers
        )
        assert_property_not_found(response)


def test_the_property_of_another_owner_is_not_found(client, scene, stranger):
    response = client.get(patterns_url(stranger.prop), headers=scene.owner_in.headers)
    assert_property_not_found(response)


def test_an_unassigned_manager_gets_property_not_found(
    client, scene, make_property, make_room, make_verified_tenant
):
    unassigned = make_property(scene.owner, name="Kos Kenanga")
    make_verified_tenant(make_room(unassigned, number="C1"))
    response = client.get(patterns_url(unassigned), headers=scene.manager_in.headers)
    assert_property_not_found(response)
    response = client.get(patterns_url(unassigned), headers=scene.owner_in.headers)
    assert response.status_code == 200


def test_a_manager_whose_assignment_was_removed_loses_access(client, database, scene):
    from sqlalchemy import delete
    from sqlalchemy.orm import Session

    from app.models import ManagerAssignment

    before = client.get(patterns_url(scene.prop), headers=scene.manager_in.headers)
    assert before.status_code == 200
    with Session(database) as db:
        db.execute(
            delete(ManagerAssignment).where(
                ManagerAssignment.manager_id == scene.manager.id
            )
        )
        db.commit()
    after = client.get(patterns_url(scene.prop), headers=scene.manager_in.headers)
    assert_property_not_found(after)
    owner = client.get(patterns_url(scene.prop), headers=scene.owner_in.headers)
    assert owner.status_code == 200


def test_a_not_found_response_does_not_differ_between_missing_and_foreign_properties(
    client, scene, stranger
):
    foreign = client.get(patterns_url(stranger.prop), headers=scene.owner_in.headers)
    missing = client.get(
        f"/properties/{uuid4()}/payment-patterns", headers=scene.owner_in.headers
    )
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["code"] == missing.json()["code"]


def test_a_malformed_property_id_is_a_validation_error(client, scene):
    response = client.get(
        "/properties/not-a-uuid/payment-patterns", headers=scene.owner_in.headers
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


# Shape


def test_the_response_has_only_items(client, scene):
    body = client.get(patterns_url(scene.prop), headers=scene.owner_in.headers).json()
    assert set(body) == {"items"}


def test_an_item_has_exactly_the_pattern_fields(client, scene):
    item = only_item(client, scene)
    assert set(item) == PATTERN_FIELDS


def test_an_item_names_its_tenant_and_room(client, scene):
    item = only_item(client, scene)
    assert item["tenant"] == {"id": str(scene.tenant.id), "name": "Budi Tenant"}
    assert item["room"] == {"id": str(scene.room.id), "number": "A1"}


def test_the_summary_is_none_and_not_withheld(client, scene, lease, add_bill):
    add_bill(lease, 0, 3)
    item = only_item(client, scene)
    assert item["summary"] is None
    assert item["summaryWithheld"] is False


def test_a_manager_and_an_owner_see_the_same_patterns(client, scene, lease, add_bill):
    add_bill(lease, 1, 40, "paid", late=3)
    add_bill(lease, 0, 12, "rejected", amount=2000000)
    owner = client.get(patterns_url(scene.prop), headers=scene.owner_in.headers)
    manager = client.get(patterns_url(scene.prop), headers=scene.manager_in.headers)
    assert owner.status_code == manager.status_code == 200
    assert owner.json() == manager.json()
    assert facts(owner.json()["items"][0]) == (1, 2, 8, 2000000, True)


# Which tenants are listed


def test_an_empty_property_gives_no_items(client, scene, make_property):
    empty = make_property(scene.owner, name="Kos Kenanga")
    response = client.get(patterns_url(empty), headers=scene.owner_in.headers)
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_a_manager_sees_an_empty_assigned_property_as_empty(
    client, scene, make_property, assign_manager
):
    empty = make_property(scene.owner, name="Kos Kenanga")
    assign_manager(scene.manager, empty)
    response = client.get(patterns_url(empty), headers=scene.manager_in.headers)
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_a_tenant_with_an_ended_lease_is_not_listed(
    client, scene, make_room, make_verified_tenant, make_rent_bill
):
    former = make_verified_tenant(
        make_room(scene.prop, number="A9"), name="Former", lease_ended=True
    )
    make_rent_bill(former.lease, due_date=days_ago(30))
    result = tenant_ids(
        client.get(patterns_url(scene.prop), headers=scene.owner_in.headers)
    )
    assert result == [str(scene.tenant.id)]


def test_a_deleted_tenant_is_not_listed(
    client, scene, make_room, make_verified_tenant, make_rent_bill
):
    gone = make_verified_tenant(
        make_room(scene.prop, number="A9"), name="Gone", deleted=True
    )
    make_rent_bill(gone.lease, due_date=days_ago(30))
    result = tenant_ids(
        client.get(patterns_url(scene.prop), headers=scene.owner_in.headers)
    )
    assert result == [str(scene.tenant.id)]


def test_a_tenant_who_has_not_activated_is_listed(
    client, scene, make_room, make_tenant, add_bill
):
    pending = make_tenant(make_room(scene.prop, number="A2"), name="Pending")
    add_bill(pending.lease, 0, 3, amount=1300000)
    by_tenant = {
        i["tenant"]["id"]: i
        for i in items(
            client.get(patterns_url(scene.prop), headers=scene.owner_in.headers)
        )
    }
    assert by_tenant[str(pending.id)]["tenant"]["name"] == "Pending"
    assert by_tenant[str(pending.id)]["arrears"] == 1300000


def test_tenants_of_other_properties_are_not_listed(
    client, scene, stranger, make_property, make_room, make_verified_tenant
):
    sibling = make_property(scene.owner, name="Kos Kenanga")
    other = make_verified_tenant(make_room(sibling, number="C1"), name="Sari")
    for headers in (scene.owner_in.headers, scene.manager_in.headers):
        result = tenant_ids(client.get(patterns_url(scene.prop), headers=headers))
        assert result == [str(scene.tenant.id)]
    result = tenant_ids(
        client.get(patterns_url(sibling), headers=scene.owner_in.headers)
    )
    assert result == [str(other.id)]


def test_bills_of_other_properties_never_appear(
    client, scene, stranger, make_property, make_room, make_verified_tenant, add_bill
):
    sibling = make_property(scene.owner, name="Kos Kenanga")
    other = make_verified_tenant(make_room(sibling, number="C1"))
    add_bill(other.lease, 0, 20, amount=8888000)
    item = only_item(client, scene)
    assert facts(item) == (0, 0, 0, 0, False)
    response = client.get(patterns_url(scene.prop), headers=scene.owner_in.headers)
    assert str(other.id) not in response.text
    assert str(stranger.tenant.id) not in response.text


# Order


def test_items_are_in_natural_room_number_order(
    client, scene, make_property, make_room, make_verified_tenant
):
    prop = make_property(scene.owner, name="Kos Urut")
    for number in ("10", "2", "1", "B12", "B3"):
        make_verified_tenant(make_room(prop, number=number), name=f"T{number}")
    result = numbers(client.get(patterns_url(prop), headers=scene.owner_in.headers))
    assert result == ["1", "2", "10", "B3", "B12"]


def test_the_room_number_comes_before_the_tenant_name_in_the_order(
    client, scene, make_property, make_room, make_verified_tenant
):
    prop = make_property(scene.owner, name="Kos Nama")
    make_verified_tenant(make_room(prop, number="5"), name="Zaki")
    make_verified_tenant(make_room(prop, number="6"), name="Adi")
    result = items(client.get(patterns_url(prop), headers=scene.owner_in.headers))
    assert [i["tenant"]["name"] for i in result] == ["Zaki", "Adi"]


def test_the_order_does_not_depend_on_the_bills(
    client, scene, make_property, make_room, make_verified_tenant, add_bill
):
    prop = make_property(scene.owner, name="Kos Urut")
    first = make_verified_tenant(make_room(prop, number="3"), name="First")
    second = make_verified_tenant(make_room(prop, number="11"), name="Second")
    add_bill(second.lease, 0, 30)
    result = tenant_ids(client.get(patterns_url(prop), headers=scene.owner_in.headers))
    assert result == [str(first.id), str(second.id)]


def test_the_order_matches_the_payment_overview(
    client, scene, make_property, make_room, make_verified_tenant
):
    prop = make_property(scene.owner, name="Kos Urut")
    for number in ("20", "3", "100", "A1"):
        make_verified_tenant(make_room(prop, number=number))
    patterns = client.get(patterns_url(prop), headers=scene.owner_in.headers)
    overview = client.get(
        f"/properties/{prop.id}/payment-overview", headers=scene.owner_in.headers
    )
    assert tenant_ids(patterns) == tenant_ids(overview)


# Facts of one tenant


def test_a_tenant_without_bills_has_zero_facts(client, scene):
    item = only_item(client, scene)
    assert facts(item) == (0, 0, 0, 0, False)


def test_a_bill_not_yet_due_is_not_counted(client, scene, lease, add_bill):
    add_bill(lease, 0, -10)
    assert facts(only_item(client, scene)) == (0, 0, 0, 0, False)


def test_a_bill_due_today_is_not_overdue(client, scene, lease, add_bill):
    add_bill(lease, 0, 0)
    assert facts(only_item(client, scene)) == (0, 0, 0, 0, False)


def test_a_bill_paid_on_its_due_date_is_on_time(client, scene, lease, add_bill):
    add_bill(lease, 0, 10, "paid", late=0)
    assert facts(only_item(client, scene)) == (1, 1, 0, 0, False)


def test_a_bill_paid_a_day_late_is_late(client, scene, lease, add_bill):
    add_bill(lease, 0, 10, "paid", late=1)
    assert facts(only_item(client, scene)) == (0, 1, 1, 0, False)


def test_an_overdue_unpaid_bill_is_late_and_in_arrears(client, scene, lease, add_bill):
    add_bill(lease, 0, 3, amount=1750000)
    assert facts(only_item(client, scene)) == (0, 1, 3, 1750000, False)


def test_a_rejected_overdue_bill_is_late_and_in_arrears(client, scene, lease, add_bill):
    add_bill(lease, 0, 4, "rejected", amount=1100000)
    assert facts(only_item(client, scene)) == (0, 1, 4, 1100000, False)


def test_a_bill_awaiting_verification_is_ignored(client, scene, lease, add_bill):
    add_bill(lease, 0, 30, "awaitingVerification", amount=5000000)
    assert facts(only_item(client, scene)) == (0, 0, 0, 0, False)


def test_a_bill_paid_late_is_not_in_arrears(client, scene, lease, add_bill):
    add_bill(lease, 0, 30, "paid", late=20, amount=5000000)
    assert facts(only_item(client, scene)) == (0, 1, 20, 0, False)


def test_a_mixed_history_gives_each_fact(client, scene, lease, add_bill):
    add_bill(lease, 4, 130, "paid")
    add_bill(lease, 3, 100, "paid", late=2)
    add_bill(lease, 2, 70, "paid", late=3)
    add_bill(lease, 1, 40, "awaitingVerification")
    add_bill(lease, 0, 5, amount=1200000)
    assert facts(only_item(client, scene)) == (1, 4, 3, 1200000, True)


def test_the_average_days_late_is_rounded_half_up(client, scene, lease, add_bill):
    add_bill(lease, 1, 40, "paid", late=2)
    add_bill(lease, 0, 10, "paid", late=3)
    assert only_item(client, scene)["averageDaysLate"] == 3


def test_only_the_latest_six_counted_bills_are_counted(client, scene, lease, add_bill):
    for slot in range(1, 7):
        add_bill(lease, slot, 10 + 30 * slot, "paid")
    add_bill(lease, 7, 10 + 30 * 7, "paid", late=9)
    item = only_item(client, scene)
    assert facts(item) == (6, 6, 0, 0, False)


def test_arrears_include_overdue_bills_outside_the_latest_six(
    client, scene, lease, add_bill
):
    for slot in range(6):
        add_bill(lease, slot, 10 + 30 * slot, "paid")
    add_bill(lease, 6, 190, amount=3000000)
    assert facts(only_item(client, scene)) == (6, 6, 0, 3000000, True)


def test_two_late_bills_make_the_tenant_at_risk(client, scene, lease, add_bill):
    add_bill(lease, 1, 40, "paid", late=1)
    add_bill(lease, 0, 10, "paid", late=1)
    assert only_item(client, scene)["atRisk"] is True


def test_one_late_bill_does_not_make_the_tenant_at_risk(client, scene, lease, add_bill):
    add_bill(lease, 1, 40, "paid")
    add_bill(lease, 0, 10, "paid", late=5)
    assert only_item(client, scene)["atRisk"] is False


def test_a_bill_overdue_by_seven_days_does_not_make_the_tenant_at_risk(
    client, scene, lease, add_bill
):
    add_bill(lease, 0, 7)
    assert only_item(client, scene)["atRisk"] is False


def test_a_bill_overdue_by_eight_days_makes_the_tenant_at_risk(
    client, scene, lease, add_bill
):
    add_bill(lease, 0, 8)
    assert only_item(client, scene)["atRisk"] is True


def test_on_time_tenants_are_not_at_risk(client, scene, lease, add_bill):
    for slot in range(8):
        add_bill(lease, slot, 10 + 30 * slot, "paid", late=-2)
    assert facts(only_item(client, scene)) == (6, 6, 0, 0, False)


# Facts are per tenant and use the clock


def test_each_tenant_gets_the_facts_of_their_own_lease(
    client, scene, lease, add_bill, make_room, make_verified_tenant
):
    other = make_verified_tenant(make_room(scene.prop, number="A2"), name="Citra")
    add_bill(lease, 0, 10, "paid")
    add_bill(other.lease, 1, 40, "paid", late=1)
    add_bill(other.lease, 0, 10, amount=2500000)
    by_tenant = {
        i["tenant"]["id"]: i
        for i in items(
            client.get(patterns_url(scene.prop), headers=scene.owner_in.headers)
        )
    }
    assert facts(by_tenant[str(scene.tenant.id)]) == (1, 1, 0, 0, False)
    assert facts(by_tenant[str(other.id)]) == (0, 2, 6, 2500000, True)


# Reading changes nothing


def test_reading_the_patterns_changes_no_stored_state(
    client, database, scene, lease, add_bill
):
    bills = [
        add_bill(lease, 1, 40, "paid", late=2),
        add_bill(lease, 0, 12, "rejected"),
    ]
    before = [snapshot(database, bill) for bill in bills]
    for headers in (scene.owner_in.headers, scene.manager_in.headers):
        assert client.get(patterns_url(scene.prop), headers=headers).status_code == 200
    assert [snapshot(database, bill) for bill in bills] == before
