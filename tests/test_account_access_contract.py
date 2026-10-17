"""Contract tests for sign-up, login, tokens, email verification, password reset,
invitation activation and acceptance, and the caller's own account endpoints."""

from typing import Any

import pytest
from conftest import OpenApiDoc, nullable_inner

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "options", "head", "trace"}

ACCOUNT_ACCESS_PATHS = {
    "/auth/register": {"post"},
    "/auth/register/google": {"post"},
    "/auth/login": {"post"},
    "/auth/login/google": {"post"},
    "/auth/refresh": {"post"},
    "/auth/logout": {"post"},
    "/auth/email-verification": {"post"},
    "/auth/email-verification/confirmation": {"post"},
    "/auth/password-reset-requests": {"post"},
    "/auth/password-reset-previews": {"post"},
    "/auth/password-resets": {"post"},
    "/invitations/previews": {"post"},
    "/invitations/activations/password": {"post"},
    "/invitations/activations/google": {"post"},
    "/invitations/acceptance-previews": {"post"},
    "/invitations/acceptances": {"post"},
    "/me": {"get"},
    "/me/local-password": {"post"},
    "/me/google-link": {"post"},
}

# (method, path, operationId, tag, success status)
ACCOUNT_ACCESS_OPERATIONS = [
    ("post", "/auth/register", "register_owner", "auth", 201),
    ("post", "/auth/register/google", "register_owner_with_google", "auth", 201),
    ("post", "/auth/login", "login", "auth", 200),
    ("post", "/auth/login/google", "login_with_google", "auth", 200),
    ("post", "/auth/refresh", "refresh_tokens", "auth", 200),
    ("post", "/auth/logout", "logout", "auth", 204),
    (
        "post",
        "/auth/email-verification",
        "send_email_verification",
        "auth",
        202,
    ),
    (
        "post",
        "/auth/email-verification/confirmation",
        "confirm_email",
        "auth",
        200,
    ),
    (
        "post",
        "/auth/password-reset-requests",
        "request_password_reset",
        "auth",
        202,
    ),
    (
        "post",
        "/auth/password-reset-previews",
        "preview_password_reset",
        "auth",
        200,
    ),
    ("post", "/auth/password-resets", "reset_password", "auth", 204),
    ("post", "/invitations/previews", "preview_invitation", "invitations", 200),
    (
        "post",
        "/invitations/activations/password",
        "activate_invitation_with_password",
        "invitations",
        201,
    ),
    (
        "post",
        "/invitations/activations/google",
        "activate_invitation_with_google",
        "invitations",
        201,
    ),
    (
        "post",
        "/invitations/acceptance-previews",
        "preview_invitation_acceptance",
        "invitations",
        200,
    ),
    ("post", "/invitations/acceptances", "accept_invitation", "invitations", 204),
    ("get", "/me", "get_my_account", "account", 200),
    ("post", "/me/local-password", "add_local_password", "account", 200),
    ("post", "/me/google-link", "link_google", "account", 200),
]

# Operations that need no session.
PUBLIC_OPERATIONS = [
    ("post", "/auth/register"),
    ("post", "/auth/register/google"),
    ("post", "/auth/login"),
    ("post", "/auth/login/google"),
    ("post", "/auth/refresh"),
    ("post", "/auth/password-reset-requests"),
    ("post", "/auth/password-reset-previews"),
    ("post", "/auth/password-resets"),
    ("post", "/invitations/previews"),
    ("post", "/invitations/activations/password"),
    ("post", "/invitations/activations/google"),
]

# (method, path, request body schema)
REQUEST_BODIES = [
    ("post", "/auth/register", "RegisterOwnerInput"),
    ("post", "/auth/register/google", "GoogleAuthInput"),
    ("post", "/auth/login", "LoginInput"),
    ("post", "/auth/login/google", "GoogleAuthInput"),
    ("post", "/auth/refresh", "RefreshInput"),
    ("post", "/auth/email-verification/confirmation", "EmailConfirmationInput"),
    ("post", "/auth/password-reset-requests", "PasswordResetRequestInput"),
    ("post", "/auth/password-reset-previews", "TokenInput"),
    ("post", "/auth/password-resets", "PasswordResetInput"),
    ("post", "/invitations/previews", "TokenInput"),
    (
        "post",
        "/invitations/activations/password",
        "InvitationPasswordActivationInput",
    ),
    (
        "post",
        "/invitations/activations/google",
        "InvitationGoogleActivationInput",
    ),
    ("post", "/invitations/acceptance-previews", "TokenInput"),
    ("post", "/invitations/acceptances", "TokenInput"),
    ("post", "/me/local-password", "AddLocalPasswordInput"),
    ("post", "/me/google-link", "LinkGoogleInput"),
]

NO_REQUEST_BODY_OPERATIONS = [
    ("post", "/auth/logout"),
    ("post", "/auth/email-verification"),
    ("get", "/me"),
]

# (method, path, status, response body schema)
RESPONSE_BODIES = [
    ("post", "/auth/register", 201, "AuthSession"),
    ("post", "/auth/register/google", 201, "AuthSession"),
    ("post", "/auth/login", 200, "AuthSession"),
    ("post", "/auth/login/google", 200, "AuthSession"),
    ("post", "/auth/refresh", 200, "AuthTokens"),
    ("post", "/auth/email-verification", 202, "EmailVerificationSent"),
    ("post", "/auth/email-verification/confirmation", 200, "Account"),
    ("post", "/auth/password-reset-previews", 200, "PasswordResetPreview"),
    ("post", "/invitations/previews", 200, "InvitationPreview"),
    ("post", "/invitations/activations/password", 201, "AuthSession"),
    ("post", "/invitations/activations/google", 201, "AuthSession"),
    (
        "post",
        "/invitations/acceptance-previews",
        200,
        "InvitationAcceptancePreview",
    ),
    ("get", "/me", 200, "Account"),
    ("post", "/me/local-password", 200, "Account"),
    ("post", "/me/google-link", 200, "Account"),
]

# Operations that succeed without a response body.
NO_RESPONSE_BODY_OPERATIONS = [
    ("post", "/auth/logout", 204),
    ("post", "/auth/password-reset-requests", 202),
    ("post", "/auth/password-resets", 204),
    ("post", "/invitations/acceptances", 204),
]

