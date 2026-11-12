"""Errors the API really answers are among the errors its document declares."""

from uuid import uuid4

import pytest
from rent_bill_support import GIF_BYTES

BANK = {
    "bankName": "BCA",
    "accountNumber": "1234567890",
    "accountHolderName": "Budi Santoso",
}
PROPERTY_BODY = {"name": "Kos Melati", "address": "Jl. Melati 5", "bankAccount": BANK}
ROOM_BODY = {"number": "A1", "baseRate": 1500000, "facilities": []}
DEVICE = {"name": "Pixel 8", "platform": "Android 14"}


def declared_codes(app, method: str, template: str) -> list[str]:
    document = app.openapi()
    return document["paths"][template][method.lower()]["x-error-codes"]


def assert_declared(app, response, method: str, template: str, code: str, status: int):
    """The response is the expected error and the operation declares it."""
    from app.error_catalog import ERROR_STATUS

    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert set(body) == {"code", "field", "message"}
    declared = declared_codes(app, method, template)
    assert code in declared
    assert ERROR_STATUS[code] == status
    operation = app.openapi()["paths"][template][method.lower()]
    assert str(status) in operation["responses"]


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


@pytest.fixture
def owner_in(owner, sign_in):
    return sign_in(owner)


def test_a_missing_token_answers_a_declared_authentication_error(app, client, database):
    response = client.get("/properties")
    assert_declared(app, response, "GET", "/properties", "ACCESS_TOKEN_INVALID", 401)


def test_a_tenant_on_a_management_endpoint_answers_a_declared_forbidden(
    app, client, scene
):
    response = client.get("/properties", headers=scene.tenant_in.headers)
    assert_declared(app, response, "GET", "/properties", "FORBIDDEN", 403)


def test_an_unreadable_json_body_answers_a_declared_validation_failure(
    app, client, owner_in
):
    response = client.post(
        "/properties",
        content=b"{not json",
        headers={**owner_in.headers, "Content-Type": "application/json"},
    )
    assert_declared(app, response, "POST", "/properties", "VALIDATION_FAILED", 422)


def test_an_unknown_rent_bill_answers_a_declared_not_found(app, client, scene):
    response = client.get(f"/rent-bills/{uuid4()}", headers=scene.tenant_in.headers)
    assert_declared(
        app, response, "GET", "/rent-bills/{rentBillId}", "RENT_BILL_NOT_FOUND", 404
    )


def test_an_unknown_room_answers_a_declared_not_found(app, client, owner_in):
    response = client.get(f"/rooms/{uuid4()}", headers=owner_in.headers)
    assert_declared(app, response, "GET", "/rooms/{roomId}", "ROOM_NOT_FOUND", 404)


def test_an_unknown_tenant_answers_a_declared_not_found(app, client, owner_in):
    response = client.get(f"/tenants/{uuid4()}", headers=owner_in.headers)
    assert_declared(
        app, response, "GET", "/tenants/{tenantId}", "TENANT_NOT_FOUND", 404
    )


def test_an_unknown_manager_answers_a_declared_not_found(app, client, owner_in):
    response = client.get(f"/managers/{uuid4()}", headers=owner_in.headers)
    assert_declared(
        app, response, "GET", "/managers/{managerId}", "MANAGER_NOT_FOUND", 404
    )


def test_an_unknown_property_answers_a_declared_not_found(app, client, owner_in):
    response = client.get(f"/properties/{uuid4()}", headers=owner_in.headers)
    assert_declared(
        app, response, "GET", "/properties/{propertyId}", "PROPERTY_NOT_FOUND", 404
    )


def test_an_unknown_complaint_answers_a_declared_not_found(app, client, owner_in):
    response = client.get(f"/complaints/{uuid4()}", headers=owner_in.headers)
    assert_declared(
        app, response, "GET", "/complaints/{complaintId}", "COMPLAINT_NOT_FOUND", 404
    )


