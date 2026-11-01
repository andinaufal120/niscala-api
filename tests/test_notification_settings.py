"""Reading and replacing the caller's push settings."""

import pytest
from notification_support import (
    ALL_CATEGORIES,
    CATEGORIES_BY_ROLE,
    SETTINGS,
    assert_error,
    default_items,
    put_settings,
    role,
    settings_items,
)

ROLES = ["tenant", "owner", "manager"]
STAFF_ROLES = ["owner", "manager"]
ITEM_FIELDS = {"category", "pushEnabled", "urgencyScope"}


def item_for(category: str, enabled: bool = True, scope: str | None = None) -> dict:
    """One settings entry with the urgency scope its category requires."""
    if category == "newComplaint":
        scope = scope or "allUrgencies"
    else:
        scope = None
    return {"category": category, "pushEnabled": enabled, "urgencyScope": scope}


def items_for(categories: list[str]) -> list[dict]:
    return [item_for(category) for category in categories]


def get_settings(client, signed_in):
    return client.get(SETTINGS, headers=signed_in.headers)


@pytest.fixture
def accounts(make_user, sign_in):
    """A signed-in account of each role that may have notification settings."""
    return {name: sign_in(make_user(role=role(name))) for name in ROLES}


# Authentication and roles


def test_reading_without_a_token_is_rejected(client, database):
    assert_error(client.get(SETTINGS), 401, "ACCESS_TOKEN_INVALID")


def test_replacing_without_a_token_is_rejected(client, database):
    body = {"items": default_items("owner")}
    assert_error(client.put(SETTINGS, json=body), 401, "ACCESS_TOKEN_INVALID")


def test_a_garbage_token_is_rejected(client, database):
    headers = {"Authorization": "Bearer garbage"}
    assert_error(client.get(SETTINGS, headers=headers), 401, "ACCESS_TOKEN_INVALID")
    response = client.put(SETTINGS, json={"items": []}, headers=headers)
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


@pytest.mark.parametrize("name", ROLES)
def test_an_unverified_account_is_rejected(client, database, make_user, sign_in, name):
    session = sign_in(make_user(role=role(name), email_verified=False))
    assert_error(get_settings(client, session), 403, "EMAIL_NOT_VERIFIED")
    response = put_settings(client, session, default_items(name))
    assert_error(response, 403, "EMAIL_NOT_VERIFIED")


def test_an_admin_is_forbidden(client, database, make_user, sign_in):
    session = sign_in(make_user(role=role("admin")))
    assert_error(get_settings(client, session), 403, "FORBIDDEN")
    response = put_settings(client, session, default_items("owner"))
    assert_error(response, 403, "FORBIDDEN")


def test_an_admin_is_refused_before_the_body_is_checked(
    client, database, make_user, sign_in
):
    session = sign_in(make_user(role=role("admin")))
    response = client.put(SETTINGS, json={"nonsense": 1}, headers=session.headers)
    assert_error(response, 403, "FORBIDDEN")


# Defaults


@pytest.mark.parametrize("name", ROLES)
def test_a_user_who_never_saved_gets_the_defaults_of_their_role(
    client, database, accounts, name
):
    response = get_settings(client, accounts[name])
    assert response.status_code == 200, response.text
    assert response.json() == {"items": default_items(name)}


@pytest.mark.parametrize("name", ROLES)
def test_the_defaults_list_the_categories_of_the_role_in_order(
    client, database, accounts, name
):
    body = get_settings(client, accounts[name]).json()
    assert [i["category"] for i in body["items"]] == CATEGORIES_BY_ROLE[name]


def test_a_tenant_has_three_categories(client, database, accounts):
    body = get_settings(client, accounts["tenant"]).json()
    assert [i["category"] for i in body["items"]] == [
        "billing",
        "paymentStatus",
        "complaintProgress",
    ]


@pytest.mark.parametrize("name", STAFF_ROLES)
def test_an_owner_and_a_manager_have_four_categories(client, database, accounts, name):
    body = get_settings(client, accounts[name]).json()
    assert [i["category"] for i in body["items"]] == [
        "newComplaint",
        "receiptUpload",
        "overdueBill",
        "accountActivity",
    ]


@pytest.mark.parametrize("name", ROLES)
def test_every_default_entry_has_exactly_the_documented_fields(
    client, database, accounts, name
):
    for item in get_settings(client, accounts[name]).json()["items"]:
        assert set(item) == ITEM_FIELDS


@pytest.mark.parametrize("name", ROLES)
def test_every_category_is_on_by_default(client, database, accounts, name):
    body = get_settings(client, accounts[name]).json()
    assert [i["pushEnabled"] for i in body["items"]] == [True] * len(body["items"])


