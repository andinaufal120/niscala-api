"""Contract tests for the property endpoints and the shared OpenAPI conventions."""

from typing import Any

import pytest
from conftest import NOT_A_UUID, PROPERTY_ID, OpenApiDoc, nullable_inner

PROPERTY_PATHS = {
    "/properties": {"post", "get"},
    "/properties/{propertyId}": {"get", "put", "delete"},
}

# (method, path, operationId, success status)
PROPERTY_OPERATIONS = [
    ("post", "/properties", "create_property", 201),
    ("get", "/properties", "list_properties", 200),
    ("get", "/properties/{propertyId}", "get_property", 200),
    ("put", "/properties/{propertyId}", "update_property", 200),
    ("delete", "/properties/{propertyId}", "delete_property", 204),
]

VALID_BANK_ACCOUNT = {
    "bankName": "BCA",
    "accountNumber": "1234567890",
    "accountHolderName": "Budi Santoso",
}

VALID_PROPERTY_INPUT = {
    "name": "Kos Melati",
    "address": "Jl. Melati No. 5, Yogyakarta",
    "bankAccount": VALID_BANK_ACCOUNT,
}

# Operations that take a PropertyInput body, with the concrete URL to call.
PROPERTY_WRITE_REQUESTS = [
    pytest.param("post", "/properties", id="create_property"),
    pytest.param("put", f"/properties/{PROPERTY_ID}", id="update_property"),
]


def _without(body: dict[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k != key}


def _property_names(schema: dict[str, Any]) -> set[str]:
    return set(schema.get("properties", {}))


# Paths, operations, tags and status codes


@pytest.mark.parametrize(("path", "methods"), PROPERTY_PATHS.items())
def test_property_path_declares_exactly_its_methods(
    openapi: OpenApiDoc, path: str, methods: set[str]
) -> None:
    declared = {
        m
        for m in openapi.document["paths"].get(path, {})
        if m in {"get", "put", "post", "delete", "patch", "options", "head", "trace"}
    }
    assert declared == methods


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), PROPERTY_OPERATIONS
)
def test_property_operation_has_operation_id(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["operationId"] == operation_id


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), PROPERTY_OPERATIONS
)
def test_property_operation_is_tagged_properties(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["tags"] == ["properties"]


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), PROPERTY_OPERATIONS
)
def test_property_operation_declares_only_its_success_status_besides_validation_error(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    responses = set(openapi.operation(method, path)["responses"])
    assert responses - {"422"} == {str(status)}


def test_delete_property_success_response_has_no_body(openapi: OpenApiDoc) -> None:
    response = openapi.operation("delete", "/properties/{propertyId}")["responses"][
        "204"
    ]
    assert "content" not in response


@pytest.mark.parametrize(
    "method", ["get", "put", "delete"], ids=lambda m: f"{m}_property"
)
def test_property_id_path_parameter_is_required_uuid(
    openapi: OpenApiDoc, method: str
) -> None:
    parameters = openapi.operation(method, "/properties/{propertyId}")["parameters"]
    assert [p["name"] for p in parameters] == ["propertyId"]
    (parameter,) = parameters
    assert parameter["in"] == "path"
    assert parameter["required"] is True
    assert parameter["schema"]["type"] == "string"
    assert parameter["schema"]["format"] == "uuid"


def test_list_properties_takes_no_parameters(openapi: OpenApiDoc) -> None:
    assert openapi.operation("get", "/properties").get("parameters", []) == []


# Request and response schema references


@pytest.mark.parametrize(
    ("method", "path"),
    [("post", "/properties"), ("put", "/properties/{propertyId}")],
    ids=["create_property", "update_property"],
)
def test_property_write_request_body_is_property_input(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert openapi.request_schema_ref(method, path) == "PropertyInput"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/properties"),
        ("get", "/properties/{propertyId}"),
        ("delete", "/properties/{propertyId}"),
    ],
    ids=["list_properties", "get_property", "delete_property"],
)
def test_property_read_and_delete_operations_take_no_request_body(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert "requestBody" not in openapi.operation(method, path)


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("post", "/properties", 201),
        ("get", "/properties/{propertyId}", 200),
        ("put", "/properties/{propertyId}", 200),
    ],
    ids=["create_property", "get_property", "update_property"],
)
def test_single_property_operations_respond_with_property(
    openapi: OpenApiDoc, method: str, path: str, status: int
) -> None:
    assert openapi.response_schema_ref(method, path, status) == "Property"


