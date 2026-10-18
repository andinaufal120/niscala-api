"""The dependency that lets only verified callers with an allowed role through."""

from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

ROUTES = {
    "tenant": "/tenant-only",
    "owner": "/owner-only",
    "manager": "/manager-only",
    "admin": "/admin-only",
    "owner-manager": "/owner-or-manager",
}


def build_client() -> TestClient:
    from app.access import require_roles
    from app.errors import register_error_handlers
    from app.schemas.auth import UserRole
    from app.security import CurrentUser

    private = FastAPI()
    register_error_handlers(private)

    def reply(current: CurrentUser) -> dict[str, str]:
        return {
            "userId": str(current.user.id),
            "sessionId": str(current.session.id),
        }

    @private.get(ROUTES["tenant"])
    def tenant_only(
        current: Annotated[CurrentUser, Depends(require_roles(UserRole.TENANT))],
    ):
        return reply(current)

    @private.get(ROUTES["owner"])
    def owner_only(
        current: Annotated[CurrentUser, Depends(require_roles(UserRole.OWNER))],
    ):
        return reply(current)

    @private.get(ROUTES["manager"])
    def manager_only(
        current: Annotated[CurrentUser, Depends(require_roles(UserRole.MANAGER))],
    ):
        return reply(current)

    @private.get(ROUTES["admin"])
    def admin_only(
        current: Annotated[CurrentUser, Depends(require_roles(UserRole.ADMIN))],
    ):
        return reply(current)

    @private.get(ROUTES["owner-manager"])
    def owner_or_manager(
        current: Annotated[
            CurrentUser,
            Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
        ],
    ):
        return reply(current)

    return TestClient(private)


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


ALL_ROLES = ["tenant", "owner", "manager", "admin"]


@pytest.mark.parametrize("name", ALL_ROLES)
def test_single_role_route_admits_exactly_its_role(database, make_user, sign_in, name):
    user = make_user(role=role(name))
    signed_in = sign_in(user)
    response = build_client().get(ROUTES[name], headers=signed_in.headers)
    assert response.status_code == 200
    assert response.json() == {
        "userId": str(user.id),
        "sessionId": str(signed_in.session_id),
    }


@pytest.mark.parametrize(
    ("route", "caller"),
    [(route, caller) for route in ALL_ROLES for caller in ALL_ROLES if route != caller],
)
def test_single_role_route_rejects_every_other_role(
    database, make_user, sign_in, route, caller
):
    signed_in = sign_in(make_user(role=role(caller)))
    response = build_client().get(ROUTES[route], headers=signed_in.headers)
    assert response.status_code == 403
    assert response.json() == {
        "code": "FORBIDDEN",
        "field": None,
        "message": response.json()["message"],
    }
    assert response.json()["message"]


@pytest.mark.parametrize("name", ["owner", "manager"])
def test_multi_role_route_admits_each_listed_role(database, make_user, sign_in, name):
    signed_in = sign_in(make_user(role=role(name)))
    response = build_client().get(ROUTES["owner-manager"], headers=signed_in.headers)
    assert response.status_code == 200


@pytest.mark.parametrize("name", ["tenant", "admin"])
def test_multi_role_route_rejects_unlisted_roles(database, make_user, sign_in, name):
    signed_in = sign_in(make_user(role=role(name)))
    response = build_client().get(ROUTES["owner-manager"], headers=signed_in.headers)
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_error_body_has_exactly_code_field_and_message(database, make_user, sign_in):
    signed_in = sign_in(make_user(role=role("tenant")))
    response = build_client().get(ROUTES["owner"], headers=signed_in.headers)
    assert set(response.json()) == {"code", "field", "message"}


@pytest.mark.parametrize("name", ALL_ROLES)
def test_unverified_user_of_the_allowed_role_gets_email_not_verified(
    database, make_user, sign_in, name
):
    signed_in = sign_in(make_user(role=role(name), email_verified=False))
    response = build_client().get(ROUTES[name], headers=signed_in.headers)
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "EMAIL_NOT_VERIFIED"
    assert body["field"] is None
    assert body["message"]


def test_unverified_user_of_a_disallowed_role_gets_email_not_verified(
    database, make_user, sign_in
):
    signed_in = sign_in(make_user(role=role("tenant"), email_verified=False))
    response = build_client().get(ROUTES["owner"], headers=signed_in.headers)
    assert response.status_code == 403
    assert response.json()["code"] == "EMAIL_NOT_VERIFIED"


def test_missing_token_is_rejected_as_an_invalid_access_token(database):
    response = build_client().get(ROUTES["owner"])
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "ACCESS_TOKEN_INVALID"
    assert body["field"] is None


def test_invalid_token_is_rejected_as_an_invalid_access_token(database):
    response = build_client().get(
        ROUTES["owner"], headers={"Authorization": "Bearer garbage"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "ACCESS_TOKEN_INVALID"


def test_token_of_a_revoked_session_is_rejected_as_invalid(
    database, make_user, sign_in, client
):
    signed_in = sign_in(make_user(role=role("owner")))
    client.post("/auth/logout", headers=signed_in.headers)
    response = build_client().get(ROUTES["owner"], headers=signed_in.headers)
    assert response.status_code == 401
    assert response.json()["code"] == "ACCESS_TOKEN_INVALID"


def test_invalid_token_is_rejected_before_the_role_check(database):
    response = build_client().get(
        ROUTES["admin"], headers={"Authorization": "Bearer garbage"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "ACCESS_TOKEN_INVALID"


def test_dependency_returns_the_caller_of_the_current_session(
    database, make_user, sign_in
):
    user = make_user(role=role("manager"))
    first = sign_in(user)
    second = sign_in(user, device_name="Galaxy")
    client = build_client()
    one = client.get(ROUTES["manager"], headers=first.headers).json()
    two = client.get(ROUTES["manager"], headers=second.headers).json()
    assert one["userId"] == two["userId"] == str(user.id)
    assert one["sessionId"] == str(first.session_id)
    assert two["sessionId"] == str(second.session_id)


def test_user_passes_once_the_email_becomes_verified(database, make_user, sign_in):
    from sqlalchemy.orm import Session

    from app.models import UserAccount

    user = make_user(role=role("owner"), email_verified=False)
    signed_in = sign_in(user)
    client = build_client()
    assert client.get(ROUTES["owner"], headers=signed_in.headers).status_code == 403
    with Session(database) as db:
        db.get(UserAccount, user.id).email_verified = True
        db.commit()
    assert client.get(ROUTES["owner"], headers=signed_in.headers).status_code == 200
