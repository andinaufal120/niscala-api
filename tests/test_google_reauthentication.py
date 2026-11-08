"""Confirming the caller's identity again with a Google ID token."""

from datetime import UTC, datetime, timedelta

import pytest
from google_support import (
    LOCK_SECONDS,
    REAUTHENTICATION_URL,
    WINDOW,
    assert_error,
    assert_locked,
    make_google_user,
    password_login,
    read_failure,
    reauthenticate,
    recent_reauthentication_status,
    set_failure,
    snapshot,
)
from sqlalchemy.orm import Session

EMAIL = "rina@example.com"
SUBJECT = "sub-rina"
TOKEN = "rina-token"
OTHER_TOKEN = "budi-token"
PASSWORD = "correct horse battery"
BANK = {
    "bankName": "BCA",
    "accountNumber": "1234567890",
    "accountHolderName": "Budi Santoso",
}
PROPERTY_BODY = {"name": "Kos Melati", "address": "Jl. Melati 5", "bankAccount": BANK}


def assert_mismatch(response) -> None:
    assert_error(response, 422, "GOOGLE_ACCOUNT_MISMATCH", "idToken")


def set_reauthenticated_at(database, session_id, value) -> None:
    from app.models import UserSession

    with Session(database) as db:
        db.get(UserSession, session_id).reauthenticated_at = value
        db.commit()


@pytest.fixture
def owner(database):
    return make_google_user(database, subject=SUBJECT, email=EMAIL)


@pytest.fixture
def tokens(google):
    """The owner's token and the token of an unrelated Google account."""
    google.add(TOKEN, subject=SUBJECT, email="rina.gmail@example.com")
    google.add(OTHER_TOKEN, subject="sub-budi", email="budi@example.com")
    return google


@pytest.fixture
def signed_in(owner, sign_in):
    from app.schemas.sessions import LoginMethod

    return sign_in(owner, login_method=LoginMethod.GOOGLE)


# Success


def test_the_matching_token_answers_with_the_end_of_the_window(
    client, database, tokens, signed_in
):
    before = datetime.now(UTC)
    response = reauthenticate(client, signed_in.headers, TOKEN)
    after = datetime.now(UTC)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"reauthenticatedUntil"}
    assert body["reauthenticatedUntil"].endswith("Z")
    until = datetime.fromisoformat(body["reauthenticatedUntil"])
    assert until.utcoffset() == timedelta(0)
    assert before + WINDOW - timedelta(seconds=1) <= until
    assert until <= after + WINDOW + timedelta(seconds=1)


def test_the_current_session_records_the_moment_of_re_authentication(
    client, database, tokens, signed_in, read_session
):
    before = datetime.now(UTC)
    response = reauthenticate(client, signed_in.headers, TOKEN)
    after = datetime.now(UTC)
    stored = read_session(signed_in.session_id).reauthenticated_at
    assert before <= stored <= after
    until = datetime.fromisoformat(response.json()["reauthenticatedUntil"])
    assert abs(until - (stored + WINDOW)) <= timedelta(seconds=1)


def test_the_token_is_handed_to_the_verifier(client, database, tokens, signed_in):
    reauthenticate(client, signed_in.headers, TOKEN)
    assert tokens.verified == [TOKEN]


def test_other_sessions_of_the_user_are_untouched(
    client, database, tokens, owner, sign_in, read_session
):
    current = sign_in(owner)
    other = sign_in(owner, device_name="Galaxy")
    assert reauthenticate(client, current.headers, TOKEN).status_code == 200
    assert read_session(current.session_id).reauthenticated_at is not None
    assert read_session(other.session_id).reauthenticated_at is None
    assert recent_reauthentication_status(current.headers) == 200
    assert recent_reauthentication_status(other.headers) == 403


def test_other_users_sessions_are_untouched(
    client, database, tokens, signed_in, make_user, sign_in, read_session
):
    stranger = sign_in(make_user(email="budi@example.com"))
    assert reauthenticate(client, signed_in.headers, TOKEN).status_code == 200
    assert read_session(stranger.session_id).reauthenticated_at is None


def test_the_session_passes_the_recent_re_authentication_guard_afterwards(
    client, database, tokens, signed_in
):
    assert recent_reauthentication_status(signed_in.headers) == 403
    assert reauthenticate(client, signed_in.headers, TOKEN).status_code == 200
    assert recent_reauthentication_status(signed_in.headers) == 200