# Component name -> (all properties, required properties).
TOKEN_FIELDS = {"accessToken", "refreshToken", "tokenType", "expiresIn"}
ACCOUNT_FIELDS = {
    "id",
    "name",
    "email",
    "role",
    "emailVerified",
    "hasPassword",
    "googleEmail",
}
INVITATION_PREVIEW_FIELDS = {
    "status",
    "role",
    "inviterName",
    "properties",
    "roomNumber",
    "expiresAt",
    "name",
    "emergencyContactsRequired",
}
COMPONENT_FIELDS: dict[str, tuple[set[str], set[str]]] = {
    "DeviceInfo": ({"name", "platform"}, {"name", "platform"}),
    "RegisterOwnerInput": (
        {"name", "email", "password", "device"},
        {"name", "email", "password", "device"},
    ),
    "LoginInput": ({"email", "password", "device"}, {"email", "password", "device"}),
    "GoogleAuthInput": ({"idToken", "device"}, {"idToken", "device"}),
    "RefreshInput": ({"refreshToken"}, {"refreshToken"}),
    "AuthTokens": (TOKEN_FIELDS, TOKEN_FIELDS),
    "Account": (ACCOUNT_FIELDS, ACCOUNT_FIELDS),
    "AuthSession": ({*TOKEN_FIELDS, "account"}, {*TOKEN_FIELDS, "account"}),
    "EmailVerificationSent": ({"resendAvailableAt"}, {"resendAvailableAt"}),
    "EmailConfirmationInput": ({"code"}, {"code"}),
    "PasswordResetRequestInput": ({"email"}, {"email"}),
    "TokenInput": ({"token"}, {"token"}),
    "PasswordResetPreview": ({"email"}, {"email"}),
    "PasswordResetInput": ({"token", "newPassword"}, {"token", "newPassword"}),
    "InvitationProperty": ({"name", "address"}, {"name", "address"}),
    "InvitationPreview": (INVITATION_PREVIEW_FIELDS, INVITATION_PREVIEW_FIELDS),
    "InvitationPasswordActivationInput": (
        {"token", "name", "email", "password", "emergencyContacts", "device"},
        {"token", "name", "password", "device"},
    ),
    "InvitationGoogleActivationInput": (
        {"token", "name", "idToken", "emergencyContacts", "device"},
        {"token", "name", "idToken", "device"},
    ),
    "ActiveLeaseSummary": (
        {"propertyName", "roomNumber", "endDate"},
        {"propertyName", "roomNumber", "endDate"},
    ),
    "InvitationAcceptancePreview": (
        {
            "invitation",
            "accountName",
            "accountEmail",
            "accountRole",
            "canAccept",
            "blocker",
            "activeLease",
        },
        {
            "invitation",
            "accountName",
            "accountEmail",
            "accountRole",
            "canAccept",
            "blocker",
            "activeLease",
        },
    ),
    "AddLocalPasswordInput": (
        {"googleIdToken", "password"},
        {"googleIdToken", "password"},
    ),
    "LinkGoogleInput": ({"idToken"}, {"idToken"}),
}

ENUM_COMPONENTS = ["UserRole", "InvitationRole", "InvitationLinkStatus"]
ACCOUNT_ACCESS_COMPONENTS = [
    *COMPONENT_FIELDS,
    "UserRole",
    "InvitationRole",
    "InvitationLinkStatus",
    "InvitationBlocker",
]

USER_ROLES = ["tenant", "owner", "manager", "admin"]
INVITATION_ROLES = ["tenant", "manager"]
INVITATION_LINK_STATUSES = ["valid", "expired", "used"]
INVITATION_BLOCKERS = ["roleMismatch", "activeLease"]

# (component, field): a new password, 8 to 128 characters.
NEW_PASSWORD_FIELDS = [
    pytest.param("RegisterOwnerInput", "password", id="register_password"),
    pytest.param("PasswordResetInput", "newPassword", id="reset_new_password"),
    pytest.param(
        "InvitationPasswordActivationInput", "password", id="activation_password"
    ),
    pytest.param("AddLocalPasswordInput", "password", id="add_local_password"),
]

# (component, field): a non-empty opaque string.
NON_EMPTY_STRING_FIELDS = [
    pytest.param("LoginInput", "password", id="login_password"),
    pytest.param("GoogleAuthInput", "idToken", id="google_auth_id_token"),
    pytest.param("RefreshInput", "refreshToken", id="refresh_token"),
    pytest.param("TokenInput", "token", id="token_input_token"),
    pytest.param("PasswordResetInput", "token", id="reset_token"),
    pytest.param(
        "InvitationPasswordActivationInput", "token", id="password_activation_token"
    ),
    pytest.param(
        "InvitationGoogleActivationInput", "token", id="google_activation_token"
    ),
    pytest.param(
        "InvitationGoogleActivationInput", "idToken", id="google_activation_id_token"
    ),
    pytest.param("AddLocalPasswordInput", "googleIdToken", id="google_id_token"),
    pytest.param("LinkGoogleInput", "idToken", id="link_google_id_token"),
]

# (component, field): a person name, 1 to 100 characters.
PERSON_NAME_FIELDS = [
    pytest.param("RegisterOwnerInput", "name", id="register_name"),
    pytest.param("InvitationPasswordActivationInput", "name", id="password_activation"),
    pytest.param("InvitationGoogleActivationInput", "name", id="google_activation"),
]

# (component, field): a required email address.
REQUIRED_EMAIL_FIELDS = [
    pytest.param("RegisterOwnerInput", "email", id="register"),
    pytest.param("LoginInput", "email", id="login"),
    pytest.param("Account", "email", id="account"),
    pytest.param("PasswordResetRequestInput", "email", id="reset_request"),
    pytest.param("PasswordResetPreview", "email", id="reset_preview"),
    pytest.param("InvitationAcceptancePreview", "accountEmail", id="account_email"),
]

# (component, field): an array of emergency contacts, 2 to 4, optional.
EMERGENCY_CONTACT_COMPONENTS = [
    "InvitationPasswordActivationInput",
    "InvitationGoogleActivationInput",
]

VALID_DEVICE = {"name": "Pixel 8", "platform": "Android 14"}
VALID_CONTACT = {"name": "Siti", "relationship": "Mother", "phone": "081234567890"}
VALID_CONTACTS = [
    {**VALID_CONTACT, "name": "Siti"},
    {**VALID_CONTACT, "name": "Budi", "relationship": "Father"},
]
VALID_PASSWORD = "correct horse battery"
VALID_TOKEN = "opaque-token-value"
VALID_ID_TOKEN = "google-id-token-value"
VALID_EMAIL = "owner@example.com"

