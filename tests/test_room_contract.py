"""Contract tests for the room and facility-suggestion endpoints."""

from typing import Any

import pytest
from conftest import NOT_A_UUID, PROPERTY_ID, ROOM_ID, OpenApiDoc, nullable_inner

ROOM_PATHS = {
    "/properties/{propertyId}/rooms": {"post", "get"},
    "/properties/{propertyId}/facility-suggestions": {"get"},
    "/rooms/{roomId}": {"get", "put", "delete"},
}

# (method, path, operationId, success status)
ROOM_OPERATIONS = [
    ("post", "/properties/{propertyId}/rooms", "create_room", 201),
    ("get", "/properties/{propertyId}/rooms", "list_rooms", 200),
    (
        "get",
        "/properties/{propertyId}/facility-suggestions",
        "list_facility_suggestions",
        200,
    ),
    ("get", "/rooms/{roomId}", "get_room", 200),
    ("put", "/rooms/{roomId}", "update_room", 200),
    ("delete", "/rooms/{roomId}", "delete_room", 204),
]

# (method, path, path parameter name)
ROOM_PATH_PARAMETERS = [
    pytest.param(
        "post", "/properties/{propertyId}/rooms", "propertyId", id="create_room"
    ),
    pytest.param(
        "get", "/properties/{propertyId}/rooms", "propertyId", id="list_rooms"
    ),
    pytest.param(
        "get",
        "/properties/{propertyId}/facility-suggestions",
        "propertyId",
        id="list_facility_suggestions",
    ),
    pytest.param("get", "/rooms/{roomId}", "roomId", id="get_room"),
    pytest.param("put", "/rooms/{roomId}", "roomId", id="update_room"),
    pytest.param("delete", "/rooms/{roomId}", "roomId", id="delete_room"),
]

VALID_ROOM_INPUT = {
    "number": "A1",
    "baseRate": 1500000,
    "lengthM": 3.5,
    "widthM": 4,
    "facilities": ["ac", "wifi"],
}

# Operations that take a RoomInput body, with the concrete URL to call.
ROOM_WRITE_REQUESTS = [
    pytest.param("post", f"/properties/{PROPERTY_ID}/rooms", id="create_room"),
    pytest.param("put", f"/rooms/{ROOM_ID}", id="update_room"),
]


def _without(body: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k not in keys}


def _property_names(schema: dict[str, Any]) -> set[str]:
    return set(schema.get("properties", {}))


# Paths, operations, tags and status codes


@pytest.mark.parametrize(("path", "methods"), ROOM_PATHS.items())
def test_room_path_declares_exactly_its_methods(
    openapi: OpenApiDoc, path: str, methods: set[str]
) -> None:
    declared = {
        m
        for m in openapi.document["paths"].get(path, {})
        if m in {"get", "put", "post", "delete", "patch", "options", "head", "trace"}
    }
    assert declared == methods


