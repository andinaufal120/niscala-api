"""Deleting one's own account, and the personal data that deletion erases."""

from datetime import UTC, datetime, timedelta

import pytest
from account_erasure_support import (
    ERASED_NAME,
    KINDS,
    ME_URL,
    ago,
    assert_erased,
    assert_history_kept,
    assert_manager_erased,
    assert_owner_erased,
    assert_tenant_erased,
    assert_untouched,
    build_person,
    delete_me,
    mark_reauthenticated,
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
    get_account,
    get_row,
    listed_ids,
    login,
    read_user,
    refresh,
    rows_of,
    sessions_of,
)

ROLES = ["tenant", "owner", "manager"]
EMAIL = "rina@example.com"
OTHER_EMAIL = "dewi@example.com"


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
    def build(role: str, **options):
        return build_person(
            role,
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


@pytest.fixture(params=ROLES)
def person(request, make_person):
    """A re-authenticated account of each role that may delete itself."""
    return make_person(request.param)


# Who may delete an account


def test_each_role_deleting_its_own_account_answers_204_without_a_body(
    client, database, person
):
    response = delete_me(client, person.headers)
    assert response.status_code == 204, response.text
    assert response.content == b""
    assert read_user(database, person.user.id).deleted_at is not None


def test_an_admin_cannot_delete_their_own_account(client, database, make_person):
    admin = make_person("admin")
    response = delete_me(client, admin.headers)
    assert_error(response, 403, "FORBIDDEN")
    assert_untouched(database, admin.user.id, "Ade Admin", EMAIL)
    assert client.get(ME_URL, headers=admin.headers).status_code == 200


def test_an_admin_is_refused_as_forbidden_without_a_recent_re_authentication(
    client, database, make_person
):
    admin = make_person("admin", reauthenticated=False)
    assert_error(delete_me(client, admin.headers), 403, "FORBIDDEN")


def test_a_request_without_a_token_is_refused(client, database):
    assert_error(client.delete(ME_URL), 401, "ACCESS_TOKEN_INVALID")


def test_a_request_with_a_bad_token_is_refused(client, database):
    response = client.delete(ME_URL, headers={"Authorization": "Bearer garbage"})
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


def test_an_account_with_an_unverified_email_is_refused(
    client, database, make_user, sign_in
):
    unverified = make_user(email_verified=False)
    session = sign_in(unverified)
    mark_reauthenticated(database, session)
    assert_error(delete_me(client, session.headers), 403, "EMAIL_NOT_VERIFIED")
    assert read_user(database, unverified.id).deleted_at is None


def test_the_deletion_cannot_be_repeated_with_the_same_token(client, database, person):
    assert delete_me(client, person.headers).status_code == 204
    assert_error(delete_me(client, person.headers), 401, "ACCESS_TOKEN_INVALID")


def test_only_the_callers_account_is_deleted(client, database, make_person, person):
    other = make_person(person.user.role.value, email=OTHER_EMAIL)
    other_state = session_state(database, other.user.id)
    assert delete_me(client, person.headers).status_code == 204
    name = read_user(database, other.user.id).name
    assert_untouched(database, other.user.id, name, OTHER_EMAIL)
    assert session_state(database, other.user.id) == other_state
    assert client.get(ME_URL, headers=other.headers).status_code == 200


# Refusals and their order


def test_an_owner_with_an_active_lease_is_refused(
    client, database, make_person, make_room, make_verified_tenant
):
    owner = make_person("owner")
    make_verified_tenant(make_room(owner.prop, number="2"))
    response = delete_me(client, owner.headers)
    assert_error(response, 409, "OWNER_HAS_ACTIVE_LEASE")
    assert_untouched(database, owner.user.id, "Rina Owner", EMAIL)


def test_an_active_lease_in_a_view_only_property_still_refuses_an_owner(
    client, database, make_person, make_property, make_room, make_verified_tenant
):
    owner = make_person("owner")
    old = make_property(owner.user, name="Kos Lama", view_only=True)
    make_verified_tenant(make_room(old, view_only=True))
    assert_error(delete_me(client, owner.headers), 409, "OWNER_HAS_ACTIVE_LEASE")


def test_an_active_lease_in_a_deleted_property_does_not_refuse_an_owner(
    client, database, make_person, make_property, make_room, make_verified_tenant
):
    owner = make_person("owner")
    gone = make_property(owner.user, name="Kos Lama", deleted=True)
    make_verified_tenant(make_room(gone, deleted=True))
    assert delete_me(client, owner.headers).status_code == 204


def test_a_tenant_with_an_active_lease_is_refused(
    client, database, make_person, make_room, make_verified_tenant, make_property
):
    tenant = make_person("tenant")
    other_room = make_room(tenant.landlord_prop, number="2")
    make_verified_tenant(other_room, user=tenant.user)
    response = delete_me(client, tenant.headers)
    assert_error(response, 409, "TENANT_HAS_ACTIVE_LEASE")
    assert_untouched(database, tenant.user.id, "Budi Tenant", EMAIL)


def test_an_owner_whose_subscription_renews_is_refused(client, database, make_person):
    owner = make_person("owner")
    set_subscription(database, owner.user, auto_renew=True)
    response = delete_me(client, owner.headers)
    assert_error(response, 409, "SUBSCRIPTION_AUTO_RENEWING")
    assert_untouched(database, owner.user.id, "Rina Owner", EMAIL)


def test_an_owner_whose_subscription_no_longer_renews_can_delete(
    client, database, make_person
):
    owner = make_person("owner")
    set_subscription(database, owner.user, auto_renew=True)
    assert delete_me(client, owner.headers).status_code == 409
    set_subscription(database, owner.user, auto_renew=False)
    assert delete_me(client, owner.headers).status_code == 204


def test_an_owner_with_a_running_subscription_that_does_not_renew_can_delete(
    client, database, make_person
):
    owner = make_person("owner")
    set_subscription(database, owner.user, plan="pro", auto_renew=False)
    assert delete_me(client, owner.headers).status_code == 204


def test_an_owner_without_a_subscription_can_delete(client, database, make_person):
    owner = make_person("owner")
    assert delete_me(client, owner.headers).status_code == 204


def test_the_subscription_of_another_owner_does_not_refuse(
    client, database, make_person
):
    owner = make_person("owner")
    other = make_person("owner", email=OTHER_EMAIL)
    set_subscription(database, other.user, auto_renew=True)
    assert delete_me(client, owner.headers).status_code == 204


def test_an_ended_lease_does_not_refuse_an_owner(
    client, database, make_person, make_room, make_verified_tenant
):
    owner = make_person("owner")
    make_verified_tenant(make_room(owner.prop, number="2"), lease_ended=True)
    assert delete_me(client, owner.headers).status_code == 204


def test_the_active_lease_of_another_owner_does_not_refuse(
    client,
    database,
    make_person,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
):
    owner = make_person("owner")
    elsewhere = make_property(make_user(email=OTHER_EMAIL), name="Kos Lain")
    make_verified_tenant(make_room(elsewhere))
    assert delete_me(client, owner.headers).status_code == 204


def test_a_lease_check_comes_before_the_subscription_check(
    client, database, make_person, make_room, make_verified_tenant
):
    owner = make_person("owner", reauthenticated=False)
    make_verified_tenant(make_room(owner.prop, number="2"))
    set_subscription(database, owner.user, auto_renew=True)
    assert_error(delete_me(client, owner.headers), 409, "OWNER_HAS_ACTIVE_LEASE")


def test_lease_refusals_come_before_re_authentication(
    client, database, make_person, make_room, make_verified_tenant
):
    owner = make_person("owner", reauthenticated=False)
    make_verified_tenant(make_room(owner.prop, number="2"))
    assert_error(delete_me(client, owner.headers), 409, "OWNER_HAS_ACTIVE_LEASE")
    tenant = make_person("tenant", reauthenticated=False, email=OTHER_EMAIL)
    make_verified_tenant(make_room(tenant.landlord_prop, number="2"), user=tenant.user)
    assert_error(delete_me(client, tenant.headers), 409, "TENANT_HAS_ACTIVE_LEASE")


def test_the_subscription_refusal_comes_before_re_authentication(
    client, database, make_person
):
    owner = make_person("owner", reauthenticated=False)
    set_subscription(database, owner.user, auto_renew=True)
    assert_error(delete_me(client, owner.headers), 409, "SUBSCRIPTION_AUTO_RENEWING")


@pytest.mark.parametrize("role", ROLES)
def test_an_account_that_never_re_authenticated_is_asked_to(
    client, database, make_person, role
):
    person = make_person(role, reauthenticated=False)
    response = delete_me(client, person.headers)
    assert_error(response, 403, "REAUTHENTICATION_REQUIRED")
    assert read_user(database, person.user.id).deleted_at is None


# The re-authentication window


def test_a_re_authentication_four_minutes_59_seconds_ago_passes(
    client, database, make_person
):
    owner = make_person("owner", reauthenticated=False)
    mark_reauthenticated(database, owner.signed_in, ago(minutes=4, seconds=59))
    assert delete_me(client, owner.headers).status_code == 204


@pytest.mark.parametrize(
    "age", [timedelta(minutes=5), timedelta(minutes=5, seconds=1), timedelta(days=2)]
)
def test_a_re_authentication_of_five_minutes_or_more_ago_is_refused(
    client, database, make_person, age
):
    owner = make_person("owner", reauthenticated=False)
    mark_reauthenticated(database, owner.signed_in, datetime.now(UTC) - age)
    response = delete_me(client, owner.headers)
    assert_error(response, 403, "REAUTHENTICATION_REQUIRED")
    assert read_user(database, owner.user.id).deleted_at is None


def test_the_re_authentication_of_another_session_does_not_count(
    client, database, make_person, sign_in
):
    owner = make_person("owner")
    second = sign_in(owner.user, device_name="Galaxy")
    assert_error(delete_me(client, second.headers), 403, "REAUTHENTICATION_REQUIRED")
    assert read_user(database, owner.user.id).deleted_at is None


def test_re_authenticating_with_the_password_allows_the_deletion(
    client, database, make_person
):
    owner = make_person("owner", reauthenticated=False)
    assert delete_me(client, owner.headers).status_code == 403
    response = client.post(
        "/me/reauthentication/password",
        json={"password": PASSWORD},
        headers=owner.headers,
    )
    assert response.status_code == 200, response.text
    assert delete_me(client, owner.headers).status_code == 204


# A refusal saves nothing


def assert_nothing_saved(client, database, file_store, person, action):
    before = table_snapshot(database)
    sessions = session_state(database, person.user.id)
    keys = set(file_store.keys)
    response = action()
    assert response.status_code in (403, 409), response.text
    assert table_snapshot(database) == before
    assert session_state(database, person.user.id) == sessions
    assert file_store.keys == keys
    assert file_store.deleted() == []
    assert client.get(ME_URL, headers=person.headers).status_code == 200


def test_a_refusal_for_an_active_lease_saves_nothing(
    client,
    database,
    file_store,
    make_person,
    make_room,
    make_verified_tenant,
    make_rent_bill,
    make_complaint,
):
    owner = make_person("owner")
    seed_personal_rows(database, owner.user, owner.email)
    seed_session_details(database, owner.user.id)
    tenant = make_verified_tenant(make_room(owner.prop, number="2"))
    seed_history(
        database, file_store, make_rent_bill, make_complaint, tenant, owner.room
    )
    assert_nothing_saved(
        client, database, file_store, owner, lambda: delete_me(client, owner.headers)
    )


def test_a_refusal_for_an_active_tenant_lease_saves_nothing(
    client, database, file_store, make_person, make_room, make_verified_tenant
):
    tenant = make_person("tenant", with_second_record=True)
    make_verified_tenant(make_room(tenant.landlord_prop, number="3"), user=tenant.user)
    seed_personal_rows(database, tenant.user, tenant.email)
    seed_tenant_data(database, tenant)
    seed_session_details(database, tenant.user.id)
    assert_nothing_saved(
        client, database, file_store, tenant, lambda: delete_me(client, tenant.headers)
    )


def test_a_refusal_for_a_renewing_subscription_saves_nothing(
    client, database, file_store, make_person, make_user
):
    owner = make_person("owner")
    set_subscription(database, owner.user, auto_renew=True)
    insert_order(database, owner.user)
    seed_personal_rows(database, owner.user, owner.email)
    seed_session_details(database, owner.user.id)
    set_bank_account(database, owner.prop)
    assert_nothing_saved(
        client, database, file_store, owner, lambda: delete_me(client, owner.headers)
    )


@pytest.mark.parametrize("role", ROLES)
def test_a_refusal_for_a_missing_re_authentication_saves_nothing(
    client, database, file_store, make_person, role
):
    person = make_person(role, reauthenticated=False, with_second_record=True)
    seed_personal_rows(database, person.user, person.email)
    seed_session_details(database, person.user.id)
    assert_nothing_saved(
        client, database, file_store, person, lambda: delete_me(client, person.headers)
    )


def test_a_refusal_for_an_admin_saves_nothing(
    client, database, file_store, make_person
):
    admin = make_person("admin")
    seed_personal_rows(database, admin.user, admin.email)
    assert_nothing_saved(
        client, database, file_store, admin, lambda: delete_me(client, admin.headers)
    )


# What is erased from the account


def test_the_account_is_deleted_and_its_identity_cleared(client, database, person):
    assert delete_me(client, person.headers).status_code == 204
    assert_erased(database, person.user.id)
    assert_close(read_user(database, person.user.id).deleted_at, datetime.now(UTC), 60)


def test_an_account_with_a_google_identity_loses_it(client, database, sign_in):
    owner = make_google_user(
        database,
        subject="sub-rina",
        google_email="rina.gmail@example.com",
        email=EMAIL,
    )
    session = sign_in(owner)
    mark_reauthenticated(database, session)
    assert delete_me(client, session.headers).status_code == 204
    assert_erased(database, owner.id)
    assert user_by_subject(database, "sub-rina") is None


def test_an_admin_sees_the_erased_account_as_deleted_without_a_name_or_email(
    client, database, admin_in, person
):
    delete_me(client, person.headers)
    detail = get_account(client, admin_in.headers, person.user.id)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["status"] == "deleted"
    assert body["name"] == ERASED_NAME
    assert body["email"] == ""
    assert body["pendingEmail"] is None
    assert body["loginMethods"] == []
    assert str(person.user.id) in listed_ids(
        client, admin_in.headers, includeDeleted="true"
    )
    assert str(person.user.id) not in listed_ids(client, admin_in.headers)


def test_every_session_of_the_account_ends_and_loses_its_device_data(
    client, database, person, sign_in
):
    second = sign_in(person.user, device_name="Galaxy S24")
    seed_session_details(database, person.user.id)
    assert delete_me(client, person.headers).status_code == 204
    rows = sessions_of(database, person.user.id)
    assert len(rows) == 2
    for row in rows:
        assert row.revoked_at is not None
        assert row.device_name in ("", None)
        assert row.push_token is None
    for session in (person.signed_in, second):
        assert_error(
            client.get(ME_URL, headers=session.headers), 401, "ACCESS_TOKEN_INVALID"
        )
        assert_error(
            refresh(client, session.tokens.refresh_token),
            401,
            "REFRESH_TOKEN_INVALID",
        )


def test_the_sessions_of_other_accounts_keep_their_device_data(
    client, database, make_person, person
):
    other = make_person(person.user.role.value, email=OTHER_EMAIL)
    seed_session_details(database, other.user.id)
    delete_me(client, person.headers)
    (row,) = sessions_of(database, other.user.id)
    assert row.revoked_at is None
    assert row.device_name == "Pixel 8"
    assert row.push_token is not None


@pytest.mark.parametrize("kind", KINDS)
def test_the_rows_of_each_personal_kind_are_deleted(client, database, person, kind):
    seed_personal_rows(database, person.user, person.email)
    assert personal_row_counts(database, person.user, person.email)[kind] >= 1
    assert delete_me(client, person.headers).status_code == 204
    assert personal_row_counts(database, person.user, person.email)[kind] == 0


def test_the_personal_rows_of_other_accounts_stay(
    client, database, make_person, person
):
    other = make_person(person.user.role.value, email=OTHER_EMAIL)
    seed_personal_rows(database, person.user, person.email)
    seed_personal_rows(database, other.user, other.email)
    before = personal_row_counts(database, other.user, other.email)
    delete_me(client, person.headers)
    assert personal_row_counts(database, other.user, other.email) == before
    assert all(count >= 1 for count in before.values())


def test_a_login_failure_record_is_found_by_the_email_as_it_was_stored(
    client, database, make_person
):
    owner = make_person("owner", email="Rina@Example.com")
    seed_personal_rows(database, owner.user, "Rina@Example.com")
    assert personal_row_counts(database, owner.user, EMAIL)["login_failures"] == 1
    delete_me(client, owner.headers)
    assert personal_row_counts(database, owner.user, EMAIL)["login_failures"] == 0


# Erasure by role


def test_a_tenant_loses_phone_occupation_contacts_and_summaries_on_every_record(
    client, database, make_person
):
    tenant = make_person("tenant", with_second_record=True)
    seed_tenant_data(database, tenant)
    assert delete_me(client, tenant.headers).status_code == 204
    assert_tenant_erased(database, tenant)


def test_the_records_and_contacts_of_other_tenants_stay(client, database, make_person):
    from app.models import EmergencyContact, PaymentPatternSummary, Tenant

    tenant = make_person("tenant")
    other = make_person("tenant", email=OTHER_EMAIL)
    seed_tenant_data(database, other)
    delete_me(client, tenant.headers)
    row = get_row(database, Tenant, other.record.id)
    assert row.deleted_at is None
    assert row.phone == "081234567890"
    assert row.occupation == "Guru"
    assert (
        len(
            rows_of(
                database,
                EmergencyContact,
                EmergencyContact.tenant_id == other.record.id,
            )
        )
        == 2
    )
    assert (
        len(
            rows_of(
                database,
                PaymentPatternSummary,
                PaymentPatternSummary.lease_id == other.record.lease.id,
            )
        )
        == 1
    )


def test_a_manager_loses_phone_and_nickname_on_every_record(
    client, database, make_person
):
    manager = make_person("manager", with_second_record=True)
    assert delete_me(client, manager.headers).status_code == 204
    assert_manager_erased(database, manager)


def test_the_records_of_other_managers_stay(client, database, make_person):
    from app.models import Manager

    manager = make_person("manager")
    other = make_person("manager", email=OTHER_EMAIL)
    delete_me(client, manager.headers)
    row = get_row(database, Manager, other.record.id)
    assert row.deleted_at is None
    assert row.phone == "081234567890"
    assert row.nickname == "Mimi"


def test_deleting_a_manager_leaves_the_owners_property_and_other_managers(
    client, database, make_person, make_manager
):
    from app.models import Property

    manager = make_person("manager")
    colleague = make_manager(
        manager.landlord, [manager.landlord_prop], activated=True, name="Lain"
    )
    delete_me(client, manager.headers)
    assert get_row(database, Property, manager.landlord_prop.id).deleted_at is None
    assert read_user(database, colleague.user_id).deleted_at is None


def test_an_owner_loses_the_bank_account_of_every_deleted_property(
    client, database, make_person, make_property
):
    owner = make_person("owner")
    second = make_property(owner.user, name="Kos Dua", view_only=True)
    set_bank_account(database, second)
    gone = make_property(owner.user, name="Kos Lama", deleted=True)
    set_bank_account(database, gone)
    assert delete_me(client, owner.headers).status_code == 204
    assert_owner_erased(database, [owner.prop, second, gone])


def test_an_owner_deletes_properties_and_rooms_and_ends_manager_assignments(
    client, database, make_person, make_room, make_manager
):
    from app.models import ManagerAssignment, Room

    owner = make_person("owner")
    second_room = make_room(owner.prop, number="2")
    manager = make_manager(owner.user, [owner.prop], activated=True)
    assert delete_me(client, owner.headers).status_code == 204
    for room in (owner.room, second_room):
        assert get_row(database, Room, room.id).deleted_at is not None
    assert (
        rows_of(
            database,
            ManagerAssignment,
            ManagerAssignment.property_id == owner.prop.id,
        )
        == []
    )
    assert read_user(database, manager.user_id).deleted_at is None


def test_the_bank_accounts_of_other_owners_stay(client, database, make_person):
    from app.models import Property

    owner = make_person("owner")
    other = make_person("owner", email=OTHER_EMAIL)
    delete_me(client, owner.headers)
    row = get_row(database, Property, other.prop.id)
    assert row.deleted_at is None
    assert row.bank_name == "Bank Mandiri"
    assert row.bank_account_number == "1234567890"
    assert row.bank_account_holder_name == "Rina Owner"


# What is kept


def test_a_tenant_keeps_bills_receipts_complaints_and_photos(
    client,
    database,
    file_store,
    make_person,
    make_rent_bill,
    make_complaint,
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
    assert delete_me(client, tenant.headers).status_code == 204
    assert_history_kept(database, file_store, history)


def test_an_owner_keeps_the_bills_receipts_complaints_and_photos_of_the_property(
    client,
    database,
    file_store,
    make_person,
    make_room,
    make_verified_tenant,
    make_rent_bill,
    make_complaint,
):
    owner = make_person("owner")
    tenant = make_verified_tenant(make_room(owner.prop, number="2"), lease_ended=True)
    history = seed_history(
        database,
        file_store,
        make_rent_bill,
        make_complaint,
        tenant,
        owner.room,
        actor_id=owner.user.id,
    )
    assert delete_me(client, owner.headers).status_code == 204
    assert_history_kept(database, file_store, history)


def test_an_owner_keeps_the_subscription_orders(client, database, make_person):
    owner = make_person("owner")
    paid = insert_order(
        database, owner.user, status="succeeded", purchase_token="tok-1"
    )
    open_order = insert_order(database, owner.user)
    set_subscription(database, owner.user, auto_renew=False)
    assert delete_me(client, owner.headers).status_code == 204
    kept = {order.id: order for order in stored_orders(database, owner.user)}
    assert set(kept) == {paid.id, open_order.id}
    assert kept[paid.id].purchase_token == "tok-1"
    assert kept[paid.id].plan == "basic"


def test_the_lease_of_a_deleted_tenant_is_kept(client, database, make_person):
    from app.models import Lease

    tenant = make_person("tenant")
    assert delete_me(client, tenant.headers).status_code == 204
    lease = get_row(database, Lease, tenant.record.lease.id)
    assert lease is not None
    assert lease.ended_at is not None


# After the deletion


@pytest.mark.parametrize("email", [EMAIL, "RINA@Example.com"])
def test_the_email_can_be_registered_again(
    client, database, person, register_owner, email
):
    assert delete_me(client, person.headers).status_code == 204
    response = register_owner(email=email, name="Rina Baru")
    assert response.status_code == 201, response.text
    created = response.json()["account"]
    assert created["id"] != str(person.user.id)
    assert created["email"] == EMAIL
    assert_erased(database, person.user.id)


def test_the_new_account_of_a_reused_email_logs_in_while_the_old_one_stays_deleted(
    client, database, person, register_owner
):
    delete_me(client, person.headers)
    register_owner(email=EMAIL, password="correct horse battery")
    assert login(client, EMAIL, "correct horse battery").status_code == 200
    assert_erased(database, person.user.id)


def test_the_email_can_be_given_to_another_account(
    client, database, person, make_user, sign_in, admin_in
):
    other = make_user(name="Dewi Owner", email=OTHER_EMAIL)
    delete_me(client, person.headers)
    response = client.put(
        f"/user-accounts/{other.id}",
        json={"name": "Dewi Owner", "email": EMAIL, "status": "active"},
        headers=admin_in.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["pendingEmail"] == EMAIL


def test_login_with_the_old_email_and_password_answers_invalid_credentials(
    client, database, person
):
    assert login(client, EMAIL).status_code == 200
    assert delete_me(client, person.headers).status_code == 204
    assert_error(login(client, EMAIL), 401, "INVALID_CREDENTIALS")


def test_the_google_identity_can_be_linked_to_another_account(
    client, database, google, make_user, sign_in, make_property
):
    from app.services.passwords import hash_password

    google.add("rina-token", subject="sub-rina", email="rina.gmail@example.com")
    former = make_google_user(
        database,
        subject="sub-rina",
        google_email="rina.gmail@example.com",
        email=EMAIL,
        password_hash=hash_password(PASSWORD),
    )
    session = sign_in(former)
    mark_reauthenticated(database, session)
    assert delete_me(client, session.headers).status_code == 204
    heir = make_user(
        name="Dewi Owner", email=OTHER_EMAIL, password_hash=hash_password(PASSWORD)
    )
    heir_in = sign_in(heir)
    response = client.post(
        "/me/google-link", json={"idToken": "rina-token"}, headers=heir_in.headers
    )
    assert response.status_code == 200, response.text
    linked = user_by_subject(database, "sub-rina")
    assert linked is not None and linked.id == heir.id
    assert user_by_subject(database, "sub-rina").id != former.id


# The contract


@pytest.fixture(scope="module")
def operation(app):
    return app.openapi()["paths"]["/me"]["delete"]


def test_the_operation_is_declared_with_a_204_and_no_body(operation):
    assert set(operation["responses"]) >= {"204"}
    assert "content" not in operation["responses"]["204"]
    assert "requestBody" not in operation
    assert not operation.get("parameters")


def test_the_operation_needs_the_bearer_token(operation):
    assert any("bearerAuth" in requirement for requirement in operation["security"])


def test_the_operation_declares_exactly_its_error_codes(operation):
    assert set(operation["x-error-codes"]) == {
        "ACCESS_TOKEN_INVALID",
        "EMAIL_NOT_VERIFIED",
        "FORBIDDEN",
        "OWNER_HAS_ACTIVE_LEASE",
        "TENANT_HAS_ACTIVE_LEASE",
        "SUBSCRIPTION_AUTO_RENEWING",
        "REAUTHENTICATION_REQUIRED",
    }


def test_the_operation_lists_its_codes_by_status_and_code(operation):
    from app.error_catalog import ERROR_STATUS

    codes = operation["x-error-codes"]
    assert codes == sorted(codes, key=lambda code: (ERROR_STATUS[code], code))
    for status in {ERROR_STATUS[code] for code in codes}:
        assert str(status) in operation["responses"]


def test_the_new_error_code_is_a_409(app):
    from app.error_catalog import ERROR_STATUS

    assert ERROR_STATUS["SUBSCRIPTION_AUTO_RENEWING"] == 409


def test_the_profile_path_keeps_its_read_operation(app):
    assert set(app.openapi()["paths"]["/me"]) == {"get", "delete"}