VALID_REGISTER_INPUT = {
    "name": "Rina Owner",
    "email": VALID_EMAIL,
    "password": VALID_PASSWORD,
    "device": VALID_DEVICE,
}
VALID_LOGIN_INPUT = {
    "email": VALID_EMAIL,
    "password": VALID_PASSWORD,
    "device": VALID_DEVICE,
}
VALID_GOOGLE_AUTH_INPUT = {"idToken": VALID_ID_TOKEN, "device": VALID_DEVICE}
VALID_REFRESH_INPUT = {"refreshToken": VALID_TOKEN}
VALID_CONFIRMATION_INPUT = {"code": "123456"}
VALID_RESET_REQUEST_INPUT = {"email": VALID_EMAIL}
VALID_TOKEN_INPUT = {"token": VALID_TOKEN}
VALID_PASSWORD_RESET_INPUT = {"token": VALID_TOKEN, "newPassword": VALID_PASSWORD}
VALID_PASSWORD_ACTIVATION_INPUT = {
    "token": VALID_TOKEN,
    "name": "Dewi Tenant",
    "password": VALID_PASSWORD,
    "device": VALID_DEVICE,
}
VALID_GOOGLE_ACTIVATION_INPUT = {
    "token": VALID_TOKEN,
    "name": "Dewi Tenant",
    "idToken": VALID_ID_TOKEN,
    "device": VALID_DEVICE,
}
VALID_ADD_LOCAL_PASSWORD_INPUT = {
    "googleIdToken": VALID_ID_TOKEN,
    "password": VALID_PASSWORD,
}
VALID_LINK_GOOGLE_INPUT = {"idToken": VALID_ID_TOKEN}

REGISTER_URL = "/auth/register"
REGISTER_GOOGLE_URL = "/auth/register/google"
LOGIN_URL = "/auth/login"
LOGIN_GOOGLE_URL = "/auth/login/google"
REFRESH_URL = "/auth/refresh"
LOGOUT_URL = "/auth/logout"
EMAIL_VERIFICATION_URL = "/auth/email-verification"
EMAIL_CONFIRMATION_URL = "/auth/email-verification/confirmation"
PASSWORD_RESET_REQUESTS_URL = "/auth/password-reset-requests"
PASSWORD_RESET_PREVIEWS_URL = "/auth/password-reset-previews"
PASSWORD_RESETS_URL = "/auth/password-resets"
INVITATION_PREVIEWS_URL = "/invitations/previews"
PASSWORD_ACTIVATION_URL = "/invitations/activations/password"
GOOGLE_ACTIVATION_URL = "/invitations/activations/google"
ACCEPTANCE_PREVIEWS_URL = "/invitations/acceptance-previews"
ACCEPTANCES_URL = "/invitations/acceptances"
ME_URL = "/me"
LOCAL_PASSWORD_URL = "/me/local-password"
GOOGLE_LINK_URL = "/me/google-link"

# (url, valid body) for every operation that takes a JSON body.
JSON_BODY_ENDPOINTS = [
    pytest.param(REGISTER_URL, VALID_REGISTER_INPUT, id="register"),
    pytest.param(REGISTER_GOOGLE_URL, VALID_GOOGLE_AUTH_INPUT, id="register_google"),
    pytest.param(LOGIN_URL, VALID_LOGIN_INPUT, id="login"),
    pytest.param(LOGIN_GOOGLE_URL, VALID_GOOGLE_AUTH_INPUT, id="login_google"),
    pytest.param(REFRESH_URL, VALID_REFRESH_INPUT, id="refresh"),
    pytest.param(EMAIL_CONFIRMATION_URL, VALID_CONFIRMATION_INPUT, id="confirm_email"),
    pytest.param(
        PASSWORD_RESET_REQUESTS_URL, VALID_RESET_REQUEST_INPUT, id="reset_request"
    ),
    pytest.param(PASSWORD_RESET_PREVIEWS_URL, VALID_TOKEN_INPUT, id="reset_preview"),
    pytest.param(PASSWORD_RESETS_URL, VALID_PASSWORD_RESET_INPUT, id="reset"),
    pytest.param(INVITATION_PREVIEWS_URL, VALID_TOKEN_INPUT, id="invitation_preview"),
    pytest.param(
        PASSWORD_ACTIVATION_URL,
        VALID_PASSWORD_ACTIVATION_INPUT,
        id="password_activation",
    ),
    pytest.param(
        GOOGLE_ACTIVATION_URL, VALID_GOOGLE_ACTIVATION_INPUT, id="google_activation"
    ),
    pytest.param(ACCEPTANCE_PREVIEWS_URL, VALID_TOKEN_INPUT, id="acceptance_preview"),
    pytest.param(ACCEPTANCES_URL, VALID_TOKEN_INPUT, id="acceptance"),
    pytest.param(
        LOCAL_PASSWORD_URL, VALID_ADD_LOCAL_PASSWORD_INPUT, id="local_password"
    ),
    pytest.param(GOOGLE_LINK_URL, VALID_LINK_GOOGLE_INPUT, id="google_link"),
]


def _without(body: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k not in keys}


def _property_names(schema: dict[str, Any]) -> set[str]:
    return set(schema.get("properties", {}))


def _assert_uuid_string(schema: dict[str, Any]) -> None:
    assert schema["type"] == "string"
    assert schema["format"] == "uuid"


def _assert_email_string(schema: dict[str, Any]) -> None:
    assert schema["type"] == "string"
    assert schema["format"] == "email"


def _assert_string_enum(schema: dict[str, Any], values: list[str]) -> None:
    assert schema["type"] == "string"
    assert sorted(schema["enum"]) == sorted(values)
    assert len(schema["enum"]) == len(values)


def _field(openapi: OpenApiDoc, component: str, field: str) -> dict[str, Any]:
    return openapi.component(component)["properties"][field]


# Paths, operations, tags and status codes


@pytest.mark.parametrize(("path", "methods"), ACCOUNT_ACCESS_PATHS.items())
def test_account_access_path_declares_exactly_its_methods(
    openapi: OpenApiDoc, path: str, methods: set[str]
) -> None:
    declared = {m for m in openapi.document["paths"].get(path, {}) if m in HTTP_METHODS}
    assert declared == methods


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "tag", "status"), ACCOUNT_ACCESS_OPERATIONS
)
def test_account_access_operation_has_operation_id(
    openapi: OpenApiDoc,
    method: str,
    path: str,
    operation_id: str,
    tag: str,
    status: int,
) -> None:
    assert openapi.operation(method, path)["operationId"] == operation_id


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "tag", "status"), ACCOUNT_ACCESS_OPERATIONS
)
def test_account_access_operation_has_its_tag(
    openapi: OpenApiDoc,
    method: str,
    path: str,
    operation_id: str,
    tag: str,
    status: int,
) -> None:
    assert openapi.operation(method, path)["tags"] == [tag]


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "tag", "status"), ACCOUNT_ACCESS_OPERATIONS
)
def test_account_access_operation_declares_only_its_success_status_besides_validation_error(
    openapi: OpenApiDoc,
    method: str,
    path: str,
    operation_id: str,
    tag: str,
    status: int,
) -> None:
    responses = set(openapi.operation(method, path)["responses"])
    assert responses - {"422"} == {str(status)}


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "tag", "status"), ACCOUNT_ACCESS_OPERATIONS
)
def test_account_access_operation_declares_no_parameters(
    openapi: OpenApiDoc,
    method: str,
    path: str,
    operation_id: str,
    tag: str,
    status: int,
) -> None:
    assert openapi.operation(method, path).get("parameters", []) == []


