"""The dependency that lets only callers who re-authenticated recently through."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

ROUTE = "/sensitive"


def build_client() -> TestClient:
    from app.access import require_recent_reauthentication
    from app.errors import register_error_handlers
    from app.security import CurrentUser

    private = FastAPI()
    register_error_handlers(private)

    @private.get(ROUTE)
    def sensitive(
        current: Annotated[CurrentUser, Depends(require_recent_reauthentication)],
    ):
        return {
            "userId": str(current.user.id),
            "sessionId": str(current.session.id),
        }

    return TestClient(private)


def set_reauthenticated_at(database, session_id, value) -> None:
    from app.models import UserSession

    with Session(database) as db:
        db.get(UserSession, session_id).reauthenticated_at = value
        db.commit()


def ago(**kwargs) -> datetime:
    return datetime.now(UTC) - timedelta(**kwargs)


def assert_reauthentication_required(response) -> None:
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "REAUTHENTICATION_REQUIRED"
    assert body["field"] is None
    assert body["message"]


def test_a_session_that_never_re_authenticated_is_refused(database, make_user, sign_in):
    signed_in = sign_in(make_user())
    assert_reauthentication_required(
        build_client().get(ROUTE, headers=signed_in.headers)
    )


def test_a_just_re_authenticated_session_passes_and_the_caller_is_returned(
    database, make_user, sign_in
):
    user = make_user()
    signed_in = sign_in(user)
    set_reauthenticated_at(database, signed_in.session_id, datetime.now(UTC))
    response = build_client().get(ROUTE, headers=signed_in.headers)
    assert response.status_code == 200
    assert response.json() == {
        "userId": str(user.id),
        "sessionId": str(signed_in.session_id),
    }


def test_a_session_re_authenticated_four_minutes_59_seconds_ago_passes(
    database, make_user, sign_in
):
    signed_in = sign_in(make_user())
    set_reauthenticated_at(database, signed_in.session_id, ago(minutes=4, seconds=59))
    response = build_client().get(ROUTE, headers=signed_in.headers)
    assert response.status_code == 200


def test_a_session_re_authenticated_exactly_five_minutes_ago_is_refused(
    database, make_user, sign_in
):
    signed_in = sign_in(make_user())
    set_reauthenticated_at(database, signed_in.session_id, ago(minutes=5))
    assert_reauthentication_required(
        build_client().get(ROUTE, headers=signed_in.headers)
    )


def test_a_session_re_authenticated_five_minutes_1_second_ago_is_refused(
    database, make_user, sign_in
):
    signed_in = sign_in(make_user())
    set_reauthenticated_at(database, signed_in.session_id, ago(minutes=5, seconds=1))
    assert_reauthentication_required(
        build_client().get(ROUTE, headers=signed_in.headers)
    )


def test_a_session_re_authenticated_long_ago_is_refused(database, make_user, sign_in):
    signed_in = sign_in(make_user())
    set_reauthenticated_at(database, signed_in.session_id, ago(days=2))
    assert_reauthentication_required(
        build_client().get(ROUTE, headers=signed_in.headers)
    )


def test_re_authentication_of_another_session_of_the_user_does_not_count(
    database, make_user, sign_in
):
    user = make_user()
    first = sign_in(user)
    second = sign_in(user, device_name="Galaxy")
    set_reauthenticated_at(database, first.session_id, datetime.now(UTC))
    client = build_client()
    assert client.get(ROUTE, headers=first.headers).status_code == 200
    assert_reauthentication_required(client.get(ROUTE, headers=second.headers))


def test_error_body_has_exactly_code_field_and_message(database, make_user, sign_in):
    signed_in = sign_in(make_user())
    response = build_client().get(ROUTE, headers=signed_in.headers)
    assert set(response.json()) == {"code", "field", "message"}


def test_the_window_lapses_after_five_minutes(database, make_user, sign_in):
    signed_in = sign_in(make_user())
    client = build_client()
    set_reauthenticated_at(database, signed_in.session_id, ago(minutes=4, seconds=59))
    assert client.get(ROUTE, headers=signed_in.headers).status_code == 200
    set_reauthenticated_at(database, signed_in.session_id, ago(minutes=5, seconds=1))
    assert_reauthentication_required(client.get(ROUTE, headers=signed_in.headers))


@pytest.mark.parametrize("role", ["owner", "manager", "tenant", "admin"])
def test_the_dependency_works_for_every_role(database, make_user, sign_in, role):
    from app.schemas.auth import UserRole

    signed_in = sign_in(make_user(role=UserRole(role)))
    set_reauthenticated_at(database, signed_in.session_id, datetime.now(UTC))
    assert build_client().get(ROUTE, headers=signed_in.headers).status_code == 200


def test_missing_token_is_rejected_as_an_invalid_access_token(database):
    response = build_client().get(ROUTE)
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "ACCESS_TOKEN_INVALID"
    assert body["field"] is None


def test_invalid_token_is_rejected_as_an_invalid_access_token(database):
    response = build_client().get(ROUTE, headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 401
    assert response.json()["code"] == "ACCESS_TOKEN_INVALID"


def test_token_of_a_revoked_session_is_rejected_as_invalid(
    database, make_user, sign_in, client
):
    signed_in = sign_in(make_user())
    set_reauthenticated_at(database, signed_in.session_id, datetime.now(UTC))
    client.post("/auth/logout", headers=signed_in.headers)
    response = build_client().get(ROUTE, headers=signed_in.headers)
    assert response.status_code == 401
    assert response.json()["code"] == "ACCESS_TOKEN_INVALID"


def test_unverified_email_is_reported_before_reauthentication(
    database, make_user, sign_in
):
    signed_in = sign_in(make_user(email_verified=False))
    response = build_client().get(ROUTE, headers=signed_in.headers)
    assert response.status_code == 403
    assert response.json()["code"] == "EMAIL_NOT_VERIFIED"


def test_unverified_email_is_refused_even_with_a_fresh_reauthentication(
    database, make_user, sign_in
):
    signed_in = sign_in(make_user(email_verified=False))
    set_reauthenticated_at(database, signed_in.session_id, datetime.now(UTC))
    response = build_client().get(ROUTE, headers=signed_in.headers)
    assert response.status_code == 403
    assert response.json()["code"] == "EMAIL_NOT_VERIFIED"
