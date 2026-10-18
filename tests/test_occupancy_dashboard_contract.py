"""Contract tests for the occupancy dashboard endpoint."""

from typing import Any

import pytest
from conftest import OpenApiDoc

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "options", "head", "trace"}

PATH = "/occupancy-dashboard"

# Component name -> fields; every field is required.
COMPONENT_FIELDS: dict[str, set[str]] = {
    "OccupancyDashboard": {"summary", "items"},
    "OccupancySummary": {
        "propertyCount",
        "roomCount",
        "occupiedRoomCount",
        "vacantRoomCount",
        "occupancyPercentage",
    },
    "PropertyOccupancy": {
        "id",
        "name",
        "roomCount",
        "occupiedRoomCount",
        "vacantRoomCount",
        "occupancyPercentage",
        "rooms",
    },
    "OccupancyRoom": {"id", "number", "occupancy"},
}

COUNT_FIELDS = [
    ("OccupancySummary", "propertyCount"),
    ("OccupancySummary", "roomCount"),
    ("OccupancySummary", "occupiedRoomCount"),
    ("OccupancySummary", "vacantRoomCount"),
    ("PropertyOccupancy", "roomCount"),
    ("PropertyOccupancy", "occupiedRoomCount"),
    ("PropertyOccupancy", "vacantRoomCount"),
]

PERCENTAGE_FIELDS = [
    ("OccupancySummary", "occupancyPercentage"),
    ("PropertyOccupancy", "occupancyPercentage"),
]


def _property_names(schema: dict[str, Any]) -> set[str]:
    return set(schema.get("properties", {}))


def _field(openapi: OpenApiDoc, component: str, field: str) -> dict[str, Any]:
    return openapi.component(component)["properties"][field]


# Path, operation, tag, security and status codes


def test_occupancy_dashboard_path_declares_exactly_get(openapi: OpenApiDoc) -> None:
    declared = {m for m in openapi.document["paths"].get(PATH, {}) if m in HTTP_METHODS}
    assert declared == {"get"}


def test_occupancy_dashboard_operation_has_operation_id(openapi: OpenApiDoc) -> None:
    assert openapi.operation("get", PATH)["operationId"] == "get_occupancy_dashboard"


def test_occupancy_dashboard_operation_is_tagged_dashboard(
    openapi: OpenApiDoc,
) -> None:
    assert openapi.operation("get", PATH)["tags"] == ["dashboard"]


def test_occupancy_dashboard_operation_declares_only_the_success_status(
    openapi: OpenApiDoc,
) -> None:
    assert set(openapi.operation("get", PATH)["responses"]) == {"200"}


def test_occupancy_dashboard_operation_requires_bearer_auth(
    openapi: OpenApiDoc,
) -> None:
    assert openapi.operation("get", PATH)["security"] == [{"bearerAuth": []}]


def test_occupancy_dashboard_operation_takes_no_parameters(openapi: OpenApiDoc) -> None:
    assert openapi.operation("get", PATH).get("parameters", []) == []


def test_occupancy_dashboard_operation_takes_no_request_body(
    openapi: OpenApiDoc,
) -> None:
    assert "requestBody" not in openapi.operation("get", PATH)


def test_occupancy_dashboard_responds_with_occupancy_dashboard(
    openapi: OpenApiDoc,
) -> None:
    assert openapi.response_schema_ref("get", PATH, 200) == "OccupancyDashboard"


# Component schemas


@pytest.mark.parametrize("name", COMPONENT_FIELDS)
def test_occupancy_component_schema_is_declared(openapi: OpenApiDoc, name: str) -> None:
    assert name in openapi.components


@pytest.mark.parametrize("name", COMPONENT_FIELDS)
@pytest.mark.parametrize("suffix", ["-Input", "-Output"])
def test_occupancy_component_schema_is_not_split_into_input_and_output_variants(
    openapi: OpenApiDoc, name: str, suffix: str
) -> None:
    assert f"{name}{suffix}" not in openapi.components


