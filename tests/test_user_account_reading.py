"""Reading one user account as an Admin."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from user_account_support import (
    ACCOUNT_FIELDS,
    PROPERTY_REF_FIELDS,
    TENANCY_FIELDS,
    assert_close,
    assert_error,
    get_account,
    parse_time,
    read_user,
    sessions_of,
    set_columns,
    set_password,
)


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


def read(client, headers, user_id) -> dict:
    response = get_account(client, headers, user_id)
    assert response.status_code == 200, response.text
    return response.json()


# Identity and shape


def test_the_detail_has_exactly_the_account_fields(
    client, database, admin_in, make_user
):
    owner = make_user(name="Rina Owner", email="rina@example.com")
    body = read(client, admin_in.headers, owner.id)
    assert set(body) == ACCOUNT_FIELDS


def test_the_detail_reports_name_email_role_and_status(
    client, database, admin_in, make_user
):
    owner = make_user(name="Rina Owner", email="rina@example.com")
    body = read(client, admin_in.headers, owner.id)
    assert body["id"] == str(owner.id)
    assert body["name"] == "Rina Owner"
    assert body["email"] == "rina@example.com"
    assert body["role"] == "owner"
    assert body["status"] == "active"


def test_the_detail_of_an_admin_has_nothing_linked(client, database, admin, admin_in):
    body = read(client, admin_in.headers, admin.id)
    assert body["role"] == "admin"
    assert body["properties"] == []
    assert body["activeLeaseCount"] == 0
    assert body["tenancy"] is None


def test_the_registration_time_is_the_creation_time(
    client, database, admin_in, make_user
):
    owner = make_user()
    body = read(client, admin_in.headers, owner.id)
    assert_close(
        parse_time(body["registeredAt"]), read_user(database, owner.id).created_at, 1
    )


def test_the_detail_has_no_pending_email_by_default(
    client, database, admin_in, make_user
):
    body = read(client, admin_in.headers, make_user().id)
    assert body["pendingEmail"] is None
    assert body["pendingEmailExpiresAt"] is None


def test_the_detail_never_exposes_the_password_hash(
    client, database, admin_in, make_user
):
    owner = make_user(password_hash="$argon2id$secret-hash-value")
    response = get_account(client, admin_in.headers, owner.id)
    assert response.status_code == 200
    assert "secret-hash-value" not in response.text
    assert "passwordHash" not in response.json()
    assert "password_hash" not in response.json()


# Not found


def test_an_unknown_account_is_not_found(client, database, admin_in):
    response = get_account(client, admin_in.headers, uuid4())
    assert_error(response, 404, "USER_ACCOUNT_NOT_FOUND")


def test_a_malformed_account_id_is_a_validation_error(client, database, admin_in):
    response = client.get("/user-accounts/not-a-uuid", headers=admin_in.headers)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


def test_a_tenant_that_has_not_activated_is_not_found(
    client, database, admin_in, make_tenant, make_user, make_property, make_room
):
    room = make_room(make_property(make_user()))
    pending = make_tenant(room)
    response = get_account(client, admin_in.headers, pending.id)
    assert_error(response, 404, "USER_ACCOUNT_NOT_FOUND")


def test_a_manager_that_has_not_activated_is_not_found(
    client, database, admin_in, make_user, make_manager
):
    pending = make_manager(make_user())
    response = get_account(client, admin_in.headers, pending.user_id)
    assert_error(response, 404, "USER_ACCOUNT_NOT_FOUND")


def test_a_manager_without_any_record_is_not_found(
    client, database, admin_in, make_user
):
    response = get_account(client, admin_in.headers, make_user(role=role("manager")).id)
    assert_error(response, 404, "USER_ACCOUNT_NOT_FOUND")


def test_a_manager_activated_for_one_owner_is_found(
    client, database, admin_in, make_user, make_manager
):
    first = make_manager(make_user(), activated=False, name="Mira")
    make_manager(make_user(), activated=True, user=first.user, invitation=False)
    assert read(client, admin_in.headers, first.user_id)["role"] == "manager"


# Status


def test_an_inactive_account_is_reported_inactive(
    client, database, admin_in, make_user
):
    suspended = make_user(status="inactive")
    assert read(client, admin_in.headers, suspended.id)["status"] == "inactive"


def test_a_deleted_account_is_still_returned_with_status_deleted(
    client, database, admin_in, make_user
):
    gone = make_user(name="Gone", deleted=True)
    body = read(client, admin_in.headers, gone.id)
    assert body["status"] == "deleted"
    assert body["name"] == "Gone"


def test_deleted_wins_over_inactive(client, database, admin_in, make_user):
    both = make_user(status="inactive", deleted=True)
    assert read(client, admin_in.headers, both.id)["status"] == "deleted"


def test_a_deleted_tenant_is_reported_deleted(
    client,
    database,
    admin_in,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
):
    room = make_room(make_property(make_user()))
    gone = make_verified_tenant(room, deleted=True)
    assert read(client, admin_in.headers, gone.id)["status"] == "deleted"


def test_a_manager_whose_records_are_all_deleted_is_reported_deleted(
    client, database, admin_in, make_user, make_manager
):
    first = make_manager(make_user(), activated=True, deleted=True)
    make_manager(make_user(), activated=True, deleted=True, user=first.user)
    assert read(client, admin_in.headers, first.user_id)["status"] == "deleted"


def test_a_manager_with_a_live_record_is_not_reported_deleted(
    client, database, admin_in, make_user, make_manager
):
    first = make_manager(make_user(), activated=True, deleted=True)
    make_manager(make_user(), activated=True, user=first.user)
    assert read(client, admin_in.headers, first.user_id)["status"] == "active"


# Login facts


def test_login_methods_hold_password_when_the_account_has_one(
    client, database, admin_in, make_user
):
    owner = make_user()
    set_password(database, owner)
    assert read(client, admin_in.headers, owner.id)["loginMethods"] == ["password"]


def test_login_methods_are_empty_without_a_password(
    client, database, admin_in, make_user
):
    assert read(client, admin_in.headers, make_user().id)["loginMethods"] == []


def test_login_methods_never_report_google_for_a_google_session(
    client, database, admin_in, make_user, sign_in
):
    from app.schemas.sessions import LoginMethod

    owner = make_user()
    sign_in(owner, login_method=LoginMethod.GOOGLE)
    assert read(client, admin_in.headers, owner.id)["loginMethods"] == []


def test_the_last_login_is_empty_for_an_account_that_never_logged_in(
    client, database, admin_in, make_user
):
    assert read(client, admin_in.headers, make_user().id)["lastLoginAt"] is None


def test_the_last_login_is_the_newest_session_creation_revoked_ones_included(
    client, database, admin_in, make_user, sign_in
):
    from app.models import UserSession

    owner = make_user()
    old, middle, recent = (sign_in(owner) for _ in range(3))
    now = datetime.now(UTC)
    set_columns(
        database, UserSession, old.session_id, created_at=now - timedelta(days=10)
    )
    set_columns(
        database,
        UserSession,
        middle.session_id,
        created_at=now - timedelta(days=5),
    )
    set_columns(
        database,
        UserSession,
        recent.session_id,
        created_at=now - timedelta(days=1),
        revoked_at=now - timedelta(hours=1),
    )
    body = read(client, admin_in.headers, owner.id)
    assert_close(parse_time(body["lastLoginAt"]), now - timedelta(days=1), 5)


def test_reading_an_account_does_not_start_a_session_for_it(
    client, database, admin_in, make_user
):
    owner = make_user()
    read(client, admin_in.headers, owner.id)
    assert sessions_of(database, owner.id) == []


# Owner links


def test_an_owner_lists_their_live_properties_ordered_by_name(
    client, database, admin_in, make_user, make_property
):
    owner = make_user()
    zebra = make_property(owner, name="Kos Zebra")
    anggrek = make_property(owner, name="Kos Anggrek")
    make_property(owner, name="Kos Deleted", deleted=True)
    make_property(make_user(), name="Kos Of Someone Else")
    body = read(client, admin_in.headers, owner.id)
    assert body["properties"] == [
        {"id": str(anggrek.id), "name": "Kos Anggrek"},
        {"id": str(zebra.id), "name": "Kos Zebra"},
    ]
    for item in body["properties"]:
        assert set(item) == PROPERTY_REF_FIELDS


def test_an_owner_without_properties_has_none_listed(
    client, database, admin_in, make_user
):
    body = read(client, admin_in.headers, make_user().id)
    assert body["properties"] == []
    assert body["activeLeaseCount"] == 0
    assert body["tenancy"] is None


def test_an_owner_counts_active_leases_of_their_live_properties(
    client,
    database,
    admin_in,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
):
    owner = make_user()
    alpha = make_property(owner, name="Kos Alpha")
    view_only = make_property(owner, name="Kos Lama", view_only=True)
    gone = make_property(owner, name="Kos Gone", deleted=True)
    make_verified_tenant(make_room(alpha, number="1"))
    make_verified_tenant(make_room(alpha, number="2"))
    make_verified_tenant(make_room(alpha, number="3"), lease_ended=True)
    make_verified_tenant(make_room(view_only, number="1"))
    make_verified_tenant(make_room(gone, number="1"))
    other = make_property(make_user(), name="Kos Other")
    make_verified_tenant(make_room(other, number="1"))
    assert read(client, admin_in.headers, owner.id)["activeLeaseCount"] == 3


def test_an_owner_with_only_ended_leases_counts_none(
    client,
    database,
    admin_in,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
):
    owner = make_user()
    make_verified_tenant(make_room(make_property(owner)), lease_ended=True)
    assert read(client, admin_in.headers, owner.id)["activeLeaseCount"] == 0


# Manager links


def test_a_manager_lists_the_live_properties_they_are_assigned_to(
    client, database, admin_in, make_user, make_property, make_manager
):
    owner = make_user()
    melati = make_property(owner, name="Kos Melati")
    anggrek = make_property(owner, name="Kos Anggrek")
    gone = make_property(owner, name="Kos Gone", deleted=True)
    make_property(owner, name="Kos Unassigned")
    manager = make_manager(owner, [melati, anggrek, gone], activated=True)
    body = read(client, admin_in.headers, manager.user_id)
    assert body["properties"] == [
        {"id": str(anggrek.id), "name": "Kos Anggrek"},
        {"id": str(melati.id), "name": "Kos Melati"},
    ]


def test_a_manager_of_two_owners_lists_properties_of_both_ordered_by_name_then_id(
    client, database, admin_in, make_user, make_property, make_manager
):
    first_owner, second_owner = make_user(), make_user()
    first = make_property(first_owner, name="Kos Melati")
    second = make_property(second_owner, name="Kos Melati")
    manager = make_manager(first_owner, [first], activated=True)
    make_manager(second_owner, [second], activated=True, user=manager.user)
    body = read(client, admin_in.headers, manager.user_id)
    assert [p["id"] for p in body["properties"]] == sorted(
        [str(first.id), str(second.id)]
    )


def test_a_manager_has_no_lease_count_and_no_tenancy(
    client,
    database,
    admin_in,
    make_user,
    make_property,
    make_room,
    make_manager,
    make_verified_tenant,
):
    owner = make_user()
    prop = make_property(owner)
    make_verified_tenant(make_room(prop))
    manager = make_manager(owner, [prop], activated=True)
    body = read(client, admin_in.headers, manager.user_id)
    assert body["activeLeaseCount"] == 0
    assert body["tenancy"] is None


# Tenant links


def test_a_tenant_with_an_active_lease_reports_the_tenancy(
    client,
    database,
    admin_in,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
):
    prop = make_property(make_user(), name="Kos Melati")
    tenant = make_verified_tenant(
        make_room(prop, number="A12"), end_date=date(2100, 12, 31)
    )
    body = read(client, admin_in.headers, tenant.id)
    assert body["role"] == "tenant"
    assert body["activeLeaseCount"] == 1
    assert body["properties"] == []
    assert body["tenancy"] == {
        "propertyName": "Kos Melati",
        "roomNumber": "A12",
        "leaseEndDate": "2100-12-31",
    }
    assert set(body["tenancy"]) == TENANCY_FIELDS


def test_a_tenant_without_a_lease_end_date_reports_it_empty(
    client,
    database,
    admin_in,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
):
    prop = make_property(make_user(), name="Kos Melati")
    tenant = make_verified_tenant(make_room(prop, number="A1"), end_date=None)
    body = read(client, admin_in.headers, tenant.id)
    assert body["tenancy"] == {
        "propertyName": "Kos Melati",
        "roomNumber": "A1",
        "leaseEndDate": None,
    }


def test_a_tenant_whose_lease_ended_has_no_tenancy(
    client,
    database,
    admin_in,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
):
    prop = make_property(make_user())
    tenant = make_verified_tenant(make_room(prop), lease_ended=True)
    body = read(client, admin_in.headers, tenant.id)
    assert body["activeLeaseCount"] == 0
    assert body["tenancy"] is None


def test_an_owner_has_no_tenancy_even_with_tenants(
    client,
    database,
    admin_in,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
):
    owner = make_user()
    make_verified_tenant(make_room(make_property(owner)))
    assert read(client, admin_in.headers, owner.id)["tenancy"] is None