@pytest.mark.parametrize("name", STAFF_ROLES)
def test_only_new_complaint_has_an_urgency_scope_and_it_defaults_to_all(
    client, database, accounts, name
):
    scopes = {
        i["category"]: i["urgencyScope"]
        for i in get_settings(client, accounts[name]).json()["items"]
    }
    assert scopes == {
        "newComplaint": "allUrgencies",
        "receiptUpload": None,
        "overdueBill": None,
        "accountActivity": None,
    }


def test_a_tenant_has_no_urgency_scope(client, database, accounts):
    body = get_settings(client, accounts["tenant"]).json()
    assert [i["urgencyScope"] for i in body["items"]] == [None, None, None]


def test_reading_the_defaults_does_not_depend_on_an_earlier_read(
    client, database, accounts
):
    first = get_settings(client, accounts["owner"]).json()
    second = get_settings(client, accounts["owner"]).json()
    assert first == second == {"items": default_items("owner")}


# Replacing


@pytest.mark.parametrize("name", ROLES)
def test_replacing_returns_the_saved_settings(client, database, accounts, name):
    body = settings_items(name, off=(CATEGORIES_BY_ROLE[name][1],))
    response = put_settings(client, accounts[name], body)
    assert response.status_code == 200, response.text
    assert response.json() == {"items": body}


@pytest.mark.parametrize("name", ROLES)
def test_reading_returns_what_was_saved(client, database, accounts, name):
    body = settings_items(name, off=CATEGORIES_BY_ROLE[name][:2])
    put_settings(client, accounts[name], body)
    assert get_settings(client, accounts[name]).json() == {"items": body}


@pytest.mark.parametrize("name", ROLES)
def test_every_category_can_be_switched_off(client, database, accounts, name):
    body = settings_items(name, off=tuple(CATEGORIES_BY_ROLE[name]))
    assert put_settings(client, accounts[name], body).status_code == 200
    saved = get_settings(client, accounts[name]).json()["items"]
    assert [i["pushEnabled"] for i in saved] == [False] * len(saved)


@pytest.mark.parametrize("scope", ["allUrgencies", "highOnly"])
@pytest.mark.parametrize("name", STAFF_ROLES)
def test_the_urgency_scope_of_new_complaint_is_saved(
    client, database, accounts, name, scope
):
    body = settings_items(name, scope=scope)
    assert put_settings(client, accounts[name], body).status_code == 200
    saved = get_settings(client, accounts[name]).json()["items"]
    assert saved[0] == {
        "category": "newComplaint",
        "pushEnabled": True,
        "urgencyScope": scope,
    }


def test_a_switched_off_new_complaint_keeps_its_scope(client, database, accounts):
    body = settings_items("owner", off=("newComplaint",), scope="highOnly")
    put_settings(client, accounts["owner"], body)
    saved = get_settings(client, accounts["owner"]).json()["items"]
    assert saved[0] == {
        "category": "newComplaint",
        "pushEnabled": False,
        "urgencyScope": "highOnly",
    }


def test_a_second_replacement_replaces_the_first(client, database, accounts):
    put_settings(
        client,
        accounts["owner"],
        settings_items("owner", off=("receiptUpload", "overdueBill"), scope="highOnly"),
    )
    second = settings_items("owner", off=("accountActivity",))
    response = put_settings(client, accounts["owner"], second)
    assert response.json() == {"items": second}
    assert get_settings(client, accounts["owner"]).json() == {"items": second}


def test_replacing_with_the_defaults_restores_them(client, database, accounts):
    put_settings(
        client, accounts["manager"], settings_items("manager", off=("receiptUpload",))
    )
    put_settings(client, accounts["manager"], default_items("manager"))
    assert get_settings(client, accounts["manager"]).json() == {
        "items": default_items("manager")
    }


def test_replacing_with_the_same_settings_twice_is_harmless(client, database, accounts):
    body = settings_items("tenant", off=("billing",))
    first = put_settings(client, accounts["tenant"], body)
    second = put_settings(client, accounts["tenant"], body)
    assert first.status_code == second.status_code == 200
    assert second.json() == first.json() == {"items": body}


@pytest.mark.parametrize("name", ROLES)
def test_the_order_of_the_body_does_not_matter(client, database, accounts, name):
    body = settings_items(name, off=(CATEGORIES_BY_ROLE[name][0],))
    response = put_settings(client, accounts[name], list(reversed(body)))
    assert response.status_code == 200, response.text
    assert get_settings(client, accounts[name]).json() == {"items": body}
    assert response.json() == {"items": body}


# Who the settings belong to


def test_settings_belong_to_the_user_who_saved_them(client, database, accounts):
    put_settings(
        client, accounts["owner"], settings_items("owner", off=("newComplaint",))
    )
    assert get_settings(client, accounts["manager"]).json() == {
        "items": default_items("manager")
    }
    assert get_settings(client, accounts["tenant"]).json() == {
        "items": default_items("tenant")
    }


