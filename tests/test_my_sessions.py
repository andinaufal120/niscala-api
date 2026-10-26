"""Listing the caller's sessions and ending one or all of the others."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

SESSIONS_URL = "/me/sessions"
ME_URL = "/me"
LOGOUT_URL = "/auth/logout"
REFRESH_URL = "/auth/refresh"
ROLES = ["tenant", "owner", "manager", "admin"]
ITEM_FIELDS = {
    "id",
    "deviceName",
    "platform",
    "loginMethod",
    "lastActiveAt",
    "isCurrent",
}


def session_url(session_id) -> str:
    return f"{SESSIONS_URL}/{session_id}"


def days_ago(days: float) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def set_session_columns(database, session_id, **columns) -> None:
    from app.models import UserSession

    with Session(database) as db:
        row = db.get(UserSession, session_id)
        for name, value in columns.items():
            setattr(row, name, value)
        db.commit()


def used_hashes(database, session_id) -> set[str]:
    from app.models import UsedRefreshToken

    with Session(database) as db:
        return set(
            db.scalars(
                select(UsedRefreshToken.token_hash).where(
                    UsedRefreshToken.session_id == session_id
                )
            )
        )


def refresh(client, token: str):
    return client.post(REFRESH_URL, json={"refreshToken": token})


def listed(client, signed_in) -> list[dict]:
    response = client.get(SESSIONS_URL, headers=signed_in.headers)
    assert response.status_code == 200
    return response.json()["items"]


def listed_ids(client, signed_in) -> list[str]:
    return [item["id"] for item in listed(client, signed_in)]


def user_with_role(make_user, role: str, **options):
    from app.schemas.auth import UserRole

    return make_user(role=UserRole(role), **options)


def assert_access_rejected(response) -> None:
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "ACCESS_TOKEN_INVALID"
    assert body["field"] is None


def assert_refresh_rejected(response) -> None:
    assert response.status_code == 401
    assert response.json()["code"] == "REFRESH_TOKEN_INVALID"


def assert_session_not_found(response) -> None:
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "SESSION_NOT_FOUND"
    assert body["field"] is None
    assert body["message"]


def assert_email_not_verified(response) -> None:
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "EMAIL_NOT_VERIFIED"
    assert body["field"] is None


def assert_ended_tokens_rejected(client, ended) -> None:
    assert_access_rejected(client.get(ME_URL, headers=ended.headers))
    assert_refresh_rejected(refresh(client, ended.tokens.refresh_token))


# GET /me/sessions


def test_list_with_only_the_current_session_returns_one_item(
    client, make_user, sign_in
):
    signed_in = sign_in(make_user())
    response = client.get(SESSIONS_URL, headers=signed_in.headers)
    assert response.status_code == 200
    assert list(response.json()) == ["items"]
    (item,) = response.json()["items"]
    assert item["id"] == str(signed_in.session_id)
    assert item["isCurrent"] is True


def test_list_item_has_exactly_the_documented_fields(client, make_user, sign_in):
    signed_in = sign_in(make_user())
    (item,) = listed(client, signed_in)
    assert set(item) == ITEM_FIELDS


def test_list_returns_device_name_and_platform_exactly_as_stored(
    client, database, make_user, sign_in
):
    signed_in = sign_in(make_user())
    set_session_columns(
        database,
        signed_in.session_id,
        device_name="  Pixel 8 Pro (Ünï) ",
        platform="Android 14/Beta-2",
    )
    (item,) = listed(client, signed_in)
    assert item["deviceName"] == "  Pixel 8 Pro (Ünï) "
    assert item["platform"] == "Android 14/Beta-2"


def test_list_does_not_interpret_the_platform(client, make_user, sign_in):
    signed_in = sign_in(make_user(), platform="Something Unheard Of 1.0")
    (item,) = listed(client, signed_in)
    assert item["platform"] == "Something Unheard Of 1.0"


@pytest.mark.parametrize("method", ["google", "password"])
def test_list_returns_the_login_method_as_its_code_name(
    client, make_user, sign_in, method
):
    from app.schemas.sessions import LoginMethod

    signed_in = sign_in(make_user(), login_method=LoginMethod(method))
    (item,) = listed(client, signed_in)
    assert item["loginMethod"] == method


def test_list_returns_last_active_at_as_utc_iso_with_z(
    client, database, make_user, sign_in
):
    signed_in = sign_in(make_user())
    moment = (days_ago(2) - timedelta(minutes=3)).replace(second=7, microsecond=0)
    set_session_columns(database, signed_in.session_id, last_active_at=moment)
    (item,) = listed(client, signed_in)
    assert item["lastActiveAt"].endswith("Z")
    assert "+00:00" not in item["lastActiveAt"]
    assert datetime.fromisoformat(item["lastActiveAt"]) == moment


def test_list_marks_only_the_requesting_session_as_current(client, make_user, sign_in):
    user = make_user()
    phone, tablet, laptop = (
        sign_in(user, "Phone"),
        sign_in(user, "Tablet"),
        sign_in(user, "Laptop"),
    )
    for caller in (phone, tablet, laptop):
        items = listed(client, caller)
        assert len(items) == 3
        current = [item["id"] for item in items if item["isCurrent"]]
        assert current == [str(caller.session_id)]
        assert all(item["isCurrent"] in (True, False) for item in items)


def test_list_describes_each_of_the_users_sessions(client, make_user, sign_in):
    from app.schemas.sessions import LoginMethod

    user = make_user()
    phone = sign_in(user, "Phone", "Android 14", LoginMethod.GOOGLE)
    tablet = sign_in(user, "Tablet", "Android 13", LoginMethod.PASSWORD)
    by_id = {item["id"]: item for item in listed(client, phone)}
    assert set(by_id) == {str(phone.session_id), str(tablet.session_id)}
    phone_item, tablet_item = (
        by_id[str(phone.session_id)],
        by_id[str(tablet.session_id)],
    )
    assert (phone_item["deviceName"], phone_item["platform"]) == ("Phone", "Android 14")
    assert phone_item["loginMethod"] == "google"
    assert (tablet_item["deviceName"], tablet_item["platform"]) == (
        "Tablet",
        "Android 13",
    )
    assert tablet_item["loginMethod"] == "password"


def test_list_is_ordered_by_last_active_at_most_recent_first(
    client, database, make_user, sign_in
):
    user = make_user()
    oldest, middle, newest = (
        sign_in(user, "Oldest"),
        sign_in(user, "Middle"),
        sign_in(user, "Newest"),
    )
    set_session_columns(database, oldest.session_id, last_active_at=days_ago(3))
    set_session_columns(database, middle.session_id, last_active_at=days_ago(2))
    set_session_columns(database, newest.session_id, last_active_at=days_ago(1))
    expected = [str(s.session_id) for s in (newest, middle, oldest)]
    assert listed_ids(client, middle) == expected


def test_list_does_not_put_the_current_session_first_when_it_is_older(
    client, database, make_user, sign_in
):
    user = make_user()
    current, other = sign_in(user, "Current"), sign_in(user, "Other")
    set_session_columns(database, current.session_id, last_active_at=days_ago(5))
    set_session_columns(database, other.session_id, last_active_at=days_ago(1))
    assert listed_ids(client, current) == [
        str(other.session_id),
        str(current.session_id),
    ]


def test_list_orders_sessions_with_equal_activity_the_same_way_every_time(
    client, database, make_user, sign_in
):
    user = make_user()
    moment = days_ago(2)
    tied = [sign_in(user, f"Tied {n}") for n in range(4)]
    newest = sign_in(user, "Newest")
    for signed_in in tied:
        set_session_columns(database, signed_in.session_id, last_active_at=moment)
    set_session_columns(database, newest.session_id, last_active_at=days_ago(1))
    first = listed_ids(client, newest)
    assert first == listed_ids(client, newest)
    assert first == listed_ids(client, tied[0])
    assert first[0] == str(newest.session_id)
    tied_ids = first[1:]
    assert set(tied_ids) == {str(s.session_id) for s in tied}
    assert tied_ids in (sorted(tied_ids), sorted(tied_ids, reverse=True))


def test_list_reflects_a_refresh_in_last_active_at_and_order(
    client, database, make_user, sign_in
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    set_session_columns(database, phone.session_id, last_active_at=days_ago(10))
    set_session_columns(database, tablet.session_id, last_active_at=days_ago(5))
    assert listed_ids(client, tablet) == [
        str(tablet.session_id),
        str(phone.session_id),
    ]
    assert refresh(client, phone.tokens.refresh_token).status_code == 200
    items = listed(client, tablet)
    assert [item["id"] for item in items] == [
        str(phone.session_id),
        str(tablet.session_id),
    ]
    refreshed = datetime.fromisoformat(items[0]["lastActiveAt"])
    assert abs(datetime.now(UTC) - refreshed) < timedelta(minutes=1)


def test_list_omits_other_users_sessions(client, make_user, sign_in):
    mine = sign_in(make_user(), "Mine")
    sign_in(make_user(), "Theirs")
    sign_in(make_user(), "Theirs too")
    assert listed_ids(client, mine) == [str(mine.session_id)]


def test_list_omits_a_session_ended_by_logout(client, make_user, sign_in):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    assert client.post(LOGOUT_URL, headers=tablet.headers).status_code == 204
    assert listed_ids(client, phone) == [str(phone.session_id)]


def test_list_omits_a_revoked_session(client, database, make_user, sign_in):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    set_session_columns(database, tablet.session_id, revoked_at=datetime.now(UTC))
    assert listed_ids(client, phone) == [str(phone.session_id)]


def test_list_omits_a_session_idle_for_more_than_90_days(
    client, database, make_user, sign_in
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    set_session_columns(database, tablet.session_id, last_active_at=days_ago(91))
    assert listed_ids(client, phone) == [str(phone.session_id)]


def test_list_keeps_a_session_idle_for_89_days(client, database, make_user, sign_in):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    set_session_columns(database, tablet.session_id, last_active_at=days_ago(89))
    assert set(listed_ids(client, phone)) == {
        str(phone.session_id),
        str(tablet.session_id),
    }


def test_list_omits_a_session_older_than_a_year_even_when_recently_active(
    client, database, make_user, sign_in
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    set_session_columns(
        database,
        tablet.session_id,
        created_at=days_ago(366),
        last_active_at=datetime.now(UTC),
    )
    assert listed_ids(client, phone) == [str(phone.session_id)]


def test_list_keeps_a_session_created_364_days_ago(
    client, database, make_user, sign_in
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    set_session_columns(database, tablet.session_id, created_at=days_ago(364))
    assert set(listed_ids(client, phone)) == {
        str(phone.session_id),
        str(tablet.session_id),
    }


def test_list_does_not_change_any_session(
    client, database, make_user, sign_in, read_session
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    before = read_session(tablet.session_id).last_active_at
    listed(client, phone)
    row = read_session(tablet.session_id)
    assert row.last_active_at == before
    assert row.revoked_at is None


@pytest.mark.parametrize("role", ROLES)
def test_every_role_can_list_its_sessions(client, make_user, sign_in, role):
    signed_in = sign_in(user_with_role(make_user, role))
    assert listed_ids(client, signed_in) == [str(signed_in.session_id)]


def test_list_without_a_token_is_rejected(client, database):
    assert_access_rejected(client.get(SESSIONS_URL))


def test_list_with_a_malformed_token_is_rejected(client, database):
    response = client.get(SESSIONS_URL, headers={"Authorization": "Bearer garbage"})
    assert_access_rejected(response)


def test_list_with_the_token_of_an_ended_session_is_rejected(
    client, make_user, sign_in
):
    signed_in = sign_in(make_user())
    client.post(LOGOUT_URL, headers=signed_in.headers)
    assert_access_rejected(client.get(SESSIONS_URL, headers=signed_in.headers))


@pytest.mark.parametrize("role", ROLES)
def test_list_with_an_unverified_email_is_forbidden(client, make_user, sign_in, role):
    user = user_with_role(make_user, role, email_verified=False)
    assert_email_not_verified(client.get(SESSIONS_URL, headers=sign_in(user).headers))


# DELETE /me/sessions/{sessionId}


def test_ending_a_session_responds_with_an_empty_204(client, make_user, sign_in):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    response = client.delete(session_url(tablet.session_id), headers=phone.headers)
    assert response.status_code == 204
    assert response.content == b""


def test_ending_a_session_sets_its_revoked_at_to_now_in_utc(
    client, make_user, sign_in, read_session
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    assert read_session(tablet.session_id).revoked_at is None
    client.delete(session_url(tablet.session_id), headers=phone.headers)
    revoked_at = read_session(tablet.session_id).revoked_at
    assert revoked_at is not None
    assert revoked_at.utcoffset() == timedelta(0)
    assert abs(datetime.now(UTC) - revoked_at) < timedelta(minutes=1)


def test_ended_session_no_longer_appears_in_the_list(client, make_user, sign_in):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    client.delete(session_url(tablet.session_id), headers=phone.headers)
    assert listed_ids(client, phone) == [str(phone.session_id)]


def test_ended_sessions_access_token_is_rejected_at_once(client, make_user, sign_in):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    assert client.get(ME_URL, headers=tablet.headers).status_code == 200
    client.delete(session_url(tablet.session_id), headers=phone.headers)
    assert_access_rejected(client.get(ME_URL, headers=tablet.headers))
    assert_access_rejected(client.get(SESSIONS_URL, headers=tablet.headers))


def test_ended_sessions_refresh_token_is_rejected(client, make_user, sign_in):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    client.delete(session_url(tablet.session_id), headers=phone.headers)
    assert_refresh_rejected(refresh(client, tablet.tokens.refresh_token))


def test_ended_session_cannot_be_used_to_end_others(client, make_user, sign_in):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    client.delete(session_url(tablet.session_id), headers=phone.headers)
    assert_access_rejected(
        client.delete(session_url(phone.session_id), headers=tablet.headers)
    )
    assert_access_rejected(client.delete(SESSIONS_URL, headers=tablet.headers))


def test_ended_sessions_rotated_refresh_tokens_are_forgotten(
    client, database, make_user, sign_in
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    token = tablet.tokens.refresh_token
    for _ in range(2):
        token = refresh(client, token).json()["refreshToken"]
    assert len(used_hashes(database, tablet.session_id)) == 2
    client.delete(session_url(tablet.session_id), headers=phone.headers)
    assert used_hashes(database, tablet.session_id) == set()


def test_ending_a_session_keeps_the_callers_session_working(
    client, make_user, sign_in, read_session
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    client.delete(session_url(tablet.session_id), headers=phone.headers)
    assert read_session(phone.session_id).revoked_at is None
    assert client.get(ME_URL, headers=phone.headers).status_code == 200
    assert refresh(client, phone.tokens.refresh_token).status_code == 200


def test_ending_a_session_leaves_the_users_other_sessions_untouched(
    client, make_user, sign_in, read_session
):
    user = make_user()
    phone, tablet, laptop = (
        sign_in(user, "Phone"),
        sign_in(user, "Tablet"),
        sign_in(user, "Laptop"),
    )
    client.delete(session_url(tablet.session_id), headers=phone.headers)
    assert read_session(laptop.session_id).revoked_at is None
    assert client.get(ME_URL, headers=laptop.headers).status_code == 200
    assert set(listed_ids(client, phone)) == {
        str(phone.session_id),
        str(laptop.session_id),
    }


def test_ending_a_session_leaves_other_users_sessions_untouched(
    client, make_user, sign_in, read_session
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    stranger = sign_in(make_user())
    client.delete(session_url(tablet.session_id), headers=phone.headers)
    assert read_session(stranger.session_id).revoked_at is None
    assert client.get(ME_URL, headers=stranger.headers).status_code == 200


def test_ending_the_same_session_twice_answers_not_found_the_second_time(
    client, make_user, sign_in
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    url = session_url(tablet.session_id)
    assert client.delete(url, headers=phone.headers).status_code == 204
    assert_session_not_found(client.delete(url, headers=phone.headers))


def test_ending_a_session_already_ended_by_logout_answers_not_found(
    client, make_user, sign_in
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    client.post(LOGOUT_URL, headers=tablet.headers)
    assert_session_not_found(
        client.delete(session_url(tablet.session_id), headers=phone.headers)
    )


def test_ending_a_session_that_does_not_exist_answers_not_found(
    client, make_user, sign_in
):
    signed_in = sign_in(make_user())
    assert_session_not_found(
        client.delete(session_url(uuid4()), headers=signed_in.headers)
    )


def test_ending_a_session_that_is_idle_past_the_limit_answers_not_found(
    client, database, make_user, sign_in
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    set_session_columns(database, tablet.session_id, last_active_at=days_ago(91))
    assert_session_not_found(
        client.delete(session_url(tablet.session_id), headers=phone.headers)
    )


def test_ending_a_session_older_than_a_year_answers_not_found(
    client, database, make_user, sign_in
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    set_session_columns(
        database,
        tablet.session_id,
        created_at=days_ago(366),
        last_active_at=datetime.now(UTC),
    )
    assert_session_not_found(
        client.delete(session_url(tablet.session_id), headers=phone.headers)
    )


def test_ending_a_session_idle_for_89_days_succeeds(
    client, database, make_user, sign_in, read_session
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    set_session_columns(database, tablet.session_id, last_active_at=days_ago(89))
    response = client.delete(session_url(tablet.session_id), headers=phone.headers)
    assert response.status_code == 204
    assert read_session(tablet.session_id).revoked_at is not None


def test_ending_a_session_created_364_days_ago_succeeds(
    client, database, make_user, sign_in, read_session
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    set_session_columns(database, tablet.session_id, created_at=days_ago(364))
    response = client.delete(session_url(tablet.session_id), headers=phone.headers)
    assert response.status_code == 204
    assert read_session(tablet.session_id).revoked_at is not None


def test_ending_another_users_session_answers_not_found_and_leaves_it_untouched(
    client, make_user, sign_in, read_session
):
    caller = sign_in(make_user())
    stranger = sign_in(make_user())
    assert_session_not_found(
        client.delete(session_url(stranger.session_id), headers=caller.headers)
    )
    assert read_session(stranger.session_id).revoked_at is None
    assert client.get(ME_URL, headers=stranger.headers).status_code == 200
    assert refresh(client, stranger.tokens.refresh_token).status_code == 200


def test_not_found_is_identical_whatever_the_reason(
    client, database, make_user, sign_in
):
    user = make_user()
    caller = sign_in(user, "Caller")
    ended = sign_in(user, "Ended")
    idle = sign_in(user, "Idle")
    old = sign_in(user, "Old")
    stranger = sign_in(make_user())
    set_session_columns(database, ended.session_id, revoked_at=datetime.now(UTC))
    set_session_columns(database, idle.session_id, last_active_at=days_ago(91))
    set_session_columns(database, old.session_id, created_at=days_ago(366))
    ids = [uuid4(), ended.session_id, idle.session_id, old.session_id]
    ids.append(stranger.session_id)
    responses = [client.delete(session_url(i), headers=caller.headers) for i in ids]
    for response in responses:
        assert_session_not_found(response)
    assert all(response.json() == responses[0].json() for response in responses)


def test_ending_the_current_session_answers_conflict(client, make_user, sign_in):
    signed_in = sign_in(make_user())
    response = client.delete(
        session_url(signed_in.session_id), headers=signed_in.headers
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "SESSION_IS_CURRENT"
    assert body["field"] is None
    assert body["message"]


def test_ending_the_current_session_leaves_it_active(
    client, make_user, sign_in, read_session
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    client.delete(session_url(phone.session_id), headers=phone.headers)
    assert read_session(phone.session_id).revoked_at is None
    assert client.get(ME_URL, headers=phone.headers).status_code == 200
    assert refresh(client, phone.tokens.refresh_token).status_code == 200
    assert set(listed_ids(client, tablet)) == {
        str(phone.session_id),
        str(tablet.session_id),
    }


def test_ending_the_current_session_keeps_its_used_refresh_tokens(
    client, database, make_user, sign_in
):
    signed_in = sign_in(make_user())
    token = signed_in.tokens.refresh_token
    for _ in range(2):
        token = refresh(client, token).json()["refreshToken"]
    client.delete(session_url(signed_in.session_id), headers=signed_in.headers)
    assert len(used_hashes(database, signed_in.session_id)) == 2


@pytest.mark.parametrize("session_id", ["not-a-uuid", "123", "9d8c7b6a-5e4f"])
def test_ending_a_session_with_a_malformed_id_is_a_validation_failure(
    client, make_user, sign_in, session_id
):
    signed_in = sign_in(make_user())
    response = client.delete(session_url(session_id), headers=signed_in.headers)
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["field"] == "sessionId"


@pytest.mark.parametrize("role", ROLES)
def test_every_role_can_end_one_of_its_other_sessions(
    client, make_user, sign_in, read_session, role
):
    user = user_with_role(make_user, role)
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    response = client.delete(session_url(tablet.session_id), headers=phone.headers)
    assert response.status_code == 204
    assert read_session(tablet.session_id).revoked_at is not None
    assert read_session(phone.session_id).revoked_at is None


def test_ending_a_session_without_a_token_is_rejected(client, make_user, sign_in):
    tablet = sign_in(make_user())
    assert_access_rejected(client.delete(session_url(tablet.session_id)))


def test_ending_a_session_without_a_token_ends_nothing(
    client, make_user, sign_in, read_session
):
    tablet = sign_in(make_user())
    client.delete(session_url(tablet.session_id))
    assert read_session(tablet.session_id).revoked_at is None


def test_ending_a_session_with_a_malformed_token_is_rejected(
    client, make_user, sign_in
):
    tablet = sign_in(make_user())
    response = client.delete(
        session_url(tablet.session_id), headers={"Authorization": "Bearer garbage"}
    )
    assert_access_rejected(response)


@pytest.mark.parametrize("role", ROLES)
def test_ending_a_session_with_an_unverified_email_is_forbidden(
    client, make_user, sign_in, read_session, role
):
    user = user_with_role(make_user, role, email_verified=False)
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    response = client.delete(session_url(tablet.session_id), headers=phone.headers)
    assert_email_not_verified(response)
    assert read_session(tablet.session_id).revoked_at is None


# DELETE /me/sessions


def test_ending_all_other_sessions_responds_with_an_empty_204(
    client, make_user, sign_in
):
    user = make_user()
    phone = sign_in(user, "Phone")
    sign_in(user, "Tablet")
    response = client.delete(SESSIONS_URL, headers=phone.headers)
    assert response.status_code == 204
    assert response.content == b""


def test_ending_all_other_sessions_revokes_every_other_active_session(
    client, make_user, sign_in, read_session
):
    user = make_user()
    phone = sign_in(user, "Phone")
    others = [sign_in(user, f"Other {n}") for n in range(3)]
    client.delete(SESSIONS_URL, headers=phone.headers)
    for other in others:
        revoked_at = read_session(other.session_id).revoked_at
        assert revoked_at is not None
        assert revoked_at.utcoffset() == timedelta(0)
        assert abs(datetime.now(UTC) - revoked_at) < timedelta(minutes=1)


def test_ending_all_other_sessions_leaves_the_current_one_active_and_listed(
    client, make_user, sign_in, read_session
):
    user = make_user()
    phone = sign_in(user, "Phone")
    sign_in(user, "Tablet")
    sign_in(user, "Laptop")
    client.delete(SESSIONS_URL, headers=phone.headers)
    assert read_session(phone.session_id).revoked_at is None
    assert client.get(ME_URL, headers=phone.headers).status_code == 200
    items = listed(client, phone)
    assert [item["id"] for item in items] == [str(phone.session_id)]
    assert items[0]["isCurrent"] is True


def test_ending_all_other_sessions_stops_their_tokens_at_once(
    client, make_user, sign_in
):
    user = make_user()
    phone = sign_in(user, "Phone")
    others = [sign_in(user, "Tablet"), sign_in(user, "Laptop")]
    for other in others:
        assert client.get(ME_URL, headers=other.headers).status_code == 200
    client.delete(SESSIONS_URL, headers=phone.headers)
    for other in others:
        assert_ended_tokens_rejected(client, other)
    assert refresh(client, phone.tokens.refresh_token).status_code == 200


def test_ending_all_other_sessions_leaves_other_users_sessions_untouched(
    client, make_user, sign_in, read_session
):
    user = make_user()
    phone = sign_in(user, "Phone")
    sign_in(user, "Tablet")
    stranger = sign_in(make_user())
    client.delete(SESSIONS_URL, headers=phone.headers)
    assert read_session(stranger.session_id).revoked_at is None
    assert client.get(ME_URL, headers=stranger.headers).status_code == 200
    assert listed_ids(client, stranger) == [str(stranger.session_id)]


def test_ending_all_other_sessions_with_none_to_end_is_still_204(
    client, make_user, sign_in, read_session
):
    signed_in = sign_in(make_user())
    response = client.delete(SESSIONS_URL, headers=signed_in.headers)
    assert response.status_code == 204
    assert response.content == b""
    assert read_session(signed_in.session_id).revoked_at is None


def test_ending_all_other_sessions_twice_is_204_both_times(client, make_user, sign_in):
    user = make_user()
    phone = sign_in(user, "Phone")
    sign_in(user, "Tablet")
    assert client.delete(SESSIONS_URL, headers=phone.headers).status_code == 204
    assert client.delete(SESSIONS_URL, headers=phone.headers).status_code == 204
    assert listed_ids(client, phone) == [str(phone.session_id)]


def test_ending_all_other_sessions_with_only_expired_ones_is_204(
    client, database, make_user, sign_in
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    set_session_columns(database, tablet.session_id, last_active_at=days_ago(91))
    assert client.delete(SESSIONS_URL, headers=phone.headers).status_code == 204
    assert listed_ids(client, phone) == [str(phone.session_id)]


def test_ending_all_other_sessions_keeps_the_revocation_time_of_ended_ones(
    client, database, make_user, sign_in, read_session
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    sign_in(user, "Laptop")
    earlier = datetime.now(UTC) - timedelta(days=2)
    set_session_columns(database, tablet.session_id, revoked_at=earlier)
    client.delete(SESSIONS_URL, headers=phone.headers)
    assert read_session(tablet.session_id).revoked_at == earlier


def test_ending_all_other_sessions_ends_sessions_idle_for_89_days(
    client, database, make_user, sign_in, read_session
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    set_session_columns(database, tablet.session_id, last_active_at=days_ago(89))
    client.delete(SESSIONS_URL, headers=phone.headers)
    assert read_session(tablet.session_id).revoked_at is not None


def test_ending_all_other_sessions_forgets_their_used_refresh_tokens_only(
    client, database, make_user, sign_in
):
    user = make_user()
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    for signed_in in (phone, tablet):
        token = signed_in.tokens.refresh_token
        for _ in range(2):
            token = refresh(client, token).json()["refreshToken"]
    client.delete(SESSIONS_URL, headers=phone.headers)
    assert used_hashes(database, tablet.session_id) == set()
    assert len(used_hashes(database, phone.session_id)) == 2


def test_ending_all_other_sessions_leaves_other_users_used_refresh_tokens(
    client, database, make_user, sign_in
):
    user = make_user()
    phone = sign_in(user, "Phone")
    sign_in(user, "Tablet")
    stranger = sign_in(make_user())
    token = stranger.tokens.refresh_token
    token = refresh(client, token).json()["refreshToken"]
    client.delete(SESSIONS_URL, headers=phone.headers)
    expected = {hashlib.sha256(stranger.tokens.refresh_token.encode()).hexdigest()}
    assert used_hashes(database, stranger.session_id) == expected
    assert refresh(client, token).status_code == 200


@pytest.mark.parametrize("role", ROLES)
def test_every_role_can_end_all_its_other_sessions(
    client, make_user, sign_in, read_session, role
):
    user = user_with_role(make_user, role)
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    assert client.delete(SESSIONS_URL, headers=phone.headers).status_code == 204
    assert read_session(tablet.session_id).revoked_at is not None
    assert read_session(phone.session_id).revoked_at is None


def test_ending_all_other_sessions_without_a_token_is_rejected(
    client, make_user, sign_in, read_session
):
    tablet = sign_in(make_user())
    assert_access_rejected(client.delete(SESSIONS_URL))
    assert read_session(tablet.session_id).revoked_at is None


def test_ending_all_other_sessions_with_a_malformed_token_is_rejected(client, database):
    response = client.delete(SESSIONS_URL, headers={"Authorization": "Bearer garbage"})
    assert_access_rejected(response)


@pytest.mark.parametrize("role", ROLES)
def test_ending_all_other_sessions_with_an_unverified_email_is_forbidden(
    client, make_user, sign_in, read_session, role
):
    user = user_with_role(make_user, role, email_verified=False)
    phone, tablet = sign_in(user, "Phone"), sign_in(user, "Tablet")
    assert_email_not_verified(client.delete(SESSIONS_URL, headers=phone.headers))
    assert read_session(tablet.session_id).revoked_at is None
