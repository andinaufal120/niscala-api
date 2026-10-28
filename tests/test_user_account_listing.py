"""Listing and searching user accounts as an Admin."""

import pytest
from user_account_support import (
    SUMMARY_FIELDS,
    assert_error_code,
    change_email,
    ids,
    list_accounts,
    listed_ids,
)


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


@pytest.fixture
def room(make_user, make_property, make_room):
    return make_room(make_property(make_user(name="Landlord Lama"), name="Kos Lama"))


def items_by_id(response) -> dict:
    assert response.status_code == 200, response.text
    return {item["id"]: item for item in response.json()["items"]}


# Content


def test_the_list_holds_the_accounts_of_every_role(
    client,
    database,
    admin,
    admin_in,
    make_user,
    make_manager,
    make_verified_tenant,
    room,
):
    owner = make_user(name="Rina Owner", email="rina@example.com")
    tenant = make_verified_tenant(room, name="Budi Tenant", email="budi@example.com")
    manager = make_manager(
        owner, activated=True, name="Mira Manager", email="mira@example.com"
    )
    response = list_accounts(client, admin_in.headers)
    found = items_by_id(response)
    assert {
        str(admin.id),
        str(owner.id),
        str(tenant.id),
        str(manager.user_id),
    } <= set(found)
    assert found[str(owner.id)] == {
        "id": str(owner.id),
        "name": "Rina Owner",
        "email": "rina@example.com",
        "role": "owner",
        "status": "active",
    }
    assert found[str(tenant.id)]["role"] == "tenant"
    assert found[str(tenant.id)]["name"] == "Budi Tenant"
    assert found[str(manager.user_id)]["role"] == "manager"
    assert found[str(manager.user_id)]["email"] == "mira@example.com"
    assert found[str(admin.id)]["role"] == "admin"


def test_the_list_is_an_object_with_items_of_exactly_the_summary_fields(
    client, database, admin_in
):
    response = list_accounts(client, admin_in.headers)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items"}
    assert body["items"]
    for item in body["items"]:
        assert set(item) == SUMMARY_FIELDS


def test_the_list_never_exposes_password_hashes(client, database, admin_in, make_user):
    make_user(password_hash="$argon2id$secret-hash-value")
    response = list_accounts(client, admin_in.headers)
    assert response.status_code == 200
    assert "secret-hash-value" not in response.text
    assert "password" not in response.text.lower()


def test_the_calling_admin_is_listed(client, database, admin, admin_in):
    assert str(admin.id) in listed_ids(client, admin_in.headers)


def test_owners_and_admins_are_always_listed(client, database, admin_in, make_user):
    owner = make_user(name="Owner Without Properties")
    other_admin = make_user(role=role("admin"), name="Other Admin")
    found = listed_ids(client, admin_in.headers)
    assert str(owner.id) in found
    assert str(other_admin.id) in found


def test_a_tenant_that_has_not_activated_is_not_listed(
    client, database, admin_in, make_tenant, room
):
    pending = make_tenant(room, name="Belum Aktif")
    assert str(pending.id) not in listed_ids(client, admin_in.headers)


def test_a_manager_that_has_not_activated_is_not_listed(
    client, database, admin_in, make_user, make_manager
):
    pending = make_manager(make_user(), name="Belum Aktif")
    assert str(pending.user_id) not in listed_ids(client, admin_in.headers)


def test_a_manager_activated_for_one_owner_only_is_listed(
    client, database, admin_in, make_user, make_manager
):
    first = make_manager(make_user(), activated=False, name="Mira")
    second = make_manager(
        make_user(), activated=True, user=first.user, invitation=False
    )
    assert str(second.user_id) in listed_ids(client, admin_in.headers)


def test_an_empty_filter_result_is_an_empty_list(client, database, admin_in):
    response = list_accounts(client, admin_in.headers, email="nobody-has-this")
    assert response.status_code == 200
    assert response.json() == {"items": []}


# Email search


@pytest.fixture
def people(make_user):
    return {
        "budi": make_user(name="Budi", email="budi.santoso@example.com"),
        "dewi": make_user(name="Dewi", email="dewi@mail.example.org"),
        "kartika": make_user(name="Kartika", email="k1@example.net"),
    }


