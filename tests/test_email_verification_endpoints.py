"""Requesting and confirming the emailed verification code."""

import hashlib
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

SEND_URL = "/auth/email-verification"
CONFIRM_URL = "/auth/email-verification/confirmation"
ME_URL = "/me"


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def seconds_ago(seconds: float) -> datetime:
    return datetime.now(UTC) - timedelta(seconds=seconds)


def send(client, headers=None):
    return client.post(SEND_URL, headers=headers)


def confirm(client, code: str, headers=None):
    return client.post(CONFIRM_URL, json={"code": code}, headers=headers)


def assert_error(response, status: int, code: str, field: str | None) -> None:
    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    assert body["field"] == field
    assert body["message"]


@pytest.fixture
def unverified(make_user, sign_in):
    """An unverified user with a session and no verification code on record."""
    user = make_user(email="rina@example.com", email_verified=False)
    return user, sign_in(user)


@pytest.fixture
def registered(register_owner, sent_emails):
    """An owner who just signed up, with the emailed code and bearer headers."""
    body = register_owner().json()
    return {
        "user_id": body["account"]["id"],
        "headers": {"Authorization": f"Bearer {body['accessToken']}"},
        "code": sent_emails[0][1],
    }


def other_code(code: str) -> str:
    return "000000" if code != "000000" else "111111"


# POST /auth/email-verification


def test_send_creates_a_code_and_emails_it(
    client, unverified, sent_emails, read_verification_code
):
    user, signed_in = unverified
    response = send(client, signed_in.headers)
    assert response.status_code == 202
    assert sent_emails and len(sent_emails) == 1
    to, code = sent_emails[0]
    assert to == "rina@example.com"
    assert re.fullmatch(r"[0-9]{6}", code)
    row = read_verification_code(user.id)
    assert row.code_hash == sha256(code)
    assert row.code_hash != code
    assert row.failed_attempts == 0


def test_send_code_is_valid_for_ten_minutes(
    client, unverified, sent_emails, read_verification_code
):
    user, signed_in = unverified
    before = datetime.now(UTC)
    send(client, signed_in.headers)
    row = read_verification_code(user.id)
    assert before - timedelta(seconds=5) <= row.created_at <= datetime.now(UTC)
    assert row.expires_at - row.created_at == timedelta(minutes=10)


def test_send_reports_when_another_code_may_be_requested(
    client, unverified, sent_emails, read_verification_code
):
    user, signed_in = unverified
    response = send(client, signed_in.headers)
    assert set(response.json()) == {"resendAvailableAt"}
    available_at = datetime.fromisoformat(response.json()["resendAvailableAt"])
    created_at = read_verification_code(user.id).created_at
    assert available_at.tzinfo is not None
    assert abs(available_at - (created_at + timedelta(seconds=60))) < timedelta(
        seconds=1
    )


def test_send_codes_are_six_digits_and_keep_leading_zeros(
    client, database, unverified, sent_emails, edit_verification_code
):
    user, signed_in = unverified
    for attempt in range(200):
        assert send(client, signed_in.headers).status_code == 202
        edit_verification_code(user.id, created_at=seconds_ago(120))
    codes = [code for _, code in sent_emails]
    assert len(codes) == 200
    assert all(re.fullmatch(r"[0-9]{6}", code) for code in codes)
    assert any(code.startswith("0") for code in codes)


def test_send_replaces_the_previous_code(
    client, database, unverified, sent_emails, edit_verification_code
):
    from app.models import EmailVerificationCode

    user, signed_in = unverified
    send(client, signed_in.headers)
    edit_verification_code(user.id, created_at=seconds_ago(120), failed_attempts=3)
    response = send(client, signed_in.headers)
    assert response.status_code == 202
    assert len(sent_emails) == 2
    old, new = sent_emails[0][1], sent_emails[1][1]
    with Session(database) as db:
        rows = db.query(EmailVerificationCode).all()
        assert len(rows) == 1
        assert rows[0].code_hash == sha256(new)
        assert rows[0].failed_attempts == 0
    if old != new:
        assert_error(
            confirm(client, old, signed_in.headers),
            422,
            "VERIFICATION_CODE_INVALID",
            "code",
        )


def test_send_after_the_code_expired_gives_a_fresh_valid_code(
    client, unverified, sent_emails, edit_verification_code
):
    user, signed_in = unverified
    send(client, signed_in.headers)
    edit_verification_code(
        user.id, created_at=seconds_ago(700), expires_at=seconds_ago(100)
    )
    assert send(client, signed_in.headers).status_code == 202
    assert confirm(client, sent_emails[1][1], signed_in.headers).status_code == 200