@pytest.mark.parametrize(("method", "path", "operation_id", "status"), ROOM_OPERATIONS)
def test_room_operation_has_operation_id(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["operationId"] == operation_id


@pytest.mark.parametrize(("method", "path", "operation_id", "status"), ROOM_OPERATIONS)
def test_room_operation_is_tagged_rooms(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["tags"] == ["rooms"]


@pytest.mark.parametrize(("method", "path", "operation_id", "status"), ROOM_OPERATIONS)
def test_room_operation_declares_only_its_success_status_besides_validation_error(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    responses = set(openapi.operation(method, path)["responses"])
    assert responses - {"422"} == {str(status)}


def test_delete_room_success_response_has_no_body(openapi: OpenApiDoc) -> None:
    response = openapi.operation("delete", "/rooms/{roomId}")["responses"]["204"]
    assert "content" not in response


@pytest.mark.parametrize(("method", "path", "name"), ROOM_PATH_PARAMETERS)
def test_room_operation_path_parameter_is_required_uuid(
    openapi: OpenApiDoc, method: str, path: str, name: str
) -> None:
    parameters = openapi.operation(method, path)["parameters"]
    assert [p["name"] for p in parameters] == [name]
    (parameter,) = parameters
    assert parameter["in"] == "path"
    assert parameter["required"] is True
    assert parameter["schema"]["type"] == "string"
    assert parameter["schema"]["format"] == "uuid"


# Request and response schema references


@pytest.mark.parametrize(
    ("method", "path"),
    [("post", "/properties/{propertyId}/rooms"), ("put", "/rooms/{roomId}")],
    ids=["create_room", "update_room"],
)
def test_room_write_request_body_is_room_input(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert openapi.request_schema_ref(method, path) == "RoomInput"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/properties/{propertyId}/rooms"),
        ("get", "/properties/{propertyId}/facility-suggestions"),
        ("get", "/rooms/{roomId}"),
        ("delete", "/rooms/{roomId}"),
    ],
    ids=["list_rooms", "list_facility_suggestions", "get_room", "delete_room"],
)
def test_room_read_and_delete_operations_take_no_request_body(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert "requestBody" not in openapi.operation(method, path)


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("post", "/properties/{propertyId}/rooms", 201),
        ("get", "/rooms/{roomId}", 200),
        ("put", "/rooms/{roomId}", 200),
    ],
    ids=["create_room", "get_room", "update_room"],
)
def test_single_room_operations_respond_with_room(
    openapi: OpenApiDoc, method: str, path: str, status: int
) -> None:
    assert openapi.response_schema_ref(method, path, status) == "Room"


def test_list_rooms_responds_with_room_list(openapi: OpenApiDoc) -> None:
    assert (
        openapi.response_schema_ref("get", "/properties/{propertyId}/rooms", 200)
        == "RoomList"
    )


def test_list_facility_suggestions_responds_with_facility_suggestion_list(
    openapi: OpenApiDoc,
) -> None:
    assert (
        openapi.response_schema_ref(
            "get", "/properties/{propertyId}/facility-suggestions", 200
        )
        == "FacilitySuggestionList"
    )


@pytest.mark.parametrize(
    "name",
    [
        "Occupancy",
        "RoomInput",
        "RoomLease",
        "RoomLeaseSummary",
        "Room",
        "RoomSummary",
        "RoomList",
        "FacilitySuggestionList",
    ],
)
def test_room_component_schema_is_declared(openapi: OpenApiDoc, name: str) -> None:
    assert name in openapi.components


# RoomInput


@pytest.fixture
def room_input_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component(
        openapi.request_schema_ref("post", "/properties/{propertyId}/rooms")
    )


def test_room_input_has_exactly_its_fields(room_input_schema: dict[str, Any]) -> None:
    assert _property_names(room_input_schema) == {
        "number",
        "baseRate",
        "lengthM",
        "widthM",
        "facilities",
    }


def test_room_input_requires_only_number_and_base_rate(
    room_input_schema: dict[str, Any],
) -> None:
    assert set(room_input_schema["required"]) == {"number", "baseRate"}


def test_room_input_number_is_non_empty_string(
    room_input_schema: dict[str, Any],
) -> None:
    schema = room_input_schema["properties"]["number"]
    assert schema["type"] == "string"
    assert schema["minLength"] == 1


def test_room_input_base_rate_is_positive_integer(
    room_input_schema: dict[str, Any],
) -> None:
    schema = room_input_schema["properties"]["baseRate"]
    assert schema["type"] == "integer"
    assert schema["exclusiveMinimum"] == 0


@pytest.mark.parametrize("field", ["lengthM", "widthM"])
def test_room_input_dimension_is_optional_nullable_number_in_range(
    room_input_schema: dict[str, Any], field: str
) -> None:
    schema = room_input_schema["properties"][field]
    inner = nullable_inner(schema)
    assert inner["type"] == "number"
    assert inner["exclusiveMinimum"] == 0
    assert inner["maximum"] == 20
    assert field not in room_input_schema["required"]


def test_room_input_facilities_is_string_array_defaulting_to_empty(
    room_input_schema: dict[str, Any],
) -> None:
    schema = room_input_schema["properties"]["facilities"]
    assert schema["type"] == "array"
    assert schema["items"]["type"] == "string"
    assert schema["default"] == []


# Room

ROOM_FIELDS = {
    "id",
    "propertyId",
    "number",
    "baseRate",
    "occupancy",
    "lengthM",
    "widthM",
    "facilities",
    "lease",
    "editable",
}


@pytest.fixture
def room_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component(openapi.response_schema_ref("get", "/rooms/{roomId}", 200))


def test_room_editable_is_required_boolean(room_schema: dict[str, Any]) -> None:
    assert room_schema["properties"]["editable"]["type"] == "boolean"
    assert "editable" in room_schema["required"]


def test_room_input_does_not_accept_editable(room_input_schema: dict[str, Any]) -> None:
    assert "editable" not in _property_names(room_input_schema)


def test_room_has_exactly_its_fields(room_schema: dict[str, Any]) -> None:
    assert _property_names(room_schema) == ROOM_FIELDS


def test_room_requires_every_field(room_schema: dict[str, Any]) -> None:
    assert set(room_schema["required"]) == ROOM_FIELDS


@pytest.mark.parametrize("field", ["id", "propertyId"])
def test_room_identifier_is_uuid_string(
    room_schema: dict[str, Any], field: str
) -> None:
    schema = room_schema["properties"][field]
    assert schema["type"] == "string"
    assert schema["format"] == "uuid"


def test_room_number_is_string(room_schema: dict[str, Any]) -> None:
    assert room_schema["properties"]["number"]["type"] == "string"


def test_room_base_rate_is_integer(room_schema: dict[str, Any]) -> None:
    assert room_schema["properties"]["baseRate"]["type"] == "integer"


def test_room_occupancy_is_occupancy_enum(
    openapi: OpenApiDoc, room_schema: dict[str, Any]
) -> None:
    assert openapi.ref_name(room_schema["properties"]["occupancy"]) == "Occupancy"


@pytest.mark.parametrize("field", ["lengthM", "widthM"])
def test_room_dimension_is_nullable_number(
    room_schema: dict[str, Any], field: str
) -> None:
    assert nullable_inner(room_schema["properties"][field])["type"] == "number"


def test_room_facilities_is_string_array(room_schema: dict[str, Any]) -> None:
    schema = room_schema["properties"]["facilities"]
    assert schema["type"] == "array"
    assert schema["items"]["type"] == "string"


def test_room_lease_is_nullable_room_lease(
    openapi: OpenApiDoc, room_schema: dict[str, Any]
) -> None:
    schema = room_schema["properties"]["lease"]
    assert openapi.ref_name(nullable_inner(schema)) == "RoomLease"


# Occupancy


def test_occupancy_is_string_enum_of_occupied_and_vacant(
    openapi: OpenApiDoc, room_schema: dict[str, Any]
) -> None:
    schema = openapi.resolve(room_schema["properties"]["occupancy"])
    assert schema["type"] == "string"
    assert sorted(schema["enum"]) == ["occupied", "vacant"]
    assert len(schema["enum"]) == 2


# RoomLease

ROOM_LEASE_FIELDS = {
    "tenantId",
    "tenantName",
    "tenantPhone",
    "startDate",
    "endDate",
    "rent",
}


@pytest.fixture
def room_lease_schema(
    openapi: OpenApiDoc, room_schema: dict[str, Any]
) -> dict[str, Any]:
    return openapi.resolve(nullable_inner(room_schema["properties"]["lease"]))


def test_room_lease_has_exactly_its_fields(room_lease_schema: dict[str, Any]) -> None:
    assert _property_names(room_lease_schema) == ROOM_LEASE_FIELDS


def test_room_lease_requires_every_field(room_lease_schema: dict[str, Any]) -> None:
    assert set(room_lease_schema["required"]) == ROOM_LEASE_FIELDS


def test_room_lease_tenant_id_is_uuid_string(
    room_lease_schema: dict[str, Any],
) -> None:
    schema = room_lease_schema["properties"]["tenantId"]
    assert schema["type"] == "string"
    assert schema["format"] == "uuid"


@pytest.mark.parametrize("field", ["tenantName", "tenantPhone"])
def test_room_lease_tenant_text_field_is_string(
    room_lease_schema: dict[str, Any], field: str
) -> None:
    assert room_lease_schema["properties"][field]["type"] == "string"


@pytest.mark.parametrize("field", ["startDate", "endDate"])
def test_room_lease_date_is_nullable_date_string(
    room_lease_schema: dict[str, Any], field: str
) -> None:
    inner = nullable_inner(room_lease_schema["properties"][field])
    assert inner["type"] == "string"
    assert inner["format"] == "date"


def test_room_lease_rent_is_integer(room_lease_schema: dict[str, Any]) -> None:
    assert room_lease_schema["properties"]["rent"]["type"] == "integer"


# RoomSummary

ROOM_SUMMARY_FIELDS = {
    "id",
    "number",
    "baseRate",
    "occupancy",
    "lengthM",
    "widthM",
    "facilities",
    "lease",
    "editable",
}


@pytest.fixture
def room_summary_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("RoomSummary")


def test_room_summary_editable_is_required_boolean(
    room_summary_schema: dict[str, Any],
) -> None:
    assert room_summary_schema["properties"]["editable"]["type"] == "boolean"
    assert "editable" in room_summary_schema["required"]


def test_room_summary_has_exactly_its_fields(
    room_summary_schema: dict[str, Any],
) -> None:
    assert _property_names(room_summary_schema) == ROOM_SUMMARY_FIELDS


def test_room_summary_requires_every_field(
    room_summary_schema: dict[str, Any],
) -> None:
    assert set(room_summary_schema["required"]) == ROOM_SUMMARY_FIELDS


def test_room_summary_leaves_out_property_id(
    room_summary_schema: dict[str, Any],
) -> None:
    assert "propertyId" not in _property_names(room_summary_schema)


def test_room_summary_id_is_uuid_string(room_summary_schema: dict[str, Any]) -> None:
    schema = room_summary_schema["properties"]["id"]
    assert schema["type"] == "string"
    assert schema["format"] == "uuid"


def test_room_summary_number_is_string(room_summary_schema: dict[str, Any]) -> None:
    assert room_summary_schema["properties"]["number"]["type"] == "string"


def test_room_summary_base_rate_is_integer(
    room_summary_schema: dict[str, Any],
) -> None:
    assert room_summary_schema["properties"]["baseRate"]["type"] == "integer"


def test_room_summary_occupancy_is_occupancy_enum(
    openapi: OpenApiDoc, room_summary_schema: dict[str, Any]
) -> None:
    schema = room_summary_schema["properties"]["occupancy"]
    assert openapi.ref_name(schema) == "Occupancy"


@pytest.mark.parametrize("field", ["lengthM", "widthM"])
def test_room_summary_dimension_is_nullable_number(
    room_summary_schema: dict[str, Any], field: str
) -> None:
    assert nullable_inner(room_summary_schema["properties"][field])["type"] == "number"


def test_room_summary_facilities_is_string_array(
    room_summary_schema: dict[str, Any],
) -> None:
    schema = room_summary_schema["properties"]["facilities"]
    assert schema["type"] == "array"
    assert schema["items"]["type"] == "string"


def test_room_summary_lease_is_nullable_room_lease_summary(
    openapi: OpenApiDoc, room_summary_schema: dict[str, Any]
) -> None:
    schema = room_summary_schema["properties"]["lease"]
    assert openapi.ref_name(nullable_inner(schema)) == "RoomLeaseSummary"


# RoomLeaseSummary

ROOM_LEASE_SUMMARY_FIELDS = {"tenantName", "endDate"}


@pytest.fixture
def room_lease_summary_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("RoomLeaseSummary")


def test_room_lease_summary_has_exactly_its_fields(
    room_lease_summary_schema: dict[str, Any],
) -> None:
    assert _property_names(room_lease_summary_schema) == ROOM_LEASE_SUMMARY_FIELDS


def test_room_lease_summary_requires_every_field(
    room_lease_summary_schema: dict[str, Any],
) -> None:
    assert set(room_lease_summary_schema["required"]) == ROOM_LEASE_SUMMARY_FIELDS


@pytest.mark.parametrize("field", ["tenantPhone", "startDate", "rent"])
def test_room_lease_summary_leaves_out_detail_only_field(
    room_lease_summary_schema: dict[str, Any], field: str
) -> None:
    assert field not in _property_names(room_lease_summary_schema)


def test_room_lease_summary_tenant_name_is_string(
    room_lease_summary_schema: dict[str, Any],
) -> None:
    assert room_lease_summary_schema["properties"]["tenantName"]["type"] == "string"


def test_room_lease_summary_end_date_is_nullable_date_string(
    room_lease_summary_schema: dict[str, Any],
) -> None:
    inner = nullable_inner(room_lease_summary_schema["properties"]["endDate"])
    assert inner["type"] == "string"
    assert inner["format"] == "date"


# RoomList and FacilitySuggestionList


def test_room_list_items_is_required_array_of_room_summary(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component(
        openapi.response_schema_ref("get", "/properties/{propertyId}/rooms", 200)
    )
    assert _property_names(schema) == {"items"}
    assert set(schema["required"]) == {"items"}
    items = schema["properties"]["items"]
    assert items["type"] == "array"
    assert openapi.ref_name(items["items"]) == "RoomSummary"


def test_facility_suggestion_list_items_is_required_array_of_string(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component(
        openapi.response_schema_ref(
            "get", "/properties/{propertyId}/facility-suggestions", 200
        )
    )
    assert _property_names(schema) == {"items"}
    assert set(schema["required"]) == {"items"}
    items = schema["properties"]["items"]
    assert items["type"] == "array"
    assert items["items"]["type"] == "string"


# Runtime: valid requests reach the not-implemented stub


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        pytest.param(
            "post",
            f"/properties/{PROPERTY_ID}/rooms",
            VALID_ROOM_INPUT,
            id="create_room",
        ),
        pytest.param("get", f"/properties/{PROPERTY_ID}/rooms", None, id="list_rooms"),
        pytest.param(
            "get",
            f"/properties/{PROPERTY_ID}/facility-suggestions",
            None,
            id="list_facility_suggestions",
        ),
        pytest.param("get", f"/rooms/{ROOM_ID}", None, id="get_room"),
        pytest.param("put", f"/rooms/{ROOM_ID}", VALID_ROOM_INPUT, id="update_room"),
        pytest.param("delete", f"/rooms/{ROOM_ID}", None, id="delete_room"),
    ],
)
def test_valid_room_request_responds_not_implemented(
    client, method: str, url: str, body: dict[str, Any] | None
) -> None:
    response = client.request(method, url, json=body)
    assert response.status_code == 501


@pytest.mark.parametrize(("method", "url"), ROOM_WRITE_REQUESTS)
@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            {**VALID_ROOM_INPUT, "lengthM": 20, "widthM": 20},
            id="dimensions_exactly_20",
        ),
        pytest.param(
            {**VALID_ROOM_INPUT, "lengthM": 0.01, "widthM": 0.01},
            id="dimensions_just_above_0",
        ),
        pytest.param(
            _without(VALID_ROOM_INPUT, "lengthM", "widthM"), id="dimensions_omitted"
        ),
        pytest.param(
            {**VALID_ROOM_INPUT, "lengthM": None, "widthM": None}, id="dimensions_null"
        ),
        pytest.param(_without(VALID_ROOM_INPUT, "facilities"), id="facilities_omitted"),
        pytest.param({**VALID_ROOM_INPUT, "facilities": []}, id="facilities_empty"),
        pytest.param({"number": "A1", "baseRate": 1}, id="only_required_fields"),
    ],
)
def test_room_input_edge_body_is_accepted(
    client, method: str, url: str, body: dict[str, Any]
) -> None:
    response = client.request(method, url, json=body)
    assert response.status_code == 501