# Security


def test_bearer_auth_security_scheme_is_http_bearer_jwt(openapi: OpenApiDoc) -> None:
    schemes = openapi.document["components"]["securitySchemes"]
    assert "bearerAuth" in schemes
    scheme = schemes["bearerAuth"]
    assert scheme["type"] == "http"
    assert scheme["scheme"] == "bearer"
    assert scheme["bearerFormat"] == "JWT"


def _all_operations(openapi: OpenApiDoc) -> list[tuple[str, str]]:
    return [
        (method, path)
        for path, item in openapi.document["paths"].items()
        for method in item
        if method in HTTP_METHODS
    ]


def test_every_operation_except_the_public_ones_requires_bearer_auth(
    openapi: OpenApiDoc,
) -> None:
    public = set(PUBLIC_OPERATIONS)
    missing = [
        (method, path)
        for method, path in _all_operations(openapi)
        if (method, path) not in public
        and openapi.operation(method, path).get("security") != [{"bearerAuth": []}]
    ]
    assert missing == []


def test_public_operations_declare_no_security_requirement(
    openapi: OpenApiDoc,
) -> None:
    secured = [
        (method, path)
        for method, path in PUBLIC_OPERATIONS
        if openapi.operation(method, path).get("security")
    ]
    assert secured == []