def test_send_within_sixty_seconds_is_rejected_and_changes_nothing(
    client, unverified, sent_emails, read_verification_code, edit_verification_code
):
    user, signed_in = unverified
    send(client, signed_in.headers)
    edit_verification_code(user.id, created_at=seconds_ago(50), failed_attempts=2)
    before = read_verification_code(user.id)
    response = send(client, signed_in.headers)
    assert_error(response, 429, "VERIFICATION_CODE_TOO_SOON", None)
    retry_after = int(response.headers["Retry-After"])
    assert 1 <= retry_after <= 60
    assert retry_after <= 11
    assert len(sent_emails) == 1
    after = read_verification_code(user.id)
    assert after.code_hash == before.code_hash
    assert after.created_at == before.created_at
    assert after.expires_at == before.expires_at
    assert after.failed_attempts == 2


def test_retry_after_is_a_whole_number_of_seconds(client, unverified, sent_emails):
    _, signed_in = unverified
    send(client, signed_in.headers)
    response = send(client, signed_in.headers)
    assert response.status_code == 429
    assert re.fullmatch(r"[0-9]+", response.headers["Retry-After"])
    assert 1 <= int(response.headers["Retry-After"]) <= 60


def test_send_is_allowed_again_after_sixty_seconds(
    client, unverified, sent_emails, edit_verification_code
):
    user, signed_in = unverified
    send(client, signed_in.headers)
    edit_verification_code(user.id, created_at=seconds_ago(61))
    assert send(client, signed_in.headers).status_code == 202
    assert len(sent_emails) == 2


def test_the_registration_code_counts_as_the_last_code(client, registered, sent_emails):
    response = send(client, registered["headers"])
    assert_error(response, 429, "VERIFICATION_CODE_TOO_SOON", None)
    assert "Retry-After" in response.headers
    assert len(sent_emails) == 1


def test_send_after_registration_works_once_the_wait_has_passed(
    client, registered, sent_emails, edit_verification_code
):
    edit_verification_code(registered["user_id"], created_at=seconds_ago(61))
    assert send(client, registered["headers"]).status_code == 202
    assert len(sent_emails) == 2
    assert confirm(client, sent_emails[1][1], registered["headers"]).status_code == 200


def test_the_wait_applies_per_user(client, make_user, sign_in, unverified, sent_emails):
    _, first = unverified
    second = sign_in(make_user(email="budi@example.com", email_verified=False))
    assert send(client, first.headers).status_code == 202
    assert send(client, second.headers).status_code == 202
    assert [to for to, _ in sent_emails] == ["rina@example.com", "budi@example.com"]


def test_send_for_a_verified_account_is_rejected(
    client, make_user, sign_in, sent_emails, read_verification_code
):
    user = make_user(email_verified=True)
    response = send(client, sign_in(user).headers)
    assert_error(response, 409, "EMAIL_ALREADY_VERIFIED", None)
    assert sent_emails == []
    assert read_verification_code(user.id) is None


def test_send_without_a_token_is_rejected(client, database, sent_emails):
    assert_error(send(client), 401, "ACCESS_TOKEN_INVALID", None)
    assert sent_emails == []


def test_send_with_an_invalid_token_is_rejected(client, database, sent_emails):
    response = send(client, {"Authorization": "Bearer garbage"})
    assert_error(response, 401, "ACCESS_TOKEN_INVALID", None)


def test_send_after_logout_is_rejected(client, unverified, sent_emails):
    _, signed_in = unverified
    client.post("/auth/logout", headers=signed_in.headers)
    assert_error(send(client, signed_in.headers), 401, "ACCESS_TOKEN_INVALID", None)


# POST /auth/email-verification/confirmation


def test_confirm_with_the_right_code_verifies_the_email(
    client, registered, read_verification_code
):
    response = confirm(client, registered["code"], registered["headers"])
    assert response.status_code == 200
    assert response.json() == {
        "id": registered["user_id"],
        "name": "Rina Owner",
        "email": "rina@example.com",
        "role": "owner",
        "emailVerified": True,
        "hasPassword": True,
        "googleEmail": None,
    }


def test_confirm_persists_the_verified_flag_and_deletes_the_code(
    client, database, registered, read_verification_code
):
    from app.models import UserAccount

    confirm(client, registered["code"], registered["headers"])
    assert read_verification_code(registered["user_id"]) is None
    me = client.get(ME_URL, headers=registered["headers"]).json()
    assert me["emailVerified"] is True
    with Session(database) as db:
        assert db.get(UserAccount, UUID(registered["user_id"])).email_verified


