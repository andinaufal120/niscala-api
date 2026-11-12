"""Scenarios of sign-up, login, sessions, passwords, Google, re-authentication and email change."""

from e2e.e2e_auth import (
    OTHER_PASSWORD,
    assert_error,
    end_login_lock,
    person_from,
    raw_login,
    token_in,
)
from e2e.e2e_people import BANK_ACCOUNT, DEVICE, PASSWORD

TABLET = {"name": "Galaxy Tab", "platform": "Android 13"}
NEW_BANK_ACCOUNT = {
    "bankName": "Bank BCA",
    "accountNumber": "9876543210",
    "accountHolderName": "Rina Owner",
}


def account_id(admin, email: str) -> str:
    items = admin.read("/user-accounts", params={"email": email})["items"]
    assert len(items) == 1, items
    return items[0]["id"]


def set_status(admin, email: str, status: str, *, new_email: str | None = None):
    account = admin.read(f"/user-accounts/{account_id(admin, email)}")
    return admin.put(
        f"/user-accounts/{account['id']}",
        json={
            "name": account["name"],
            "email": new_email or account["email"],
            "status": status,
        },
    )


# Sign-up and sessions


def test_owner_signs_up_confirms_the_email_and_manages_two_devices(world):
    owner = world.owner_signs_up(email="rina@example.com", verified=False)

    refused = owner.post("/properties", json={"name": "Kos Melati", "address": "x"})
    assert_error(refused, 403, "EMAIL_NOT_VERIFIED")
    assert_error(owner.get("/properties"), 403, "EMAIL_NOT_VERIFIED")
    profile = owner.read("/me")
    assert profile["email"] == "rina@example.com"
    assert profile["emailVerified"] is False

    owner.confirm_email()

    assert owner.read("/me")["emailVerified"] is True
    melati = owner.add_property("Kos Melati")
    assert [p["name"] for p in owner.properties()] == ["Kos Melati"]

    tablet = world.client.post(
        "/auth/login",
        json={"email": "rina@example.com", "password": PASSWORD, "device": TABLET},
    )
    second = person_from(world, tablet, password=PASSWORD)
    assert [p["id"] for p in second.properties()] == [melati["id"]]

    sessions = owner.read("/me/sessions")["items"]
    assert len(sessions) == 2
    current = [s for s in sessions if s["isCurrent"]]
    assert [s["id"] for s in current] == [str(owner.session_id)]
    assert {s["deviceName"] for s in sessions} == {"Pixel 8", "Galaxy Tab"}
    assert {s["loginMethod"] for s in sessions} == {"password"}

    assert_error(
        owner.delete(f"/me/sessions/{owner.session_id}"), 409, "SESSION_IS_CURRENT"
    )
    owner.delete(f"/me/sessions/{second.session_id}", expect=204)

    assert_error(second.get("/properties"), 401, "ACCESS_TOKEN_INVALID")
    assert_error(
        world.client.post("/auth/refresh", json={"refreshToken": second.refresh_token}),
        401,
        "REFRESH_TOKEN_INVALID",
    )
    assert [s["id"] for s in owner.read("/me/sessions")["items"]] == [
        str(owner.session_id)
    ]
    assert_error(
        owner.delete(f"/me/sessions/{second.session_id}"), 404, "SESSION_NOT_FOUND"
    )
    assert owner.properties()


def test_signing_up_with_a_registered_email_is_refused(world):
    world.owner_signs_up(email="rina@example.com")

    response = world.client.post(
        "/auth/register",
        json={
            "name": "Rina Again",
            "email": " Rina@Example.com ",
            "password": PASSWORD,
            "device": DEVICE,
        },
    )

    body = assert_error(response, 409, "EMAIL_ALREADY_REGISTERED")
    assert body["field"] == "email"


def test_ending_all_other_sessions_keeps_only_the_current_device(world):
    owner = world.owner_signs_up()
    phone = world.login(owner.email)
    tablet = world.login(owner.email)

    owner.delete("/me/sessions", expect=204)

    assert_error(phone.get("/properties"), 401, "ACCESS_TOKEN_INVALID")
    assert_error(tablet.get("/properties"), 401, "ACCESS_TOKEN_INVALID")
    assert len(owner.read("/me/sessions")["items"]) == 1
    owner.delete("/me/sessions", expect=204)
    assert owner.properties() == []


