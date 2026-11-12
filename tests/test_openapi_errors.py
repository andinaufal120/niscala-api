"""How the OpenAPI document declares the errors of every operation."""

import json
import tomllib
from pathlib import Path

import pytest

ERROR_BODY_REF = "#/components/schemas/ErrorBody"
REPO_ROOT = Path(__file__).resolve().parent.parent

# Every operation of the document with the status of its success response.
OPERATIONS = {
    ("GET", "/health"): "200",
    ("POST", "/auth/register"): "201",
    ("POST", "/auth/register/google"): "201",
    ("POST", "/auth/login"): "200",
    ("POST", "/auth/login/google"): "200",
    ("POST", "/auth/refresh"): "200",
    ("POST", "/auth/logout"): "204",
    ("POST", "/auth/email-verification"): "202",
    ("POST", "/auth/email-verification/confirmation"): "200",
    ("POST", "/auth/email-changes"): "204",
    ("POST", "/auth/password-reset-requests"): "202",
    ("POST", "/auth/password-reset-previews"): "200",
    ("POST", "/auth/password-resets"): "204",
    ("POST", "/invitations/previews"): "200",
    ("POST", "/invitations/activations/password"): "201",
    ("POST", "/invitations/activations/google"): "201",
    ("POST", "/invitations/acceptance-previews"): "200",
    ("POST", "/invitations/acceptances"): "204",
    ("GET", "/me"): "200",
    ("POST", "/me/local-password"): "200",
    ("POST", "/me/google-link"): "200",
    ("GET", "/me/sessions"): "200",
    ("DELETE", "/me/sessions"): "204",
    ("DELETE", "/me/sessions/{sessionId}"): "204",
    ("POST", "/me/password-changes"): "200",
    ("POST", "/me/reauthentication/password"): "200",
    ("POST", "/me/reauthentication/google"): "200",
    ("GET", "/properties"): "200",
    ("POST", "/properties"): "201",
    ("GET", "/properties/{propertyId}"): "200",
    ("PUT", "/properties/{propertyId}"): "200",
    ("DELETE", "/properties/{propertyId}"): "204",
    ("POST", "/properties/{propertyId}/rooms"): "201",
    ("GET", "/properties/{propertyId}/rooms"): "200",
    ("GET", "/properties/{propertyId}/facility-suggestions"): "200",
    ("POST", "/properties/{propertyId}/tenants"): "201",
    ("GET", "/properties/{propertyId}/tenants"): "200",
    ("GET", "/properties/{propertyId}/payment-overview"): "200",
    ("GET", "/properties/{propertyId}/payment-patterns"): "200",
    ("GET", "/rooms/{roomId}"): "200",
    ("PUT", "/rooms/{roomId}"): "200",
    ("DELETE", "/rooms/{roomId}"): "204",
    ("GET", "/tenants/{tenantId}"): "200",
    ("PUT", "/tenants/{tenantId}"): "200",
    ("DELETE", "/tenants/{tenantId}"): "204",
    ("POST", "/tenants/{tenantId}/invitation"): "201",
    ("POST", "/managers"): "201",
    ("GET", "/managers"): "200",
    ("GET", "/managers/{managerId}"): "200",
    ("PUT", "/managers/{managerId}"): "200",
    ("DELETE", "/managers/{managerId}"): "204",
    ("POST", "/managers/{managerId}/invitation"): "201",
    ("GET", "/complaints"): "200",
    ("POST", "/complaints"): "201",
    ("GET", "/complaints/{complaintId}"): "200",
    ("POST", "/complaints/{complaintId}/status-changes"): "201",
    ("PUT", "/complaints/{complaintId}/classification"): "200",
    ("PUT", "/complaints/{complaintId}/photo"): "200",
    ("GET", "/complaints/{complaintId}/photo"): "200",
    ("GET", "/complaint-categories"): "200",
    ("GET", "/rent-bills"): "200",
    ("GET", "/rent-bills/{rentBillId}"): "200",
    ("PUT", "/rent-bills/{rentBillId}/receipt"): "200",
    ("GET", "/rent-bills/{rentBillId}/receipt"): "200",
    ("POST", "/rent-bills/{rentBillId}/verification"): "200",
    ("POST", "/rent-bills/{rentBillId}/rejection"): "200",
    ("POST", "/rent-bills/{rentBillId}/cash-payment"): "200",
    ("POST", "/rent-bills/{rentBillId}/status-changes"): "201",
    ("GET", "/me/leases"): "200",
    ("GET", "/occupancy-dashboard"): "200",
    ("GET", "/notifications"): "200",
    ("POST", "/notifications/read-all"): "204",
    ("POST", "/notifications/{notificationId}/read"): "200",
    ("GET", "/me/notification-settings"): "200",
    ("PUT", "/me/notification-settings"): "200",
    ("PUT", "/me/push-token"): "204",
    ("GET", "/user-accounts"): "200",
    ("GET", "/user-accounts/{userAccountId}"): "200",
    ("PUT", "/user-accounts/{userAccountId}"): "200",
    ("DELETE", "/user-accounts/{userAccountId}"): "204",
    ("GET", "/subscription"): "200",
    ("POST", "/subscription/orders"): "201",
    ("GET", "/subscription/orders/{orderId}"): "200",
    ("POST", "/subscription/orders/{orderId}/purchase-verification"): "200",
    ("PUT", "/subscription/scheduled-downgrade"): "200",
    ("DELETE", "/subscription/scheduled-downgrade"): "204",
    ("GET", "/subscription-plans"): "200",
}