def test_a_receipt_of_the_wrong_type_answers_a_declared_field_error(
    app, client, scene, make_rent_bill
):
    bill = make_rent_bill(scene.tenant.lease)
    response = client.put(
        f"/rent-bills/{bill.id}/receipt",
        files={"file": ("receipt.gif", GIF_BYTES, "image/gif")},
        headers=scene.tenant_in.headers,
    )
    assert_declared(
        app,
        response,
        "PUT",
        "/rent-bills/{rentBillId}/receipt",
        "RECEIPT_TYPE_INVALID",
        422,
    )


def test_a_wrong_password_answers_a_declared_invalid_credentials(
    app, client, make_user
):
    from app.services.passwords import hash_password

    make_user(email="rina@example.com", password_hash=hash_password("right password"))
    response = client.post(
        "/auth/login",
        json={"email": "rina@example.com", "password": "wrong", "device": DEVICE},
    )
    assert_declared(app, response, "POST", "/auth/login", "INVALID_CREDENTIALS", 401)


def test_a_taken_property_name_answers_a_declared_conflict(
    app, client, owner, owner_in, make_property
):
    make_property(owner, name="Kos Melati")
    response = client.post("/properties", json=PROPERTY_BODY, headers=owner_in.headers)
    assert_declared(app, response, "POST", "/properties", "PROPERTY_NAME_TAKEN", 409)


def test_a_taken_room_number_answers_a_declared_conflict(
    app, client, owner, owner_in, make_property, make_room
):
    prop = make_property(owner)
    make_room(prop, number="A1")
    response = client.post(
        f"/properties/{prop.id}/rooms", json=ROOM_BODY, headers=owner_in.headers
    )
    assert_declared(
        app,
        response,
        "POST",
        "/properties/{propertyId}/rooms",
        "ROOM_NUMBER_TAKEN",
        409,
    )


def test_editing_a_view_only_property_answers_a_declared_read_only_error(
    app, client, owner, owner_in, make_property
):
    prop = make_property(owner, view_only=True)
    response = client.put(
        f"/properties/{prop.id}", json=PROPERTY_BODY, headers=owner_in.headers
    )
    assert_declared(
        app, response, "PUT", "/properties/{propertyId}", "PROPERTY_READ_ONLY", 403
    )


def test_a_second_verification_code_too_soon_answers_a_declared_rate_limit(
    app, client, make_user, sign_in, sent_emails
):
    session = sign_in(make_user(email_verified=False))
    first = client.post("/auth/email-verification", headers=session.headers)
    assert first.status_code == 202
    response = client.post("/auth/email-verification", headers=session.headers)
    assert_declared(
        app,
        response,
        "POST",
        "/auth/email-verification",
        "VERIFICATION_CODE_TOO_SOON",
        429,
    )
    assert "Retry-After" in response.headers


def test_a_status_change_to_the_same_status_answers_a_declared_field_error(
    app, client, scene, make_rent_bill
):
    bill = make_rent_bill(scene.tenant.lease)
    response = client.post(
        f"/rent-bills/{bill.id}/status-changes",
        json={"status": "unpaid", "reason": "No change."},
        headers=scene.owner_in.headers,
    )
    assert_declared(
        app,
        response,
        "POST",
        "/rent-bills/{rentBillId}/status-changes",
        "STATUS_UNCHANGED",
        422,
    )


def test_ending_the_current_session_answers_a_declared_conflict(app, client, owner_in):
    response = client.delete(
        f"/me/sessions/{owner_in.session_id}", headers=owner_in.headers
    )
    assert_declared(
        app,
        response,
        "DELETE",
        "/me/sessions/{sessionId}",
        "SESSION_IS_CURRENT",
        409,
    )


def test_a_malformed_path_id_answers_a_declared_validation_failure(
    app, client, owner_in
):
    response = client.get("/rooms/not-a-uuid", headers=owner_in.headers)
    assert_declared(app, response, "GET", "/rooms/{roomId}", "VALIDATION_FAILED", 422)
