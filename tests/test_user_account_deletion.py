"""Deleting a user account as an Admin."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from account_erasure_support import (
    ERASED_NAME,
    KINDS,
    assert_erased,
    assert_history_kept,
    assert_manager_erased,
    assert_owner_erased,
    assert_tenant_erased,
    build_person,
    personal_row_counts,
    seed_history,
    seed_personal_rows,
    seed_session_details,
    seed_tenant_data,
    session_state,
    set_bank_account,
    table_snapshot,
)
from google_support import make_google_user, user_by_subject
from subscription_support import insert_order, set_subscription, stored_orders
from user_account_support import (
    PASSWORD,
    assert_close,
    assert_error,
    count_rows,
    delete_account,
    edit_account,
    get_account,
    get_row,
    listed_ids,
    login,
    read_user,
    refresh,
    rows_of,
    sessions_of,
    set_password,
)


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


@pytest.fixture
def owner(database, make_user):
    user = make_user(name="Rina Owner", email="rina@example.com")
    set_password(database, user)
    return user


def status_of(client, admin_in, user_id) -> str:
    response = get_account(client, admin_in.headers, user_id)
    assert response.status_code == 200, response.text
    return response.json()["status"]


def assigned(database, property_id) -> list:
    from app.models import ManagerAssignment

    return rows_of(
        database, ManagerAssignment, ManagerAssignment.property_id == property_id
    )


def deleted_at_of(database, model, key):
    return get_row(database, model, key).deleted_at


# Deleting an account


def test_deleting_answers_204_without_a_body(client, database, admin_in, owner):
    response = delete_account(client, admin_in.headers, owner.id)
    assert response.status_code == 204
    assert response.content == b""


def test_a_deleted_account_has_status_deleted_and_stays_readable(
    client, database, admin_in, owner
):
    delete_account(client, admin_in.headers, owner.id)
    response = get_account(client, admin_in.headers, owner.id)
    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    assert response.json()["email"] == ""
    assert response.json()["name"] == ERASED_NAME
    assert_close(read_user(database, owner.id).deleted_at, datetime.now(UTC), 60)


def test_a_deleted_account_leaves_the_default_list_but_shows_on_request(
    client, database, admin_in, owner
):
    delete_account(client, admin_in.headers, owner.id)
    assert str(owner.id) not in listed_ids(client, admin_in.headers)
    assert str(owner.id) in listed_ids(client, admin_in.headers, includeDeleted="true")


def test_deleting_ends_every_session_of_the_account(
    client, database, admin_in, owner, sign_in
):
    first, second = sign_in(owner), sign_in(owner)
    assert delete_account(client, admin_in.headers, owner.id).status_code == 204
    assert all(row.revoked_at is not None for row in sessions_of(database, owner.id))
    for session in (first, second):
        assert_error(
            client.get("/me", headers=session.headers), 401, "ACCESS_TOKEN_INVALID"
        )
        assert_error(
            refresh(client, session.tokens.refresh_token),
            401,
            "REFRESH_TOKEN_INVALID",
        )


def test_deleting_leaves_the_sessions_of_other_accounts_alone(
    client, database, admin_in, owner, make_user, sign_in
):
    bystander = sign_in(make_user())
    assert delete_account(client, admin_in.headers, owner.id).status_code == 204
    assert client.get("/me", headers=bystander.headers).status_code == 200
    assert client.get("/me", headers=admin_in.headers).status_code == 200


def test_a_deleted_account_cannot_log_in(client, database, admin_in, owner):
    assert login(client, "rina@example.com").status_code == 200
    delete_account(client, admin_in.headers, owner.id)
    assert_error(login(client, "rina@example.com"), 401, "INVALID_CREDENTIALS")


@pytest.mark.parametrize("email", ["rina@example.com", "RINA@Example.com"])
def test_the_email_of_a_deleted_account_can_be_registered_again(
    client, database, admin_in, owner, register_owner, email
):
    assert delete_account(client, admin_in.headers, owner.id).status_code == 204
    response = register_owner(email=email)
    assert response.status_code == 201, response.text
    assert response.json()["account"]["id"] != str(owner.id)
    assert_erased(database, owner.id)


def test_the_email_of_a_deleted_account_can_be_given_to_another_account(
    client, database, admin_in, owner, make_user
):
    other = make_user(name="Dewi Owner", email="dewi@example.com")
    delete_account(client, admin_in.headers, owner.id)
    response = edit_account(client, admin_in.headers, other, email="rina@example.com")
    assert response.status_code == 200, response.text
    assert response.json()["pendingEmail"] == "rina@example.com"


def test_an_admin_can_delete_another_admin(
    client, database, admin_in, make_user, sign_in
):
    other = make_user(role=role("admin"), email="second@example.com")
    set_password(database, other)
    session = sign_in(other)
    assert delete_account(client, admin_in.headers, other.id).status_code == 204
    assert status_of(client, admin_in, other.id) == "deleted"
    assert_error(
        client.get("/me", headers=session.headers), 401, "ACCESS_TOKEN_INVALID"
    )
    assert_error(login(client, "second@example.com"), 401, "INVALID_CREDENTIALS")


def test_an_inactive_account_can_be_deleted(client, database, admin_in, make_user):
    suspended = make_user(status="inactive")
    assert delete_account(client, admin_in.headers, suspended.id).status_code == 204
    assert status_of(client, admin_in, suspended.id) == "deleted"


def test_deleting_an_account_does_not_touch_other_accounts(
    client, database, admin_in, owner, make_user
):
    other = make_user()
    delete_account(client, admin_in.headers, owner.id)
    assert read_user(database, other.id).deleted_at is None
    assert status_of(client, admin_in, other.id) == "active"


# Refusals


def test_an_admin_cannot_delete_their_own_account(client, database, admin, admin_in):
    response = delete_account(client, admin_in.headers, admin.id)
    assert_error(response, 409, "CANNOT_MODIFY_OWN_ACCOUNT")
    assert read_user(database, admin.id).deleted_at is None
    assert client.get("/me", headers=admin_in.headers).status_code == 200
    assert sessions_of(database, admin.id)[0].revoked_at is None


def test_an_unknown_account_is_not_found(client, database, admin_in):
    response = delete_account(client, admin_in.headers, uuid4())
    assert_error(response, 404, "USER_ACCOUNT_NOT_FOUND")


def test_a_tenant_that_has_not_activated_is_not_found(
    client, database, admin_in, owner, make_tenant, make_property, make_room
):
    from app.models import Tenant

    pending = make_tenant(make_room(make_property(owner)), name="Belum Aktif")
    response = delete_account(client, admin_in.headers, pending.user.id)
    assert_error(response, 404, "USER_ACCOUNT_NOT_FOUND")
    assert deleted_at_of(database, Tenant, pending.id) is None


def test_a_manager_that_has_not_activated_is_not_found(
    client, database, admin_in, owner, make_manager
):
    from app.models import Manager

    pending = make_manager(owner, name="Belum Aktif")
    response = delete_account(client, admin_in.headers, pending.user_id)
    assert_error(response, 404, "USER_ACCOUNT_NOT_FOUND")
    assert deleted_at_of(database, Manager, pending.id) is None


def test_a_malformed_account_id_is_a_validation_error(client, database, admin_in):
    response = client.delete("/user-accounts/not-a-uuid", headers=admin_in.headers)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


def test_deleting_an_account_twice_is_refused_the_second_time(
    client, database, admin_in, owner
):
    assert delete_account(client, admin_in.headers, owner.id).status_code == 204
    response = delete_account(client, admin_in.headers, owner.id)
    assert_error(response, 409, "USER_ACCOUNT_DELETED")


def test_a_tenant_deleted_through_the_tenant_endpoints_counts_as_deleted(
    client,
    database,
    admin_in,
    owner,
    sign_in,
    make_property,
    make_room,
    make_verified_tenant,
):
    prop = make_property(owner)
    tenant = make_verified_tenant(make_room(prop))
    removed = client.delete(f"/tenants/{tenant.id}", headers=sign_in(owner).headers)
    assert removed.status_code == 204, removed.text
    assert status_of(client, admin_in, tenant.user.id) == "deleted"
    response = delete_account(client, admin_in.headers, tenant.user.id)
    assert_error(response, 409, "USER_ACCOUNT_DELETED")


def test_a_tenant_with_one_record_left_does_not_count_as_deleted(
    client,
    database,
    admin_in,
    owner,
    sign_in,
    make_property,
    make_room,
    make_verified_tenant,
):
    prop = make_property(owner)
    first = make_verified_tenant(make_room(prop, number="1"))
    second = make_verified_tenant(make_room(prop, number="2"), user=first.user)
    removed = client.delete(f"/tenants/{first.id}", headers=sign_in(owner).headers)
    assert removed.status_code == 204, removed.text
    assert status_of(client, admin_in, first.user.id) == "active"
    removed = client.delete(f"/tenants/{second.id}", headers=sign_in(owner).headers)
    assert removed.status_code == 204, removed.text
    assert status_of(client, admin_in, first.user.id) == "deleted"
    assert str(first.user.id) not in listed_ids(client, admin_in.headers)
    assert str(first.user.id) in listed_ids(
        client, admin_in.headers, includeDeleted="true"
    )


def test_a_manager_deleted_through_the_manager_endpoints_counts_as_deleted(
    client, database, admin_in, owner, sign_in, make_property, make_manager
):
    prop = make_property(owner)
    manager = make_manager(owner, [prop], activated=True)
    removed = client.delete(f"/managers/{manager.id}", headers=sign_in(owner).headers)
    assert removed.status_code == 204, removed.text
    assert status_of(client, admin_in, manager.user_id) == "deleted"
    response = delete_account(client, admin_in.headers, manager.user_id)
    assert_error(response, 409, "USER_ACCOUNT_DELETED")


def test_a_deleted_tenant_with_an_active_lease_is_reported_deleted_first(
    client, database, admin_in, owner, make_property, make_room, make_verified_tenant
):
    tenant = make_verified_tenant(make_room(make_property(owner)), deleted=True)
    response = delete_account(client, admin_in.headers, tenant.user.id)
    assert_error(response, 409, "USER_ACCOUNT_DELETED")


def test_a_deleted_owner_with_an_active_lease_is_reported_deleted_first(
    client,
    database,
    admin_in,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
):
    gone = make_user(deleted=True)
    make_verified_tenant(make_room(make_property(gone)))
    response = delete_account(client, admin_in.headers, gone.id)
    assert_error(response, 409, "USER_ACCOUNT_DELETED")


# Owners


def test_an_owner_with_an_active_lease_cannot_be_deleted(
    client,
    database,
    admin_in,
    owner,
    make_property,
    make_room,
    make_verified_tenant,
    sign_in,
):
    from app.models import Property, Room

    quiet = make_property(owner, name="Kos Quiet")
    busy = make_property(owner, name="Kos Busy")
    quiet_room = make_room(quiet, number="1")
    busy_room = make_room(busy, number="1")
    make_verified_tenant(busy_room)
    session = sign_in(owner)
    response = delete_account(client, admin_in.headers, owner.id)
    assert_error(response, 409, "OWNER_HAS_ACTIVE_LEASE")
    assert read_user(database, owner.id).deleted_at is None
    assert deleted_at_of(database, Property, quiet.id) is None
    assert deleted_at_of(database, Property, busy.id) is None
    assert deleted_at_of(database, Room, quiet_room.id) is None
    assert deleted_at_of(database, Room, busy_room.id) is None
    assert client.get("/me", headers=session.headers).status_code == 200
    assert status_of(client, admin_in, owner.id) == "active"


def test_a_view_only_property_with_an_active_lease_blocks_the_deletion(
    client, database, admin_in, owner, make_property, make_room, make_verified_tenant
):
    old = make_property(owner, view_only=True)
    make_verified_tenant(make_room(old, view_only=True))
    response = delete_account(client, admin_in.headers, owner.id)
    assert_error(response, 409, "OWNER_HAS_ACTIVE_LEASE")


def test_a_view_only_property_without_an_active_lease_does_not_block(
    client, database, admin_in, owner, make_property, make_room
):
    from app.models import Property

    old = make_property(owner, view_only=True)
    make_room(old, view_only=True)
    assert delete_account(client, admin_in.headers, owner.id).status_code == 204
    assert deleted_at_of(database, Property, old.id) is not None


def test_an_ended_lease_does_not_block_the_deletion(
    client, database, admin_in, owner, make_property, make_room, make_verified_tenant
):
    prop = make_property(owner)
    make_verified_tenant(make_room(prop), lease_ended=True)
    assert delete_account(client, admin_in.headers, owner.id).status_code == 204


def test_a_deleted_property_with_an_active_lease_does_not_block_the_deletion(
    client, database, admin_in, owner, make_property, make_room, make_verified_tenant
):
    gone = make_property(owner, deleted=True)
    make_verified_tenant(make_room(gone, deleted=True))
    assert delete_account(client, admin_in.headers, owner.id).status_code == 204


def test_another_owners_active_lease_does_not_block_the_deletion(
    client,
    database,
    admin_in,
    owner,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
):
    make_verified_tenant(make_room(make_property(make_user())))
    assert delete_account(client, admin_in.headers, owner.id).status_code == 204


def test_deleting_an_owner_deletes_their_properties_and_rooms(
    client, database, admin_in, owner, make_property, make_room
):
    from app.models import Property, Room

    first = make_property(owner, name="Kos Satu")
    second = make_property(owner, name="Kos Dua", view_only=True)
    rooms = [
        make_room(first, number="1"),
        make_room(first, number="2"),
        make_room(second),
    ]
    delete_account(client, admin_in.headers, owner.id)
    for prop in (first, second):
        assert_close(deleted_at_of(database, Property, prop.id), datetime.now(UTC), 60)
    for room in rooms:
        assert_close(deleted_at_of(database, Room, room.id), datetime.now(UTC), 60)


def test_deleted_properties_leave_the_detail_of_the_owner(
    client, database, admin_in, owner, make_property
):
    make_property(owner, name="Kos Satu")
    delete_account(client, admin_in.headers, owner.id)
    body = get_account(client, admin_in.headers, owner.id).json()
    assert body["properties"] == []
    assert body["activeLeaseCount"] == 0


def test_a_manager_of_a_deleted_owner_no_longer_sees_the_properties(
    client, database, admin_in, owner, make_property, make_manager, sign_in
):
    prop = make_property(owner)
    manager = make_manager(owner, [prop], activated=True)
    session = sign_in(manager.user)
    delete_account(client, admin_in.headers, owner.id)
    listed = client.get("/properties", headers=session.headers)
    assert listed.status_code == 200
    assert listed.json()["items"] == []


def test_deleting_an_owner_removes_the_assignments_of_their_managers(
    client, database, admin_in, owner, make_user, make_property, make_manager
):
    mine = make_property(owner)
    elsewhere_owner = make_user(name="Dewi Owner")
    elsewhere = make_property(elsewhere_owner, name="Kos Elsewhere")
    manager = make_manager(owner, [mine], activated=True)
    make_manager(elsewhere_owner, [elsewhere], activated=True, user=manager.user)
    delete_account(client, admin_in.headers, owner.id)
    assert assigned(database, mine.id) == []
    assert len(assigned(database, elsewhere.id)) == 1


def test_deleting_an_owner_keeps_their_managers_and_other_owners_untouched(
    client, database, admin_in, owner, make_user, make_property, make_room, make_manager
):
    from app.models import Manager, Property, Room

    mine = make_property(owner)
    other_owner = make_user(name="Dewi Owner")
    theirs = make_property(other_owner, name="Kos Theirs")
    their_room = make_room(theirs)
    manager = make_manager(owner, [mine], activated=True)
    delete_account(client, admin_in.headers, owner.id)
    assert deleted_at_of(database, Property, theirs.id) is None
    assert deleted_at_of(database, Room, their_room.id) is None
    assert read_user(database, other_owner.id).deleted_at is None
    assert read_user(database, manager.user_id).deleted_at is None
    assert deleted_at_of(database, Manager, manager.id) is None


def test_deleting_an_owner_keeps_payment_and_complaint_history(
    client,
    database,
    admin_in,
    owner,
    make_property,
    make_room,
    make_verified_tenant,
    make_rent_bill,
    make_complaint,
):
    from app.models import Complaint, Lease, RentBill, RentBillStatusChange

    prop = make_property(owner)
    room = make_room(prop)
    tenant = make_verified_tenant(room, lease_ended=True)
    bill = make_rent_bill(tenant.lease)
    complaint = make_complaint(tenant, room)
    bills, changes = (
        count_rows(database, RentBill),
        count_rows(database, RentBillStatusChange),
    )
    assert delete_account(client, admin_in.headers, owner.id).status_code == 204
    assert get_row(database, RentBill, bill.id) is not None
    assert get_row(database, Complaint, complaint.id) is not None
    assert get_row(database, Lease, tenant.lease.id) is not None
    assert count_rows(database, RentBill) == bills
    assert count_rows(database, RentBillStatusChange) == changes


# Managers


def test_deleting_a_manager_removes_every_assignment_and_deletes_every_record(
    client, database, admin_in, make_user, make_property, make_manager
):
    from app.models import Manager, ManagerAssignment, Property

    first_owner, second_owner = make_user(), make_user()
    first_prop = make_property(first_owner, name="Kos Satu")
    second_prop = make_property(second_owner, name="Kos Dua")
    first = make_manager(first_owner, [first_prop], activated=True)
    second = make_manager(second_owner, [second_prop], activated=True, user=first.user)
    assert delete_account(client, admin_in.headers, first.user_id).status_code == 204
    assert (
        rows_of(
            database,
            ManagerAssignment,
            ManagerAssignment.manager_id == first.user_id,
        )
        == []
    )
    assert deleted_at_of(database, Manager, first.id) is not None
    assert deleted_at_of(database, Manager, second.id) is not None
    assert status_of(client, admin_in, first.user_id) == "deleted"
    assert deleted_at_of(database, Property, first_prop.id) is None
    assert deleted_at_of(database, Property, second_prop.id) is None


def test_deleting_a_manager_ends_their_sessions_and_login(
    client, database, admin_in, owner, make_property, make_manager, sign_in
):
    manager = make_manager(
        owner,
        [make_property(owner)],
        activated=True,
        email="mira@example.com",
        password="T7#vq9-lorem-ipsum",
    )
    session = sign_in(manager.user)
    assert login(client, "mira@example.com", "T7#vq9-lorem-ipsum").status_code == 200
    delete_account(client, admin_in.headers, manager.user_id)
    assert_error(
        client.get("/me", headers=session.headers), 401, "ACCESS_TOKEN_INVALID"
    )
    response = login(client, "mira@example.com", "T7#vq9-lorem-ipsum")
    assert_error(response, 401, "INVALID_CREDENTIALS")


def test_deleting_a_manager_leaves_the_owners_properties_and_other_managers(
    client, database, admin_in, owner, make_property, make_room, make_manager
):
    from app.models import Property, Room

    prop = make_property(owner)
    room = make_room(prop)
    gone = make_manager(owner, [prop], activated=True)
    stays = make_manager(owner, [prop], activated=True, name="Mira Lain")
    delete_account(client, admin_in.headers, gone.user_id)
    assert deleted_at_of(database, Property, prop.id) is None
    assert deleted_at_of(database, Room, room.id) is None
    assert [a.manager_id for a in assigned(database, prop.id)] == [stays.user_id]
    assert status_of(client, admin_in, stays.user_id) == "active"


def test_a_deleted_manager_leaves_the_manager_list_of_the_owner(
    client, database, admin_in, owner, make_property, make_manager, sign_in
):
    manager = make_manager(owner, [make_property(owner)], activated=True)
    delete_account(client, admin_in.headers, manager.user_id)
    response = client.get("/managers", headers=sign_in(owner).headers)
    assert response.status_code == 200
    assert response.json()["items"] == []


# Tenants


def test_a_tenant_with_an_active_lease_cannot_be_deleted(
    client,
    database,
    admin_in,
    owner,
    make_property,
    make_room,
    make_verified_tenant,
    sign_in,
):
    from app.models import Tenant

    tenant = make_verified_tenant(make_room(make_property(owner)))
    session = sign_in(tenant.user)
    response = delete_account(client, admin_in.headers, tenant.user.id)
    assert_error(response, 409, "TENANT_HAS_ACTIVE_LEASE")
    assert deleted_at_of(database, Tenant, tenant.id) is None
    assert client.get("/me", headers=session.headers).status_code == 200
    assert status_of(client, admin_in, tenant.user.id) == "active"


def test_a_tenant_with_an_active_lease_through_one_of_two_records_cannot_be_deleted(
    client,
    database,
    admin_in,
    owner,
    make_property,
    make_room,
    make_verified_tenant,
):
    from app.models import Tenant

    prop = make_property(owner)
    ended = make_verified_tenant(make_room(prop, number="1"), lease_ended=True)
    active = make_verified_tenant(make_room(prop, number="2"), user=ended.user)
    response = delete_account(client, admin_in.headers, ended.user.id)
    assert_error(response, 409, "TENANT_HAS_ACTIVE_LEASE")
    assert deleted_at_of(database, Tenant, ended.id) is None
    assert deleted_at_of(database, Tenant, active.id) is None
    assert status_of(client, admin_in, ended.user.id) == "active"


def test_a_tenant_with_active_leases_through_both_records_cannot_be_deleted(
    client,
    database,
    admin_in,
    owner,
    make_property,
    make_room,
    make_verified_tenant,
):
    from app.models import Tenant

    prop = make_property(owner)
    first = make_verified_tenant(make_room(prop, number="1"))
    second = make_verified_tenant(make_room(prop, number="2"), user=first.user)
    response = delete_account(client, admin_in.headers, first.user.id)
    assert_error(response, 409, "TENANT_HAS_ACTIVE_LEASE")
    assert deleted_at_of(database, Tenant, first.id) is None
    assert deleted_at_of(database, Tenant, second.id) is None


def test_a_tenant_whose_other_record_is_already_deleted_is_blocked_by_the_live_lease(
    client,
    database,
    admin_in,
    owner,
    make_property,
    make_room,
    make_verified_tenant,
):
    prop = make_property(owner)
    first = make_verified_tenant(make_room(prop, number="1"))
    make_verified_tenant(make_room(prop, number="2"), user=first.user, deleted=True)
    response = delete_account(client, admin_in.headers, first.user.id)
    assert_error(response, 409, "TENANT_HAS_ACTIVE_LEASE")


def test_a_tenant_without_an_active_lease_is_deleted(
    client, database, admin_in, owner, make_property, make_room, make_verified_tenant
):
    from app.models import Tenant

    tenant = make_verified_tenant(make_room(make_property(owner)), lease_ended=True)
    assert delete_account(client, admin_in.headers, tenant.user.id).status_code == 204
    assert_close(deleted_at_of(database, Tenant, tenant.id), datetime.now(UTC), 60)
    assert status_of(client, admin_in, tenant.user.id) == "deleted"
    assert str(tenant.user.id) not in listed_ids(client, admin_in.headers)


def test_deleting_a_tenant_account_deletes_every_record_of_it(
    client,
    database,
    admin_in,
    owner,
    make_property,
    make_room,
    make_verified_tenant,
):
    from app.models import Lease, Tenant

    prop = make_property(owner)
    first = make_verified_tenant(make_room(prop, number="1"), lease_ended=True)
    second = make_verified_tenant(
        make_room(prop, number="2"), user=first.user, lease_ended=True
    )
    other = make_verified_tenant(make_room(prop, number="3"))
    assert delete_account(client, admin_in.headers, first.user.id).status_code == 204
    for record in (first, second):
        assert_close(deleted_at_of(database, Tenant, record.id), datetime.now(UTC), 60)
    assert deleted_at_of(database, Tenant, other.id) is None
    assert get_row(database, Lease, other.lease.id).ended_at is None
    assert status_of(client, admin_in, other.user.id) == "active"


def test_deleting_a_tenant_account_ends_the_sessions_of_the_account_only(
    client,
    database,
    admin_in,
    owner,
    make_property,
    make_room,
    make_verified_tenant,
    sign_in,
):
    prop = make_property(owner)
    first = make_verified_tenant(make_room(prop, number="1"), lease_ended=True)
    make_verified_tenant(make_room(prop, number="2"), user=first.user, lease_ended=True)
    bystander = make_verified_tenant(make_room(prop, number="3"))
    mine = [sign_in(first.user), sign_in(first.user)]
    other = sign_in(bystander.user)
    assert delete_account(client, admin_in.headers, first.user.id).status_code == 204
    for session in mine:
        assert_error(
            client.get("/me", headers=session.headers), 401, "ACCESS_TOKEN_INVALID"
        )
    assert client.get("/me", headers=other.headers).status_code == 200


def test_deleting_a_tenant_ends_sessions_and_login(
    client,
    database,
    admin_in,
    owner,
    make_property,
    make_room,
    make_verified_tenant,
    sign_in,
):
    tenant = make_verified_tenant(
        make_room(make_property(owner)), lease_ended=True, email="budi@example.com"
    )
    set_password(database, tenant.user)
    session = sign_in(tenant.user)
    assert login(client, "budi@example.com").status_code == 200
    delete_account(client, admin_in.headers, tenant.user.id)
    assert_error(
        client.get("/me", headers=session.headers), 401, "ACCESS_TOKEN_INVALID"
    )
    assert_error(login(client, "budi@example.com"), 401, "INVALID_CREDENTIALS")


def test_deleting_a_tenant_keeps_their_history_and_the_property(
    client,
    database,
    admin_in,
    owner,
    make_property,
    make_room,
    make_verified_tenant,
    make_rent_bill,
    make_complaint,
):
    from app.models import Complaint, Lease, Property, RentBill

    prop = make_property(owner)
    room = make_room(prop)
    tenant = make_verified_tenant(room, lease_ended=True)
    bill = make_rent_bill(tenant.lease)
    complaint = make_complaint(tenant, room)
    delete_account(client, admin_in.headers, tenant.user.id)
    assert get_row(database, RentBill, bill.id) is not None
    assert get_row(database, Complaint, complaint.id) is not None
    assert get_row(database, Lease, tenant.lease.id) is not None
    assert deleted_at_of(database, Property, prop.id) is None
    assert read_user(database, owner.id).deleted_at is None


def test_the_email_of_a_deleted_tenant_can_be_registered_again(
    client,
    database,
    admin_in,
    owner,
    make_property,
    make_room,
    make_verified_tenant,
    register_owner,
):
    tenant = make_verified_tenant(
        make_room(make_property(owner)), lease_ended=True, email="budi@example.com"
    )
    assert delete_account(client, admin_in.headers, tenant.user.id).status_code == 204
    response = register_owner(email="Budi@Example.com")
    assert response.status_code == 201, response.text


# Owners with a subscription that renews


def test_an_owner_whose_subscription_renews_cannot_be_deleted(
    client, database, admin_in, owner, sign_in
):
    set_subscription(database, owner, auto_renew=True)
    session = sign_in(owner)
    response = delete_account(client, admin_in.headers, owner.id)
    assert_error(response, 409, "SUBSCRIPTION_AUTO_RENEWING")
    assert read_user(database, owner.id).deleted_at is None
    assert status_of(client, admin_in, owner.id) == "active"
    assert client.get("/me", headers=session.headers).status_code == 200


def test_an_owner_can_be_deleted_once_the_subscription_stops_renewing(
    client, database, admin_in, owner
):
    set_subscription(database, owner, auto_renew=True)
    assert delete_account(client, admin_in.headers, owner.id).status_code == 409
    set_subscription(database, owner, auto_renew=False)
    assert delete_account(client, admin_in.headers, owner.id).status_code == 204


def test_an_owner_with_a_running_subscription_that_does_not_renew_can_be_deleted(
    client, database, admin_in, owner
):
    set_subscription(database, owner, plan="pro", auto_renew=False)
    assert delete_account(client, admin_in.headers, owner.id).status_code == 204


def test_the_subscription_of_another_owner_does_not_block_the_deletion(
    client, database, admin_in, owner, make_user
):
    set_subscription(database, make_user(email="dewi@example.com"), auto_renew=True)
    assert delete_account(client, admin_in.headers, owner.id).status_code == 204


def test_an_active_lease_is_reported_before_a_renewing_subscription(
    client, database, admin_in, owner, make_property, make_room, make_verified_tenant
):
    make_verified_tenant(make_room(make_property(owner)))
    set_subscription(database, owner, auto_renew=True)
    response = delete_account(client, admin_in.headers, owner.id)
    assert_error(response, 409, "OWNER_HAS_ACTIVE_LEASE")


def test_a_deleted_owner_is_reported_deleted_before_the_subscription(
    client, database, admin_in, make_user
):
    gone = make_user(deleted=True)
    set_subscription(database, gone, auto_renew=True)
    response = delete_account(client, admin_in.headers, gone.id)
    assert_error(response, 409, "USER_ACCOUNT_DELETED")


def test_the_subscription_row_of_a_non_owner_never_blocks(
    client, database, admin_in, make_user
):
    colleague = make_user(role=role("admin"), email="second@example.com")
    set_subscription(database, colleague, auto_renew=True)
    assert delete_account(client, admin_in.headers, colleague.id).status_code == 204


def test_a_refusal_for_a_renewing_subscription_saves_nothing(
    client, database, admin_in, make_person
):
    owner = make_person("owner")
    set_subscription(database, owner.user, auto_renew=True)
    insert_order(database, owner.user)
    seed_personal_rows(database, owner.user, owner.email)
    seed_session_details(database, owner.user.id)
    before = table_snapshot(database)
    sessions = session_state(database, owner.user.id)
    response = delete_account(client, admin_in.headers, owner.user.id)
    assert_error(response, 409, "SUBSCRIPTION_AUTO_RENEWING")
    assert table_snapshot(database) == before
    assert session_state(database, owner.user.id) == sessions


def test_a_refusal_for_an_active_lease_saves_nothing(
    client, database, admin_in, make_person, make_room, make_verified_tenant
):
    owner = make_person("owner")
    make_verified_tenant(make_room(owner.prop, number="2"))
    seed_personal_rows(database, owner.user, owner.email)
    seed_session_details(database, owner.user.id)
    before = table_snapshot(database)
    sessions = session_state(database, owner.user.id)
    response = delete_account(client, admin_in.headers, owner.user.id)
    assert_error(response, 409, "OWNER_HAS_ACTIVE_LEASE")
    assert table_snapshot(database) == before
    assert session_state(database, owner.user.id) == sessions


# Erasure of personal data


@pytest.fixture
def make_person(
    database,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
    make_manager,
    sign_in,
):
    def build(name: str, **options):
        return build_person(
            name,
            database=database,
            make_user=make_user,
            make_property=make_property,
            make_room=make_room,
            make_verified_tenant=make_verified_tenant,
            make_manager=make_manager,
            sign_in=sign_in,
            **options,
        )

    return build


@pytest.fixture(params=["tenant", "owner", "manager", "admin"])
def person(request, make_person):
    return make_person(request.param, email="subject@example.com")


def test_an_account_of_every_role_is_erased_when_an_admin_deletes_it(
    client, database, admin_in, person
):
    assert delete_account(client, admin_in.headers, person.user.id).status_code == 204
    assert_erased(database, person.user.id)


def test_the_erased_account_reads_as_deleted_without_name_or_email(
    client, database, admin_in, person
):
    delete_account(client, admin_in.headers, person.user.id)
    body = get_account(client, admin_in.headers, person.user.id).json()
    assert body["status"] == "deleted"
    assert body["name"] == ERASED_NAME
    assert body["email"] == ""
    assert body["pendingEmail"] is None
    assert body["loginMethods"] == []


def test_the_erased_account_is_no_longer_found_by_its_old_email(
    client, database, admin_in, person
):
    from user_account_support import list_accounts, set_columns

    from app.models import UserAccount

    if person.landlord is not None:
        set_columns(
            database, UserAccount, person.landlord.id, email="landlord@example.com"
        )
    old_email = person.email
    delete_account(client, admin_in.headers, person.user.id)
    response = list_accounts(
        client, admin_in.headers, email=old_email, includeDeleted="true"
    )
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_deleting_by_an_admin_ends_sessions_and_clears_their_device_data(
    client, database, admin_in, person, sign_in
):
    sign_in(person.user, device_name="Galaxy S24")
    seed_session_details(database, person.user.id)
    delete_account(client, admin_in.headers, person.user.id)
    rows = sessions_of(database, person.user.id)
    assert len(rows) == 2
    for row in rows:
        assert row.revoked_at is not None
        assert row.device_name in ("", None)
        assert row.push_token is None


@pytest.mark.parametrize("kind", KINDS)
def test_deleting_by_an_admin_deletes_the_rows_of_each_personal_kind(
    client, database, admin_in, person, kind
):
    seed_personal_rows(database, person.user, person.email)
    assert personal_row_counts(database, person.user, person.email)[kind] >= 1
    delete_account(client, admin_in.headers, person.user.id)
    assert personal_row_counts(database, person.user, person.email)[kind] == 0


def test_the_personal_rows_of_other_accounts_stay_when_an_admin_deletes(
    client, database, admin_in, make_person, person
):
    other = make_person("owner", email="dewi@example.com")
    seed_personal_rows(database, person.user, person.email)
    seed_personal_rows(database, other.user, other.email)
    before = personal_row_counts(database, other.user, other.email)
    delete_account(client, admin_in.headers, person.user.id)
    assert personal_row_counts(database, other.user, other.email) == before


def test_an_admin_deleting_a_tenant_erases_every_record(
    client, database, admin_in, make_person
):
    tenant = make_person("tenant", with_second_record=True)
    seed_tenant_data(database, tenant)
    assert delete_account(client, admin_in.headers, tenant.user.id).status_code == 204
    assert_tenant_erased(database, tenant)


def test_an_admin_deleting_a_manager_erases_every_record(
    client, database, admin_in, make_person
):
    manager = make_person("manager", with_second_record=True)
    assert delete_account(client, admin_in.headers, manager.user.id).status_code == 204
    assert_manager_erased(database, manager)


def test_an_admin_deleting_an_owner_clears_the_bank_accounts_of_their_properties(
    client, database, admin_in, make_person, make_property
):
    owner = make_person("owner")
    second = make_property(owner.user, name="Kos Dua", view_only=True)
    set_bank_account(database, second)
    gone = make_property(owner.user, name="Kos Lama", deleted=True)
    set_bank_account(database, gone)
    other = make_person("owner", email="dewi@example.com")
    assert delete_account(client, admin_in.headers, owner.user.id).status_code == 204
    assert_owner_erased(database, [owner.prop, second, gone])
    from app.models import Property

    assert get_row(database, Property, other.prop.id).bank_name == "Bank Mandiri"


def test_an_admin_deleting_an_owner_keeps_history_and_subscription_orders(
    client,
    database,
    file_store,
    admin_in,
    make_person,
    make_room,
    make_verified_tenant,
    make_rent_bill,
    make_complaint,
):
    owner = make_person("owner")
    tenant = make_verified_tenant(make_room(owner.prop, number="2"), lease_ended=True)
    history = seed_history(
        database, file_store, make_rent_bill, make_complaint, tenant, owner.room
    )
    paid = insert_order(
        database, owner.user, status="succeeded", purchase_token="tok-1"
    )
    assert delete_account(client, admin_in.headers, owner.user.id).status_code == 204
    assert_history_kept(database, file_store, history)
    assert [o.id for o in stored_orders(database, owner.user)] == [paid.id]


def test_an_admin_deleting_a_tenant_keeps_their_history(
    client, database, file_store, admin_in, make_person, make_rent_bill, make_complaint
):
    tenant = make_person("tenant")
    history = seed_history(
        database,
        file_store,
        make_rent_bill,
        make_complaint,
        tenant.record,
        tenant.landlord_room,
        actor_id=tenant.user.id,
    )
    assert delete_account(client, admin_in.headers, tenant.user.id).status_code == 204
    assert_history_kept(database, file_store, history)


def test_the_email_can_be_registered_again_after_an_admin_deletes_the_account(
    client, database, admin_in, person, register_owner
):
    delete_account(client, admin_in.headers, person.user.id)
    response = register_owner(email="subject@example.com")
    assert response.status_code == 201, response.text
    assert_erased(database, person.user.id)


def test_the_google_identity_can_be_linked_elsewhere_after_an_admin_deletes_the_account(
    client, database, google, admin_in, make_user, sign_in
):
    from app.services.passwords import hash_password

    google.add("rina-token", subject="sub-rina", email="rina.gmail@example.com")
    former = make_google_user(
        database,
        subject="sub-rina",
        google_email="rina.gmail@example.com",
        email="rina@example.com",
        password_hash=hash_password(PASSWORD),
    )
    assert delete_account(client, admin_in.headers, former.id).status_code == 204
    assert user_by_subject(database, "sub-rina") is None
    heir = make_user(
        name="Dewi Owner",
        email="dewi@example.com",
        password_hash=hash_password(PASSWORD),
    )
    response = client.post(
        "/me/google-link",
        json={"idToken": "rina-token"},
        headers=sign_in(heir).headers,
    )
    assert response.status_code == 200, response.text
    assert user_by_subject(database, "sub-rina").id == heir.id


def test_login_after_an_admin_deletes_the_account_answers_invalid_credentials(
    client, database, admin_in, person
):
    assert login(client, "subject@example.com").status_code == 200
    delete_account(client, admin_in.headers, person.user.id)
    assert_error(login(client, "subject@example.com"), 401, "INVALID_CREDENTIALS")
