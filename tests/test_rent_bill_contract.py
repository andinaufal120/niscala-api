"""Contract tests for the rent bill, receipt and payment overview endpoints."""

from typing import Any

import pytest
from conftest import (
    PROPERTY_ID,
    RENT_BILL_ID,
    OpenApiDoc,
    nullable_inner,
)

RENT_BILL_PATHS = {
    "/rent-bills": {"get"},
    "/rent-bills/{rentBillId}": {"get"},
    "/rent-bills/{rentBillId}/receipt": {"put", "get"},
    "/rent-bills/{rentBillId}/verification": {"post"},
    "/rent-bills/{rentBillId}/rejection": {"post"},
    "/rent-bills/{rentBillId}/cash-payment": {"post"},
    "/rent-bills/{rentBillId}/status-changes": {"post"},
    "/properties/{propertyId}/payment-overview": {"get"},
}

# (method, path, operationId, success status)
RENT_BILL_OPERATIONS = [
    ("get", "/rent-bills", "list_rent_bills", 200),
    ("get", "/rent-bills/{rentBillId}", "get_rent_bill", 200),
    ("put", "/rent-bills/{rentBillId}/receipt", "upload_receipt", 200),
    ("get", "/rent-bills/{rentBillId}/receipt", "get_receipt", 200),
    ("post", "/rent-bills/{rentBillId}/verification", "verify_receipt", 200),
    ("post", "/rent-bills/{rentBillId}/rejection", "reject_receipt", 200),
    ("post", "/rent-bills/{rentBillId}/cash-payment", "record_cash_payment", 200),
    ("post", "/rent-bills/{rentBillId}/status-changes", "change_payment_status", 201),
    (
        "get",
        "/properties/{propertyId}/payment-overview",
        "get_payment_overview",
        200,
    ),
]

# (method, path, path parameter name)
RENT_BILL_PATH_PARAMETERS = [
    pytest.param(m, p, "propertyId" if "{propertyId}" in p else "rentBillId", id=o)
    for m, p, o, _ in RENT_BILL_OPERATIONS
    if "{" in p
]

PAYMENT_STATUSES = ["unpaid", "awaitingVerification", "paid", "rejected"]
PAYMENT_METHODS = ["transfer", "cash"]
MANUAL_TARGET_STATUSES = ["unpaid", "paid", "rejected"]

VALID_REJECTION_INPUT = {"reason": "The receipt is unreadable."}
VALID_CASH_PAYMENT_INPUT = {"receivedOn": "2026-10-17"}
VALID_STATUS_CHANGE_INPUT = {"status": "paid", "reason": "Confirmed in person."}

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 16

LIST_URL = "/rent-bills"
BILL_URL = f"/rent-bills/{RENT_BILL_ID}"
RECEIPT_URL = f"{BILL_URL}/receipt"
VERIFICATION_URL = f"{BILL_URL}/verification"
REJECTION_URL = f"{BILL_URL}/rejection"
CASH_PAYMENT_URL = f"{BILL_URL}/cash-payment"
STATUS_CHANGES_URL = f"{BILL_URL}/status-changes"
OVERVIEW_URL = f"/properties/{PROPERTY_ID}/payment-overview"

RENT_BILL_COMPONENTS = [
    "PaymentStatus",
    "PaymentMethod",
    "TenantRef",
    "Payment",
    "RentBillSummary",
    "RentBill",
    "RentBillList",
    "ReceiptRejectionInput",
    "CashPaymentInput",
    "PaymentStatusChange",
    "PaymentStatusChangeInput",
    "PaymentOverviewItem",
    "PaymentOverview",
]


def _without(body: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k not in keys}


def _property_names(schema: dict[str, Any]) -> set[str]:
    return set(schema.get("properties", {}))


def _assert_uuid_string(schema: dict[str, Any]) -> None:
    assert schema["type"] == "string"
    assert schema["format"] == "uuid"