def test_list_properties_responds_with_property_list(openapi: OpenApiDoc) -> None:
    assert openapi.response_schema_ref("get", "/properties", 200) == "PropertyList"


@pytest.mark.parametrize(
    "name", ["BankAccount", "PropertyInput", "ManagerRef", "Property", "PropertyList"]
)
def test_property_component_schema_is_declared(openapi: OpenApiDoc, name: str) -> None:
    assert name in openapi.components


# BankAccount


@pytest.fixture
def bank_account_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    property_input = openapi.resolve({"$ref": "#/components/schemas/PropertyInput"})
    inner = nullable_inner(property_input["properties"]["bankAccount"])
    return openapi.resolve(inner)


def test_bank_account_has_exactly_its_fields(
    bank_account_schema: dict[str, Any],
) -> None:
    assert _property_names(bank_account_schema) == {
        "bankName",
        "accountNumber",
        "accountHolderName",
    }


def test_bank_account_requires_every_field(
    bank_account_schema: dict[str, Any],
) -> None:
    assert set(bank_account_schema["required"]) == {
        "bankName",
        "accountNumber",
        "accountHolderName",
    }


@pytest.mark.parametrize("field", ["bankName", "accountNumber", "accountHolderName"])
def test_bank_account_field_is_non_empty_string(
    bank_account_schema: dict[str, Any], field: str
) -> None:
    schema = bank_account_schema["properties"][field]
    assert schema["type"] == "string"
    assert schema["minLength"] == 1


# PropertyInput


@pytest.fixture
def property_input_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component(openapi.request_schema_ref("post", "/properties"))


def test_property_input_has_exactly_its_fields(
    property_input_schema: dict[str, Any],
) -> None:
    assert _property_names(property_input_schema) == {"name", "address", "bankAccount"}


def test_property_input_requires_only_name_and_address(
    property_input_schema: dict[str, Any],
) -> None:
    assert set(property_input_schema["required"]) == {"name", "address"}


@pytest.mark.parametrize("field", ["name", "address"])
def test_property_input_text_field_is_non_empty_string(
    property_input_schema: dict[str, Any], field: str
) -> None:
    schema = property_input_schema["properties"][field]
    assert schema["type"] == "string"
    assert schema["minLength"] == 1


def test_property_input_bank_account_is_nullable_bank_account_defaulting_to_null(
    openapi: OpenApiDoc, property_input_schema: dict[str, Any]
) -> None:
    schema = property_input_schema["properties"]["bankAccount"]
    assert openapi.ref_name(nullable_inner(schema)) == "BankAccount"
    assert "default" in schema
    assert schema["default"] is None


# ManagerRef


@pytest.fixture
def property_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component(
        openapi.response_schema_ref("get", "/properties/{propertyId}", 200)
    )


@pytest.fixture
def manager_ref_schema(
    openapi: OpenApiDoc, property_schema: dict[str, Any]
) -> dict[str, Any]:
    return openapi.resolve(property_schema["properties"]["managers"]["items"])


def test_manager_ref_has_exactly_id_and_name(
    manager_ref_schema: dict[str, Any],
) -> None:
    assert _property_names(manager_ref_schema) == {"id", "name"}


def test_manager_ref_requires_id_and_name(manager_ref_schema: dict[str, Any]) -> None:
    assert set(manager_ref_schema["required"]) == {"id", "name"}


def test_manager_ref_id_is_uuid_string(manager_ref_schema: dict[str, Any]) -> None:
    schema = manager_ref_schema["properties"]["id"]
    assert schema["type"] == "string"
    assert schema["format"] == "uuid"