def test_confirm_works_for_a_code_with_leading_zeros(
    client, unverified, edit_verification_code, sent_emails
):
    user, signed_in = unverified
    send(client, signed_in.headers)
    edit_verification_code(user.id, code_hash=sha256("000042"))
    assert confirm(client, "000042", signed_in.headers).status_code == 200


def test_confirm_twice_is_rejected_the_second_time(client, registered):
    assert confirm(client, registered["code"], registered["headers"]).status_code == 200
    response = confirm(client, registered["code"], registered["headers"])
    assert_error(response, 409, "EMAIL_ALREADY_VERIFIED", None)


def test_confirm_for_a_verified_account_is_rejected(client, make_user, sign_in):
    signed_in = sign_in(make_user(email_verified=True))
    assert_error(
        confirm(client, "123456", signed_in.headers),
        409,
        "EMAIL_ALREADY_VERIFIED",
        None,
    )


def test_confirm_with_a_wrong_code_is_rejected_and_counts_the_attempt(
    client, registered, read_verification_code
):
    wrong = other_code(registered["code"])
    response = confirm(client, wrong, registered["headers"])
    assert_error(response, 422, "VERIFICATION_CODE_INVALID", "code")
    row = read_verification_code(registered["user_id"])
    assert row.failed_attempts == 1
    assert row.code_hash == sha256(registered["code"])


def test_each_wrong_code_adds_one_failed_attempt(
    client, registered, read_verification_code
):
    wrong = other_code(registered["code"])
    for expected in (1, 2, 3):
        confirm(client, wrong, registered["headers"])
        assert read_verification_code(registered["user_id"]).failed_attempts == expected


def test_a_wrong_code_does_not_verify_the_account(client, registered):
    confirm(client, other_code(registered["code"]), registered["headers"])
    me = client.get(ME_URL, headers=registered["headers"]).json()
    assert me["emailVerified"] is False


def test_the_right_code_still_works_after_four_wrong_attempts(client, registered):
    wrong = other_code(registered["code"])
    for _ in range(4):
        assert_error(
            confirm(client, wrong, registered["headers"]),
            422,
            "VERIFICATION_CODE_INVALID",
            "code",
        )
    assert confirm(client, registered["code"], registered["headers"]).status_code == 200


def test_five_wrong_attempts_are_each_invalid_then_the_code_is_void(client, registered):
    wrong = other_code(registered["code"])
    for _ in range(5):
        assert_error(
            confirm(client, wrong, registered["headers"]),
            422,
            "VERIFICATION_CODE_INVALID",
            "code",
        )
    assert_error(
        confirm(client, wrong, registered["headers"]),
        422,
        "VERIFICATION_CODE_EXPIRED",
        "code",
    )


def test_a_voided_code_is_rejected_even_when_correct(client, registered):
    wrong = other_code(registered["code"])
    for _ in range(5):
        confirm(client, wrong, registered["headers"])
    response = confirm(client, registered["code"], registered["headers"])
    assert_error(response, 422, "VERIFICATION_CODE_EXPIRED", "code")
    me = client.get(ME_URL, headers=registered["headers"]).json()
    assert me["emailVerified"] is False


def test_a_code_with_five_recorded_failures_is_void(
    client, registered, edit_verification_code
):
    edit_verification_code(registered["user_id"], failed_attempts=5)
    response = confirm(client, registered["code"], registered["headers"])
    assert_error(response, 422, "VERIFICATION_CODE_EXPIRED", "code")


def test_a_code_with_four_recorded_failures_still_works(
    client, registered, edit_verification_code
):
    edit_verification_code(registered["user_id"], failed_attempts=4)
    assert confirm(client, registered["code"], registered["headers"]).status_code == 200


def test_a_new_code_after_the_old_one_was_voided_resets_the_attempts(
    client, registered, sent_emails, edit_verification_code, read_verification_code
):
    wrong = other_code(registered["code"])
    for _ in range(6):
        confirm(client, wrong, registered["headers"])
    edit_verification_code(registered["user_id"], created_at=seconds_ago(61))
    assert send(client, registered["headers"]).status_code == 202
    assert read_verification_code(registered["user_id"]).failed_attempts == 0
    assert confirm(client, sent_emails[1][1], registered["headers"]).status_code == 200


def test_confirm_without_a_code_on_record_is_expired(
    client, unverified, read_verification_code
):
    user, signed_in = unverified
    response = confirm(client, "123456", signed_in.headers)
    assert_error(response, 422, "VERIFICATION_CODE_EXPIRED", "code")
    assert read_verification_code(user.id) is None


