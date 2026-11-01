"""Login for suspended and deleted accounts."""

from datetime import UTC, datetime

import pytest
from user_account_support import (
    PASSWORD,
    assert_error,
    edit_account,
    login,
    sessions_of,
    set_columns,
    set_password,
    set_status,
)


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


@pytest.fixture
def owner(database, make_user):
    user = make_user(name="Rina Owner", email="rina@example.com")
    set_password(database, user)
    return user


@pytest.fixture
def tenant(database, make_user, make_property, make_room, make_verified_tenant):
    room = make_room(make_property(make_user(name="Landlord")))
    stored = make_verified_tenant(room, email="budi@example.com")
    set_password(database, stored.user)
    return stored


@pytest.fixture
def manager(database, make_user, make_manager):
    return make_manager(
        make_user(name="Landlord"),
        activated=True,
        email="mira@example.com",
        password=PASSWORD,
    )


# Suspended accounts


def test_a_suspended_account_with_the_right_password_is_told_it_is_inactive(
    client, database, owner
):
    set_status(database, owner, "inactive")
    response = login(client, "rina@example.com")
    assert_error(response, 403, "ACCOUNT_INACTIVE")


def test_a_refused_login_of_a_suspended_account_starts_no_session(
    client, database, owner
):
    set_status(database, owner, "inactive")
    login(client, "rina@example.com")
    assert sessions_of(database, owner.id) == []


@pytest.mark.parametrize(
    "email", ["RINA@EXAMPLE.COM", "  rina@example.com  ", " Rina@Example.Com"]
)
def test_the_email_is_matched_ignoring_case_and_spaces_for_a_suspended_account(
    client, database, owner, email
):
    set_status(database, owner, "inactive")
    assert_error(login(client, email), 403, "ACCOUNT_INACTIVE")


def test_a_suspended_account_with_a_wrong_password_gets_invalid_credentials(
    client, database, owner
):
    set_status(database, owner, "inactive")
    response = login(client, "rina@example.com", "not the password at all")
    assert_error(response, 401, "INVALID_CREDENTIALS")


def test_a_suspended_account_without_a_password_gets_invalid_credentials(
    client, database, make_user
):
    make_user(email="google@example.com", status="inactive")
    response = login(client, "google@example.com")
    assert_error(response, 401, "INVALID_CREDENTIALS")


def test_a_suspended_tenant_is_told_it_is_inactive(client, database, tenant):
    set_status(database, tenant.user, "inactive")
    assert_error(login(client, "budi@example.com"), 403, "ACCOUNT_INACTIVE")


def test_a_suspended_manager_is_told_it_is_inactive(client, database, manager):
    set_status(database, manager.user, "inactive")
    assert_error(login(client, "mira@example.com"), 403, "ACCOUNT_INACTIVE")


def test_a_suspended_admin_is_told_it_is_inactive(client, database, make_user):
    admin = make_user(role=role("admin"), email="ade@example.com")
    set_password(database, admin)
    set_status(database, admin, "inactive")
    assert_error(login(client, "ade@example.com"), 403, "ACCOUNT_INACTIVE")


def test_login_works_again_after_reactivation(client, database, owner):
    set_status(database, owner, "inactive")
    assert login(client, "rina@example.com").status_code == 403
    set_status(database, owner, "active")
    response = login(client, "rina@example.com")
    assert response.status_code == 200
    assert response.json()["account"]["id"] == str(owner.id)


def test_suspending_and_reactivating_through_the_admin_endpoint_gates_login(
    client, database, owner, admin_in
):
    assert login(client, "rina@example.com").status_code == 200
    edit_account(client, admin_in.headers, owner, status="inactive")
    assert_error(login(client, "rina@example.com"), 403, "ACCOUNT_INACTIVE")
    edit_account(client, admin_in.headers, owner, status="active")
    assert login(client, "rina@example.com").status_code == 200


def test_an_active_account_logs_in_as_before(client, database, owner):
    response = login(client, "rina@example.com")
    assert response.status_code == 200
    assert response.json()["account"]["email"] == "rina@example.com"


# Deleted accounts


def test_a_deleted_account_gets_invalid_credentials_with_the_right_password(
    client, database, make_user
):
    gone = make_user(email="gone@example.com", deleted=True)
    set_password(database, gone)
    assert_error(login(client, "gone@example.com"), 401, "INVALID_CREDENTIALS")
    assert sessions_of(database, gone.id) == []


def test_a_deleted_tenant_gets_invalid_credentials_with_the_right_password(
    client, database, tenant
):
    from app.models import Tenant

    set_columns(database, Tenant, tenant.id, deleted_at=datetime.now(UTC))
    assert_error(login(client, "budi@example.com"), 401, "INVALID_CREDENTIALS")


def test_a_manager_with_every_record_deleted_gets_invalid_credentials(
    client, database, manager
):
    from app.models import Manager

    set_columns(database, Manager, manager.id, deleted_at=datetime.now(UTC))
    assert_error(login(client, "mira@example.com"), 401, "INVALID_CREDENTIALS")


def test_a_deleted_account_that_was_suspended_gets_invalid_credentials(
    client, database, make_user
):
    both = make_user(email="both@example.com", status="inactive", deleted=True)
    set_password(database, both)
    assert_error(login(client, "both@example.com"), 401, "INVALID_CREDENTIALS")


def test_an_unknown_email_still_gets_invalid_credentials(client, database):
    assert_error(login(client, "nobody@example.com"), 401, "INVALID_CREDENTIALS")


def test_deleting_through_the_admin_endpoint_blocks_login(
    client, database, owner, admin_in
):
    assert login(client, "rina@example.com").status_code == 200
    client.delete(f"/user-accounts/{owner.id}", headers=admin_in.headers)
    assert_error(login(client, "rina@example.com"), 401, "INVALID_CREDENTIALS")