# Schemas of the document that are not about errors and must stay.
KEPT_SCHEMAS = {
    "Account",
    "AccountPropertyRef",
    "AccountTenancy",
    "AddLocalPasswordInput",
    "AiComplaintClassification",
    "AuthSession",
    "AuthTokens",
    "BankAccount",
    "BillingCycle",
    "Body_upload_complaint_photo",
    "Body_upload_receipt",
    "CashPaymentInput",
    "Complaint",
    "ComplaintCategoryList",
    "ComplaintClassification",
    "ComplaintClassificationInput",
    "ComplaintClassificationState",
    "ComplaintInput",
    "ComplaintList",
    "ComplaintStatus",
    "ComplaintStatusChange",
    "ComplaintStatusChangeInput",
    "ComplaintSummary",
    "ComplaintUrgency",
    "CurrentLease",
    "CurrentLeaseList",
    "CurrentLeaseProperty",
    "CurrentLeaseRoom",
    "DeviceInfo",
    "EditableAccountStatus",
    "EmailConfirmationInput",
    "EmailVerificationSent",
    "EmergencyContact",
    "ErrorBody",
    "FacilitySuggestionList",
    "GoogleAuthInput",
    "Health",
    "InvitationAcceptanceInput",
    "InvitationAcceptancePreview",
    "InvitationBlocker",
    "InvitationGoogleActivationInput",
    "InvitationLinkStatus",
    "InvitationPasswordActivationInput",
    "InvitationPreview",
    "InvitationProperty",
    "InvitationRole",
    "Lease",
    "LeaseInput",
    "LinkGoogleInput",
    "LoginInput",
    "LoginMethod",
    "Manager",
    "ManagerAccountStatus",
    "ManagerInput",
    "ManagerInvitation",
    "ManagerList",
    "ManagerProperty",
    "ManagerRef",
    "ManagerSummary",
    "NewTenantInput",
    "Notification",
    "NotificationCategory",
    "NotificationComplaint",
    "NotificationList",
    "NotificationRentBill",
    "NotificationSettingItem",
    "NotificationSettings",
    "NotificationSettingsInput",
    "NotificationType",
    "NotificationUrgencyScope",
    "Occupancy",
    "OccupancyDashboard",
    "OccupancyRoom",
    "OccupancySummary",
    "OrderStatus",
    "PaidPlanCode",
    "PasswordChangeInput",
    "PasswordChangeResult",
    "PasswordResetInput",
    "PasswordResetPreview",
    "PasswordResetRequestInput",
    "Payment",
    "PaymentMethod",
    "PaymentOverview",
    "PaymentOverviewItem",
    "PaymentPattern",
    "PaymentPatternList",
    "PaymentStatus",
    "PaymentStatusChange",
    "PaymentStatusChangeInput",
    "PlanCode",
    "Property",
    "PropertyInput",
    "PropertyList",
    "PropertyOccupancy",
    "PropertyRef",
    "PropertySummary",
    "PurchaseVerificationInput",
    "PushTokenInput",
    "Reauthentication",
    "ReauthenticationGoogleInput",
    "ReauthenticationPasswordInput",
    "ReceiptRejectionInput",
    "RefreshInput",
    "RegisterOwnerInput",
    "RentBill",
    "RentBillList",
    "RentBillSummary",
    "Room",
    "RoomInput",
    "RoomLease",
    "RoomLeaseSummary",
    "RoomList",
    "RoomRef",
    "RoomSummary",
    "ScheduledDowngrade",
    "ScheduledDowngradeInput",
    "Session",
    "SessionList",
    "Subscription",
    "SubscriptionOrder",
    "SubscriptionOrderInput",
    "SubscriptionPeriod",
    "SubscriptionPlan",
    "SubscriptionPlanList",
    "SubscriptionPlanPrice",
    "SubscriptionStatus",
    "Tenant",
    "TenantAccountStatus",
    "TenantInput",
    "TenantInvitation",
    "TenantList",
    "TenantRef",
    "TenantSummary",
    "TokenInput",
    "UserAccount",
    "UserAccountInput",
    "UserAccountList",
    "UserAccountStatus",
    "UserAccountSummary",
    "UserRole",
}

