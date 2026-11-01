"""Listing the caller's notifications and marking them read."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from notification_support import (
    NOTIFICATION_FIELDS,
    NOTIFICATIONS,
    READ_ALL,
    assert_error,
    assert_not_found,
    items,
    list_all,
    mark_read,
    minutes_ago,
    pay_cash,
    read_all,
    role,
    set_created_at,
    stored_for,
    stored_row,
    stored_rows,
    unassign,
    upload_receipt,
)
from rent_bill_support import days_ago

REQUESTS = [
    pytest.param("get", NOTIFICATIONS, id="list"),
    pytest.param("post", READ_ALL, id="read_all"),
    pytest.param("post", f"{NOTIFICATIONS}/{uuid4()}/read", id="read_one"),
]
STAFF_AND_TENANT = ["tenant_in", "owner_in", "manager_in"]


@pytest.fixture
def lease(scene):
    return scene.tenant.lease


@pytest.fixture
def bill(make_rent_bill, lease):
    return make_rent_bill(lease)


def tenant_notices(client, scene, make_rent_bill, count: int) -> list:
    """Make the owner settle `count` bills in cash, giving the tenant as many notices."""
    bills = []
    for number in range(count):
        bills.append(
            make_rent_bill(scene.tenant.lease, period_start=days_ago(45 + 40 * number))
        )
        assert pay_cash(client, scene.owner_in.headers, bills[-1]).status_code == 200
    return bills


def staff_notices(client, scene, bill) -> None:
    """The tenant uploads a receipt, which notifies the owner and the manager."""
    assert upload_receipt(client, scene.tenant_in.headers, bill).status_code == 200


# Authentication and roles


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


@pytest.mark.parametrize(("method", "url"), REQUESTS)
def test_an_admin_is_forbidden(client, database, make_user, sign_in, method, url):
    session = sign_in(make_user(role=role("admin")))
    response = client.request(method, url, headers=session.headers)
    assert_error(response, 403, "FORBIDDEN")


def test_an_admin_is_refused_before_the_notification_is_looked_up(
    client, database, scene, bill, make_user, sign_in
):
    staff_notices(client, scene, bill)
    (row,) = stored_for(database, scene.owner)
    admin = sign_in(make_user(role=role("admin")))
    assert_error(mark_read(client, admin, row["id"]), 403, "FORBIDDEN")


# Listing


@pytest.mark.parametrize("who", STAFF_AND_TENANT)
def test_a_user_without_notifications_gets_an_empty_list(client, database, scene, who):
    response = client.get(NOTIFICATIONS, headers=getattr(scene, who).headers)
    assert response.status_code == 200
    assert response.json() == {"items": [], "unreadCount": 0}


def test_the_list_has_exactly_the_documented_fields(client, database, scene, bill):
    staff_notices(client, scene, bill)
    body = list_all(client, scene.owner_in)
    assert set(body) == {"items", "unreadCount"}
    (item,) = body["items"]
    assert set(item) == NOTIFICATION_FIELDS


def test_a_new_notification_is_unread_and_counted(client, database, scene, bill):
    staff_notices(client, scene, bill)
    body = list_all(client, scene.owner_in)
    assert [item["read"] for item in body["items"]] == [False]
    assert body["unreadCount"] == 1


def test_the_creation_time_is_a_utc_timestamp_of_the_event(
    client, database, scene, bill
):
    before = datetime.now(UTC)
    staff_notices(client, scene, bill)
    (item,) = items(client, scene.owner_in)
    created = datetime.fromisoformat(item["createdAt"])
    assert created.utcoffset() == timedelta(0)
    assert item["createdAt"].endswith("Z")
    assert before - timedelta(seconds=5) <= created <= datetime.now(UTC)


def test_a_tenant_sees_only_their_own_notifications(
    client, database, scene, make_site, make_rent_bill
):
    neighbour = make_site(scene.owner, name="Kos Kedua", number="B1")
    mine = make_rent_bill(scene.tenant.lease)
    theirs = neighbour.bill
    assert pay_cash(client, scene.owner_in.headers, mine).status_code == 200
    assert pay_cash(client, scene.owner_in.headers, theirs).status_code == 200
    (own,) = items(client, scene.tenant_in)
    (other,) = items(client, neighbour.tenant_in)
    assert own["rentBill"]["rentBillId"] == str(mine.id)
    assert other["rentBill"]["rentBillId"] == str(theirs.id)


def test_an_owner_sees_the_notifications_of_every_property(
    client, database, scene, make_site, bill
):
    second = make_site(scene.owner, name="Kos Kedua", number="B1")
    staff_notices(client, scene, bill)
    assert (
        upload_receipt(client, second.tenant_in.headers, second.bill).status_code == 200
    )
    shown = {item["property"]["name"] for item in items(client, scene.owner_in)}
    assert shown == {"Kos Melati", "Kos Kedua"}


def test_notifications_of_another_owner_never_appear(
    client, database, scene, make_user, make_site, bill
):
    stranger = make_user(name="Other Owner")
    foreign = make_site(stranger, name="Kos Asing", number="Z1")
    assert (
        upload_receipt(client, foreign.tenant_in.headers, foreign.bill).status_code
        == 200
    )
    staff_notices(client, scene, bill)
    names = {item["property"]["name"] for item in items(client, scene.owner_in)}
    assert names == {"Kos Melati"}


def test_a_manager_of_another_property_gets_nothing(
    client, database, scene, make_user, make_site, sign_in, bill
):
    outsider = make_user(name="Outside Manager", role=role("manager"))
    outsider_in = sign_in(outsider)
    staff_notices(client, scene, bill)
    body = list_all(client, outsider_in)
    assert body == {"items": [], "unreadCount": 0}


def test_the_list_is_newest_first(client, database, scene, make_rent_bill):
    bills = tenant_notices(client, scene, make_rent_bill, 3)
    shown = [item["rentBill"]["rentBillId"] for item in items(client, scene.tenant_in)]
    assert shown == [str(b.id) for b in reversed(bills)]


def test_the_order_follows_the_creation_time_not_the_insertion_order(
    client, database, scene, make_rent_bill
):
    bills = tenant_notices(client, scene, make_rent_bill, 3)
    by_bill = {
        item["rentBill"]["rentBillId"]: item["id"]
        for item in items(client, scene.tenant_in)
    }
    # The first-created notification becomes the newest, the last-created the oldest.
    set_created_at(database, by_bill[str(bills[0].id)], minutes_ago(1))
    set_created_at(database, by_bill[str(bills[1].id)], minutes_ago(30))
    set_created_at(database, by_bill[str(bills[2].id)], minutes_ago(60))
    shown = [item["rentBill"]["rentBillId"] for item in items(client, scene.tenant_in)]
    assert shown == [str(b.id) for b in bills]


def test_notifications_created_at_the_same_time_are_ordered_by_id_descending(
    client, database, scene, make_rent_bill
):
    tenant_notices(client, scene, make_rent_bill, 4)
    moment = minutes_ago(10)
    for row in stored_for(database, scene.tenant.user):
        set_created_at(database, row["id"], moment)
    shown = [item["id"] for item in items(client, scene.tenant_in)]
    assert shown == sorted(shown, reverse=True)
    assert len(shown) == 4


def test_unread_count_counts_only_unread_notifications(
    client, database, scene, make_rent_bill
):
    tenant_notices(client, scene, make_rent_bill, 3)
    first = items(client, scene.tenant_in)[0]
    assert mark_read(client, scene.tenant_in, first["id"]).status_code == 200
    body = list_all(client, scene.tenant_in)
    assert len(body["items"]) == 3
    assert body["unreadCount"] == 2
    assert [item["read"] for item in body["items"]] == [True, False, False]


# Manager scoping


@pytest.fixture
def second(scene, make_site):
    """A second property of the owner that the manager is assigned to as well."""
    return make_site(
        scene.owner, name="Kos Kedua", number="B1", managers=[scene.manager]
    )


def both_properties_notify(client, scene, bill, second) -> None:
    assert upload_receipt(client, scene.tenant_in.headers, bill).status_code == 200
    assert (
        upload_receipt(client, second.tenant_in.headers, second.bill).status_code == 200
    )


def test_a_manager_sees_the_notifications_of_every_assigned_property(
    client, database, scene, bill, second
):
    both_properties_notify(client, scene, bill, second)
    body = list_all(client, scene.manager_in)
    assert {item["property"]["name"] for item in body["items"]} == {
        "Kos Melati",
        "Kos Kedua",
    }
    assert body["unreadCount"] == 2


def test_an_unassigned_property_is_hidden_from_the_list_and_the_count_at_once(
    client, database, scene, bill, second
):
    both_properties_notify(client, scene, bill, second)
    unassign(database, scene.manager, second.prop)
    body = list_all(client, scene.manager_in)
    assert [item["property"]["name"] for item in body["items"]] == ["Kos Melati"]
    assert body["unreadCount"] == 1


def test_the_owner_still_sees_a_notification_hidden_from_the_manager(
    client, database, scene, bill, second
):
    both_properties_notify(client, scene, bill, second)
    unassign(database, scene.manager, second.prop)
    body = list_all(client, scene.owner_in)
    assert len(body["items"]) == 2
    assert body["unreadCount"] == 2


def test_assigning_the_property_again_shows_its_notifications_again(
    client, database, scene, bill, second, assign_manager
):
    both_properties_notify(client, scene, bill, second)
    unassign(database, scene.manager, second.prop)
    assign_manager(scene.manager, second.prop)
    body = list_all(client, scene.manager_in)
    assert len(body["items"]) == 2
    assert body["unreadCount"] == 2


def test_a_notification_stays_stored_while_it_is_hidden(
    client, database, scene, bill, second
):
    both_properties_notify(client, scene, bill, second)
    unassign(database, scene.manager, second.prop)
    assert len(stored_for(database, scene.manager)) == 2


def test_a_manager_of_two_owners_sees_both_while_assigned(
    client, database, scene, bill, make_user, make_site
):
    far_owner = make_user(name="Far Owner")
    far = make_site(far_owner, name="Kos Jauh", number="Z1", managers=[scene.manager])
    assert upload_receipt(client, scene.tenant_in.headers, bill).status_code == 200
    assert upload_receipt(client, far.tenant_in.headers, far.bill).status_code == 200
    assert len(items(client, scene.manager_in)) == 2
    unassign(database, scene.manager, scene.prop)
    shown = items(client, scene.manager_in)
    assert [item["property"]["name"] for item in shown] == ["Kos Jauh"]


def test_a_manager_without_assignments_sees_no_notifications(
    client, database, scene, bill, second
):
    both_properties_notify(client, scene, bill, second)
    unassign(database, scene.manager, scene.prop)
    unassign(database, scene.manager, second.prop)
    assert list_all(client, scene.manager_in) == {"items": [], "unreadCount": 0}


# Marking one notification read


def test_marking_a_notification_read_returns_it_as_read(client, database, scene, bill):
    staff_notices(client, scene, bill)
    (item,) = items(client, scene.owner_in)
    response = mark_read(client, scene.owner_in, item["id"])
    assert response.status_code == 200, response.text
    assert response.json() == {**item, "read": True}


def test_a_notification_read_stays_read_in_the_list(client, database, scene, bill):
    staff_notices(client, scene, bill)
    (item,) = items(client, scene.owner_in)
    mark_read(client, scene.owner_in, item["id"])
    body = list_all(client, scene.owner_in)
    assert [i["read"] for i in body["items"]] == [True]
    assert body["unreadCount"] == 0


def test_marking_read_stores_the_read_time(client, database, scene, bill):
    staff_notices(client, scene, bill)
    (item,) = items(client, scene.owner_in)
    assert stored_row(database, item["id"])["read_at"] is None
    before = datetime.now(UTC)
    mark_read(client, scene.owner_in, item["id"])
    stored = stored_row(database, item["id"])["read_at"]
    assert before - timedelta(seconds=5) <= stored <= datetime.now(UTC)


def test_marking_an_already_read_notification_changes_nothing(
    client, database, scene, bill
):
    staff_notices(client, scene, bill)
    (item,) = items(client, scene.owner_in)
    first = mark_read(client, scene.owner_in, item["id"])
    read_at = stored_row(database, item["id"])["read_at"]
    second = mark_read(client, scene.owner_in, item["id"])
    assert second.status_code == 200
    assert second.json() == first.json()
    assert stored_row(database, item["id"])["read_at"] == read_at
    assert list_all(client, scene.owner_in)["unreadCount"] == 0


def test_marking_one_notification_leaves_the_others_unread(
    client, database, scene, make_rent_bill
):
    tenant_notices(client, scene, make_rent_bill, 3)
    target = items(client, scene.tenant_in)[1]
    mark_read(client, scene.tenant_in, target["id"])
    assert [i["read"] for i in items(client, scene.tenant_in)] == [False, True, False]


def test_each_recipient_of_one_event_reads_independently(client, database, scene, bill):
    staff_notices(client, scene, bill)
    (owner_item,) = items(client, scene.owner_in)
    (manager_item,) = items(client, scene.manager_in)
    assert owner_item["id"] != manager_item["id"]
    mark_read(client, scene.manager_in, manager_item["id"])
    assert items(client, scene.owner_in)[0]["read"] is False
    assert items(client, scene.manager_in)[0]["read"] is True


def test_an_unknown_notification_is_not_found(client, database, scene):
    for who in STAFF_AND_TENANT:
        assert_not_found(mark_read(client, getattr(scene, who), uuid4()))


def test_the_notification_of_another_user_is_not_found_and_stays_unread(
    client, database, scene, bill
):
    staff_notices(client, scene, bill)
    (owner_item,) = items(client, scene.owner_in)
    assert_not_found(mark_read(client, scene.manager_in, owner_item["id"]))
    assert_not_found(mark_read(client, scene.tenant_in, owner_item["id"]))
    assert stored_row(database, owner_item["id"])["read_at"] is None


def test_the_notification_of_another_owner_is_not_found(
    client, database, scene, bill, make_user, sign_in
):
    staff_notices(client, scene, bill)
    (owner_item,) = items(client, scene.owner_in)
    stranger = sign_in(make_user(name="Other Owner"))
    assert_not_found(mark_read(client, stranger, owner_item["id"]))


def test_a_notification_hidden_from_a_manager_is_not_found_and_stays_unread(
    client, database, scene, bill, second
):
    both_properties_notify(client, scene, bill, second)
    hidden = next(
        i
        for i in items(client, scene.manager_in)
        if i["property"]["name"] == "Kos Kedua"
    )
    unassign(database, scene.manager, second.prop)
    assert_not_found(mark_read(client, scene.manager_in, hidden["id"]))
    assert stored_row(database, hidden["id"])["read_at"] is None


def test_a_malformed_notification_id_is_a_validation_error(client, database, scene):
    response = client.post(
        f"{NOTIFICATIONS}/not-a-uuid/read", headers=scene.owner_in.headers
    )
    assert_error(response, 422, "VALIDATION_FAILED", "notificationId")


# Marking all notifications read


def test_read_all_answers_no_content(client, database, scene, bill):
    staff_notices(client, scene, bill)
    response = read_all(client, scene.owner_in)
    assert response.status_code == 204
    assert response.content == b""


def test_read_all_marks_every_notification_of_the_caller_read(
    client, database, scene, make_rent_bill
):
    tenant_notices(client, scene, make_rent_bill, 3)
    read_all(client, scene.tenant_in)
    body = list_all(client, scene.tenant_in)
    assert [i["read"] for i in body["items"]] == [True, True, True]
    assert body["unreadCount"] == 0
    assert all(
        r["read_at"] is not None for r in stored_for(database, scene.tenant.user)
    )


def test_read_all_without_notifications_succeeds(client, database, scene):
    for who in STAFF_AND_TENANT:
        assert read_all(client, getattr(scene, who)).status_code == 204


def test_read_all_twice_changes_nothing_the_second_time(client, database, scene, bill):
    staff_notices(client, scene, bill)
    read_all(client, scene.owner_in)
    before = stored_rows(database)
    assert read_all(client, scene.owner_in).status_code == 204
    assert stored_rows(database) == before


def test_read_all_keeps_the_read_time_of_notifications_already_read(
    client, database, scene, make_rent_bill
):
    tenant_notices(client, scene, make_rent_bill, 2)
    first = items(client, scene.tenant_in)[0]
    mark_read(client, scene.tenant_in, first["id"])
    read_at = stored_row(database, first["id"])["read_at"]
    read_all(client, scene.tenant_in)
    assert stored_row(database, first["id"])["read_at"] == read_at


def test_read_all_leaves_the_notifications_of_other_users_unread(
    client, database, scene, bill, make_rent_bill
):
    staff_notices(client, scene, bill)
    tenant_notices(client, scene, make_rent_bill, 1)
    read_all(client, scene.owner_in)
    assert list_all(client, scene.manager_in)["unreadCount"] == 1
    assert list_all(client, scene.tenant_in)["unreadCount"] == 1
    assert list_all(client, scene.owner_in)["unreadCount"] == 0


def test_read_all_leaves_notifications_hidden_from_a_manager_unread(
    client, database, scene, bill, second, assign_manager
):
    both_properties_notify(client, scene, bill, second)
    unassign(database, scene.manager, second.prop)
    read_all(client, scene.manager_in)
    assert list_all(client, scene.manager_in)["unreadCount"] == 0
    hidden = [
        r
        for r in stored_for(database, scene.manager)
        if r["property_id"] == second.prop.id
    ]
    assert [r["read_at"] for r in hidden] == [None]
    assign_manager(scene.manager, second.prop)
    body = list_all(client, scene.manager_in)
    assert body["unreadCount"] == 1
    assert [
        i["read"] for i in body["items"] if i["property"]["name"] == "Kos Kedua"
    ] == [False]


def test_a_notification_created_after_read_all_is_unread(
    client, database, scene, bill, make_rent_bill
):
    staff_notices(client, scene, bill)
    read_all(client, scene.owner_in)
    other = make_rent_bill(scene.tenant.lease, period_start=days_ago(60))
    staff_notices(client, scene, other)
    body = list_all(client, scene.owner_in)
    assert body["unreadCount"] == 1
    assert [i["read"] for i in body["items"]] == [False, True]