# Login


def test_login_locks_after_repeated_failures_and_recovers_when_the_lock_passes(
    world, database
):
    owner = world.owner_signs_up(email="rina@example.com")

    for _ in range(4):
        assert_error(
            raw_login(world, "rina@example.com", "wrong password"),
            401,
            "INVALID_CREDENTIALS",
        )
    assert_error(
        raw_login(world, "Rina@Example.com ", "wrong password"),
        401,
        "INVALID_CREDENTIALS",
    )

    locked = raw_login(world, "rina@example.com", PASSWORD)
    assert_error(locked, 429, "TOO_MANY_LOGIN_ATTEMPTS")
    assert 1 <= int(locked.headers["Retry-After"]) <= 15 * 60
    still_locked = raw_login(world, "rina@example.com", "wrong password")
    assert_error(still_locked, 429, "TOO_MANY_LOGIN_ATTEMPTS")
    assert owner.properties() == []

    end_login_lock(database, "rina@example.com")

    assert_error(
        raw_login(world, "rina@example.com", "wrong password"),
        401,
        "INVALID_CREDENTIALS",
    )
    again = world.login("rina@example.com")
    assert again.properties() == []


def test_failures_for_an_unknown_email_lock_it_the_same_way(world):
    for _ in range(5):
        assert_error(
            raw_login(world, "nobody@example.com", "whatever"),
            401,
            "INVALID_CREDENTIALS",
        )

    assert_error(
        raw_login(world, "nobody@example.com", "whatever"),
        429,
        "TOO_MANY_LOGIN_ATTEMPTS",
    )


def test_a_successful_login_resets_the_failure_count(world):
    world.owner_signs_up(email="rina@example.com")
    for _ in range(4):
        raw_login(world, "rina@example.com", "wrong password")

    world.login("rina@example.com")

    for _ in range(4):
        assert_error(
            raw_login(world, "rina@example.com", "wrong password"),
            401,
            "INVALID_CREDENTIALS",
        )
    world.login("rina@example.com")


def test_an_admin_deactivating_an_account_ends_its_sessions_and_blocks_login(world):
    owner = world.owner_signs_up(email="rina@example.com")
    admin = world.admin()

    set_status(admin, "rina@example.com", "inactive").json()

    assert_error(owner.get("/properties"), 401, "ACCESS_TOKEN_INVALID")
    assert_error(
        raw_login(world, "rina@example.com", PASSWORD), 403, "ACCOUNT_INACTIVE"
    )
    assert_error(
        raw_login(world, "rina@example.com", "wrong password"),
        401,
        "INVALID_CREDENTIALS",
    )

    set_status(admin, "rina@example.com", "active")

    assert world.login("rina@example.com").properties() == []


def test_refresh_rotates_tokens_and_reusing_an_old_one_ends_the_session(world):
    owner = world.owner_signs_up()
    first_refresh = owner.refresh_token

    owner.refresh()

    assert owner.refresh_token != first_refresh
    assert owner.properties() == []
    assert [s["id"] for s in owner.read("/me/sessions")["items"]] == [
        str(owner.session_id)
    ]

    reuse = world.client.post("/auth/refresh", json={"refreshToken": first_refresh})
    assert_error(reuse, 401, "REFRESH_TOKEN_INVALID")

    assert_error(owner.get("/properties"), 401, "ACCESS_TOKEN_INVALID")
    assert_error(
        world.client.post("/auth/refresh", json={"refreshToken": owner.refresh_token}),
        401,
        "REFRESH_TOKEN_INVALID",
    )
    assert world.login(owner.email).properties() == []


def test_logout_ends_only_the_current_session(world):
    first = world.owner_signs_up()
    second = world.login(first.email)

    second.logout()

    assert_error(second.get("/properties"), 401, "ACCESS_TOKEN_INVALID")
    assert_error(
        world.client.post("/auth/refresh", json={"refreshToken": second.refresh_token}),
        401,
        "REFRESH_TOKEN_INVALID",
    )
    assert first.properties() == []
    assert [s["id"] for s in first.read("/me/sessions")["items"]] == [
        str(first.session_id)
    ]