def test_manager_ref_name_is_string(manager_ref_schema: dict[str, Any]) -> None:
    assert manager_ref_schema["properties"]["name"]["type"] == "string"


# Property

PROPERTY_FIELDS = {
    "id",
    "name",
    "address",
    "bankAccount",
    "roomCount",
    "occupiedRoomCount",
    "vacantRoomCount",
    "managers",
}


def test_property_has_exactly_its_fields(property_schema: dict[str, Any]) -> None:
    assert _property_names(property_schema) == PROPERTY_FIELDS


def test_property_requires_every_field(property_schema: dict[str, Any]) -> None:
    assert set(property_schema["required"]) == PROPERTY_FIELDS


def test_property_id_is_uuid_string(property_schema: dict[str, Any]) -> None:
    schema = property_schema["properties"]["id"]
    assert schema["type"] == "string"
    assert schema["format"] == "uuid"


@pytest.mark.parametrize("field", ["name", "address"])
def test_property_text_field_is_string(
    property_schema: dict[str, Any], field: str
) -> None:
    assert property_schema["properties"][field]["type"] == "string"


def test_property_bank_account_is_nullable_bank_account(
    openapi: OpenApiDoc, property_schema: dict[str, Any]
) -> None:
    schema = property_schema["properties"]["bankAccount"]
    assert openapi.ref_name(nullable_inner(schema)) == "BankAccount"


@pytest.mark.parametrize("field", ["roomCount", "occupiedRoomCount", "vacantRoomCount"])
def test_property_room_count_is_integer(
    property_schema: dict[str, Any], field: str
) -> None:
    assert property_schema["properties"][field]["type"] == "integer"


def test_property_managers_is_array_of_manager_ref(
    openapi: OpenApiDoc, property_schema: dict[str, Any]
) -> None:
    schema = property_schema["properties"]["managers"]
    assert schema["type"] == "array"
    assert openapi.ref_name(schema["items"]) == "ManagerRef"


# PropertyList


@pytest.fixture
def property_list_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component(openapi.response_schema_ref("get", "/properties", 200))


def test_property_list_has_exactly_items(property_list_schema: dict[str, Any]) -> None:
    assert _property_names(property_list_schema) == {"items"}
    assert set(property_list_schema["required"]) == {"items"}


def test_property_list_items_is_array_of_property(
    openapi: OpenApiDoc, property_list_schema: dict[str, Any]
) -> None:
    schema = property_list_schema["properties"]["items"]
    assert schema["type"] == "array"
    assert openapi.ref_name(schema["items"]) == "Property"


# Wire naming conventions across the whole document


def _property_names_with_underscore(node: Any, location: str) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            found += [f"{location}.{name}" for name in properties if "_" in name]
        for key, value in node.items():
            found += _property_names_with_underscore(value, f"{location}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found += _property_names_with_underscore(value, f"{location}[{index}]")
    return found


def test_no_component_schema_property_name_contains_underscore(
    openapi: OpenApiDoc,
) -> None:
    assert _property_names_with_underscore(openapi.components, "components") == []


def test_no_parameter_name_contains_underscore(openapi: OpenApiDoc) -> None:
    offenders = [
        f"{method.upper()} {path}: {parameter['name']}"
        for path, item in openapi.document["paths"].items()
        for method, operation in item.items()
        if isinstance(operation, dict)
        for parameter in operation.get("parameters", [])
        if "_" in parameter["name"]
    ]
    assert offenders == []


# Runtime: valid requests reach the not-implemented stub


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        pytest.param("post", "/properties", VALID_PROPERTY_INPUT, id="create_property"),
        pytest.param("get", "/properties", None, id="list_properties"),
        pytest.param("get", f"/properties/{PROPERTY_ID}", None, id="get_property"),
        pytest.param(
            "put",
            f"/properties/{PROPERTY_ID}",
            VALID_PROPERTY_INPUT,
            id="update_property",
        ),
        pytest.param(
            "delete", f"/properties/{PROPERTY_ID}", None, id="delete_property"
        ),
    ],
)
def test_valid_property_request_responds_not_implemented(
    client, method: str, url: str, body: dict[str, Any] | None
) -> None:
    response = client.request(method, url, json=body)
    assert response.status_code == 501