@pytest.mark.parametrize("term", ["budi", "BUDI", "Budi.Santoso", "santoso@exam"])
def test_the_email_filter_matches_any_part_ignoring_case(
    client, database, admin_in, people, term
):
    found = listed_ids(client, admin_in.headers, email=term)
    assert found == [str(people["budi"].id)]


def test_the_email_filter_matches_the_domain(client, database, admin_in, people):
    found = listed_ids(client, admin_in.headers, email="example.org")
    assert found == [str(people["dewi"].id)]


def test_the_email_filter_keeps_every_account_that_matches(
    client, database, admin_in, people
):
    found = listed_ids(client, admin_in.headers, email="example")
    assert {str(p.id) for p in people.values()} <= set(found)


def test_the_email_filter_does_not_look_at_names(client, database, admin_in, people):
    assert listed_ids(client, admin_in.headers, email="kartika") == []


def test_the_email_filter_ignores_a_pending_email(
    client, database, admin_in, people, mailbox
):
    response = change_email(
        client, admin_in.headers, people["dewi"], "brand.new@pending.example"
    )
    assert response.status_code == 200
    assert listed_ids(client, admin_in.headers, email="brand.new") == []
    assert listed_ids(client, admin_in.headers, email="dewi@") == [
        str(people["dewi"].id)
    ]


def test_an_underscore_in_the_filter_matches_only_an_underscore(
    client, database, admin_in, make_user
):
    literal = make_user(email="a_b@example.com")
    make_user(email="axb@example.com")
    assert listed_ids(client, admin_in.headers, email="a_b") == [str(literal.id)]
    assert listed_ids(client, admin_in.headers, email="_") == [str(literal.id)]


def test_a_percent_sign_in_the_filter_matches_only_a_percent_sign(
    client, database, admin_in, make_user
):
    literal = make_user(email="100%done@example.com")
    make_user(email="100done@example.com")
    assert listed_ids(client, admin_in.headers, email="%") == [str(literal.id)]
    assert listed_ids(client, admin_in.headers, email="0%d") == [str(literal.id)]


def test_a_backslash_in_the_filter_matches_literally(
    client, database, admin_in, make_user
):
    make_user(email="plain@example.com")
    assert listed_ids(client, admin_in.headers, email="\\") == []


@pytest.mark.parametrize("value", ["", " ", "   "])
def test_a_blank_email_filter_is_rejected(client, database, admin_in, value):
    response = list_accounts(client, admin_in.headers, email=value)
    assert_error_code(response, 422, "VALIDATION_FAILED")


# Role filter


@pytest.fixture
def every_role(make_user, make_manager, make_verified_tenant, room):
    owner = make_user(name="Rina Owner", email="rina@example.com")
    return {
        "owner": owner,
        "tenant": make_verified_tenant(room, name="Budi Tenant"),
        "manager": make_manager(owner, activated=True, name="Mira Manager").user,
        "admin": make_user(role=role("admin"), name="Second Admin"),
    }


@pytest.mark.parametrize("name", ["tenant", "owner", "manager", "admin"])
def test_the_role_filter_keeps_only_that_role(
    client, database, admin_in, every_role, name
):
    response = list_accounts(client, admin_in.headers, role=name)
    found = items_by_id(response)
    assert str(every_role[name].id) in found
    assert {item["role"] for item in found.values()} == {name}


def test_the_role_filter_excludes_the_other_roles(
    client, database, admin_in, every_role
):
    found = listed_ids(client, admin_in.headers, role="owner")
    for other in ("tenant", "manager", "admin"):
        assert str(every_role[other].id) not in found


@pytest.mark.parametrize("value", ["superuser", "Owner", "OWNER", "", "owner,admin"])
def test_an_unknown_role_filter_is_rejected(client, database, admin_in, value):
    response = list_accounts(client, admin_in.headers, role=value)
    assert_error_code(response, 422, "VALIDATION_FAILED")


def test_the_email_and_role_filters_combine(client, database, admin_in, make_user):
    owner = make_user(email="shared.name@example.com")
    make_user(role=role("admin"), email="shared.admin@example.com")
    found = listed_ids(client, admin_in.headers, email="shared", role="owner")
    assert found == [str(owner.id)]


def test_the_role_filter_with_an_email_that_does_not_match_is_empty(
    client, database, admin_in, every_role
):
    assert listed_ids(client, admin_in.headers, email="rina", role="admin") == []


# Statuses and deleted accounts