# Runtime: invalid requests are rejected with a validation error


@pytest.mark.parametrize(("method", "url"), ROOM_WRITE_REQUESTS)
@pytest.mark.parametrize(
    "body",
    [
        pytest.param(_without(VALID_ROOM_INPUT, "number"), id="missing_number"),
        pytest.param({**VALID_ROOM_INPUT, "number": ""}, id="empty_number"),
        pytest.param(_without(VALID_ROOM_INPUT, "baseRate"), id="missing_base_rate"),
        pytest.param({**VALID_ROOM_INPUT, "baseRate": 0}, id="base_rate_zero"),
        pytest.param({**VALID_ROOM_INPUT, "baseRate": -1}, id="base_rate_negative"),
        pytest.param({**VALID_ROOM_INPUT, "baseRate": 1500.5}, id="base_rate_fraction"),
        pytest.param({**VALID_ROOM_INPUT, "lengthM": 0}, id="length_zero"),
        pytest.param({**VALID_ROOM_INPUT, "lengthM": -1}, id="length_negative"),
        pytest.param({**VALID_ROOM_INPUT, "lengthM": 20.01}, id="length_above_20"),
        pytest.param({**VALID_ROOM_INPUT, "widthM": 0}, id="width_zero"),
        pytest.param({**VALID_ROOM_INPUT, "widthM": -1}, id="width_negative"),
        pytest.param({**VALID_ROOM_INPUT, "widthM": 20.01}, id="width_above_20"),
        pytest.param(
            {**VALID_ROOM_INPUT, "facilities": "ac"}, id="facilities_not_array"
        ),
        pytest.param({**VALID_ROOM_INPUT, "facilities": [1]}, id="facility_not_string"),
        pytest.param({}, id="empty_object"),
    ],
)
def test_invalid_room_input_is_rejected_with_validation_error(
    client, method: str, url: str, body: dict[str, Any]
) -> None:
    response = client.request(method, url, json=body)
    assert response.status_code == 422


@pytest.mark.parametrize(("method", "url"), ROOM_WRITE_REQUESTS)
def test_room_write_without_body_is_rejected_with_validation_error(
    client, method: str, url: str
) -> None:
    response = client.request(method, url)
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        pytest.param(
            "post",
            f"/properties/{NOT_A_UUID}/rooms",
            VALID_ROOM_INPUT,
            id="create_room",
        ),
        pytest.param("get", f"/properties/{NOT_A_UUID}/rooms", None, id="list_rooms"),
        pytest.param(
            "get",
            f"/properties/{NOT_A_UUID}/facility-suggestions",
            None,
            id="list_facility_suggestions",
        ),
        pytest.param("get", f"/rooms/{NOT_A_UUID}", None, id="get_room"),
        pytest.param("put", f"/rooms/{NOT_A_UUID}", VALID_ROOM_INPUT, id="update_room"),
        pytest.param("delete", f"/rooms/{NOT_A_UUID}", None, id="delete_room"),
    ],
)
def test_non_uuid_path_id_is_rejected_with_validation_error(
    client, method: str, url: str, body: dict[str, Any] | None
) -> None:
    response = client.request(method, url, json=body)
    assert response.status_code == 422
