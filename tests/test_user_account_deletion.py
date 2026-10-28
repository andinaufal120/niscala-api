"""Deleting a user account as an Admin."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from user_account_support import (
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
    assert response.json()["email"] == "rina@example.com"
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


def test_the_email_of_a_deleted_account_stays_reserved_for_sign_up(
    client, database, admin_in, owner, register_owner
):
    assert delete_account(client, admin_in.headers, owner.id).status_code == 204
    for email in ("rina@example.com", "RINA@Example.com"):
        response = register_owner(email=email)
        assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")


def test_the_email_of_a_deleted_account_stays_reserved_for_edits(
    client, database, admin_in, owner, make_user
):
    other = make_user(name="Dewi Owner", email="dewi@example.com")
    delete_account(client, admin_in.headers, owner.id)
    response = edit_account(client, admin_in.headers, other, email="rina@example.com")
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")


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
    response = delete_account(client, admin_in.headers, pending.id)
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
    assert status_of(client, admin_in, tenant.id) == "deleted"
    response = delete_account(client, admin_in.headers, tenant.id)
    assert_error(response, 409, "USER_ACCOUNT_DELETED")


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
    response = delete_account(client, admin_in.headers, tenant.id)
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
    response = delete_account(client, admin_in.headers, tenant.id)
    assert_error(response, 409, "TENANT_HAS_ACTIVE_LEASE")
    assert deleted_at_of(database, Tenant, tenant.id) is None
    assert client.get("/me", headers=session.headers).status_code == 200
    assert status_of(client, admin_in, tenant.id) == "active"


def test_a_tenant_without_an_active_lease_is_deleted(
    client, database, admin_in, owner, make_property, make_room, make_verified_tenant
):
    from app.models import Tenant

    tenant = make_verified_tenant(make_room(make_property(owner)), lease_ended=True)
    assert delete_account(client, admin_in.headers, tenant.id).status_code == 204
    assert_close(deleted_at_of(database, Tenant, tenant.id), datetime.now(UTC), 60)
    assert status_of(client, admin_in, tenant.id) == "deleted"
    assert str(tenant.id) not in listed_ids(client, admin_in.headers)


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
    delete_account(client, admin_in.headers, tenant.id)
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
    delete_account(client, admin_in.headers, tenant.id)
    assert get_row(database, RentBill, bill.id) is not None
    assert get_row(database, Complaint, complaint.id) is not None
    assert get_row(database, Lease, tenant.lease.id) is not None
    assert deleted_at_of(database, Property, prop.id) is None
    assert read_user(database, owner.id).deleted_at is None


def test_the_email_of_a_deleted_tenant_stays_reserved(
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
    assert delete_account(client, admin_in.headers, tenant.id).status_code == 204
    response = register_owner(email="Budi@Example.com")
    assert_error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