def test_public_operations_are_exactly_the_account_access_entry_points(
    openapi: OpenApiDoc,
) -> None:
    unsecured = {
        (method, path)
        for method, path in _all_operations(openapi)
        if not openapi.operation(method, path).get("security")
    }
    assert unsecured == set(PUBLIC_OPERATIONS)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        pytest.param("get", "/properties", id="list_properties"),
        pytest.param("get", "/complaints", id="list_complaints"),
        pytest.param("get", "/complaint-categories", id="list_complaint_categories"),
        pytest.param("get", "/me/lease", id="get_current_lease"),
        pytest.param("post", "/auth/logout", id="logout"),
        pytest.param("get", "/me", id="get_my_account"),
        pytest.param("post", "/invitations/acceptances", id="accept_invitation"),
    ],
)
def test_session_operation_requires_bearer_auth(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert openapi.operation(method, path)["security"] == [{"bearerAuth": []}]


# Request and response schema references


@pytest.mark.parametrize(
    ("method", "path", "schema"),
    REQUEST_BODIES,
    ids=[f"{m}_{p}" for m, p, _ in REQUEST_BODIES],
)
def test_account_access_operation_request_body_schema(
    openapi: OpenApiDoc, method: str, path: str, schema: str
) -> None:
    assert openapi.request_schema_ref(method, path) == schema


@pytest.mark.parametrize(("method", "path"), NO_REQUEST_BODY_OPERATIONS)
def test_account_access_operation_takes_no_request_body(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert "requestBody" not in openapi.operation(method, path)


@pytest.mark.parametrize(
    ("method", "path", "status", "schema"),
    RESPONSE_BODIES,
    ids=[f"{m}_{p}" for m, p, _, _ in RESPONSE_BODIES],
)
def test_account_access_operation_response_schema(
    openapi: OpenApiDoc, method: str, path: str, status: int, schema: str
) -> None:
    assert openapi.response_schema_ref(method, path, status) == schema


@pytest.mark.parametrize(("method", "path", "status"), NO_RESPONSE_BODY_OPERATIONS)
def test_account_access_operation_succeeds_without_a_response_body(
    openapi: OpenApiDoc, method: str, path: str, status: int
) -> None:
    response = openapi.operation(method, path)["responses"][str(status)]
    assert "content" not in response


# Component schemas


@pytest.mark.parametrize("name", ACCOUNT_ACCESS_COMPONENTS)
def test_account_access_component_schema_is_declared(
    openapi: OpenApiDoc, name: str
) -> None:
    assert name in openapi.components


@pytest.mark.parametrize("name", ACCOUNT_ACCESS_COMPONENTS)
@pytest.mark.parametrize("suffix", ["-Input", "-Output"])
def test_account_access_component_schema_is_not_split_into_input_and_output_variants(
    openapi: OpenApiDoc, name: str, suffix: str
) -> None:
    assert f"{name}{suffix}" not in openapi.components


@pytest.mark.parametrize("name", ACCOUNT_ACCESS_COMPONENTS)
def test_account_access_component_property_names_contain_no_underscore(
    openapi: OpenApiDoc, name: str
) -> None:
    offenders = [p for p in _property_names(openapi.component(name)) if "_" in p]
    assert offenders == []


@pytest.mark.parametrize("name", ["DevicePlatform"])
def test_enum_not_defined_by_account_access_is_absent(
    openapi: OpenApiDoc, name: str
) -> None:
    assert name not in openapi.components


@pytest.mark.parametrize(("name", "fields"), COMPONENT_FIELDS.items())
def test_component_has_exactly_its_fields(
    openapi: OpenApiDoc, name: str, fields: tuple[set[str], set[str]]
) -> None:
    assert _property_names(openapi.component(name)) == fields[0]


@pytest.mark.parametrize(("name", "fields"), COMPONENT_FIELDS.items())
def test_component_requires_exactly_its_required_fields(
    openapi: OpenApiDoc, name: str, fields: tuple[set[str], set[str]]
) -> None:
    assert set(openapi.component(name).get("required", [])) == fields[1]


# Enums


def test_user_role_is_string_enum_of_the_four_roles(openapi: OpenApiDoc) -> None:
    _assert_string_enum(openapi.component("UserRole"), USER_ROLES)


def test_invitation_role_is_string_enum_of_tenant_and_manager(
    openapi: OpenApiDoc,
) -> None:
    _assert_string_enum(openapi.component("InvitationRole"), INVITATION_ROLES)


def test_invitation_link_status_is_string_enum_of_its_states(
    openapi: OpenApiDoc,
) -> None:
    _assert_string_enum(
        openapi.component("InvitationLinkStatus"), INVITATION_LINK_STATUSES
    )


def test_invitation_blocker_is_string_enum_of_its_reasons(openapi: OpenApiDoc) -> None:
    _assert_string_enum(openapi.component("InvitationBlocker"), INVITATION_BLOCKERS)


# Shared field shapes


@pytest.mark.parametrize(("component", "field"), NEW_PASSWORD_FIELDS)
def test_new_password_is_string_of_8_to_128_characters(
    openapi: OpenApiDoc, component: str, field: str
) -> None:
    schema = _field(openapi, component, field)
    assert schema["type"] == "string"
    assert schema["minLength"] == 8
    assert schema["maxLength"] == 128


@pytest.mark.parametrize(("component", "field"), NON_EMPTY_STRING_FIELDS)
def test_opaque_string_field_is_non_empty_string(
    openapi: OpenApiDoc, component: str, field: str
) -> None:
    schema = _field(openapi, component, field)
    assert schema["type"] == "string"
    assert schema["minLength"] == 1


def test_login_password_has_no_minimum_beyond_non_empty(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "LoginInput", "password")
    assert schema["minLength"] == 1


@pytest.mark.parametrize(("component", "field"), PERSON_NAME_FIELDS)
def test_person_name_is_string_of_1_to_100_characters(
    openapi: OpenApiDoc, component: str, field: str
) -> None:
    schema = _field(openapi, component, field)
    assert schema["type"] == "string"
    assert schema["minLength"] == 1
    assert schema["maxLength"] == 100


@pytest.mark.parametrize(("component", "field"), REQUIRED_EMAIL_FIELDS)
def test_required_email_field_is_email_string(
    openapi: OpenApiDoc, component: str, field: str
) -> None:
    _assert_email_string(_field(openapi, component, field))


@pytest.mark.parametrize("component", ["RegisterOwnerInput", "LoginInput"])
def test_device_field_is_device_info(openapi: OpenApiDoc, component: str) -> None:
    assert openapi.ref_name(_field(openapi, component, "device")) == "DeviceInfo"


@pytest.mark.parametrize(
    "component",
    [
        "GoogleAuthInput",
        "InvitationPasswordActivationInput",
        "InvitationGoogleActivationInput",
    ],
)
def test_device_field_of_other_inputs_is_device_info(
    openapi: OpenApiDoc, component: str
) -> None:
    assert openapi.ref_name(_field(openapi, component, "device")) == "DeviceInfo"


# DeviceInfo


def test_device_info_name_is_string_of_1_to_100_characters(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "DeviceInfo", "name")
    assert schema["type"] == "string"
    assert schema["minLength"] == 1
    assert schema["maxLength"] == 100


def test_device_info_platform_is_free_text_of_1_to_50_characters(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "DeviceInfo", "platform")
    assert schema["type"] == "string"
    assert "enum" not in schema
    assert "$ref" not in schema
    assert schema["minLength"] == 1
    assert schema["maxLength"] == 50


# AuthTokens and AuthSession


def test_auth_tokens_access_and_refresh_tokens_are_strings(
    openapi: OpenApiDoc,
) -> None:
    assert _field(openapi, "AuthTokens", "accessToken")["type"] == "string"
    assert _field(openapi, "AuthTokens", "refreshToken")["type"] == "string"


def test_auth_tokens_token_type_is_always_bearer(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "AuthTokens", "tokenType")
    assert schema.get("const") == "bearer" or schema.get("enum") == ["bearer"]


def test_auth_tokens_expires_in_is_integer_of_at_most_900_seconds(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "AuthTokens", "expiresIn")
    assert schema["type"] == "integer"
    assert schema["maximum"] == 900


def test_auth_session_carries_the_token_fields_with_the_same_shapes(
    openapi: OpenApiDoc,
) -> None:
    for field in TOKEN_FIELDS:
        assert _field(openapi, "AuthSession", field) == _field(
            openapi, "AuthTokens", field
        )


def test_auth_session_account_is_account(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "AuthSession", "account")
    assert openapi.ref_name(schema) == "Account"


# Account


def test_account_id_is_uuid_string(openapi: OpenApiDoc) -> None:
    _assert_uuid_string(_field(openapi, "Account", "id"))


def test_account_name_is_string(openapi: OpenApiDoc) -> None:
    assert _field(openapi, "Account", "name")["type"] == "string"


def test_account_role_is_user_role(openapi: OpenApiDoc) -> None:
    assert openapi.ref_name(_field(openapi, "Account", "role")) == "UserRole"


@pytest.mark.parametrize("field", ["emailVerified", "hasPassword"])
def test_account_flag_is_boolean(openapi: OpenApiDoc, field: str) -> None:
    assert _field(openapi, "Account", field)["type"] == "boolean"


def test_account_google_email_is_nullable_string(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "Account", "googleEmail")
    assert nullable_inner(schema)["type"] == "string"


# EmailVerificationSent and EmailConfirmationInput


def test_email_verification_sent_resend_available_at_is_date_time_string(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "EmailVerificationSent", "resendAvailableAt")
    assert schema["type"] == "string"
    assert schema["format"] == "date-time"


def test_email_confirmation_code_is_six_digit_string(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "EmailConfirmationInput", "code")
    assert schema["type"] == "string"
    assert schema["pattern"] == r"^\d{6}$"


# InvitationProperty and InvitationPreview


@pytest.mark.parametrize("field", ["name", "address"])
def test_invitation_property_field_is_string(openapi: OpenApiDoc, field: str) -> None:
    assert _field(openapi, "InvitationProperty", field)["type"] == "string"


def test_invitation_preview_has_no_email(openapi: OpenApiDoc) -> None:
    assert "email" not in _property_names(openapi.component("InvitationPreview"))


def test_invitation_preview_status_is_invitation_link_status(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "InvitationPreview", "status")
    assert openapi.ref_name(schema) == "InvitationLinkStatus"


def test_invitation_preview_role_is_invitation_role(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "InvitationPreview", "role")
    assert openapi.ref_name(schema) == "InvitationRole"


@pytest.mark.parametrize("field", ["inviterName", "name"])
def test_invitation_preview_text_field_is_string(
    openapi: OpenApiDoc, field: str
) -> None:
    assert _field(openapi, "InvitationPreview", field)["type"] == "string"


def test_invitation_preview_properties_is_array_of_invitation_property(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "InvitationPreview", "properties")
    assert schema["type"] == "array"
    assert openapi.ref_name(schema["items"]) == "InvitationProperty"


def test_invitation_preview_room_number_is_nullable_string(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "InvitationPreview", "roomNumber")
    assert nullable_inner(schema)["type"] == "string"


def test_invitation_preview_expires_at_is_date_time_string(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "InvitationPreview", "expiresAt")
    assert schema["type"] == "string"
    assert schema["format"] == "date-time"


def test_invitation_preview_emergency_contacts_required_is_boolean(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "InvitationPreview", "emergencyContactsRequired")
    assert schema["type"] == "boolean"


# Invitation activation inputs


def test_password_activation_email_is_optional_nullable_email_string(
    openapi: OpenApiDoc,
) -> None:
    component = openapi.component("InvitationPasswordActivationInput")
    _assert_email_string(nullable_inner(component["properties"]["email"]))
    assert "email" not in component["required"]


def test_google_activation_input_takes_no_email(openapi: OpenApiDoc) -> None:
    assert "email" not in _property_names(
        openapi.component("InvitationGoogleActivationInput")
    )


@pytest.mark.parametrize("component", EMERGENCY_CONTACT_COMPONENTS)
def test_activation_emergency_contacts_is_optional_nullable_array_of_contacts(
    openapi: OpenApiDoc, component: str
) -> None:
    schema = openapi.component(component)
    inner = nullable_inner(schema["properties"]["emergencyContacts"])
    assert inner["type"] == "array"
    assert openapi.ref_name(inner["items"]) == "EmergencyContact"
    assert "emergencyContacts" not in schema["required"]


@pytest.mark.parametrize("component", EMERGENCY_CONTACT_COMPONENTS)
def test_activation_emergency_contacts_holds_2_to_4_items_when_given(
    openapi: OpenApiDoc, component: str
) -> None:
    schema = openapi.component(component)
    inner = nullable_inner(schema["properties"]["emergencyContacts"])
    assert inner["minItems"] == 2
    assert inner["maxItems"] == 4


# InvitationAcceptancePreview and ActiveLeaseSummary


def test_acceptance_preview_invitation_is_invitation_preview(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "InvitationAcceptancePreview", "invitation")
    assert openapi.ref_name(schema) == "InvitationPreview"


def test_acceptance_preview_account_name_is_string(openapi: OpenApiDoc) -> None:
    assert _field(openapi, "InvitationAcceptancePreview", "accountName")["type"] == (
        "string"
    )


def test_acceptance_preview_account_role_is_user_role(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "InvitationAcceptancePreview", "accountRole")
    assert openapi.ref_name(schema) == "UserRole"


def test_acceptance_preview_can_accept_is_boolean(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "InvitationAcceptancePreview", "canAccept")
    assert schema["type"] == "boolean"


def test_acceptance_preview_blocker_is_nullable_invitation_blocker(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "InvitationAcceptancePreview", "blocker")
    assert openapi.ref_name(nullable_inner(schema)) == "InvitationBlocker"


def test_acceptance_preview_active_lease_is_nullable_active_lease_summary(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "InvitationAcceptancePreview", "activeLease")
    assert openapi.ref_name(nullable_inner(schema)) == "ActiveLeaseSummary"


@pytest.mark.parametrize("field", ["propertyName", "roomNumber"])
def test_active_lease_summary_text_field_is_string(
    openapi: OpenApiDoc, field: str
) -> None:
    assert _field(openapi, "ActiveLeaseSummary", field)["type"] == "string"


def test_active_lease_summary_end_date_is_nullable_date_string(
    openapi: OpenApiDoc,
) -> None:
    inner = nullable_inner(_field(openapi, "ActiveLeaseSummary", "endDate"))
    assert inner["type"] == "string"
    assert inner["format"] == "date"


# Runtime: valid requests reach the not-implemented stub


@pytest.mark.parametrize(("url", "body"), JSON_BODY_ENDPOINTS)
def test_valid_account_access_request_responds_not_implemented(
    client, url: str, body: dict[str, Any]
) -> None:
    response = client.post(url, json=body)
    assert response.status_code == 501


@pytest.mark.parametrize(
    ("method", "url"),
    [
        pytest.param("post", LOGOUT_URL, id="logout"),
        pytest.param("post", EMAIL_VERIFICATION_URL, id="send_email_verification"),
        pytest.param("get", ME_URL, id="get_my_account"),
    ],
)
def test_valid_bodiless_account_access_request_responds_not_implemented(
    client, method: str, url: str
) -> None:
    response = client.request(method, url)
    assert response.status_code == 501


@pytest.mark.parametrize("password", ["12345678", "a" * 128, "pässwörd with spaces"])
def test_register_password_of_8_to_128_characters_is_accepted(
    client, password: str
) -> None:
    body = {**VALID_REGISTER_INPUT, "password": password}
    assert client.post(REGISTER_URL, json=body).status_code == 501


@pytest.mark.parametrize("password", ["x", " ", "a" * 200])
def test_login_accepts_any_non_empty_password(client, password: str) -> None:
    body = {**VALID_LOGIN_INPUT, "password": password}
    assert client.post(LOGIN_URL, json=body).status_code == 501


@pytest.mark.parametrize("platform", ["a", "Android 14", "p" * 50])
def test_device_platform_of_1_to_50_characters_is_accepted(
    client, platform: str
) -> None:
    body = {**VALID_LOGIN_INPUT, "device": {**VALID_DEVICE, "platform": platform}}
    assert client.post(LOGIN_URL, json=body).status_code == 501


@pytest.mark.parametrize("code", ["000000", "123456", "999999"])
def test_six_digit_email_code_is_accepted(client, code: str) -> None:
    response = client.post(EMAIL_CONFIRMATION_URL, json={"code": code})
    assert response.status_code == 501


@pytest.mark.parametrize("count", [2, 3, 4])
@pytest.mark.parametrize(
    ("url", "base"),
    [
        pytest.param(PASSWORD_ACTIVATION_URL, VALID_PASSWORD_ACTIVATION_INPUT, id="pw"),
        pytest.param(GOOGLE_ACTIVATION_URL, VALID_GOOGLE_ACTIVATION_INPUT, id="google"),
    ],
)
def test_activation_with_2_to_4_emergency_contacts_is_accepted(
    client, url: str, base: dict[str, Any], count: int
) -> None:
    contacts = [{**VALID_CONTACT, "name": f"Contact {i}"} for i in range(count)]
    response = client.post(url, json={**base, "emergencyContacts": contacts})
    assert response.status_code == 501


@pytest.mark.parametrize(
    ("url", "base"),
    [
        pytest.param(PASSWORD_ACTIVATION_URL, VALID_PASSWORD_ACTIVATION_INPUT, id="pw"),
        pytest.param(GOOGLE_ACTIVATION_URL, VALID_GOOGLE_ACTIVATION_INPUT, id="google"),
    ],
)
def test_activation_with_null_emergency_contacts_is_accepted(
    client, url: str, base: dict[str, Any]
) -> None:
    response = client.post(url, json={**base, "emergencyContacts": None})
    assert response.status_code == 501


@pytest.mark.parametrize("email", [None, "tenant@example.com"])
def test_password_activation_accepts_an_optional_email(
    client, email: str | None
) -> None:
    body = {**VALID_PASSWORD_ACTIVATION_INPUT, "email": email}
    assert client.post(PASSWORD_ACTIVATION_URL, json=body).status_code == 501


# Runtime: invalid requests are rejected with a validation error


@pytest.mark.parametrize(("url", "body"), JSON_BODY_ENDPOINTS)
def test_account_access_write_without_body_is_rejected_with_validation_error(
    client, url: str, body: dict[str, Any]
) -> None:
    assert client.post(url).status_code == 422


@pytest.mark.parametrize(("url", "body"), JSON_BODY_ENDPOINTS)
def test_account_access_write_with_empty_object_is_rejected_with_validation_error(
    client, url: str, body: dict[str, Any]
) -> None:
    assert client.post(url, json={}).status_code == 422


@pytest.mark.parametrize(("url", "body"), JSON_BODY_ENDPOINTS)
def test_account_access_write_with_each_required_field_missing_is_rejected(
    client, url: str, body: dict[str, Any]
) -> None:
    from_schema = {
        REGISTER_URL: {"name", "email", "password", "device"},
        REGISTER_GOOGLE_URL: {"idToken", "device"},
        LOGIN_URL: {"email", "password", "device"},
        LOGIN_GOOGLE_URL: {"idToken", "device"},
        REFRESH_URL: {"refreshToken"},
        EMAIL_CONFIRMATION_URL: {"code"},
        PASSWORD_RESET_REQUESTS_URL: {"email"},
        PASSWORD_RESET_PREVIEWS_URL: {"token"},
        PASSWORD_RESETS_URL: {"token", "newPassword"},
        INVITATION_PREVIEWS_URL: {"token"},
        PASSWORD_ACTIVATION_URL: {"token", "name", "password", "device"},
        GOOGLE_ACTIVATION_URL: {"token", "name", "idToken", "device"},
        ACCEPTANCE_PREVIEWS_URL: {"token"},
        ACCEPTANCES_URL: {"token"},
        LOCAL_PASSWORD_URL: {"googleIdToken", "password"},
        GOOGLE_LINK_URL: {"idToken"},
    }[url]
    statuses = {
        field: client.post(url, json=_without(body, field)).status_code
        for field in from_schema
    }
    assert statuses == dict.fromkeys(from_schema, 422)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({**VALID_REGISTER_INPUT, "password": "1234567"}, id="7_chars"),
        pytest.param({**VALID_REGISTER_INPUT, "password": ""}, id="empty_password"),
        pytest.param({**VALID_REGISTER_INPUT, "password": "a" * 129}, id="129_chars"),
        pytest.param({**VALID_REGISTER_INPUT, "password": None}, id="null_password"),
        pytest.param({**VALID_REGISTER_INPUT, "password": 12345678}, id="number"),
        pytest.param({**VALID_REGISTER_INPUT, "email": "not-an-email"}, id="bad_email"),
        pytest.param({**VALID_REGISTER_INPUT, "email": ""}, id="empty_email"),
        pytest.param({**VALID_REGISTER_INPUT, "email": None}, id="null_email"),
        pytest.param({**VALID_REGISTER_INPUT, "name": ""}, id="empty_name"),
        pytest.param({**VALID_REGISTER_INPUT, "name": "   "}, id="blank_name"),
        pytest.param({**VALID_REGISTER_INPUT, "name": "n" * 101}, id="long_name"),
        pytest.param({**VALID_REGISTER_INPUT, "device": None}, id="null_device"),
        pytest.param({**VALID_REGISTER_INPUT, "device": "Pixel 8"}, id="text_device"),
    ],
)
def test_invalid_register_input_is_rejected_with_validation_error(
    client, body: dict[str, Any]
) -> None:
    assert client.post(REGISTER_URL, json=body).status_code == 422