def test_the_guard_stops_passing_five_minutes_after_re_authentication(
    client, database, tokens, signed_in
):
    assert reauthenticate(client, signed_in.headers, TOKEN).status_code == 200
    set_reauthenticated_at(
        database,
        signed_in.session_id,
        datetime.now(UTC) - WINDOW - timedelta(seconds=1),
    )
    assert recent_reauthentication_status(signed_in.headers) == 403


def test_re_authenticating_again_refreshes_the_time(
    client, database, tokens, signed_in, read_session
):
    old = datetime.now(UTC) - timedelta(minutes=4)
    set_reauthenticated_at(database, signed_in.session_id, old)
    response = reauthenticate(client, signed_in.headers, TOKEN)
    assert response.status_code == 200
    assert read_session(signed_in.session_id).reauthenticated_at > old + timedelta(
        minutes=3
    )


def test_re_authenticating_after_the_window_lapsed_opens_it_again(
    client, database, tokens, signed_in
):
    set_reauthenticated_at(
        database, signed_in.session_id, datetime.now(UTC) - timedelta(hours=1)
    )
    assert recent_reauthentication_status(signed_in.headers) == 403
    assert reauthenticate(client, signed_in.headers, TOKEN).status_code == 200
    assert recent_reauthentication_status(signed_in.headers) == 200


@pytest.mark.parametrize("role", ["owner", "manager", "tenant", "admin"])
def test_every_role_with_a_linked_subject_can_re_authenticate(
    client, database, google, sign_in, read_session, role
):
    from app.schemas.auth import UserRole

    google.add("role-token", subject="sub-role")
    user = make_google_user(database, subject="sub-role", role=UserRole(role))
    session = sign_in(user)
    assert reauthenticate(client, session.headers, "role-token").status_code == 200
    assert read_session(session.session_id).reauthenticated_at is not None


def test_a_user_with_a_password_and_a_linked_subject_can_re_authenticate(
    client, database, tokens, make_user, sign_in
):
    from app.services.passwords import hash_password

    user = make_google_user(
        database,
        subject="sub-both",
        email="both@example.com",
        password_hash=hash_password(PASSWORD),
    )
    tokens.add("both-token", subject="sub-both")
    session = sign_in(user)
    assert reauthenticate(client, session.headers, "both-token").status_code == 200


def test_the_token_email_does_not_have_to_match_the_account(
    client, database, tokens, signed_in
):
    tokens.add("moved", subject=SUBJECT, email="brand.new@example.com")
    assert reauthenticate(client, signed_in.headers, "moved").status_code == 200


def test_a_session_started_with_a_password_can_re_authenticate_with_google(
    client, database, tokens, owner, sign_in
):
    from app.schemas.sessions import LoginMethod

    session = sign_in(owner, login_method=LoginMethod.PASSWORD)
    assert reauthenticate(client, session.headers, TOKEN).status_code == 200


# Bank account change


def bank_change(client, headers, property_id, **overrides):
    return client.put(
        f"/properties/{property_id}",
        json={**PROPERTY_BODY, **overrides},
        headers=headers,
    )


def test_a_bank_account_change_needs_the_google_re_authentication(
    client, database, tokens, owner, signed_in, make_property
):
    prop = make_property(owner)
    refused = bank_change(client, signed_in.headers, prop.id)
    assert_error(refused, 403, "REAUTHENTICATION_REQUIRED")
    assert reauthenticate(client, signed_in.headers, TOKEN).status_code == 200
    changed = bank_change(client, signed_in.headers, prop.id)
    assert changed.status_code == 200, changed.text
    assert changed.json()["bankAccount"] == BANK


def test_the_google_re_authentication_opens_the_window_for_that_session_only(
    client, database, tokens, owner, signed_in, sign_in, make_property
):
    prop = make_property(owner)
    other = sign_in(owner, device_name="Galaxy")
    assert reauthenticate(client, signed_in.headers, TOKEN).status_code == 200
    assert_error(
        bank_change(client, other.headers, prop.id), 403, "REAUTHENTICATION_REQUIRED"
    )
    assert bank_change(client, signed_in.headers, prop.id).status_code == 200


def test_a_refused_re_authentication_leaves_the_bank_account_locked(
    client, database, tokens, owner, signed_in, make_property
):
    prop = make_property(owner)
    assert_mismatch(reauthenticate(client, signed_in.headers, OTHER_TOKEN))
    assert_error(
        bank_change(client, signed_in.headers, prop.id),
        403,
        "REAUTHENTICATION_REQUIRED",
    )