DEFAULT_VALIDATION_SCHEMAS = ("HTTPValidationError", "ValidationError")

# The health check answers 503 with its own body when the database is down; the
# document already declared that before errors were catalogued.
HEALTH_UNAVAILABLE = ("GET", "/health", "503")

OPERATION_IDS = sorted(OPERATIONS)


@pytest.fixture(scope="module")
def document(app):
    return app.openapi()


@pytest.fixture(scope="module")
def catalog():
    from app import error_catalog

    return error_catalog


def operation_of(document, method, path):
    assert path in document["paths"], f"{path} is not declared"
    assert method.lower() in document["paths"][path], f"{method} {path} not declared"
    return document["paths"][path][method.lower()]


def error_statuses(operation):
    return {s for s in operation["responses"] if s[:1] in "45"}


def uses_bearer(operation):
    return any("bearerAuth" in req for req in operation.get("security", []))


def takes_input(operation):
    return bool(operation.get("parameters")) or "requestBody" in operation


def refs_in(value):
    """Every `$ref` string found anywhere inside a JSON value."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref":
                yield item
            else:
                yield from refs_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from refs_in(item)


# The set of operations


def test_the_document_declares_exactly_the_known_operations(document):
    declared = {
        (method.upper(), path)
        for path, item in document["paths"].items()
        for method in item
    }
    assert declared == set(OPERATIONS)
    assert len(declared) == 87


# The error object


def test_the_error_body_schema_has_code_field_and_message(document):
    schema = document["components"]["schemas"]["ErrorBody"]
    assert set(schema["properties"]) == {"code", "field", "message"}
    assert set(schema["required"]) == {"code", "field", "message"}


def test_the_default_validation_error_schemas_are_gone(document):
    schemas = document["components"]["schemas"]
    for name in DEFAULT_VALIDATION_SCHEMAS:
        assert name not in schemas


def test_nothing_in_the_document_refers_to_the_default_validation_error(document):
    refs = list(refs_in(document))
    assert refs
    for ref in refs:
        assert not ref.endswith(DEFAULT_VALIDATION_SCHEMAS), ref


def test_every_reference_in_the_document_resolves(document):
    schemas = document["components"]["schemas"]
    prefix = "#/components/schemas/"
    for ref in refs_in(document):
        assert ref.startswith(prefix), ref
        assert ref.removeprefix(prefix) in schemas, ref


# Per operation


@pytest.mark.parametrize(("method", "path"), OPERATION_IDS)
def test_an_operation_lists_its_codes_in_x_error_codes(document, catalog, method, path):
    operation = operation_of(document, method, path)
    assert "x-error-codes" in operation
    codes = operation["x-error-codes"]
    assert isinstance(codes, list)
    assert all(isinstance(code, str) for code in codes)
    assert set(codes) == set(catalog.ROUTE_ERRORS[(method, path)])


@pytest.mark.parametrize(("method", "path"), OPERATION_IDS)
def test_x_error_codes_are_sorted_by_status_and_code_without_repeats(
    document, catalog, method, path
):
    codes = operation_of(document, method, path)["x-error-codes"]
    assert len(set(codes)) == len(codes)
    expected = sorted(codes, key=lambda code: (catalog.ERROR_STATUS[code], code))
    assert codes == expected


@pytest.mark.parametrize(("method", "path"), OPERATION_IDS)
def test_each_status_of_the_codes_has_an_error_response(
    document, catalog, method, path
):
    operation = operation_of(document, method, path)
    for status in {catalog.ERROR_STATUS[c] for c in operation["x-error-codes"]}:
        assert str(status) in operation["responses"], status


@pytest.mark.parametrize(("method", "path"), OPERATION_IDS)
def test_error_responses_carry_the_error_body(document, catalog, method, path):
    operation = operation_of(document, method, path)
    for status in {catalog.ERROR_STATUS[c] for c in operation["x-error-codes"]}:
        response = operation["responses"][str(status)]
        schema = response["content"]["application/json"]["schema"]
        assert schema == {"$ref": ERROR_BODY_REF} or schema["$ref"] == ERROR_BODY_REF
        assert response["description"]


@pytest.mark.parametrize(("method", "path"), OPERATION_IDS)
def test_no_error_status_is_declared_without_a_code(document, catalog, method, path):
    operation = operation_of(document, method, path)
    from_codes = {str(catalog.ERROR_STATUS[c]) for c in operation["x-error-codes"]}
    extra = error_statuses(operation) - from_codes
    if (method, path) == HEALTH_UNAVAILABLE[:2]:
        extra -= {HEALTH_UNAVAILABLE[2]}
    assert not extra, extra


@pytest.mark.parametrize(
    ("method", "path", "status"), [(*k, v) for k, v in OPERATIONS.items()]
)
def test_the_success_response_is_kept(document, method, path, status):
    operation = operation_of(document, method, path)
    assert status in operation["responses"]
    success = {s for s in operation["responses"] if s.startswith("2")}
    assert success == {status}
    for ref in refs_in(operation["responses"][status]):
        assert ref != ERROR_BODY_REF


@pytest.mark.parametrize(("method", "path"), OPERATION_IDS)
def test_an_operation_with_input_declares_validation_failure(
    document, catalog, method, path
):
    operation = operation_of(document, method, path)
    if not takes_input(operation):
        pytest.skip("no parameter or body")
    assert "VALIDATION_FAILED" in operation["x-error-codes"]
    schema = operation["responses"]["422"]["content"]["application/json"]["schema"]
    assert schema["$ref"] == ERROR_BODY_REF


@pytest.mark.parametrize(("method", "path"), OPERATION_IDS)
def test_authentication_is_declared_exactly_for_secured_operations(
    document, catalog, method, path
):
    operation = operation_of(document, method, path)
    codes = operation["x-error-codes"]
    if uses_bearer(operation):
        assert "ACCESS_TOKEN_INVALID" in codes
        response = operation["responses"]["401"]
        schema = response["content"]["application/json"]["schema"]
        assert schema["$ref"] == ERROR_BODY_REF
    else:
        assert "ACCESS_TOKEN_INVALID" not in codes


@pytest.mark.parametrize(("method", "path"), OPERATION_IDS)
def test_every_code_of_an_operation_is_in_the_catalog(document, catalog, method, path):
    for code in operation_of(document, method, path)["x-error-codes"]:
        assert code in catalog.ERROR_STATUS


# Sampled operations written from the use cases

AUTHENTICATED_READ = {"ACCESS_TOKEN_INVALID", "EMAIL_NOT_VERIFIED"}

GOLDEN = {
    ("GET", "/health"): set(),
    ("POST", "/auth/login"): {
        "INVALID_CREDENTIALS",
        "ACCOUNT_INACTIVE",
        "TOO_MANY_LOGIN_ATTEMPTS",
        "VALIDATION_FAILED",
    },
    ("POST", "/auth/refresh"): {"REFRESH_TOKEN_INVALID", "VALIDATION_FAILED"},
    ("POST", "/auth/logout"): {"ACCESS_TOKEN_INVALID"},
    ("GET", "/me"): {"ACCESS_TOKEN_INVALID"},
    ("POST", "/auth/email-verification"): {
        "ACCESS_TOKEN_INVALID",
        "EMAIL_ALREADY_VERIFIED",
        "VERIFICATION_CODE_TOO_SOON",
    },
    ("POST", "/auth/password-resets"): {
        "PASSWORD_RESET_NOT_FOUND",
        "PASSWORD_RESET_EXPIRED",
        "PASSWORD_RESET_USED",
        "PASSWORD_TOO_COMMON",
        "VALIDATION_FAILED",
    },
    ("POST", "/me/password-changes"): AUTHENTICATED_READ
    | {
        "PASSWORD_NOT_SET",
        "CURRENT_PASSWORD_INCORRECT",
        "PASSWORD_TOO_COMMON",
        "PASSWORD_UNCHANGED",
        "VALIDATION_FAILED",
        "TOO_MANY_ATTEMPTS",
    },
    ("POST", "/me/reauthentication/password"): AUTHENTICATED_READ
    | {
        "PASSWORD_NOT_SET",
        "PASSWORD_INCORRECT",
        "VALIDATION_FAILED",
        "TOO_MANY_LOGIN_ATTEMPTS",
    },
    ("DELETE", "/me/sessions/{sessionId}"): AUTHENTICATED_READ
    | {"SESSION_NOT_FOUND", "SESSION_IS_CURRENT", "VALIDATION_FAILED"},
    ("POST", "/properties"): AUTHENTICATED_READ
    | {
        "FORBIDDEN",
        "PROPERTY_LIMIT_REACHED",
        "PROPERTY_NAME_TAKEN",
        "VALIDATION_FAILED",
    },
    ("PUT", "/properties/{propertyId}"): AUTHENTICATED_READ
    | {
        "FORBIDDEN",
        "PROPERTY_READ_ONLY",
        "REAUTHENTICATION_REQUIRED",
        "PROPERTY_NOT_FOUND",
        "PROPERTY_NAME_TAKEN",
        "VALIDATION_FAILED",
    },
    ("DELETE", "/properties/{propertyId}"): AUTHENTICATED_READ
    | {
        "FORBIDDEN",
        "PROPERTY_NOT_FOUND",
        "PROPERTY_HAS_ACTIVE_LEASE",
        "VALIDATION_FAILED",
    },
    ("POST", "/properties/{propertyId}/rooms"): AUTHENTICATED_READ
    | {
        "FORBIDDEN",
        "PROPERTY_READ_ONLY",
        "ROOM_LIMIT_REACHED",
        "PROPERTY_NOT_FOUND",
        "ROOM_NUMBER_TAKEN",
        "VALIDATION_FAILED",
    },
    ("GET", "/rent-bills/{rentBillId}"): AUTHENTICATED_READ
    | {"FORBIDDEN", "RENT_BILL_NOT_FOUND", "VALIDATION_FAILED"},
    ("PUT", "/rent-bills/{rentBillId}/receipt"): AUTHENTICATED_READ
    | {
        "FORBIDDEN",
        "RECEIPT_TYPE_INVALID",
        "RECEIPT_TOO_LARGE",
        "RENT_BILL_NOT_UPLOADABLE",
        "PROPERTY_BANK_ACCOUNT_MISSING",
        "RENT_BILL_NOT_FOUND",
        "VALIDATION_FAILED",
    },
    ("GET", "/rent-bills/{rentBillId}/receipt"): AUTHENTICATED_READ
    | {
        "FORBIDDEN",
        "RENT_BILL_NOT_FOUND",
        "RECEIPT_NOT_FOUND",
        "VALIDATION_FAILED",
        "INTERNAL_ERROR",
    },
    ("POST", "/rent-bills/{rentBillId}/status-changes"): AUTHENTICATED_READ
    | {
        "FORBIDDEN",
        "RENT_BILL_NOT_FOUND",
        "REASON_REQUIRED",
        "RECEIVED_ON_IN_FUTURE",
        "STATUS_UNCHANGED",
        "VALIDATION_FAILED",
    },
    ("PUT", "/complaints/{complaintId}/photo"): AUTHENTICATED_READ
    | {
        "FORBIDDEN",
        "COMPLAINT_NOT_FOUND",
        "COMPLAINT_NOT_NEW",
        "PHOTO_TOO_LARGE",
        "PHOTO_TYPE_INVALID",
        "VALIDATION_FAILED",
    },
    ("POST", "/subscription/orders/{orderId}/purchase-verification"): (
        AUTHENTICATED_READ
        | {
            "FORBIDDEN",
            "SUBSCRIPTION_ORDER_NOT_FOUND",
            "PURCHASE_TOKEN_IN_USE",
            "SUBSCRIPTION_ORDER_CLOSED",
            "PURCHASE_PRODUCT_MISMATCH",
            "PURCHASE_TOKEN_INVALID",
            "VALIDATION_FAILED",
            "GOOGLE_PLAY_UNREACHABLE",
        }
    ),
    ("PUT", "/subscription/scheduled-downgrade"): AUTHENTICATED_READ
    | {
        "FORBIDDEN",
        "KEPT_PROPERTIES_INVALID",
        "KEPT_ROOMS_INVALID",
        "SUBSCRIPTION_NOT_A_DOWNGRADE",
        "VALIDATION_FAILED",
    },
    ("DELETE", "/user-accounts/{userAccountId}"): AUTHENTICATED_READ
    | {
        "FORBIDDEN",
        "USER_ACCOUNT_NOT_FOUND",
        "CANNOT_MODIFY_OWN_ACCOUNT",
        "OWNER_HAS_ACTIVE_LEASE",
        "TENANT_HAS_ACTIVE_LEASE",
        "USER_ACCOUNT_DELETED",
        "VALIDATION_FAILED",
    },
}


@pytest.mark.parametrize(("method", "path"), sorted(GOLDEN))
def test_a_sampled_operation_answers_exactly_the_codes_of_its_use_case(
    document, method, path
):
    codes = operation_of(document, method, path)["x-error-codes"]
    assert set(codes) == GOLDEN[(method, path)]


def test_login_does_not_declare_an_invalid_access_token(document):
    login = operation_of(document, "POST", "/auth/login")
    assert "401" in login["responses"]
    assert "ACCESS_TOKEN_INVALID" not in login["x-error-codes"]
    assert not uses_bearer(login)


def test_the_health_check_declares_no_codes(document):
    assert operation_of(document, "GET", "/health")["x-error-codes"] == []


# The rest of the document stays as it was


def test_every_non_error_schema_is_kept(document):
    schemas = set(document["components"]["schemas"])
    assert KEPT_SCHEMAS <= schemas
    assert schemas - KEPT_SCHEMAS == set()


def test_the_version_is_the_project_version(document):
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert document["info"]["version"] == pyproject["project"]["version"]


def test_the_document_is_valid_json_and_stable_between_calls(app):
    first = json.dumps(app.openapi(), sort_keys=True)
    second = json.dumps(app.openapi(), sort_keys=True)
    assert first == second


def test_the_secured_operations_keep_the_bearer_scheme(document):
    assert "bearerAuth" in document["components"]["securitySchemes"]
    secured = [
        key for key in OPERATIONS if uses_bearer(operation_of(document, key[0], key[1]))
    ]
    assert len(secured) > 60