@pytest.mark.parametrize(
    "device",
    [
        pytest.param({}, id="empty_device"),
        pytest.param(_without(VALID_DEVICE, "name"), id="no_device_name"),
        pytest.param(_without(VALID_DEVICE, "platform"), id="no_device_platform"),
        pytest.param({**VALID_DEVICE, "name": ""}, id="empty_device_name"),
        pytest.param({**VALID_DEVICE, "name": "d" * 101}, id="long_device_name"),
        pytest.param({**VALID_DEVICE, "platform": ""}, id="empty_platform"),
        pytest.param({**VALID_DEVICE, "platform": "p" * 51}, id="long_platform"),
        pytest.param({**VALID_DEVICE, "platform": None}, id="null_platform"),
    ],
)
def test_invalid_device_info_is_rejected_with_validation_error(
    client, device: dict[str, Any]
) -> None:
    body = {**VALID_LOGIN_INPUT, "device": device}
    assert client.post(LOGIN_URL, json=body).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({**VALID_LOGIN_INPUT, "password": ""}, id="empty_password"),
        pytest.param({**VALID_LOGIN_INPUT, "password": None}, id="null_password"),
        pytest.param({**VALID_LOGIN_INPUT, "email": "nobody"}, id="bad_email"),
        pytest.param({**VALID_LOGIN_INPUT, "email": None}, id="null_email"),
    ],
)
def test_invalid_login_input_is_rejected_with_validation_error(
    client, body: dict[str, Any]
) -> None:
    assert client.post(LOGIN_URL, json=body).status_code == 422