# Failure count


def test_success_clears_the_failed_login_count(client, database, tokens, signed_in):
    set_failure(database, EMAIL, failed_attempts=3)
    assert reauthenticate(client, signed_in.headers, TOKEN).status_code == 200
    assert read_failure(database, EMAIL) is None


def test_success_without_earlier_failures_leaves_no_failure_row(
    client, database, tokens, signed_in
):
    assert reauthenticate(client, signed_in.headers, TOKEN).status_code == 200
    assert read_failure(database, EMAIL) is None


def test_success_does_not_clear_the_count_of_other_emails(
    client, database, tokens, signed_in
):
    set_failure(database, "other@example.com", failed_attempts=2)
    assert reauthenticate(client, signed_in.headers, TOKEN).status_code == 200
    assert read_failure(database, "other@example.com").failed_attempts == 2


def test_success_after_mismatches_restarts_the_count(
    client, database, tokens, signed_in
):
    for _ in range(4):
        assert_mismatch(reauthenticate(client, signed_in.headers, OTHER_TOKEN))
    assert reauthenticate(client, signed_in.headers, TOKEN).status_code == 200
    for _ in range(4):
        assert_mismatch(reauthenticate(client, signed_in.headers, OTHER_TOKEN))
    assert read_failure(database, EMAIL).locked_until is None
    assert reauthenticate(client, signed_in.headers, TOKEN).status_code == 200


def test_success_resets_failed_password_logins_of_the_email(
    client, database, tokens, signed_in
):
    for _ in range(4):
        assert password_login(client, EMAIL).status_code == 401
    assert reauthenticate(client, signed_in.headers, TOKEN).status_code == 200
    assert read_failure(database, EMAIL) is None


# Mismatch


def test_a_token_of_another_subject_is_a_mismatch(
    client, database, tokens, signed_in, read_session
):
    assert_mismatch(reauthenticate(client, signed_in.headers, OTHER_TOKEN))
    assert read_session(signed_in.session_id).reauthenticated_at is None
    assert recent_reauthentication_status(signed_in.headers) == 403


def test_a_mismatch_keeps_an_earlier_re_authentication_time(
    client, database, tokens, signed_in, read_session
):
    earlier = datetime.now(UTC) - timedelta(minutes=2)
    set_reauthenticated_at(database, signed_in.session_id, earlier)
    assert_mismatch(reauthenticate(client, signed_in.headers, OTHER_TOKEN))
    assert read_session(signed_in.session_id).reauthenticated_at == earlier


def test_a_token_with_the_account_email_but_another_subject_is_a_mismatch(
    client, database, tokens, signed_in
):
    tokens.add("lookalike", subject="sub-lookalike", email=EMAIL)
    assert_mismatch(reauthenticate(client, signed_in.headers, "lookalike"))


@pytest.mark.parametrize("attempts", [1, 2, 3, 4])
def test_mismatches_are_counted_for_the_account_email_without_locking(
    client, database, tokens, signed_in, attempts
):
    for _ in range(attempts):
        assert_mismatch(reauthenticate(client, signed_in.headers, OTHER_TOKEN))
    row = read_failure(database, EMAIL)
    assert row.failed_attempts == attempts
    assert row.locked_until is None


def test_the_fifth_mismatch_still_answers_mismatch_and_locks_the_email(
    client, database, tokens, signed_in
):
    for _ in range(4):
        assert_mismatch(reauthenticate(client, signed_in.headers, OTHER_TOKEN))
    before = datetime.now(UTC)
    assert_mismatch(reauthenticate(client, signed_in.headers, OTHER_TOKEN))
    after = datetime.now(UTC)
    row = read_failure(database, EMAIL)
    assert row.failed_attempts == 5
    assert (
        before + timedelta(seconds=LOCK_SECONDS)
        <= row.locked_until
        <= after + timedelta(seconds=LOCK_SECONDS)
    )


def test_a_locked_email_cannot_re_authenticate_even_with_the_right_token(
    client, database, tokens, signed_in, read_session
):
    for _ in range(5):
        reauthenticate(client, signed_in.headers, OTHER_TOKEN)
    assert_locked(reauthenticate(client, signed_in.headers, TOKEN))
    assert read_session(signed_in.session_id).reauthenticated_at is None


