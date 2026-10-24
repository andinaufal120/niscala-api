"""Contract tests for the current-lease endpoint."""

from typing import Any

import pytest
from conftest import OpenApiDoc, nullable_inner

LEASE_PATH = "/me/lease"
ROOM_FIELDS = {"id", "number", "facilities", "lengthM", "widthM"}


def _property_names(schema: dict[str, Any]) -> set[str]:
    return set(schema.get("properties", {}))


def _assert_uuid_string(schema: dict[str, Any]) -> None:
    assert schema["type"] == "string"
    assert schema["format"] == "uuid"


def _assert_date_string(schema: dict[str, Any]) -> None:
    assert schema["type"] == "string"
    assert schema["format"] == "date"


# Path and operation


def test_lease_path_declares_only_get(openapi: OpenApiDoc) -> None:
    declared = {
        m
        for m in openapi.document["paths"].get(LEASE_PATH, {})
        if m in {"get", "put", "post", "delete", "patch", "options", "head", "trace"}
    }
    assert declared == {"get"}


def test_get_my_lease_has_operation_id(openapi: OpenApiDoc) -> None:
    assert openapi.operation("get", LEASE_PATH)["operationId"] == "get_my_lease"


def test_get_my_lease_declares_only_ok_besides_validation_error(
    openapi: OpenApiDoc,
) -> None:
    responses = set(openapi.operation("get", LEASE_PATH)["responses"])
    assert responses - {"422"} == {"200"}


def test_get_my_lease_declares_no_parameters(openapi: OpenApiDoc) -> None:
    assert openapi.operation("get", LEASE_PATH).get("parameters", []) == []


def test_get_my_lease_takes_no_request_body(openapi: OpenApiDoc) -> None:
    assert "requestBody" not in openapi.operation("get", LEASE_PATH)


def test_get_my_lease_responds_with_current_lease_result(openapi: OpenApiDoc) -> None:
    assert openapi.response_schema_ref("get", LEASE_PATH, 200) == "CurrentLeaseResult"


@pytest.mark.parametrize(
    "name", ["CurrentLeaseResult", "CurrentLease", "CurrentLeaseRoom"]
)
def test_lease_component_schema_is_declared(openapi: OpenApiDoc, name: str) -> None:
    assert name in openapi.components


@pytest.mark.parametrize(
    "name", ["CurrentLeaseResult", "CurrentLease", "CurrentLeaseRoom"]
)
@pytest.mark.parametrize("suffix", ["-Input", "-Output"])
def test_lease_component_schema_is_not_split_into_input_and_output_variants(
    openapi: OpenApiDoc, name: str, suffix: str
) -> None:
    assert f"{name}{suffix}" not in openapi.components


@pytest.mark.parametrize(
    "name", ["CurrentLeaseResult", "CurrentLease", "CurrentLeaseRoom"]
)
def test_lease_component_property_names_contain_no_underscore(
    openapi: OpenApiDoc, name: str
) -> None:
    offenders = [p for p in _property_names(openapi.component(name)) if "_" in p]
    assert offenders == []


# CurrentLeaseResult


def test_current_lease_result_has_only_required_lease(openapi: OpenApiDoc) -> None:
    schema = openapi.component("CurrentLeaseResult")
    assert _property_names(schema) == {"lease"}
    assert set(schema["required"]) == {"lease"}


def test_current_lease_result_lease_is_nullable_current_lease(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component("CurrentLeaseResult")["properties"]["lease"]
    assert openapi.ref_name(nullable_inner(schema)) == "CurrentLease"


# CurrentLease


@pytest.fixture
def current_lease_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("CurrentLease")


CURRENT_LEASE_FIELDS = {
    "room",
    "property",
    "startDate",
    "endDate",
    "rent",
    "billingCycle",
}


def test_current_lease_has_exactly_its_fields(
    current_lease_schema: dict[str, Any],
) -> None:
    assert _property_names(current_lease_schema) == CURRENT_LEASE_FIELDS


def test_current_lease_requires_every_field(
    current_lease_schema: dict[str, Any],
) -> None:
    assert set(current_lease_schema["required"]) == CURRENT_LEASE_FIELDS


def test_current_lease_property_is_a_component_with_id_name_and_address(
    openapi: OpenApiDoc, current_lease_schema: dict[str, Any]
) -> None:
    schema = openapi.resolve(current_lease_schema["properties"]["property"])
    assert _property_names(schema) == {"id", "name", "address"}
    assert set(schema["required"]) == {"id", "name", "address"}
    _assert_uuid_string(schema["properties"]["id"])
    assert schema["properties"]["name"]["type"] == "string"
    assert schema["properties"]["address"]["type"] == "string"


def test_current_lease_property_is_not_nullable(
    current_lease_schema: dict[str, Any],
) -> None:
    schema = current_lease_schema["properties"]["property"]
    assert "$ref" in schema
    assert "anyOf" not in schema


def test_current_lease_rent_is_integer(
    current_lease_schema: dict[str, Any],
) -> None:
    assert current_lease_schema["properties"]["rent"]["type"] == "integer"


def test_current_lease_billing_cycle_is_the_billing_cycle_enum(
    openapi: OpenApiDoc, current_lease_schema: dict[str, Any]
) -> None:
    schema = current_lease_schema["properties"]["billingCycle"]
    assert openapi.ref_name(schema) == "BillingCycle"


def test_current_lease_room_is_current_lease_room(
    openapi: OpenApiDoc, current_lease_schema: dict[str, Any]
) -> None:
    schema = current_lease_schema["properties"]["room"]
    assert openapi.ref_name(schema) == "CurrentLeaseRoom"


@pytest.mark.parametrize("field", ["startDate", "endDate"])
def test_current_lease_date_is_nullable_date_string(
    current_lease_schema: dict[str, Any], field: str
) -> None:
    _assert_date_string(nullable_inner(current_lease_schema["properties"][field]))


# CurrentLeaseRoom


@pytest.fixture
def current_lease_room_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("CurrentLeaseRoom")


def test_current_lease_room_has_exactly_its_fields(
    current_lease_room_schema: dict[str, Any],
) -> None:
    assert _property_names(current_lease_room_schema) == ROOM_FIELDS


def test_current_lease_room_requires_every_field(
    current_lease_room_schema: dict[str, Any],
) -> None:
    assert set(current_lease_room_schema["required"]) == ROOM_FIELDS


@pytest.mark.parametrize("field", ["lengthM", "widthM"])
def test_current_lease_room_dimension_is_nullable_number(
    current_lease_room_schema: dict[str, Any], field: str
) -> None:
    inner = nullable_inner(current_lease_room_schema["properties"][field])
    assert inner["type"] == "number"


def test_current_lease_room_id_is_uuid_string(
    current_lease_room_schema: dict[str, Any],
) -> None:
    _assert_uuid_string(current_lease_room_schema["properties"]["id"])


def test_current_lease_room_number_is_string(
    current_lease_room_schema: dict[str, Any],
) -> None:
    assert current_lease_room_schema["properties"]["number"]["type"] == "string"


def test_current_lease_room_facilities_is_array_of_strings(
    current_lease_room_schema: dict[str, Any],
) -> None:
    schema = current_lease_room_schema["properties"]["facilities"]
    assert schema["type"] == "array"
    assert schema["items"]["type"] == "string"
