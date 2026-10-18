"""The dependency that turns a bearer access token into the caller and session."""

import time
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def secret() -> str:
    from app.config import get_settings

    return get_settings().jwt_secret


def build_client() -> TestClient:
    from app.errors import register_error_handlers
    from app.security import CurrentUser, get_current_user

    private = FastAPI()
    register_error_handlers(private)

    @private.get("/whoami")
    def whoami(current: Annotated[CurrentUser, Depends(get_current_user)]):
        return {"userId": str(current.user.id), "sessionId": str(current.session.id)}

    return TestClient(private)


def claims_for(signed_in, user, **overrides) -> dict:
    now = int(time.time())
    claims = {
        "sub": str(user.id),
        "sid": str(signed_in.session_id),
        "iat": now,
        "exp": now + 900,
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_rejected(response) -> None:
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "ACCESS_TOKEN_INVALID"
    assert body["field"] is None
    assert body["message"]


def revoke(database, session_id) -> None:
    from app.models import UserSession

    with Session(database) as db:
        db.get(UserSession, session_id).revoked_at = datetime.now(UTC)
        db.commit()


def test_valid_token_yields_the_user_and_session(database, make_user, sign_in):
    user = make_user()
    signed_in = sign_in(user)
    response = build_client().get("/whoami", headers=signed_in.headers)
    assert response.status_code == 200
    assert response.json() == {
        "userId": str(user.id),
        "sessionId": str(signed_in.session_id),
    }


def test_current_user_is_a_frozen_dataclass():
    import dataclasses

    from app.security import CurrentUser

    assert dataclasses.is_dataclass(CurrentUser)
    assert CurrentUser.__dataclass_params__.frozen


def test_each_session_resolves_to_its_own_session_id(database, make_user, sign_in):
    user = make_user()
    first, second = sign_in(user, "Phone"), sign_in(user, "Tablet")
    client = build_client()
    assert client.get("/whoami", headers=first.headers).json()["sessionId"] == str(
        first.session_id
    )
    assert client.get("/whoami", headers=second.headers).json()["sessionId"] == str(
        second.session_id
    )


def test_missing_authorization_header_is_rejected(database):
    assert_rejected(build_client().get("/whoami"))


@pytest.mark.parametrize(
    "header",
    ["Basic dXNlcjpwYXNz", "Token abc", "abc", "Bearer"],
)
def test_non_bearer_authorization_header_is_rejected(database, header):
    response = build_client().get("/whoami", headers={"Authorization": header})
    assert_rejected(response)


def test_valid_access_token_under_another_scheme_is_rejected(
    database, make_user, sign_in
):
    signed_in = sign_in(make_user())
    token = signed_in.tokens.access_token
    response = build_client().get(
        "/whoami", headers={"Authorization": f"Basic {token}"}
    )
    assert_rejected(response)


@pytest.mark.parametrize("token", ["garbage", "a.b.c", "not.a.jwt.token", "x" * 200])
def test_token_that_is_not_a_jwt_is_rejected(database, token):
    assert_rejected(build_client().get("/whoami", headers=bearer(token)))


def test_refresh_token_is_not_accepted_as_an_access_token(database, make_user, sign_in):
    signed_in = sign_in(make_user())
    response = build_client().get(
        "/whoami", headers=bearer(signed_in.tokens.refresh_token)
    )
    assert_rejected(response)


def test_token_signed_with_another_secret_is_rejected(database, make_user, sign_in):
    user = make_user()
    signed_in = sign_in(user)
    token = jwt.encode(
        claims_for(signed_in, user), "another-secret-0123456789abcdef0123", "HS256"
    )
    assert_rejected(build_client().get("/whoami", headers=bearer(token)))


def test_token_with_a_tampered_payload_is_rejected(database, make_user, sign_in):
    user = make_user()
    other = make_user()
    signed_in = sign_in(user)
    header, _, signature = signed_in.tokens.access_token.split(".")
    forged_payload = jwt.encode(
        claims_for(signed_in, other), "irrelevant-secret-0123456789abcdef", "HS256"
    ).split(".")[1]
    token = f"{header}.{forged_payload}.{signature}"
    assert_rejected(build_client().get("/whoami", headers=bearer(token)))


def test_token_signed_with_another_algorithm_is_rejected(database, make_user, sign_in):
    user = make_user()
    signed_in = sign_in(user)
    token = jwt.encode(claims_for(signed_in, user), secret(), "HS512")
    assert_rejected(build_client().get("/whoami", headers=bearer(token)))


def test_unsigned_token_with_alg_none_is_rejected(database, make_user, sign_in):
    user = make_user()
    signed_in = sign_in(user)
    token = jwt.encode(claims_for(signed_in, user), None, algorithm="none")
    assert_rejected(build_client().get("/whoami", headers=bearer(token)))


def test_expired_token_is_rejected(database, make_user, sign_in):
    user = make_user()
    signed_in = sign_in(user)
    now = int(time.time())
    token = jwt.encode(
        claims_for(signed_in, user, iat=now - 1000, exp=now - 100), secret(), "HS256"
    )
    assert_rejected(build_client().get("/whoami", headers=bearer(token)))


def test_token_without_expiry_is_rejected(database, make_user, sign_in):
    user = make_user()
    signed_in = sign_in(user)
    claims = claims_for(signed_in, user)
    del claims["exp"]
    token = jwt.encode(claims, secret(), "HS256")
    assert_rejected(build_client().get("/whoami", headers=bearer(token)))


def test_token_without_subject_is_rejected(database, make_user, sign_in):
    user = make_user()
    signed_in = sign_in(user)
    token = jwt.encode(claims_for(signed_in, user, sub=None), secret(), "HS256")
    assert_rejected(build_client().get("/whoami", headers=bearer(token)))


def test_token_without_session_id_is_rejected(database, make_user, sign_in):
    user = make_user()
    signed_in = sign_in(user)
    token = jwt.encode(claims_for(signed_in, user, sid=None), secret(), "HS256")
    assert_rejected(build_client().get("/whoami", headers=bearer(token)))


@pytest.mark.parametrize("value", ["not-a-uuid", "", 42, ["x"]])
def test_token_with_an_invalid_subject_is_rejected(database, make_user, sign_in, value):
    user = make_user()
    signed_in = sign_in(user)
    token = jwt.encode(claims_for(signed_in, user, sub=value), secret(), "HS256")
    assert_rejected(build_client().get("/whoami", headers=bearer(token)))


@pytest.mark.parametrize("value", ["not-a-uuid", "", 42, ["x"]])
def test_token_with_an_invalid_session_id_is_rejected(
    database, make_user, sign_in, value
):
    user = make_user()
    signed_in = sign_in(user)
    token = jwt.encode(claims_for(signed_in, user, sid=value), secret(), "HS256")
    assert_rejected(build_client().get("/whoami", headers=bearer(token)))


def test_token_for_an_unknown_session_is_rejected(database, make_user, sign_in):
    user = make_user()
    signed_in = sign_in(user)
    token = jwt.encode(claims_for(signed_in, user, sid=str(uuid4())), secret(), "HS256")
    assert_rejected(build_client().get("/whoami", headers=bearer(token)))


def test_token_for_an_unknown_user_is_rejected(database, make_user, sign_in):
    user = make_user()
    signed_in = sign_in(user)
    token = jwt.encode(claims_for(signed_in, user, sub=str(uuid4())), secret(), "HS256")
    assert_rejected(build_client().get("/whoami", headers=bearer(token)))


def test_token_of_a_revoked_session_is_rejected_at_once(database, make_user, sign_in):
    user = make_user()
    signed_in = sign_in(user)
    client = build_client()
    assert client.get("/whoami", headers=signed_in.headers).status_code == 200
    revoke(database, signed_in.session_id)
    assert_rejected(client.get("/whoami", headers=signed_in.headers))


def test_revoking_one_session_leaves_the_users_other_sessions_working(
    database, make_user, sign_in
):
    user = make_user()
    first, second = sign_in(user, "Phone"), sign_in(user, "Tablet")
    revoke(database, first.session_id)
    client = build_client()
    assert_rejected(client.get("/whoami", headers=first.headers))
    assert client.get("/whoami", headers=second.headers).status_code == 200