@pytest.mark.parametrize(("method", "url"), PROPERTY_WRITE_REQUESTS)
@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            {**VALID_PROPERTY_INPUT, "bankAccount": None}, id="bank_account_null"
        ),
        pytest.param(
            _without(VALID_PROPERTY_INPUT, "bankAccount"), id="bank_account_omitted"
        ),
        pytest.param(
            {
                "name": "K",
                "address": "J",
                "bankAccount": {
                    "bankName": "B",
                    "accountNumber": "1",
                    "accountHolderName": "H",
                },
            },
            id="single_character_fields",
        ),
    ],
)
def test_property_input_edge_body_is_accepted(
    client, method: str, url: str, body: dict[str, Any]
) -> None:
    response = client.request(method, url, json=body)
    assert response.status_code == 501


# Runtime: invalid requests are rejected with a validation error


@pytest.mark.parametrize(("method", "url"), PROPERTY_WRITE_REQUESTS)
@pytest.mark.parametrize(
    "body",
    [
        pytest.param(_without(VALID_PROPERTY_INPUT, "name"), id="missing_name"),
        pytest.param({**VALID_PROPERTY_INPUT, "name": ""}, id="empty_name"),
        pytest.param(_without(VALID_PROPERTY_INPUT, "address"), id="missing_address"),
        pytest.param({**VALID_PROPERTY_INPUT, "address": ""}, id="empty_address"),
        pytest.param(
            {**VALID_PROPERTY_INPUT, "bankAccount": {"bankName": "BCA"}},
            id="bank_account_only_bank_name",
        ),
        pytest.param(
            {
                **VALID_PROPERTY_INPUT,
                "bankAccount": _without(VALID_BANK_ACCOUNT, "accountHolderName"),
            },
            id="bank_account_missing_holder_name",
        ),
        pytest.param(
            {**VALID_PROPERTY_INPUT, "bankAccount": {}}, id="bank_account_empty_object"
        ),
        pytest.param(
            {
                **VALID_PROPERTY_INPUT,
                "bankAccount": {**VALID_BANK_ACCOUNT, "bankName": ""},
            },
            id="bank_account_empty_bank_name",
        ),
        pytest.param(
            {
                **VALID_PROPERTY_INPUT,
                "bankAccount": {**VALID_BANK_ACCOUNT, "accountNumber": ""},
            },
            id="bank_account_empty_account_number",
        ),
        pytest.param(
            {
                **VALID_PROPERTY_INPUT,
                "bankAccount": {**VALID_BANK_ACCOUNT, "accountHolderName": ""},
            },
            id="bank_account_empty_holder_name",
        ),
        pytest.param({}, id="empty_object"),
    ],
)
def test_invalid_property_input_is_rejected_with_validation_error(
    client, method: str, url: str, body: dict[str, Any]
) -> None:
    response = client.request(method, url, json=body)
    assert response.status_code == 422


@pytest.mark.parametrize(("method", "url"), PROPERTY_WRITE_REQUESTS)
def test_property_write_without_body_is_rejected_with_validation_error(
    client, method: str, url: str
) -> None:
    response = client.request(method, url)
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("method", "body"),
    [
        pytest.param("get", None, id="get_property"),
        pytest.param("put", VALID_PROPERTY_INPUT, id="update_property"),
        pytest.param("delete", None, id="delete_property"),
    ],
)
def test_non_uuid_property_id_is_rejected_with_validation_error(
    client, method: str, body: dict[str, Any] | None
) -> None:
    response = client.request(method, f"/properties/{NOT_A_UUID}", json=body)
    assert response.status_code == 422