def test_an_inactive_account_is_listed_by_default_with_its_status(
    client, database, admin_in, make_user
):
    suspended = make_user(status="inactive")
    found = items_by_id(list_accounts(client, admin_in.headers))
    assert found[str(suspended.id)]["status"] == "inactive"


def test_an_active_account_is_reported_active(client, database, admin_in, make_user):
    user = make_user()
    found = items_by_id(list_accounts(client, admin_in.headers))
    assert found[str(user.id)]["status"] == "active"


@pytest.fixture
def deleted_accounts(
    make_user, make_manager, make_verified_tenant, make_property, make_room
):
    owner = make_user(name="Landlord")
    live_room = make_room(make_property(owner, name="Kos Live"))
    return {
        "account": make_user(name="Deleted Owner", deleted=True),
        "tenant": make_verified_tenant(live_room, name="Deleted Tenant", deleted=True),
        "manager": make_manager(
            owner, activated=True, name="Deleted Manager", deleted=True
        ).user,
    }


@pytest.mark.parametrize("kind", ["account", "tenant", "manager"])
def test_deleted_accounts_are_hidden_by_default(
    client, database, admin_in, deleted_accounts, kind
):
    found = listed_ids(client, admin_in.headers)
    assert str(deleted_accounts[kind].id) not in found


@pytest.mark.parametrize("kind", ["account", "tenant", "manager"])
def test_deleted_accounts_are_hidden_when_not_asked_for_explicitly(
    client, database, admin_in, deleted_accounts, kind
):
    found = listed_ids(client, admin_in.headers, includeDeleted="false")
    assert str(deleted_accounts[kind].id) not in found


@pytest.mark.parametrize("kind", ["account", "tenant", "manager"])
def test_deleted_accounts_are_listed_with_status_deleted_on_request(
    client, database, admin_in, deleted_accounts, kind
):
    response = list_accounts(client, admin_in.headers, includeDeleted="true")
    found = items_by_id(response)
    assert found[str(deleted_accounts[kind].id)]["status"] == "deleted"


def test_including_deleted_accounts_keeps_the_live_ones(
    client, database, admin, admin_in, deleted_accounts
):
    found = listed_ids(client, admin_in.headers, includeDeleted="true")
    assert str(admin.id) in found


def test_a_deleted_account_that_was_inactive_is_reported_deleted(
    client, database, admin_in, make_user
):
    both = make_user(status="inactive", deleted=True)
    found = items_by_id(list_accounts(client, admin_in.headers, includeDeleted="true"))
    assert found[str(both.id)]["status"] == "deleted"


def test_a_manager_with_a_live_record_left_is_not_deleted(
    client, database, admin_in, make_user, make_manager
):
    first = make_manager(make_user(), activated=True, deleted=True)
    second = make_manager(
        make_user(), activated=True, user=first.user, invitation=False
    )
    found = items_by_id(list_accounts(client, admin_in.headers))
    assert found[str(second.user_id)]["status"] == "active"


def test_deleted_accounts_still_obey_the_other_filters(
    client, database, admin_in, make_user
):
    gone = make_user(email="gone.owner@example.com", deleted=True)
    make_user(email="gone.admin@example.com", role=role("admin"), deleted=True)
    found = listed_ids(
        client,
        admin_in.headers,
        email="gone",
        role="owner",
        includeDeleted="true",
    )
    assert found == [str(gone.id)]


# Order


def test_accounts_are_ordered_by_name_ignoring_case_then_email(
    client, database, admin_in, make_user
):
    charlie = make_user(name="charlie", email="c@example.com")
    alpha_upper = make_user(name="Alpha", email="z@example.com")
    alpha_lower = make_user(name="alpha", email="a@example.com")
    bravo = make_user(name="Bravo", email="b@example.com")
    response = list_accounts(client, admin_in.headers, role="owner")
    assert ids(response) == [
        str(alpha_lower.id),
        str(alpha_upper.id),
        str(bravo.id),
        str(charlie.id),
    ]


def test_accounts_of_all_roles_share_one_ordering(
    client, database, admin, admin_in, make_user
):
    first = make_user(name="Aaa Owner")
    last = make_user(name="Zzz Owner")
    found = listed_ids(client, admin_in.headers)
    assert found[0] == str(first.id)
    assert found[-1] == str(last.id)
    assert found.index(str(admin.id)) in range(1, len(found) - 1)
