"""The dependency that lets only callers with a verified email through."""

from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


def build_client() -> TestClient:
    from app.errors import register_error_handlers
    from app.security import CurrentUser, get_verified_user

    private = FastAPI()
    register_error_handlers(private)

    @private.get("/verified-only")
    def verified_only(current: Annotated[CurrentUser, Depends(get_verified_user)]):
        return {"userId": str(current.user.id), "sessionId": str(current.session.id)}

    return TestClient(private)


def test_verified_user_passes(database, make_user, sign_in):
    user = make_user(email_verified=True)
    signed_in = sign_in(user)
    response = build_client().get("/verified-only", headers=signed_in.headers)
    assert response.status_code == 200
    assert response.json() == {
        "userId": str(user.id),
        "sessionId": str(signed_in.session_id),
    }


def test_unverified_user_is_forbidden(database, make_user, sign_in):
    signed_in = sign_in(make_user(email_verified=False))
    response = build_client().get("/verified-only", headers=signed_in.headers)
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "EMAIL_NOT_VERIFIED"
    assert body["field"] is None
    assert body["message"]


def test_missing_token_is_rejected_as_an_invalid_access_token(database):
    response = build_client().get("/verified-only")
    assert response.status_code == 401
    assert response.json()["code"] == "ACCESS_TOKEN_INVALID"


def test_invalid_token_is_rejected_before_the_verification_check(database):
    response = build_client().get(
        "/verified-only", headers={"Authorization": "Bearer garbage"}
    )
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "ACCESS_TOKEN_INVALID"
    assert body["field"] is None


def test_token_of_a_revoked_session_of_an_unverified_user_is_rejected_as_invalid(
    database, make_user, sign_in, client
):
    signed_in = sign_in(make_user(email_verified=False))
    client.post("/auth/logout", headers=signed_in.headers)
    response = build_client().get("/verified-only", headers=signed_in.headers)
    assert response.status_code == 401
    assert response.json()["code"] == "ACCESS_TOKEN_INVALID"


def test_user_passes_once_the_email_becomes_verified(database, make_user, sign_in):
    from sqlalchemy.orm import Session

    from app.models import UserAccount

    user = make_user(email_verified=False)
    signed_in = sign_in(user)
    client = build_client()
    assert client.get("/verified-only", headers=signed_in.headers).status_code == 403
    with Session(database) as db:
        db.get(UserAccount, user.id).email_verified = True
        db.commit()
    assert client.get("/verified-only", headers=signed_in.headers).status_code == 200