def test_two_owners_have_separate_settings(
    client, database, accounts, make_user, sign_in
):
    other = sign_in(make_user(name="Other Owner"))
    put_settings(
        client, accounts["owner"], settings_items("owner", off=("receiptUpload",))
    )
    assert get_settings(client, other).json() == {"items": default_items("owner")}
    put_settings(client, other, settings_items("owner", scope="highOnly"))
    saved = get_settings(client, accounts["owner"]).json()["items"]
    assert saved[0]["urgencyScope"] == "allUrgencies"
    assert saved[1]["pushEnabled"] is False


def test_a_manager_and_an_owner_save_the_same_categories_separately(
    client, database, accounts
):
    put_settings(
        client, accounts["owner"], settings_items("owner", off=("overdueBill",))
    )
    put_settings(
        client, accounts["manager"], settings_items("manager", off=("accountActivity",))
    )
    owner = get_settings(client, accounts["owner"]).json()["items"]
    manager = get_settings(client, accounts["manager"]).json()["items"]
    assert [i["pushEnabled"] for i in owner] == [True, True, False, True]
    assert [i["pushEnabled"] for i in manager] == [True, True, True, False]


def test_settings_are_shared_by_every_session_of_the_user(
    client, database, make_user, sign_in
):
    user = make_user()
    phone = sign_in(user, device_name="Pixel 8")
    tablet = sign_in(user, device_name="Galaxy Tab")
    body = settings_items("owner", off=("receiptUpload",), scope="highOnly")
    put_settings(client, phone, body)
    assert get_settings(client, tablet).json() == {"items": body}
    updated = settings_items("owner", off=("overdueBill",))
    put_settings(client, tablet, updated)
    assert get_settings(client, phone).json() == {"items": updated}


def test_settings_survive_a_new_login(client, database, make_user, sign_in):
    user = make_user()
    first = sign_in(user)
    body = settings_items("owner", off=("accountActivity",))
    put_settings(client, first, body)
    later = sign_in(user)
    assert get_settings(client, later).json() == {"items": body}


# Invalid category sets


def category_sets() -> list:
    tenant = CATEGORIES_BY_ROLE["tenant"]
    staff = CATEGORIES_BY_ROLE["owner"]
    return [
        pytest.param("tenant", [], id="tenant_empty"),
        pytest.param("tenant", tenant[:2], id="tenant_missing_one"),
        pytest.param("tenant", tenant[:1], id="tenant_missing_two"),
        pytest.param("tenant", [*tenant, "newComplaint"], id="tenant_extra"),
        pytest.param("tenant", [*tenant, tenant[0]], id="tenant_duplicate_added"),
        pytest.param(
            "tenant", [tenant[0], tenant[0], tenant[2]], id="tenant_duplicate_replaces"
        ),
        pytest.param("tenant", staff, id="tenant_with_staff_categories"),
        pytest.param("tenant", ALL_CATEGORIES, id="tenant_with_every_category"),
        pytest.param("owner", [], id="owner_empty"),
        pytest.param("owner", staff[:3], id="owner_missing_one"),
        pytest.param("owner", staff[:1], id="owner_missing_three"),
        pytest.param("owner", [*staff, "billing"], id="owner_extra"),
        pytest.param("owner", [*staff, staff[0]], id="owner_duplicate_added"),
        pytest.param(
            "owner",
            [staff[0], staff[1], staff[1], staff[3]],
            id="owner_duplicate_replaces",
        ),
        pytest.param("owner", tenant, id="owner_with_tenant_categories"),
        pytest.param("owner", ALL_CATEGORIES, id="owner_with_every_category"),
        pytest.param("manager", [], id="manager_empty"),
        pytest.param("manager", staff[1:], id="manager_missing_one"),
        pytest.param("manager", [*staff, "paymentStatus"], id="manager_extra"),
        pytest.param("manager", tenant, id="manager_with_tenant_categories"),
        pytest.param("manager", [staff[0]] * 4, id="manager_one_category_four_times"),
    ]


@pytest.mark.parametrize(("name", "categories"), category_sets())
def test_a_wrong_set_of_categories_is_rejected_on_the_items_field(
    client, database, accounts, name, categories
):
    response = put_settings(client, accounts[name], items_for(categories))
    assert_error(response, 422, "NOTIFICATION_CATEGORIES_INVALID", "items")


@pytest.mark.parametrize(("name", "categories"), category_sets()[:8])
def test_a_rejected_replacement_saves_nothing(
    client, database, accounts, name, categories
):
    before = settings_items(name, off=(CATEGORIES_BY_ROLE[name][0],))
    put_settings(client, accounts[name], before)
    put_settings(client, accounts[name], items_for(categories))
    assert get_settings(client, accounts[name]).json() == {"items": before}


