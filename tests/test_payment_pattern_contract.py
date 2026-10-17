"""Contract tests for the payment pattern endpoint."""

from typing import Any

import pytest
from conftest import NOT_A_UUID, PROPERTY_ID, OpenApiDoc, nullable_inner

PATH = "/properties/{propertyId}/payment-patterns"
URL = f"/properties/{PROPERTY_ID}/payment-patterns"

PATTERN_FIELDS = {
    "tenant",
    "room",
    "onTimeCount",
    "countedBillCount",
    "averageDaysLate",
    "arrears",
    "atRisk",
    "summary",
    "summaryWithheld",
}


@pytest.fixture
def pattern_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("PaymentPattern")


# Path and operation


def test_payment_patterns_path_declares_exactly_get(openapi: OpenApiDoc) -> None:
    methods = {
        m
        for m in openapi.document["paths"].get(PATH, {})
        if m in {"get", "put", "post", "delete", "patch", "options", "head", "trace"}
    }
    assert methods == {"get"}


def test_get_payment_patterns_has_operation_id(openapi: OpenApiDoc) -> None:
    assert openapi.operation("get", PATH)["operationId"] == "get_payment_patterns"


def test_get_payment_patterns_is_tagged_like_payment_overview(
    openapi: OpenApiDoc,
) -> None:
    overview = openapi.operation("get", "/properties/{propertyId}/payment-overview")
    assert openapi.operation("get", PATH)["tags"] == overview["tags"]


def test_get_payment_patterns_declares_only_ok_besides_validation_error(
    openapi: OpenApiDoc,
) -> None:
    assert set(openapi.operation("get", PATH)["responses"]) - {"422"} == {"200"}


def test_get_payment_patterns_declares_one_required_uuid_path_parameter(
    openapi: OpenApiDoc,
) -> None:
    parameters = openapi.operation("get", PATH)["parameters"]
    path_parameters = [p for p in parameters if p["in"] == "path"]
    assert [p["name"] for p in path_parameters] == ["propertyId"]
    (parameter,) = path_parameters
    assert parameter["required"] is True
    assert parameter["schema"]["type"] == "string"
    assert parameter["schema"]["format"] == "uuid"


def test_get_payment_patterns_declares_no_query_parameters(
    openapi: OpenApiDoc,
) -> None:
    parameters = openapi.operation("get", PATH).get("parameters", [])
    assert [p for p in parameters if p["in"] == "query"] == []


def test_get_payment_patterns_takes_no_request_body(openapi: OpenApiDoc) -> None:
    assert "requestBody" not in openapi.operation("get", PATH)


def test_get_payment_patterns_responds_with_payment_pattern_list(
    openapi: OpenApiDoc,
) -> None:
    assert openapi.response_schema_ref("get", PATH, 200) == "PaymentPatternList"


# Component schemas


@pytest.mark.parametrize("name", ["PaymentPattern", "PaymentPatternList"])
def test_payment_pattern_component_schema_is_declared(
    openapi: OpenApiDoc, name: str
) -> None:
    assert name in openapi.components


@pytest.mark.parametrize("name", ["PaymentPattern", "PaymentPatternList"])
@pytest.mark.parametrize("suffix", ["-Input", "-Output"])
def test_payment_pattern_component_schema_is_not_split_into_input_and_output_variants(
    openapi: OpenApiDoc, name: str, suffix: str
) -> None:
    assert f"{name}{suffix}" not in openapi.components


def test_payment_pattern_property_names_contain_no_underscore(
    pattern_schema: dict[str, Any],
) -> None:
    assert [p for p in pattern_schema["properties"] if "_" in p] == []


def test_payment_pattern_has_exactly_its_fields(
    pattern_schema: dict[str, Any],
) -> None:
    assert set(pattern_schema["properties"]) == PATTERN_FIELDS


def test_payment_pattern_requires_every_field(pattern_schema: dict[str, Any]) -> None:
    assert set(pattern_schema["required"]) == PATTERN_FIELDS


def test_payment_pattern_tenant_is_tenant_ref(
    openapi: OpenApiDoc, pattern_schema: dict[str, Any]
) -> None:
    assert openapi.ref_name(pattern_schema["properties"]["tenant"]) == "TenantRef"


def test_payment_pattern_room_is_room_ref(
    openapi: OpenApiDoc, pattern_schema: dict[str, Any]
) -> None:
    assert openapi.ref_name(pattern_schema["properties"]["room"]) == "RoomRef"


@pytest.mark.parametrize(
    ("field", "maximum"),
    [
        ("onTimeCount", None),
        ("countedBillCount", 6),
        ("averageDaysLate", None),
        ("arrears", None),
    ],
)
def test_payment_pattern_count_is_bounded_integer(
    pattern_schema: dict[str, Any], field: str, maximum: int | None
) -> None:
    schema = pattern_schema["properties"][field]
    assert schema["type"] == "integer"
    assert schema["minimum"] == 0
    if maximum is None:
        assert "maximum" not in schema
    else:
        assert schema["maximum"] == maximum


@pytest.mark.parametrize("field", ["atRisk", "summaryWithheld"])
def test_payment_pattern_flag_is_boolean(
    pattern_schema: dict[str, Any], field: str
) -> None:
    assert pattern_schema["properties"][field]["type"] == "boolean"


def test_payment_pattern_summary_is_nullable_string(
    pattern_schema: dict[str, Any],
) -> None:
    assert nullable_inner(pattern_schema["properties"]["summary"])["type"] == "string"


def test_payment_pattern_list_has_only_required_array_of_payment_pattern(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component("PaymentPatternList")
    assert set(schema["properties"]) == {"items"}
    assert set(schema["required"]) == {"items"}
    items = schema["properties"]["items"]
    assert items["type"] == "array"
    assert openapi.ref_name(items["items"]) == "PaymentPattern"


# Runtime


def test_valid_payment_patterns_request_responds_not_implemented(client) -> None:
    assert client.get(URL).status_code == 501


def test_non_uuid_property_id_is_rejected_with_validation_error(client) -> None:
    response = client.get(f"/properties/{NOT_A_UUID}/payment-patterns")
    assert response.status_code == 422