@pytest.mark.parametrize("url", [REGISTER_GOOGLE_URL, LOGIN_GOOGLE_URL])
@pytest.mark.parametrize("id_token", ["", None, 5])
def test_invalid_google_id_token_is_rejected_with_validation_error(
    client, url: str, id_token: Any
) -> None:
    body = {**VALID_GOOGLE_AUTH_INPUT, "idToken": id_token}
    assert client.post(url, json=body).status_code == 422


@pytest.mark.parametrize("refresh_token", ["", None, 5])
def test_invalid_refresh_token_is_rejected_with_validation_error(
    client, refresh_token: Any
) -> None:
    response = client.post(REFRESH_URL, json={"refreshToken": refresh_token})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "code",
    [
        pytest.param("", id="empty"),
        pytest.param("12345", id="five_digits"),
        pytest.param("1234567", id="seven_digits"),
        pytest.param("12345a", id="letter"),
        pytest.param("12 456", id="inner_space"),
        pytest.param(" 123456", id="leading_space"),
        pytest.param("123456 ", id="trailing_space"),
        pytest.param("-12345", id="sign"),
        pytest.param("١٢٣٤٥٦", id="non_ascii_digits"),
        pytest.param(None, id="null"),
        pytest.param(123456, id="number"),
    ],
)
def test_invalid_email_confirmation_code_is_rejected_with_validation_error(
    client, code: Any
) -> None:
    response = client.post(EMAIL_CONFIRMATION_URL, json={"code": code})
    assert response.status_code == 422