@pytest.mark.parametrize(("name", "fields"), COMPONENT_FIELDS.items())
def test_occupancy_component_has_exactly_its_fields(
    openapi: OpenApiDoc, name: str, fields: set[str]
) -> None:
    assert _property_names(openapi.component(name)) == fields


@pytest.mark.parametrize(("name", "fields"), COMPONENT_FIELDS.items())
def test_occupancy_component_requires_every_field(
    openapi: OpenApiDoc, name: str, fields: set[str]
) -> None:
    assert set(openapi.component(name).get("required", [])) == fields


@pytest.mark.parametrize("name", COMPONENT_FIELDS)
def test_occupancy_component_property_names_contain_no_underscore(
    openapi: OpenApiDoc, name: str
) -> None:
    offenders = [p for p in _property_names(openapi.component(name)) if "_" in p]
    assert offenders == []


@pytest.mark.parametrize(
    ("component", "field"),
    [(name, field) for name, fields in COMPONENT_FIELDS.items() for field in fields],
)
def test_occupancy_field_is_not_nullable(
    openapi: OpenApiDoc, component: str, field: str
) -> None:
    schema = _field(openapi, component, field)
    assert "anyOf" not in schema
    assert schema.get("type") != "null"
    assert not isinstance(schema.get("type"), list)


# OccupancyDashboard


def test_dashboard_summary_is_occupancy_summary(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "OccupancyDashboard", "summary")
    assert openapi.ref_name(schema) == "OccupancySummary"


def test_dashboard_items_is_array_of_property_occupancy(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "OccupancyDashboard", "items")
    assert schema["type"] == "array"
    assert openapi.ref_name(schema["items"]) == "PropertyOccupancy"


# Counts and percentages


@pytest.mark.parametrize(("component", "field"), COUNT_FIELDS)
def test_occupancy_count_is_non_negative_integer(
    openapi: OpenApiDoc, component: str, field: str
) -> None:
    schema = _field(openapi, component, field)
    assert schema["type"] == "integer"
    assert schema["minimum"] == 0


@pytest.mark.parametrize(("component", "field"), PERCENTAGE_FIELDS)
def test_occupancy_percentage_is_integer_from_0_to_100(
    openapi: OpenApiDoc, component: str, field: str
) -> None:
    schema = _field(openapi, component, field)
    assert schema["type"] == "integer"
    assert schema["minimum"] == 0
    assert schema["maximum"] == 100


# PropertyOccupancy


def test_property_occupancy_id_is_uuid_string(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "PropertyOccupancy", "id")
    assert schema["type"] == "string"
    assert schema["format"] == "uuid"


def test_property_occupancy_name_is_string(openapi: OpenApiDoc) -> None:
    assert _field(openapi, "PropertyOccupancy", "name")["type"] == "string"


def test_property_occupancy_rooms_is_array_of_occupancy_room(
    openapi: OpenApiDoc,
) -> None:
    schema = _field(openapi, "PropertyOccupancy", "rooms")
    assert schema["type"] == "array"
    assert openapi.ref_name(schema["items"]) == "OccupancyRoom"


# OccupancyRoom


def test_occupancy_room_id_is_uuid_string(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "OccupancyRoom", "id")
    assert schema["type"] == "string"
    assert schema["format"] == "uuid"


def test_occupancy_room_number_is_string(openapi: OpenApiDoc) -> None:
    assert _field(openapi, "OccupancyRoom", "number")["type"] == "string"


def test_occupancy_room_occupancy_is_occupancy_enum(openapi: OpenApiDoc) -> None:
    schema = _field(openapi, "OccupancyRoom", "occupancy")
    assert openapi.ref_name(schema) == "Occupancy"


def test_occupancy_enum_is_string_enum_of_occupied_and_vacant(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component("Occupancy")
    assert schema["type"] == "string"
    assert sorted(schema["enum"]) == ["occupied", "vacant"]


# Runtime


def test_valid_occupancy_dashboard_request_responds_not_implemented(client) -> None:
    assert client.get(PATH).status_code == 501