def test_the_next_mismatch_after_the_lock_is_answered_locked(
    client, database, tokens, signed_in
):
    for _ in range(5):
        reauthenticate(client, signed_in.headers, OTHER_TOKEN)
    assert_locked(reauthenticate(client, signed_in.headers, OTHER_TOKEN))


def test_a_lock_from_mismatches_blocks_password_login(
    client, database, tokens, signed_in
):
    for _ in range(5):
        reauthenticate(client, signed_in.headers, OTHER_TOKEN)
    assert_locked(password_login(client, EMAIL))
    assert_locked(password_login(client, EMAIL, PASSWORD))


def test_failed_password_logins_and_mismatches_share_one_counter(
    client, database, tokens, signed_in
):
    for _ in range(2):
        assert password_login(client, EMAIL).status_code == 401
    for _ in range(3):
        assert_mismatch(reauthenticate(client, signed_in.headers, OTHER_TOKEN))
    row = read_failure(database, EMAIL)
    assert row.failed_attempts == 5
    assert row.locked_until is not None
    assert_locked(reauthenticate(client, signed_in.headers, TOKEN))
    assert_locked(password_login(client, EMAIL))


def test_failed_password_logins_alone_lock_google_re_authentication(
    client, database, tokens, signed_in
):
    for _ in range(5):
        assert password_login(client, EMAIL).status_code in (401, 429)
    assert_locked(reauthenticate(client, signed_in.headers, TOKEN))


def test_an_existing_lock_answers_before_the_token_is_compared(
    client, database, tokens, signed_in, read_session
):
    locked_until = datetime.now(UTC) + timedelta(seconds=100)
    set_failure(database, EMAIL, failed_attempts=5, locked_until=locked_until)
    assert_locked(reauthenticate(client, signed_in.headers, TOKEN))
    assert_locked(reauthenticate(client, signed_in.headers, OTHER_TOKEN))
    row = read_failure(database, EMAIL)
    assert row.failed_attempts == 5
    assert row.locked_until == locked_until
    assert read_session(signed_in.session_id).reauthenticated_at is None


def test_the_lock_answer_reports_the_remaining_time_rounded_up(
    client, database, tokens, signed_in
):
    set_failure(
        database,
        EMAIL,
        failed_attempts=5,
        locked_until=datetime.now(UTC) + timedelta(seconds=100.9),
    )
    response = reauthenticate(client, signed_in.headers, TOKEN)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "101"