@pytest.mark.parametrize("email", ["", "plain", "a@", "@example.com", None, 5])
def test_invalid_password_reset_request_email_is_rejected_with_validation_error(
    client, email: Any
) -> None:
    response = client.post(PASSWORD_RESET_REQUESTS_URL, json={"email": email})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        PASSWORD_RESET_PREVIEWS_URL,
        INVITATION_PREVIEWS_URL,
        ACCEPTANCE_PREVIEWS_URL,
        ACCEPTANCES_URL,
    ],
)
@pytest.mark.parametrize("token", ["", None, 5])
def test_invalid_token_input_is_rejected_with_validation_error(
    client, url: str, token: Any
) -> None:
    assert client.post(url, json={"token": token}).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            {**VALID_PASSWORD_RESET_INPUT, "newPassword": "1234567"}, id="7_chars"
        ),
        pytest.param({**VALID_PASSWORD_RESET_INPUT, "newPassword": ""}, id="empty"),
        pytest.param(
            {**VALID_PASSWORD_RESET_INPUT, "newPassword": "a" * 129}, id="129_chars"
        ),
        pytest.param({**VALID_PASSWORD_RESET_INPUT, "newPassword": None}, id="null"),
        pytest.param({**VALID_PASSWORD_RESET_INPUT, "token": ""}, id="empty_token"),
        pytest.param({**VALID_PASSWORD_RESET_INPUT, "token": None}, id="null_token"),
        pytest.param(
            {"token": VALID_TOKEN, "password": VALID_PASSWORD}, id="wrong_field_name"
        ),
    ],
)
def test_invalid_password_reset_input_is_rejected_with_validation_error(
    client, body: dict[str, Any]
) -> None:
    assert client.post(PASSWORD_RESETS_URL, json=body).status_code == 422


@pytest.mark.parametrize("password", ["a" * 8, "a" * 128])
def test_password_reset_with_8_to_128_character_password_is_accepted(
    client, password: str
) -> None:
    body = {**VALID_PASSWORD_RESET_INPUT, "newPassword": password}
    assert client.post(PASSWORD_RESETS_URL, json=body).status_code == 501


_CONTACT_CASES = [
    pytest.param([VALID_CONTACT], id="one_contact"),
    pytest.param([], id="empty_list"),
    pytest.param([VALID_CONTACT] * 5, id="five_contacts"),
    pytest.param(
        [VALID_CONTACT, _without(VALID_CONTACT, "phone")], id="contact_without_phone"
    ),
    pytest.param(
        [VALID_CONTACT, _without(VALID_CONTACT, "relationship")],
        id="contact_without_relationship",
    ),
    pytest.param(
        [VALID_CONTACT, _without(VALID_CONTACT, "name")], id="contact_without_name"
    ),
    pytest.param([VALID_CONTACT, {**VALID_CONTACT, "name": ""}], id="empty_name"),
    pytest.param([VALID_CONTACT, {**VALID_CONTACT, "phone": ""}], id="empty_phone"),
    pytest.param([VALID_CONTACT, "Siti"], id="contact_as_text"),
    pytest.param("Siti", id="contacts_as_text"),
]


@pytest.mark.parametrize("contacts", _CONTACT_CASES)
def test_password_activation_with_invalid_emergency_contacts_is_rejected(
    client, contacts: Any
) -> None:
    body = {**VALID_PASSWORD_ACTIVATION_INPUT, "emergencyContacts": contacts}
    assert client.post(PASSWORD_ACTIVATION_URL, json=body).status_code == 422


@pytest.mark.parametrize("contacts", _CONTACT_CASES)
def test_google_activation_with_invalid_emergency_contacts_is_rejected(
    client, contacts: Any
) -> None:
    body = {**VALID_GOOGLE_ACTIVATION_INPUT, "emergencyContacts": contacts}
    assert client.post(GOOGLE_ACTIVATION_URL, json=body).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            {**VALID_PASSWORD_ACTIVATION_INPUT, "password": "1234567"}, id="7_chars"
        ),
        pytest.param(
            {**VALID_PASSWORD_ACTIVATION_INPUT, "password": "a" * 129}, id="129_chars"
        ),
        pytest.param({**VALID_PASSWORD_ACTIVATION_INPUT, "password": ""}, id="empty"),
        pytest.param({**VALID_PASSWORD_ACTIVATION_INPUT, "name": ""}, id="empty_name"),
        pytest.param(
            {**VALID_PASSWORD_ACTIVATION_INPUT, "name": "n" * 101}, id="long_name"
        ),
        pytest.param(
            {**VALID_PASSWORD_ACTIVATION_INPUT, "token": ""}, id="empty_token"
        ),
        pytest.param(
            {**VALID_PASSWORD_ACTIVATION_INPUT, "email": "not-an-email"}, id="bad_email"
        ),
        pytest.param(
            {**VALID_PASSWORD_ACTIVATION_INPUT, "email": ""}, id="empty_email"
        ),
        pytest.param(
            {**VALID_PASSWORD_ACTIVATION_INPUT, "device": None}, id="no_device"
        ),
    ],
)
def test_invalid_password_activation_input_is_rejected_with_validation_error(
    client, body: dict[str, Any]
) -> None:
    assert client.post(PASSWORD_ACTIVATION_URL, json=body).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({**VALID_GOOGLE_ACTIVATION_INPUT, "idToken": ""}, id="empty_id"),
        pytest.param({**VALID_GOOGLE_ACTIVATION_INPUT, "idToken": None}, id="null_id"),
        pytest.param({**VALID_GOOGLE_ACTIVATION_INPUT, "name": ""}, id="empty_name"),
        pytest.param(
            {**VALID_GOOGLE_ACTIVATION_INPUT, "name": "n" * 101}, id="long_name"
        ),
        pytest.param({**VALID_GOOGLE_ACTIVATION_INPUT, "token": ""}, id="empty_token"),
        pytest.param({**VALID_GOOGLE_ACTIVATION_INPUT, "device": None}, id="no_device"),
    ],
)
def test_invalid_google_activation_input_is_rejected_with_validation_error(
    client, body: dict[str, Any]
) -> None:
    assert client.post(GOOGLE_ACTIVATION_URL, json=body).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            {**VALID_ADD_LOCAL_PASSWORD_INPUT, "password": "1234567"}, id="7_chars"
        ),
        pytest.param(
            {**VALID_ADD_LOCAL_PASSWORD_INPUT, "password": "a" * 129}, id="129_chars"
        ),
        pytest.param({**VALID_ADD_LOCAL_PASSWORD_INPUT, "password": ""}, id="empty"),
        pytest.param(
            {**VALID_ADD_LOCAL_PASSWORD_INPUT, "googleIdToken": ""}, id="empty_id_token"
        ),
        pytest.param(
            {**VALID_ADD_LOCAL_PASSWORD_INPUT, "googleIdToken": None},
            id="null_id_token",
        ),
    ],
)
def test_invalid_add_local_password_input_is_rejected_with_validation_error(
    client, body: dict[str, Any]
) -> None:
    assert client.post(LOCAL_PASSWORD_URL, json=body).status_code == 422


@pytest.mark.parametrize("id_token", ["", None, 5])
def test_invalid_link_google_input_is_rejected_with_validation_error(
    client, id_token: Any
) -> None:
    response = client.post(GOOGLE_LINK_URL, json={"idToken": id_token})
    assert response.status_code == 422
