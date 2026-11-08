"""Contract tests for the current-leases endpoint."""

from typing import Any

import pytest
from conftest import OpenApiDoc, nullable_inner

LEASES_PATH = "/me/leases"
LEASE_PATH_GONE = "/me/lease"
ROOM_FIELDS = {"id", "number", "facilities", "lengthM", "widthM"}
LEASE_FIELDS = {
    "tenantId",
    "room",
    "property",
    "startDate",
    "endDate",
    "rent",
    "billingCycle",
}


def _property_names(schema: dict[str, Any]) -> set[str]:
    return set(schema.get("properties", {}))


def _assert_uuid_string(schema: dict[str, Any]) -> None:
    assert schema["type"] == "string"
    assert schema["format"] == "uuid"


def _assert_date_string(schema: dict[str, Any]) -> None:
    assert schema["type"] == "string"
    assert schema["format"] == "date"


@pytest.fixture
def list_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component(openapi.response_schema_ref("get", LEASES_PATH, 200))


@pytest.fixture
def lease_name(openapi: OpenApiDoc, list_schema: dict[str, Any]) -> str:
    return openapi.ref_name(list_schema["properties"]["items"]["items"])


@pytest.fixture
def lease_schema(openapi: OpenApiDoc, lease_name: str) -> dict[str, Any]:
    return openapi.component(lease_name)


@pytest.fixture
def room_name(openapi: OpenApiDoc, lease_schema: dict[str, Any]) -> str:
    return openapi.ref_name(lease_schema["properties"]["room"])


@pytest.fixture
def room_schema(openapi: OpenApiDoc, room_name: str) -> dict[str, Any]:
    return openapi.component(room_name)


# Path and operation


def test_leases_path_declares_only_get(openapi: OpenApiDoc) -> None:
    declared = {
        m
        for m in openapi.document["paths"].get(LEASES_PATH, {})
        if m in {"get", "put", "post", "delete", "patch", "options", "head", "trace"}
    }
    assert declared == {"get"}


def test_the_single_lease_path_is_no_longer_declared(openapi: OpenApiDoc) -> None:
    assert LEASE_PATH_GONE not in openapi.document["paths"]


def test_get_my_leases_declares_only_ok_besides_validation_error(
    openapi: OpenApiDoc,
) -> None:
    responses = set(openapi.operation("get", LEASES_PATH)["responses"])
    assert responses - {"422"} == {"200"}


def test_get_my_leases_declares_no_parameters(openapi: OpenApiDoc) -> None:
    assert openapi.operation("get", LEASES_PATH).get("parameters", []) == []


def test_get_my_leases_takes_no_request_body(openapi: OpenApiDoc) -> None:
    assert "requestBody" not in openapi.operation("get", LEASES_PATH)


def test_the_old_single_lease_result_is_gone(openapi: OpenApiDoc) -> None:
    assert "CurrentLeaseResult" not in openapi.components


def test_lease_component_schemas_are_not_split_into_input_and_output_variants(
    openapi: OpenApiDoc, list_schema, lease_name: str, room_name: str
) -> None:
    names = [
        lease_name,
        room_name,
        openapi.response_schema_ref("get", LEASES_PATH, 200),
    ]
    for name in names:
        for suffix in ("-Input", "-Output"):
            assert f"{name}{suffix}" not in openapi.components


def test_lease_component_property_names_contain_no_underscore(
    list_schema, lease_schema, room_schema
) -> None:
    for schema in (list_schema, lease_schema, room_schema):
        assert [p for p in _property_names(schema) if "_" in p] == []


# The list


def test_the_list_has_only_required_items(list_schema: dict[str, Any]) -> None:
    assert _property_names(list_schema) == {"items"}
    assert set(list_schema["required"]) == {"items"}


def test_the_items_are_an_array_of_leases(list_schema: dict[str, Any]) -> None:
    schema = list_schema["properties"]["items"]
    assert schema["type"] == "array"
    assert "$ref" in schema["items"]


# The lease


def test_a_lease_has_exactly_its_fields(lease_schema: dict[str, Any]) -> None:
    assert _property_names(lease_schema) == LEASE_FIELDS


def test_a_lease_requires_every_field(lease_schema: dict[str, Any]) -> None:
    assert set(lease_schema["required"]) == LEASE_FIELDS


def test_a_lease_tenant_id_is_a_uuid_string(lease_schema: dict[str, Any]) -> None:
    _assert_uuid_string(lease_schema["properties"]["tenantId"])


def test_a_lease_property_is_a_component_with_id_name_and_address(
    openapi: OpenApiDoc, lease_schema: dict[str, Any]
) -> None:
    schema = openapi.resolve(lease_schema["properties"]["property"])
    assert _property_names(schema) == {"id", "name", "address"}
    assert set(schema["required"]) == {"id", "name", "address"}
    _assert_uuid_string(schema["properties"]["id"])
    assert schema["properties"]["name"]["type"] == "string"
    assert schema["properties"]["address"]["type"] == "string"


def test_a_lease_property_is_not_nullable(lease_schema: dict[str, Any]) -> None:
    schema = lease_schema["properties"]["property"]
    assert "$ref" in schema
    assert "anyOf" not in schema


def test_a_lease_rent_is_integer(lease_schema: dict[str, Any]) -> None:
    assert lease_schema["properties"]["rent"]["type"] == "integer"


def test_a_lease_billing_cycle_is_the_billing_cycle_enum(
    openapi: OpenApiDoc, lease_schema: dict[str, Any]
) -> None:
    schema = lease_schema["properties"]["billingCycle"]
    assert openapi.ref_name(schema) == "BillingCycle"


def test_a_lease_room_is_not_nullable(lease_schema: dict[str, Any]) -> None:
    schema = lease_schema["properties"]["room"]
    assert "$ref" in schema
    assert "anyOf" not in schema


@pytest.mark.parametrize("field", ["startDate", "endDate"])
def test_a_lease_date_is_nullable_date_string(
    lease_schema: dict[str, Any], field: str
) -> None:
    _assert_date_string(nullable_inner(lease_schema["properties"][field]))


# The room


def test_the_room_has_exactly_its_fields(room_schema: dict[str, Any]) -> None:
    assert _property_names(room_schema) == ROOM_FIELDS


def test_the_room_requires_every_field(room_schema: dict[str, Any]) -> None:
    assert set(room_schema["required"]) == ROOM_FIELDS


@pytest.mark.parametrize("field", ["lengthM", "widthM"])
def test_the_room_dimension_is_nullable_number(
    room_schema: dict[str, Any], field: str
) -> None:
    inner = nullable_inner(room_schema["properties"][field])
    assert inner["type"] == "number"


def test_the_room_id_is_uuid_string(room_schema: dict[str, Any]) -> None:
    _assert_uuid_string(room_schema["properties"]["id"])


def test_the_room_number_is_string(room_schema: dict[str, Any]) -> None:
    assert room_schema["properties"]["number"]["type"] == "string"


def test_the_room_facilities_is_array_of_strings(room_schema: dict[str, Any]) -> None:
    schema = room_schema["properties"]["facilities"]
    assert schema["type"] == "array"
    assert schema["items"]["type"] == "string"