def test_confirm_after_the_expiry_time_is_rejected_even_when_correct(
    client, registered, edit_verification_code
):
    edit_verification_code(
        registered["user_id"],
        created_at=seconds_ago(11 * 60),
        expires_at=seconds_ago(60),
    )
    response = confirm(client, registered["code"], registered["headers"])
    assert_error(response, 422, "VERIFICATION_CODE_EXPIRED", "code")


def test_confirm_with_a_wrong_code_after_the_expiry_time_is_expired_not_invalid(
    client, registered, edit_verification_code
):
    edit_verification_code(registered["user_id"], expires_at=seconds_ago(60))
    response = confirm(client, other_code(registered["code"]), registered["headers"])
    assert_error(response, 422, "VERIFICATION_CODE_EXPIRED", "code")


def test_confirm_is_valid_at_nine_minutes(client, registered, edit_verification_code):
    edit_verification_code(
        registered["user_id"],
        created_at=seconds_ago(9 * 60),
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    assert confirm(client, registered["code"], registered["headers"]).status_code == 200


def test_confirm_is_expired_after_ten_minutes(
    client, registered, edit_verification_code
):
    edit_verification_code(
        registered["user_id"],
        created_at=seconds_ago(10 * 60 + 1),
        expires_at=seconds_ago(1),
    )
    response = confirm(client, registered["code"], registered["headers"])
    assert_error(response, 422, "VERIFICATION_CODE_EXPIRED", "code")


def test_the_code_of_another_user_never_works(
    client, registered, make_user, sign_in, read_verification_code, sent_emails
):
    other = make_user(email="budi@example.com", email_verified=False)
    other_in = sign_in(other)
    response = confirm(client, registered["code"], other_in.headers)
    assert_error(response, 422, "VERIFICATION_CODE_EXPIRED", "code")
    assert read_verification_code(registered["user_id"]).failed_attempts == 0
    me = client.get(ME_URL, headers=other_in.headers).json()
    assert me["emailVerified"] is False


def test_the_code_of_another_user_is_invalid_when_the_caller_has_a_code_too(
    client, registered, make_user, sign_in, edit_verification_code
):
    other = make_user(email="budi@example.com", email_verified=False)
    other_in = sign_in(other)
    assert send(client, other_in.headers).status_code == 202
    edit_verification_code(other.id, code_hash=sha256(other_code(registered["code"])))
    response = confirm(client, registered["code"], other_in.headers)
    assert_error(response, 422, "VERIFICATION_CODE_INVALID", "code")


def test_failed_attempts_of_one_user_do_not_count_against_another(
    client, registered, make_user, sign_in, sent_emails, read_verification_code
):
    other = sign_in(make_user(email="budi@example.com", email_verified=False))
    send(client, other.headers)
    wrong = other_code(sent_emails[1][1])
    for _ in range(3):
        confirm(client, wrong, other.headers)
    assert read_verification_code(registered["user_id"]).failed_attempts == 0
    assert confirm(client, registered["code"], registered["headers"]).status_code == 200


def test_confirm_without_a_token_is_rejected(client, database):
    assert_error(confirm(client, "123456"), 401, "ACCESS_TOKEN_INVALID", None)


def test_confirm_with_an_invalid_token_is_rejected(client, database):
    response = confirm(client, "123456", {"Authorization": "Bearer garbage"})
    assert_error(response, 401, "ACCESS_TOKEN_INVALID", None)


def test_confirm_with_a_malformed_code_is_a_validation_failure(
    client, registered, read_verification_code
):
    response = confirm(client, "12345", registered["headers"])
    assert_error(response, 422, "VALIDATION_FAILED", "code")
    assert read_verification_code(registered["user_id"]).failed_attempts == 0


def test_only_the_hash_of_the_code_is_stored(registered, read_verification_code):
    row = read_verification_code(registered["user_id"])
    assert row.code_hash == sha256(registered["code"])
    assert re.fullmatch(r"[0-9a-f]{64}", row.code_hash)


def test_confirm_for_an_unknown_user_token_is_rejected(client, database):
    import time

    import jwt

    from app.config import get_settings

    now = int(time.time())
    token = jwt.encode(
        {"sub": str(uuid4()), "sid": str(uuid4()), "iat": now, "exp": now + 900},
        get_settings().jwt_secret,
        "HS256",
    )
    response = confirm(client, "123456", {"Authorization": f"Bearer {token}"})
    assert_error(response, 401, "ACCESS_TOKEN_INVALID", None)