def test_a_rejected_first_replacement_leaves_the_defaults(client, database, accounts):
    put_settings(client, accounts["owner"], items_for(["newComplaint"]))
    assert get_settings(client, accounts["owner"]).json() == {
        "items": default_items("owner")
    }


# Invalid items


def test_new_complaint_requires_an_urgency_scope(client, database, accounts):
    body = default_items("owner")
    body[0]["urgencyScope"] = None
    response = put_settings(client, accounts["owner"], body)
    assert_error(response, 422, "VALIDATION_FAILED", "items.0.urgencyScope")


def test_the_scope_error_names_the_index_of_the_entry(client, database, accounts):
    body = list(reversed(default_items("manager")))
    index = [i["category"] for i in body].index("newComplaint")
    assert index == 3
    body[index]["urgencyScope"] = None
    response = put_settings(client, accounts["manager"], body)
    assert_error(response, 422, "VALIDATION_FAILED", "items.3.urgencyScope")


@pytest.mark.parametrize("scope", ["allUrgencies", "highOnly"])
@pytest.mark.parametrize("index", [1, 2, 3])
def test_other_staff_categories_must_not_carry_a_scope(
    client, database, accounts, index, scope
):
    body = default_items("owner")
    body[index]["urgencyScope"] = scope
    response = put_settings(client, accounts["owner"], body)
    assert_error(response, 422, "VALIDATION_FAILED", f"items.{index}.urgencyScope")


@pytest.mark.parametrize("scope", ["allUrgencies", "highOnly"])
@pytest.mark.parametrize("index", [0, 1, 2])
def test_tenant_categories_must_not_carry_a_scope(
    client, database, accounts, index, scope
):
    body = default_items("tenant")
    body[index]["urgencyScope"] = scope
    response = put_settings(client, accounts["tenant"], body)
    assert_error(response, 422, "VALIDATION_FAILED", f"items.{index}.urgencyScope")


def test_a_rejected_scope_saves_nothing(client, database, accounts):
    before = settings_items("owner", off=("overdueBill",), scope="highOnly")
    put_settings(client, accounts["owner"], before)
    body = default_items("owner")
    body[1]["urgencyScope"] = "highOnly"
    put_settings(client, accounts["owner"], body)
    assert get_settings(client, accounts["owner"]).json() == {"items": before}


@pytest.mark.parametrize("category", ["email", "new_complaint", "Billing", "", "sms"])
def test_an_unknown_category_is_rejected_on_its_field(
    client, database, accounts, category
):
    body = default_items("owner")
    body[0]["category"] = category
    response = put_settings(client, accounts["owner"], body)
    assert_error(response, 422, "VALIDATION_FAILED", "items.0.category")


@pytest.mark.parametrize("scope", ["mediumOnly", "high_only", "", "ALL"])
def test_an_unknown_scope_is_rejected_on_its_field(client, database, accounts, scope):
    body = default_items("owner")
    body[0]["urgencyScope"] = scope
    response = put_settings(client, accounts["owner"], body)
    assert_error(response, 422, "VALIDATION_FAILED", "items.0.urgencyScope")


def test_a_missing_push_enabled_is_rejected_on_its_field(client, database, accounts):
    body = default_items("tenant")
    del body[1]["pushEnabled"]
    response = put_settings(client, accounts["tenant"], body)
    assert_error(response, 422, "VALIDATION_FAILED", "items.1.pushEnabled")


@pytest.mark.parametrize("value", [None, "maybe", [True], {}])
def test_a_non_boolean_push_enabled_is_rejected_on_its_field(
    client, database, accounts, value
):
    body = default_items("tenant")
    body[2]["pushEnabled"] = value
    response = put_settings(client, accounts["tenant"], body)
    assert_error(response, 422, "VALIDATION_FAILED", "items.2.pushEnabled")


def test_a_missing_category_is_rejected_on_its_field(client, database, accounts):
    body = default_items("tenant")
    del body[0]["category"]
    response = put_settings(client, accounts["tenant"], body)
    assert_error(response, 422, "VALIDATION_FAILED", "items.0.category")


@pytest.mark.parametrize(
    "body",
    [{}, {"items": None}, {"items": "billing"}, {"item": []}],
    ids=["empty_object", "null_items", "string_items", "wrong_name"],
)
def test_a_body_without_a_list_of_items_is_rejected(client, database, accounts, body):
    response = client.put(SETTINGS, json=body, headers=accounts["owner"].headers)
    assert_error(response, 422, "VALIDATION_FAILED", "items")


def test_a_missing_body_is_rejected(client, database, accounts):
    response = client.put(SETTINGS, headers=accounts["owner"].headers)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