def _assert_date_string(schema: dict[str, Any]) -> None:
    assert schema["type"] == "string"
    assert schema["format"] == "date"


def _assert_string_enum(schema: dict[str, Any], values: list[str]) -> None:
    assert schema["type"] == "string"
    assert sorted(schema["enum"]) == sorted(values)
    assert len(schema["enum"]) == len(values)


def _query_parameters(openapi: OpenApiDoc, method: str, path: str) -> dict[str, Any]:
    parameters = openapi.operation(method, path).get("parameters", [])
    return {p["name"]: p for p in parameters if p["in"] == "query"}


def _unwrap_optional(schema: dict[str, Any]) -> dict[str, Any]:
    """Return the schema itself, or its non-null part when it allows null."""
    return nullable_inner(schema) if "anyOf" in schema else schema


# Paths, operations and status codes


@pytest.mark.parametrize(("path", "methods"), RENT_BILL_PATHS.items())
def test_rent_bill_path_declares_exactly_its_methods(
    openapi: OpenApiDoc, path: str, methods: set[str]
) -> None:
    declared = {
        m
        for m in openapi.document["paths"].get(path, {})
        if m in {"get", "put", "post", "delete", "patch", "options", "head", "trace"}
    }
    assert declared == methods


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), RENT_BILL_OPERATIONS
)
def test_rent_bill_operation_has_operation_id(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["operationId"] == operation_id


# (method, path): the error statuses the operation documents. 401 is not declared.
DECLARED_ERROR_STATUSES = {
    ("get", "/rent-bills"): {"403", "422"},
    ("get", "/rent-bills/{rentBillId}"): {"403", "404", "422"},
    ("put", "/rent-bills/{rentBillId}/receipt"): {"403", "404", "409", "422"},
    ("get", "/rent-bills/{rentBillId}/receipt"): {"403", "404", "422"},
    ("post", "/rent-bills/{rentBillId}/verification"): {"403", "404", "409", "422"},
    ("post", "/rent-bills/{rentBillId}/rejection"): {"403", "404", "409", "422"},
    ("post", "/rent-bills/{rentBillId}/cash-payment"): {"403", "404", "409", "422"},
    ("post", "/rent-bills/{rentBillId}/status-changes"): {"403", "404", "422"},
}


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), RENT_BILL_OPERATIONS
)
def test_rent_bill_operation_declares_its_success_and_error_statuses(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    responses = set(openapi.operation(method, path)["responses"])
    errors = DECLARED_ERROR_STATUSES.get((method, path), {"422"})
    assert responses == {str(status)} | errors


@pytest.mark.parametrize(
    ("method", "path"),
    [pytest.param(m, p, id=p + ":" + m) for (m, p) in DECLARED_ERROR_STATUSES],
)
def test_rent_bill_error_responses_carry_the_error_body(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    responses = openapi.operation(method, path)["responses"]
    for status in DECLARED_ERROR_STATUSES[(method, path)] - {"422"}:
        schema = openapi.resolve(
            responses[status]["content"]["application/json"]["schema"]
        )
        assert {"code", "field", "message"} <= _property_names(schema)


@pytest.mark.parametrize(("method", "path", "name"), RENT_BILL_PATH_PARAMETERS)
def test_rent_bill_operation_declares_one_required_uuid_path_parameter(
    openapi: OpenApiDoc, method: str, path: str, name: str
) -> None:
    parameters = openapi.operation(method, path)["parameters"]
    path_parameters = [p for p in parameters if p["in"] == "path"]
    assert [p["name"] for p in path_parameters] == [name]
    (parameter,) = path_parameters
    assert parameter["required"] is True
    _assert_uuid_string(parameter["schema"])


def test_list_rent_bills_declares_no_path_parameters(openapi: OpenApiDoc) -> None:
    parameters = openapi.operation("get", "/rent-bills").get("parameters", [])
    assert [p for p in parameters if p["in"] == "path"] == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/rent-bills/{rentBillId}"),
        ("put", "/rent-bills/{rentBillId}/receipt"),
        ("get", "/rent-bills/{rentBillId}/receipt"),
        ("post", "/rent-bills/{rentBillId}/verification"),
        ("post", "/rent-bills/{rentBillId}/rejection"),
        ("post", "/rent-bills/{rentBillId}/cash-payment"),
        ("post", "/rent-bills/{rentBillId}/status-changes"),
    ],
)
def test_single_bill_operation_declares_no_query_parameters(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert _query_parameters(openapi, method, path) == {}


# Query parameters


def test_list_rent_bills_declares_exactly_tenant_and_payment_status_filters(
    openapi: OpenApiDoc,
) -> None:
    assert set(_query_parameters(openapi, "get", "/rent-bills")) == {
        "tenantId",
        "propertyId",
        "paymentStatus",
    }


@pytest.mark.parametrize("name", ["tenantId", "propertyId", "paymentStatus"])
def test_list_rent_bills_filter_is_optional(openapi: OpenApiDoc, name: str) -> None:
    parameter = _query_parameters(openapi, "get", "/rent-bills")[name]
    assert parameter.get("required", False) is False


def test_list_rent_bills_tenant_id_filter_is_uuid_string(openapi: OpenApiDoc) -> None:
    parameter = _query_parameters(openapi, "get", "/rent-bills")["tenantId"]
    _assert_uuid_string(_unwrap_optional(parameter["schema"]))


def test_list_rent_bills_property_id_filter_is_uuid_string(
    openapi: OpenApiDoc,
) -> None:
    parameter = _query_parameters(openapi, "get", "/rent-bills")["propertyId"]
    _assert_uuid_string(_unwrap_optional(parameter["schema"]))


def test_list_rent_bills_payment_status_filter_is_a_repeatable_payment_status(
    openapi: OpenApiDoc,
) -> None:
    parameter = _query_parameters(openapi, "get", "/rent-bills")["paymentStatus"]
    schema = _unwrap_optional(parameter["schema"])
    assert schema["type"] == "array"
    assert openapi.ref_name(schema["items"]) == "PaymentStatus"
    assert parameter.get("explode", True) is True


def test_payment_overview_declares_exactly_the_date_query_parameter(
    openapi: OpenApiDoc,
) -> None:
    path = "/properties/{propertyId}/payment-overview"
    assert set(_query_parameters(openapi, "get", path)) == {"date"}


def test_payment_overview_date_is_optional_date_string(openapi: OpenApiDoc) -> None:
    path = "/properties/{propertyId}/payment-overview"
    parameter = _query_parameters(openapi, "get", path)["date"]
    assert parameter.get("required", False) is False
    _assert_date_string(_unwrap_optional(parameter["schema"]))


# Request and response schema references


@pytest.mark.parametrize(
    ("path", "schema"),
    [
        ("/rent-bills/{rentBillId}/rejection", "ReceiptRejectionInput"),
        ("/rent-bills/{rentBillId}/cash-payment", "CashPaymentInput"),
        ("/rent-bills/{rentBillId}/status-changes", "PaymentStatusChangeInput"),
    ],
    ids=["reject_receipt", "record_cash_payment", "change_payment_status"],
)
def test_rent_bill_write_operation_request_body_schema(
    openapi: OpenApiDoc, path: str, schema: str
) -> None:
    assert openapi.request_schema_ref("post", path) == schema


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/rent-bills"),
        ("get", "/rent-bills/{rentBillId}"),
        ("get", "/rent-bills/{rentBillId}/receipt"),
        ("post", "/rent-bills/{rentBillId}/verification"),
        ("get", "/properties/{propertyId}/payment-overview"),
    ],
    ids=[
        "list_rent_bills",
        "get_rent_bill",
        "get_receipt",
        "verify_receipt",
        "get_payment_overview",
    ],
)
def test_rent_bill_operations_without_input_take_no_request_body(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert "requestBody" not in openapi.operation(method, path)


@pytest.mark.parametrize(
    ("method", "path", "status", "schema"),
    [
        ("get", "/rent-bills", 200, "RentBillList"),
        ("get", "/rent-bills/{rentBillId}", 200, "RentBill"),
        ("put", "/rent-bills/{rentBillId}/receipt", 200, "RentBill"),
        ("post", "/rent-bills/{rentBillId}/verification", 200, "RentBill"),
        ("post", "/rent-bills/{rentBillId}/rejection", 200, "RentBill"),
        ("post", "/rent-bills/{rentBillId}/cash-payment", 200, "RentBill"),
        ("post", "/rent-bills/{rentBillId}/status-changes", 201, "RentBill"),
        ("get", "/properties/{propertyId}/payment-overview", 200, "PaymentOverview"),
    ],
    ids=[
        "list_rent_bills",
        "get_rent_bill",
        "upload_receipt",
        "verify_receipt",
        "reject_receipt",
        "record_cash_payment",
        "change_payment_status",
        "get_payment_overview",
    ],
)
def test_rent_bill_operation_response_schema(
    openapi: OpenApiDoc, method: str, path: str, status: int, schema: str
) -> None:
    assert openapi.response_schema_ref(method, path, status) == schema


# Receipt upload and download


def test_upload_receipt_requires_multipart_form_data_body(openapi: OpenApiDoc) -> None:
    body = openapi.operation("put", "/rent-bills/{rentBillId}/receipt")["requestBody"]
    assert body["required"] is True
    assert set(body["content"]) == {"multipart/form-data"}


@pytest.fixture
def upload_form_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    body = openapi.operation("put", "/rent-bills/{rentBillId}/receipt")["requestBody"]
    return openapi.resolve(body["content"]["multipart/form-data"]["schema"])


def test_upload_receipt_form_has_exactly_the_file_field(
    upload_form_schema: dict[str, Any],
) -> None:
    assert _property_names(upload_form_schema) == {"file"}


def test_upload_receipt_form_requires_the_file_field(
    upload_form_schema: dict[str, Any],
) -> None:
    assert set(upload_form_schema["required"]) == {"file"}


def test_upload_receipt_file_field_is_binary_string(
    upload_form_schema: dict[str, Any],
) -> None:
    schema = upload_form_schema["properties"]["file"]
    assert schema["type"] == "string"
    assert schema["format"] == "binary"


def test_get_receipt_responds_with_jpeg_and_png_images_only(
    openapi: OpenApiDoc,
) -> None:
    responses = openapi.operation("get", "/rent-bills/{rentBillId}/receipt")[
        "responses"
    ]
    assert set(responses["200"]["content"]) == {"image/jpeg", "image/png"}


@pytest.mark.parametrize("content_type", ["image/jpeg", "image/png"])
def test_get_receipt_image_response_is_binary(
    openapi: OpenApiDoc, content_type: str
) -> None:
    responses = openapi.operation("get", "/rent-bills/{rentBillId}/receipt")[
        "responses"
    ]
    schema = responses["200"]["content"][content_type].get("schema", {})
    assert "$ref" not in schema
    assert schema.get("format", "binary") == "binary"


# Component schemas


@pytest.mark.parametrize("name", RENT_BILL_COMPONENTS)
def test_rent_bill_component_schema_is_declared(openapi: OpenApiDoc, name: str) -> None:
    assert name in openapi.components


@pytest.mark.parametrize("name", RENT_BILL_COMPONENTS)
@pytest.mark.parametrize("suffix", ["-Input", "-Output"])
def test_rent_bill_component_schema_is_not_split_into_input_and_output_variants(
    openapi: OpenApiDoc, name: str, suffix: str
) -> None:
    assert f"{name}{suffix}" not in openapi.components


@pytest.mark.parametrize("name", RENT_BILL_COMPONENTS)
def test_rent_bill_component_property_names_contain_no_underscore(
    openapi: OpenApiDoc, name: str
) -> None:
    offenders = [p for p in _property_names(openapi.component(name)) if "_" in p]
    assert offenders == []


# Enums


def test_payment_status_is_string_enum_of_its_statuses(openapi: OpenApiDoc) -> None:
    _assert_string_enum(openapi.component("PaymentStatus"), PAYMENT_STATUSES)


def test_payment_method_is_string_enum_of_its_methods(openapi: OpenApiDoc) -> None:
    _assert_string_enum(openapi.component("PaymentMethod"), PAYMENT_METHODS)


# TenantRef


@pytest.fixture
def tenant_ref_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("TenantRef")


def test_tenant_ref_has_exactly_id_and_name(tenant_ref_schema: dict[str, Any]) -> None:
    assert _property_names(tenant_ref_schema) == {"id", "name"}


def test_tenant_ref_requires_id_and_name(tenant_ref_schema: dict[str, Any]) -> None:
    assert set(tenant_ref_schema["required"]) == {"id", "name"}


def test_tenant_ref_id_is_uuid_string(tenant_ref_schema: dict[str, Any]) -> None:
    _assert_uuid_string(tenant_ref_schema["properties"]["id"])


def test_tenant_ref_name_is_string(tenant_ref_schema: dict[str, Any]) -> None:
    assert tenant_ref_schema["properties"]["name"]["type"] == "string"


# Payment

PAYMENT_FIELDS = {"status", "method", "paidOn", "hasReceipt", "rejectionReason"}


@pytest.fixture
def payment_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("Payment")


def test_payment_has_exactly_its_fields(payment_schema: dict[str, Any]) -> None:
    assert _property_names(payment_schema) == PAYMENT_FIELDS


def test_payment_requires_every_field(payment_schema: dict[str, Any]) -> None:
    assert set(payment_schema["required"]) == PAYMENT_FIELDS


def test_payment_status_is_payment_status(
    openapi: OpenApiDoc, payment_schema: dict[str, Any]
) -> None:
    assert openapi.ref_name(payment_schema["properties"]["status"]) == "PaymentStatus"


def test_payment_method_is_nullable_payment_method(
    openapi: OpenApiDoc, payment_schema: dict[str, Any]
) -> None:
    schema = payment_schema["properties"]["method"]
    assert openapi.ref_name(nullable_inner(schema)) == "PaymentMethod"


def test_payment_paid_on_is_nullable_date_string(
    payment_schema: dict[str, Any],
) -> None:
    _assert_date_string(nullable_inner(payment_schema["properties"]["paidOn"]))


def test_payment_has_receipt_is_boolean(payment_schema: dict[str, Any]) -> None:
    assert payment_schema["properties"]["hasReceipt"]["type"] == "boolean"


def test_payment_rejection_reason_is_nullable_string(
    payment_schema: dict[str, Any],
) -> None:
    schema = payment_schema["properties"]["rejectionReason"]
    assert nullable_inner(schema)["type"] == "string"


# RentBillSummary and RentBill

SUMMARY_FIELDS = {
    "id",
    "tenant",
    "room",
    "periodStart",
    "periodEnd",
    "dueDate",
    "amount",
    "daysOverdue",
    "payment",
    "property",
    "isCurrent",
    "canUploadReceipt",
}

RENT_BILL_FIELDS = {*SUMMARY_FIELDS, "bankAccount", "statusChanges"}


@pytest.fixture(params=["RentBill", "RentBillSummary"])
def any_rent_bill_schema(
    request: pytest.FixtureRequest, openapi: OpenApiDoc
) -> dict[str, Any]:
    return openapi.component(request.param)


def test_rent_bill_has_exactly_its_fields(openapi: OpenApiDoc) -> None:
    assert _property_names(openapi.component("RentBill")) == RENT_BILL_FIELDS


def test_rent_bill_requires_every_field(openapi: OpenApiDoc) -> None:
    assert set(openapi.component("RentBill")["required"]) == RENT_BILL_FIELDS


def test_rent_bill_summary_has_exactly_the_rent_bill_fields_without_detail_only_fields(
    openapi: OpenApiDoc,
) -> None:
    assert _property_names(openapi.component("RentBillSummary")) == SUMMARY_FIELDS


def test_rent_bill_summary_requires_every_field(openapi: OpenApiDoc) -> None:
    assert set(openapi.component("RentBillSummary")["required"]) == SUMMARY_FIELDS


def test_rent_bill_id_is_uuid_string(any_rent_bill_schema: dict[str, Any]) -> None:
    _assert_uuid_string(any_rent_bill_schema["properties"]["id"])


def test_rent_bill_tenant_is_tenant_ref(
    openapi: OpenApiDoc, any_rent_bill_schema: dict[str, Any]
) -> None:
    schema = any_rent_bill_schema["properties"]["tenant"]
    assert openapi.ref_name(schema) == "TenantRef"


def test_rent_bill_room_is_room_ref(
    openapi: OpenApiDoc, any_rent_bill_schema: dict[str, Any]
) -> None:
    assert openapi.ref_name(any_rent_bill_schema["properties"]["room"]) == "RoomRef"


@pytest.mark.parametrize("field", ["periodStart", "periodEnd", "dueDate"])
def test_rent_bill_date_is_date_string(
    any_rent_bill_schema: dict[str, Any], field: str
) -> None:
    _assert_date_string(any_rent_bill_schema["properties"][field])


def test_rent_bill_amount_is_integer(any_rent_bill_schema: dict[str, Any]) -> None:
    assert any_rent_bill_schema["properties"]["amount"]["type"] == "integer"


def test_rent_bill_days_overdue_is_non_negative_integer(
    any_rent_bill_schema: dict[str, Any],
) -> None:
    schema = any_rent_bill_schema["properties"]["daysOverdue"]
    assert schema["type"] == "integer"
    assert schema["minimum"] == 0


def test_rent_bill_status_changes_is_array_of_payment_status_change(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component("RentBill")["properties"]["statusChanges"]
    assert schema["type"] == "array"
    assert openapi.ref_name(schema["items"]) == "PaymentStatusChange"


def test_rent_bill_summary_does_not_declare_status_changes(
    openapi: OpenApiDoc,
) -> None:
    assert "statusChanges" not in _property_names(openapi.component("RentBillSummary"))


def test_payment_overview_item_bill_carries_days_overdue(openapi: OpenApiDoc) -> None:
    item = openapi.component("PaymentOverviewItem")
    bill = openapi.component(
        openapi.ref_name(nullable_inner(item["properties"]["bill"]))
    )
    assert bill["properties"]["daysOverdue"]["minimum"] == 0
    assert "daysOverdue" in bill["required"]


# PaymentStatusChange

STATUS_CHANGE_FIELDS = {
    "status",
    "method",
    "reason",
    "manual",
    "actorName",
    "changedAt",
}


@pytest.fixture
def status_change_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("PaymentStatusChange")


def test_payment_status_change_has_exactly_its_fields(
    status_change_schema: dict[str, Any],
) -> None:
    assert _property_names(status_change_schema) == STATUS_CHANGE_FIELDS


def test_payment_status_change_requires_every_field(
    status_change_schema: dict[str, Any],
) -> None:
    assert set(status_change_schema["required"]) == STATUS_CHANGE_FIELDS


def test_payment_status_change_status_is_payment_status(
    openapi: OpenApiDoc, status_change_schema: dict[str, Any]
) -> None:
    schema = status_change_schema["properties"]["status"]
    assert openapi.ref_name(schema) == "PaymentStatus"


def test_payment_status_change_method_is_nullable_payment_method(
    openapi: OpenApiDoc, status_change_schema: dict[str, Any]
) -> None:
    schema = status_change_schema["properties"]["method"]
    assert openapi.ref_name(nullable_inner(schema)) == "PaymentMethod"


@pytest.mark.parametrize("field", ["reason", "actorName"])
def test_payment_status_change_text_field_is_nullable_string(
    status_change_schema: dict[str, Any], field: str
) -> None:
    schema = status_change_schema["properties"][field]
    assert nullable_inner(schema)["type"] == "string"


def test_payment_status_change_manual_is_boolean(
    status_change_schema: dict[str, Any],
) -> None:
    assert status_change_schema["properties"]["manual"]["type"] == "boolean"


def test_payment_status_change_changed_at_is_date_time_string(
    status_change_schema: dict[str, Any],
) -> None:
    schema = status_change_schema["properties"]["changedAt"]
    assert schema["type"] == "string"
    assert schema["format"] == "date-time"


def test_rent_bill_payment_is_payment(
    openapi: OpenApiDoc, any_rent_bill_schema: dict[str, Any]
) -> None:
    schema = any_rent_bill_schema["properties"]["payment"]
    assert openapi.ref_name(schema) == "Payment"


def test_rent_bill_property_is_property_ref(
    openapi: OpenApiDoc, any_rent_bill_schema: dict[str, Any]
) -> None:
    schema = any_rent_bill_schema["properties"]["property"]
    assert openapi.ref_name(schema) == "PropertyRef"


@pytest.mark.parametrize("field", ["isCurrent", "canUploadReceipt"])
def test_rent_bill_flag_is_boolean(
    any_rent_bill_schema: dict[str, Any], field: str
) -> None:
    assert any_rent_bill_schema["properties"][field]["type"] == "boolean"


@pytest.mark.parametrize("field", ["isCurrent", "canUploadReceipt"])
def test_rent_bill_flag_is_described(
    any_rent_bill_schema: dict[str, Any], field: str
) -> None:
    assert any_rent_bill_schema["properties"][field]["description"].strip()


def test_rent_bill_bank_account_is_nullable_bank_account(openapi: OpenApiDoc) -> None:
    schema = openapi.component("RentBill")["properties"]["bankAccount"]
    assert openapi.ref_name(nullable_inner(schema)) == "BankAccount"


# RentBillList


def test_rent_bill_list_items_is_required_array_of_rent_bill_summary(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component("RentBillList")
    assert _property_names(schema) == {"items"}
    assert set(schema["required"]) == {"items"}
    items = schema["properties"]["items"]
    assert items["type"] == "array"
    assert openapi.ref_name(items["items"]) == "RentBillSummary"


# ReceiptRejectionInput


@pytest.fixture
def rejection_input_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("ReceiptRejectionInput")


def test_rejection_input_has_only_required_reason(
    rejection_input_schema: dict[str, Any],
) -> None:
    assert _property_names(rejection_input_schema) == {"reason"}
    assert set(rejection_input_schema["required"]) == {"reason"}


def test_rejection_input_reason_is_non_empty_string(
    rejection_input_schema: dict[str, Any],
) -> None:
    schema = rejection_input_schema["properties"]["reason"]
    assert schema["type"] == "string"
    assert schema["minLength"] == 1


# CashPaymentInput


@pytest.fixture
def cash_payment_input_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("CashPaymentInput")


def test_cash_payment_input_has_only_required_received_on(
    cash_payment_input_schema: dict[str, Any],
) -> None:
    assert _property_names(cash_payment_input_schema) == {"receivedOn"}
    assert set(cash_payment_input_schema["required"]) == {"receivedOn"}


def test_cash_payment_input_received_on_is_date_string(
    cash_payment_input_schema: dict[str, Any],
) -> None:
    _assert_date_string(cash_payment_input_schema["properties"]["receivedOn"])


def test_cash_payment_input_received_on_is_described(
    cash_payment_input_schema: dict[str, Any],
) -> None:
    assert cash_payment_input_schema["properties"]["receivedOn"]["description"].strip()


# PaymentStatusChangeInput


@pytest.fixture
def status_change_input_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("PaymentStatusChangeInput")


def test_status_change_input_has_exactly_status_reason_method_and_received_on(
    status_change_input_schema: dict[str, Any],
) -> None:
    assert _property_names(status_change_input_schema) == {
        "status",
        "reason",
        "method",
        "receivedOn",
    }


def test_status_change_input_method_is_optional_nullable_payment_method(
    openapi: OpenApiDoc, status_change_input_schema: dict[str, Any]
) -> None:
    schema = status_change_input_schema["properties"]["method"]
    assert openapi.ref_name(nullable_inner(schema)) == "PaymentMethod"
    assert "method" not in status_change_input_schema["required"]


def test_status_change_input_received_on_is_optional_nullable_date(
    status_change_input_schema: dict[str, Any],
) -> None:
    schema = status_change_input_schema["properties"]["receivedOn"]
    _assert_date_string(nullable_inner(schema))
    assert "receivedOn" not in status_change_input_schema["required"]


@pytest.mark.parametrize("field", ["method", "receivedOn"])
def test_status_change_input_conditional_field_is_described(
    status_change_input_schema: dict[str, Any], field: str
) -> None:
    assert status_change_input_schema["properties"][field]["description"].strip()


def test_status_change_input_requires_status_and_reason(
    status_change_input_schema: dict[str, Any],
) -> None:
    assert set(status_change_input_schema["required"]) == {"status", "reason"}


def test_status_change_input_status_allows_only_manual_target_statuses(
    openapi: OpenApiDoc, status_change_input_schema: dict[str, Any]
) -> None:
    schema = openapi.resolve(status_change_input_schema["properties"]["status"])
    _assert_string_enum(schema, MANUAL_TARGET_STATUSES)


def test_status_change_input_reason_is_non_empty_string(
    status_change_input_schema: dict[str, Any],
) -> None:
    schema = status_change_input_schema["properties"]["reason"]
    assert schema["type"] == "string"
    assert schema["minLength"] == 1


# PaymentOverviewItem and PaymentOverview


@pytest.fixture
def overview_item_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("PaymentOverviewItem")


def test_payment_overview_item_has_exactly_its_fields(
    overview_item_schema: dict[str, Any],
) -> None:
    assert _property_names(overview_item_schema) == {"tenant", "room", "bill"}


def test_payment_overview_item_requires_every_field(
    overview_item_schema: dict[str, Any],
) -> None:
    assert set(overview_item_schema["required"]) == {"tenant", "room", "bill"}


def test_payment_overview_item_tenant_is_tenant_ref(
    openapi: OpenApiDoc, overview_item_schema: dict[str, Any]
) -> None:
    assert openapi.ref_name(overview_item_schema["properties"]["tenant"]) == "TenantRef"


def test_payment_overview_item_room_is_room_ref(
    openapi: OpenApiDoc, overview_item_schema: dict[str, Any]
) -> None:
    assert openapi.ref_name(overview_item_schema["properties"]["room"]) == "RoomRef"


def test_payment_overview_item_bill_is_nullable_rent_bill_summary(
    openapi: OpenApiDoc, overview_item_schema: dict[str, Any]
) -> None:
    schema = overview_item_schema["properties"]["bill"]
    assert openapi.ref_name(nullable_inner(schema)) == "RentBillSummary"


def test_payment_overview_has_exactly_required_date_and_items(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component("PaymentOverview")
    assert _property_names(schema) == {"date", "items"}
    assert set(schema["required"]) == {"date", "items"}


def test_payment_overview_date_is_date_string(openapi: OpenApiDoc) -> None:
    schema = openapi.component("PaymentOverview")["properties"]["date"]
    _assert_date_string(schema)


def test_payment_overview_items_is_array_of_payment_overview_item(
    openapi: OpenApiDoc,
) -> None:
    items = openapi.component("PaymentOverview")["properties"]["items"]
    assert items["type"] == "array"
    assert openapi.ref_name(items["items"]) == "PaymentOverviewItem"