def test_a_lapsed_lock_lets_the_right_token_through(
    client, database, tokens, signed_in
):
    set_failure(
        database,
        EMAIL,
        failed_attempts=5,
        locked_until=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert reauthenticate(client, signed_in.headers, TOKEN).status_code == 200
    assert read_failure(database, EMAIL) is None


def test_a_lapsed_lock_starts_the_count_again_on_a_mismatch(
    client, database, tokens, signed_in
):
    set_failure(
        database,
        EMAIL,
        failed_attempts=5,
        locked_until=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert_mismatch(reauthenticate(client, signed_in.headers, OTHER_TOKEN))
    row = read_failure(database, EMAIL)
    assert row.failed_attempts == 1
    assert row.locked_until is None


def test_the_lock_of_another_email_does_not_block(client, database, tokens, signed_in):
    set_failure(
        database,
        "other@example.com",
        failed_attempts=5,
        locked_until=datetime.now(UTC) + timedelta(minutes=10),
    )
    assert reauthenticate(client, signed_in.headers, TOKEN).status_code == 200


# No linked Google account


@pytest.fixture
def password_only(database, tokens, make_user, sign_in):
    from app.services.passwords import hash_password

    user = make_user(email="pw@example.com", password_hash=hash_password(PASSWORD))
    return sign_in(user)


def test_an_account_without_a_linked_google_subject_gets_google_not_linked(
    client, database, tokens, password_only, read_session
):
    response = reauthenticate(client, password_only.headers, TOKEN)
    assert_error(response, 409, "GOOGLE_NOT_LINKED")
    assert read_session(password_only.session_id).reauthenticated_at is None


def test_google_not_linked_is_not_counted_as_a_failure(
    client, database, tokens, password_only
):
    for _ in range(6):
        assert reauthenticate(client, password_only.headers, TOKEN).status_code == 409
    assert read_failure(database, "pw@example.com") is None


def test_google_not_linked_is_answered_for_any_valid_token(
    client, database, tokens, password_only
):
    response = reauthenticate(client, password_only.headers, OTHER_TOKEN)
    assert_error(response, 409, "GOOGLE_NOT_LINKED")


# Invalid token


def test_an_invalid_token_is_unauthorized_on_the_token_field(
    client, database, tokens, signed_in, read_session
):
    response = reauthenticate(client, signed_in.headers, "forged-token")
    assert_error(response, 401, "GOOGLE_TOKEN_INVALID", "idToken")
    assert read_session(signed_in.session_id).reauthenticated_at is None


def test_an_invalid_token_counts_no_failure(client, database, tokens, signed_in):
    for _ in range(6):
        response = reauthenticate(client, signed_in.headers, "forged-token")
        assert_error(response, 401, "GOOGLE_TOKEN_INVALID", "idToken")
    assert read_failure(database, EMAIL) is None
    assert reauthenticate(client, signed_in.headers, TOKEN).status_code == 200


def test_an_invalid_token_leaves_an_earlier_failure_count_alone(
    client, database, tokens, signed_in
):
    assert_mismatch(reauthenticate(client, signed_in.headers, OTHER_TOKEN))
    reauthenticate(client, signed_in.headers, "forged-token")
    assert read_failure(database, EMAIL).failed_attempts == 1


# Validation


@pytest.mark.parametrize("value", ["", None, 12345])
def test_an_unusable_token_value_is_a_validation_failure_and_not_counted(
    client, database, tokens, signed_in, value
):
    for _ in range(6):
        response = client.post(
            REAUTHENTICATION_URL, json={"idToken": value}, headers=signed_in.headers
        )
        assert_error(response, 422, "VALIDATION_FAILED", "idToken")
    assert read_failure(database, EMAIL) is None
    assert tokens.verified == []
    assert reauthenticate(client, signed_in.headers, TOKEN).status_code == 200


def test_a_missing_body_is_a_validation_failure(client, database, tokens, signed_in):
    response = client.post(REAUTHENTICATION_URL, headers=signed_in.headers)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert read_failure(database, EMAIL) is None


# Authentication


def assert_access_rejected(response) -> None:
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


def test_no_access_token_is_rejected(client, database, tokens, owner):
    response = client.post(REAUTHENTICATION_URL, json={"idToken": TOKEN})
    assert_access_rejected(response)
    assert tokens.verified == []


def test_an_invalid_access_token_is_rejected(client, database, tokens, owner):
    response = client.post(
        REAUTHENTICATION_URL,
        json={"idToken": TOKEN},
        headers={"Authorization": "Bearer garbage"},
    )
    assert_access_rejected(response)


def test_a_revoked_session_is_rejected(
    client, database, tokens, signed_in, read_session
):
    client.post("/auth/logout", headers=signed_in.headers)
    assert_access_rejected(reauthenticate(client, signed_in.headers, TOKEN))
    assert read_session(signed_in.session_id).reauthenticated_at is None


def test_a_rejected_access_token_counts_no_failure(client, database, tokens, owner):
    for _ in range(6):
        response = client.post(
            REAUTHENTICATION_URL,
            json={"idToken": OTHER_TOKEN},
            headers={"Authorization": "Bearer garbage"},
        )
        assert_access_rejected(response)
    assert read_failure(database, EMAIL) is None


def test_an_unverified_account_gets_email_not_verified(
    client, database, tokens, sign_in, read_session
):
    user = make_google_user(
        database, subject="sub-new", email="new@example.com", email_verified=False
    )
    tokens.add("new-token", subject="sub-new")
    session = sign_in(user)
    response = reauthenticate(client, session.headers, "new-token")
    assert_error(response, 403, "EMAIL_NOT_VERIFIED")
    assert read_session(session.session_id).reauthenticated_at is None
    assert read_failure(database, "new@example.com") is None


def test_an_unverified_account_with_a_mismatching_token_counts_no_failure(
    client, database, tokens, sign_in
):
    user = make_google_user(
        database, subject="sub-new", email="new@example.com", email_verified=False
    )
    session = sign_in(user)
    response = reauthenticate(client, session.headers, OTHER_TOKEN)
    assert response.json()["code"] == "EMAIL_NOT_VERIFIED"
    assert read_failure(database, "new@example.com") is None


def test_a_refused_re_authentication_changes_no_stored_account_data(
    client, database, tokens, signed_in
):
    before = snapshot(database)["users"]
    reauthenticate(client, signed_in.headers, OTHER_TOKEN)
    reauthenticate(client, signed_in.headers, TOKEN)
    assert snapshot(database)["users"] == before