# Password change


def test_changing_the_password_checks_each_rule_and_keeps_the_current_session(world):
    owner = world.owner_signs_up(email="rina@example.com", name="Rina Owner")
    other = world.login(owner.email)

    wrong = owner.post(
        "/me/password-changes",
        json={"currentPassword": "not my password", "newPassword": OTHER_PASSWORD},
    )
    body = assert_error(wrong, 422, "CURRENT_PASSWORD_INCORRECT")
    assert body["field"] == "currentPassword"

    unchanged = owner.post(
        "/me/password-changes",
        json={"currentPassword": PASSWORD, "newPassword": PASSWORD},
    )
    body = assert_error(unchanged, 422, "PASSWORD_UNCHANGED")
    assert body["field"] == "newPassword"

    common = owner.post(
        "/me/password-changes",
        json={"currentPassword": PASSWORD, "newPassword": "12345678"},
    )
    body = assert_error(common, 422, "PASSWORD_TOO_COMMON")
    assert body["field"] == "newPassword"

    changed = owner.post(
        "/me/password-changes",
        json={"currentPassword": PASSWORD, "newPassword": OTHER_PASSWORD},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json() == {"hasOtherSessions": True}
    assert owner.properties() == []
    assert other.properties() == []

    owner.delete("/me/sessions", expect=204)

    assert_error(other.get("/properties"), 401, "ACCESS_TOKEN_INVALID")
    assert owner.properties() == []
    assert_error(
        raw_login(world, "rina@example.com", PASSWORD), 401, "INVALID_CREDENTIALS"
    )
    assert world.login("rina@example.com", OTHER_PASSWORD).properties() == []


def test_a_password_change_reports_when_no_other_session_exists(world):
    owner = world.owner_signs_up()

    changed = owner.post(
        "/me/password-changes",
        json={"currentPassword": PASSWORD, "newPassword": OTHER_PASSWORD},
    )

    assert changed.status_code == 200, changed.text
    assert changed.json() == {"hasOtherSessions": False}


def test_repeated_wrong_current_passwords_lock_further_password_changes(world):
    owner = world.owner_signs_up()

    for _ in range(5):
        assert_error(
            owner.post(
                "/me/password-changes",
                json={
                    "currentPassword": "nope nope nope",
                    "newPassword": OTHER_PASSWORD,
                },
            ),
            422,
            "CURRENT_PASSWORD_INCORRECT",
        )

    locked = owner.post(
        "/me/password-changes",
        json={"currentPassword": PASSWORD, "newPassword": OTHER_PASSWORD},
    )
    assert_error(locked, 429, "TOO_MANY_ATTEMPTS")
    assert int(locked.headers["Retry-After"]) >= 1


# Password reset


def test_password_reset_by_link_ends_every_session_and_works_once(world):
    owner = world.owner_signs_up(email="rina@example.com")
    other = world.login(owner.email)

    known = world.client.post(
        "/auth/password-reset-requests", json={"email": "rina@example.com"}
    )
    unknown = world.client.post(
        "/auth/password-reset-requests", json={"email": "nobody@example.com"}
    )
    assert known.status_code == unknown.status_code
    assert known.status_code < 300, known.text
    assert known.text == unknown.text
    resets = world.stubs.mailbox.reset_links
    assert [to for to, _ in resets] == ["rina@example.com"]
    token = token_in(resets[0][1])

    previewed = world.client.post(
        "/auth/password-reset-previews", json={"token": token}
    )
    assert previewed.status_code == 200, previewed.text
    assert previewed.json() == {"email": "rina@example.com"}

    reset = world.client.post(
        "/auth/password-resets", json={"token": token, "newPassword": OTHER_PASSWORD}
    )
    assert reset.status_code < 300, reset.text

    assert_error(owner.get("/properties"), 401, "ACCESS_TOKEN_INVALID")
    assert_error(other.get("/properties"), 401, "ACCESS_TOKEN_INVALID")
    assert_error(
        raw_login(world, "rina@example.com", PASSWORD), 401, "INVALID_CREDENTIALS"
    )
    assert world.login("rina@example.com", OTHER_PASSWORD).properties() == []

    again = world.client.post(
        "/auth/password-resets",
        json={"token": token, "newPassword": "amber meadow cloud"},
    )
    assert_error(again, 409, "PASSWORD_RESET_USED")
    used_preview = world.client.post(
        "/auth/password-reset-previews", json={"token": token}
    )
    assert_error(used_preview, 409, "PASSWORD_RESET_USED")


def test_a_new_reset_link_replaces_the_previous_one_and_unknown_links_are_refused(
    world,
):
    world.owner_signs_up(email="rina@example.com")
    for _ in range(2):
        world.client.post(
            "/auth/password-reset-requests", json={"email": "rina@example.com"}
        )
    old, new = (token_in(url) for _, url in world.stubs.mailbox.reset_links)

    assert_error(
        world.client.post(
            "/auth/password-resets", json={"token": old, "newPassword": OTHER_PASSWORD}
        ),
        409,
        "PASSWORD_RESET_USED",
    )
    assert_error(
        world.client.post("/auth/password-reset-previews", json={"token": "nonsense"}),
        404,
        "PASSWORD_RESET_NOT_FOUND",
    )
    assert_error(
        world.client.post(
            "/auth/password-resets",
            json={"token": "nonsense", "newPassword": OTHER_PASSWORD},
        ),
        404,
        "PASSWORD_RESET_NOT_FOUND",
    )

    done = world.client.post(
        "/auth/password-resets", json={"token": new, "newPassword": OTHER_PASSWORD}
    )
    assert done.status_code < 300, done.text
    assert world.login("rina@example.com", OTHER_PASSWORD).properties() == []


def test_a_password_reset_rejects_a_common_password_and_keeps_the_link(world):
    world.owner_signs_up(email="rina@example.com")
    world.client.post(
        "/auth/password-reset-requests", json={"email": "rina@example.com"}
    )
    token = token_in(world.stubs.mailbox.reset_links[0][1])

    weak = world.client.post(
        "/auth/password-resets", json={"token": token, "newPassword": "12345678"}
    )
    assert_error(weak, 422, "PASSWORD_TOO_COMMON")

    done = world.client.post(
        "/auth/password-resets", json={"token": token, "newPassword": OTHER_PASSWORD}
    )
    assert done.status_code < 300, done.text


# Google


def test_owner_signs_up_and_logs_in_with_google(world):
    world.stubs.google.add("owner-token", subject="g-1", email="gina@example.com")

    registered = world.client.post(
        "/auth/register/google",
        json={"idToken": "owner-token", "device": DEVICE, "name": "Gina Owner"},
    )
    owner = person_from(world, registered)

    assert owner.name == "Gina Owner"
    assert owner.email == "gina@example.com"
    profile = owner.read("/me")
    assert profile["emailVerified"] is True
    assert profile["hasPassword"] is False
    assert profile["googleEmail"] == "gina@example.com"
    owner.add_property("Kos Melati")
    assert [s["loginMethod"] for s in owner.read("/me/sessions")["items"]] == ["google"]

    logged_in = person_from(
        world,
        world.client.post(
            "/auth/login/google", json={"idToken": "owner-token", "device": TABLET}
        ),
    )

    assert logged_in.user_id == owner.user_id
    assert [p["name"] for p in logged_in.properties()] == ["Kos Melati"]
    assert len(owner.read("/me/sessions")["items"]) == 2

    assert_error(
        world.client.post(
            "/auth/login/google", json={"idToken": "forged", "device": DEVICE}
        ),
        401,
        "GOOGLE_TOKEN_INVALID",
    )
    world.stubs.google.add("stranger", subject="g-2", email="stranger@example.com")
    assert_error(
        world.client.post(
            "/auth/login/google", json={"idToken": "stranger", "device": DEVICE}
        ),
        401,
        "INVALID_CREDENTIALS",
    )


def test_google_sign_up_with_an_unverified_email_or_a_taken_identity_is_refused(world):
    world.stubs.google.add(
        "unverified", subject="g-1", email="gina@example.com", email_verified=False
    )
    world.stubs.google.add("good", subject="g-2", email="hana@example.com")
    world.stubs.google.add("same-email", subject="g-3", email="hana@example.com")

    refused = world.client.post(
        "/auth/register/google", json={"idToken": "unverified", "device": DEVICE}
    )
    body = assert_error(refused, 422, "GOOGLE_EMAIL_UNVERIFIED")
    assert body["field"] == "idToken"
    assert_error(
        world.client.post(
            "/auth/login/google", json={"idToken": "unverified", "device": DEVICE}
        ),
        401,
        "INVALID_CREDENTIALS",
    )

    first = world.client.post(
        "/auth/register/google", json={"idToken": "good", "device": DEVICE}
    )
    assert first.status_code == 201, first.text
    assert first.json()["account"]["name"] == "Google Person"
    assert_error(
        world.client.post(
            "/auth/register/google", json={"idToken": "good", "device": DEVICE}
        ),
        409,
        "GOOGLE_ACCOUNT_ALREADY_REGISTERED",
    )
    assert_error(
        world.client.post(
            "/auth/register/google", json={"idToken": "same-email", "device": DEVICE}
        ),
        409,
        "EMAIL_ALREADY_REGISTERED",
    )


def test_google_is_linked_only_from_a_password_login_and_never_by_matching_email(
    world,
):
    owner = world.owner_signs_up(email="rina@example.com")
    world.stubs.google.add("rina-google", subject="g-rina", email="rina@gmail.example")
    world.stubs.google.add(
        "unverified", subject="g-bad", email="x@gmail.example", email_verified=False
    )
    assert_error(
        world.client.post(
            "/auth/login/google", json={"idToken": "rina-google", "device": DEVICE}
        ),
        401,
        "INVALID_CREDENTIALS",
    )

    unverified = owner.post("/me/google-link", json={"idToken": "unverified"})
    assert_error(unverified, 422, "GOOGLE_EMAIL_UNVERIFIED")
    assert_error(
        owner.post("/me/google-link", json={"idToken": "forged"}),
        401,
        "GOOGLE_TOKEN_INVALID",
    )
    linked = owner.post("/me/google-link", json={"idToken": "rina-google"})
    assert linked.status_code < 300, linked.text

    profile = owner.read("/me")
    assert profile["googleEmail"] == "rina@gmail.example"
    assert profile["email"] == "rina@example.com"
    assert profile["hasPassword"] is True
    assert_error(
        owner.post("/me/google-link", json={"idToken": "rina-google"}),
        409,
        "GOOGLE_ALREADY_LINKED",
    )

    via_google = person_from(
        world,
        world.client.post(
            "/auth/login/google", json={"idToken": "rina-google", "device": TABLET}
        ),
    )
    assert via_google.user_id == owner.user_id
    assert via_google.read("/me")["email"] == "rina@example.com"

    still_password = world.login("rina@example.com")
    assert still_password.properties() == []


def test_a_session_that_did_not_start_with_a_password_cannot_link_google(world):
    world.stubs.google.add("gina", subject="g-gina", email="gina@example.com")
    world.stubs.google.add("other", subject="g-other", email="other@example.com")
    gina = person_from(
        world,
        world.client.post(
            "/auth/register/google",
            json={"idToken": "gina", "device": DEVICE, "name": "Gina Owner"},
        ),
    )
    added = gina.post(
        "/me/local-password",
        json={"googleIdToken": "gina", "password": OTHER_PASSWORD},
    )
    assert added.status_code < 300, added.text

    refused = gina.post("/me/google-link", json={"idToken": "other"})

    assert_error(refused, 403, "PASSWORD_LOGIN_REQUIRED")


def test_a_google_account_adds_a_local_password_and_then_logs_in_with_it(world):
    world.stubs.google.add("gina", subject="g-gina", email="gina@example.com")
    world.stubs.google.add("other", subject="g-other", email="other@example.com")
    gina = person_from(
        world,
        world.client.post(
            "/auth/register/google",
            json={"idToken": "gina", "device": DEVICE, "name": "Gina Owner"},
        ),
    )
    other_device = person_from(
        world,
        world.client.post(
            "/auth/login/google", json={"idToken": "gina", "device": TABLET}
        ),
    )
    assert_error(
        raw_login(world, "gina@example.com", OTHER_PASSWORD), 401, "INVALID_CREDENTIALS"
    )
    assert_error(
        gina.post(
            "/me/local-password",
            json={"googleIdToken": "other", "password": OTHER_PASSWORD},
        ),
        422,
        "GOOGLE_ACCOUNT_MISMATCH",
    )
    assert_error(
        gina.post(
            "/me/local-password",
            json={"googleIdToken": "forged", "password": OTHER_PASSWORD},
        ),
        401,
        "GOOGLE_TOKEN_INVALID",
    )
    assert_error(
        gina.post(
            "/me/local-password",
            json={"googleIdToken": "gina", "password": "12345678"},
        ),
        422,
        "PASSWORD_TOO_COMMON",
    )

    added = gina.post(
        "/me/local-password",
        json={"googleIdToken": "gina", "password": OTHER_PASSWORD},
    )
    assert added.status_code < 300, added.text

    assert gina.read("/me")["hasPassword"] is True
    assert other_device.properties() == []
    with_password = world.login("gina@example.com", OTHER_PASSWORD)
    assert with_password.user_id == gina.user_id
    assert_error(
        gina.post(
            "/me/local-password",
            json={"googleIdToken": "gina", "password": "amber meadow cloud"},
        ),
        409,
        "PASSWORD_ALREADY_SET",
    )
    assert {s["loginMethod"] for s in gina.read("/me/sessions")["items"]} == {
        "google",
        "password",
    }


def test_a_google_account_has_no_password_to_change_or_log_in_with(world):
    world.stubs.google.add("gina", subject="g-gina", email="gina@example.com")
    gina = person_from(
        world,
        world.client.post(
            "/auth/register/google",
            json={"idToken": "gina", "device": DEVICE, "name": "Gina Owner"},
        ),
    )

    assert_error(
        gina.post(
            "/me/password-changes",
            json={"currentPassword": "anything", "newPassword": OTHER_PASSWORD},
        ),
        409,
        "PASSWORD_NOT_SET",
    )
    assert_error(
        raw_login(world, "gina@example.com", "anything"), 401, "INVALID_CREDENTIALS"
    )
    world.client.post(
        "/auth/password-reset-requests", json={"email": "gina@example.com"}
    )
    world.stubs.assert_mailbox_empty()


def test_a_google_identity_linked_elsewhere_cannot_be_linked_again(world):
    world.stubs.google.add("shared", subject="g-shared", email="shared@gmail.example")
    first = world.owner_signs_up(email="rina@example.com")
    second = world.owner_signs_up(email="sari@example.com", name="Sari Owner")
    linked = first.post("/me/google-link", json={"idToken": "shared"})
    assert linked.status_code < 300, linked.text

    refused = second.post("/me/google-link", json={"idToken": "shared"})

    assert_error(refused, 409, "GOOGLE_ACCOUNT_ALREADY_REGISTERED")
    assert second.read("/me")["googleEmail"] is None
    assert first.read("/me")["googleEmail"] == "shared@gmail.example"


# Re-authentication


def test_changing_a_bank_account_needs_a_recent_reauthentication_of_the_session(world):
    owner = world.owner_signs_up()
    melati = owner.add_property("Kos Melati", bank_account=BANK_ACCOUNT)
    other_device = world.login(owner.email)
    edit = {"name": "Kos Melati", "address": "Jl. Melati 5", "bankAccount": None}

    renamed = owner.put(
        f"/properties/{melati['id']}",
        json={**edit, "name": "Kos Melati Baru", "bankAccount": BANK_ACCOUNT},
    )
    assert renamed.status_code == 200, renamed.text

    refused = owner.put(
        f"/properties/{melati['id']}",
        json={**edit, "name": "Kos Melati Baru", "bankAccount": NEW_BANK_ACCOUNT},
    )
    assert_error(refused, 403, "REAUTHENTICATION_REQUIRED")
    assert owner.read(f"/properties/{melati['id']}")["bankAccount"] == BANK_ACCOUNT

    wrong = owner.post("/me/reauthentication/password", json={"password": "nope"})
    body = assert_error(wrong, 422, "PASSWORD_INCORRECT")
    assert body["field"] == "password"
    reauthenticated = owner.post(
        "/me/reauthentication/password", json={"password": PASSWORD}
    )
    assert reauthenticated.status_code < 300, reauthenticated.text

    changed = owner.put(
        f"/properties/{melati['id']}",
        json={**edit, "name": "Kos Melati Baru", "bankAccount": NEW_BANK_ACCOUNT},
    )
    assert changed.status_code == 200, changed.text
    assert owner.read(f"/properties/{melati['id']}")["bankAccount"] == NEW_BANK_ACCOUNT

    assert_error(
        other_device.put(
            f"/properties/{melati['id']}",
            json={**edit, "name": "Kos Melati Baru", "bankAccount": BANK_ACCOUNT},
        ),
        403,
        "REAUTHENTICATION_REQUIRED",
    )


def test_a_google_account_reauthenticates_with_its_google_identity(world):
    world.stubs.google.add("gina", subject="g-gina", email="gina@example.com")
    world.stubs.google.add("other", subject="g-other", email="other@example.com")
    gina = person_from(
        world,
        world.client.post(
            "/auth/register/google",
            json={"idToken": "gina", "device": DEVICE, "name": "Gina Owner"},
        ),
    )
    melati = gina.add_property("Kos Melati", bank_account=BANK_ACCOUNT)
    edit = {
        "name": "Kos Melati",
        "address": "Jl. Melati 5",
        "bankAccount": NEW_BANK_ACCOUNT,
    }
    assert_error(
        gina.put(f"/properties/{melati['id']}", json=edit),
        403,
        "REAUTHENTICATION_REQUIRED",
    )
    assert_error(
        gina.post("/me/reauthentication/password", json={"password": "anything"}),
        409,
        "PASSWORD_NOT_SET",
    )
    assert_error(
        gina.post("/me/reauthentication/google", json={"idToken": "other"}),
        422,
        "GOOGLE_ACCOUNT_MISMATCH",
    )

    done = gina.post("/me/reauthentication/google", json={"idToken": "gina"})
    assert done.status_code < 300, done.text

    assert gina.put(f"/properties/{melati['id']}", json=edit).status_code == 200


# Email change by an Admin


def test_an_admin_email_change_stays_pending_until_the_link_is_confirmed(world):
    owner = world.owner_signs_up(email="rina@example.com")
    admin = world.admin()
    user_id = account_id(admin, "rina@example.com")

    pending = set_status(
        admin, "rina@example.com", "active", new_email="rani@example.com"
    )

    assert pending.status_code == 200, pending.text
    assert pending.json()["email"] == "rina@example.com"
    assert pending.json()["pendingEmail"] == "rani@example.com"
    assert pending.json()["pendingEmailExpiresAt"]
    assert [to for to, _ in world.stubs.mailbox.links] == ["rani@example.com"]
    assert [to for to, _ in world.stubs.mailbox.notices] == ["rina@example.com"]
    assert world.login("rina@example.com").properties() == []
    assert_error(
        raw_login(world, "rani@example.com", PASSWORD), 401, "INVALID_CREDENTIALS"
    )
    assert owner.properties() == []

    token = token_in(world.stubs.mailbox.links[0][1])
    confirmed = world.client.post("/auth/email-changes", json={"token": token})
    assert confirmed.status_code < 300, confirmed.text

    detail = admin.read(f"/user-accounts/{user_id}")
    assert detail["email"] == "rani@example.com"
    assert detail["pendingEmail"] is None
    assert world.login("rani@example.com").user_id == owner.user_id
    assert_error(
        raw_login(world, "rina@example.com", PASSWORD), 401, "INVALID_CREDENTIALS"
    )
    assert_error(
        world.client.post("/auth/email-changes", json={"token": token}),
        409,
        "EMAIL_CHANGE_USED",
    )
    assert_error(
        world.client.post("/auth/email-changes", json={"token": "nonsense"}),
        404,
        "EMAIL_CHANGE_NOT_FOUND",
    )


def test_an_admin_cannot_move_an_account_to_an_email_that_is_taken(world):
    world.owner_signs_up(email="rina@example.com")
    world.owner_signs_up(email="sari@example.com", name="Sari Owner")
    admin = world.admin()

    response = set_status(
        admin, "rina@example.com", "active", new_email="sari@example.com"
    )

    body = assert_error(response, 409, "EMAIL_ALREADY_REGISTERED")
    assert body["field"] == "email"
