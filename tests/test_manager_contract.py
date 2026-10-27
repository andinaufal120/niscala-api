"""Contract tests for the manager and manager-invitation endpoints."""

from typing import Any

import pytest
from conftest import OpenApiDoc, nullable_inner

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "options", "head", "trace"}

MANAGER_PATHS = {
    "/managers": {"post", "get"},
    "/managers/{managerId}": {"get", "put", "delete"},
    "/managers/{managerId}/invitation": {"post"},
}

# (method, path, operationId, success status)
MANAGER_OPERATIONS = [
    ("post", "/managers", "create_manager", 201),
    ("get", "/managers", "list_managers", 200),
    ("get", "/managers/{managerId}", "get_manager", 200),
    ("put", "/managers/{managerId}", "update_manager", 200),
    ("delete", "/managers/{managerId}", "delete_manager", 204),
    (
        "post",
        "/managers/{managerId}/invitation",
        "regenerate_manager_invitation",
        201,
    ),
]

# (method, path) of operations that take a managerId path parameter
MANAGER_ID_OPERATIONS = [
    pytest.param("get", "/managers/{managerId}", id="get_manager"),
    pytest.param("put", "/managers/{managerId}", id="update_manager"),
    pytest.param("delete", "/managers/{managerId}", id="delete_manager"),
    pytest.param(
        "post",
        "/managers/{managerId}/invitation",
        id="regenerate_manager_invitation",
    ),
]

MANAGER_COMPONENTS = [
    "ManagerAccountStatus",
    "ManagerInput",
    "ManagerProperty",
    "ManagerInvitation",
    "Manager",
    "ManagerSummary",
    "ManagerList",
]


def _property_names(schema: dict[str, Any]) -> set[str]:
    return set(schema.get("properties", {}))


def _assert_uuid_string(schema: dict[str, Any]) -> None:
    assert schema["type"] == "string"
    assert schema["format"] == "uuid"


# Paths, operations, tags, security and status codes


@pytest.mark.parametrize(("path", "methods"), MANAGER_PATHS.items())
def test_manager_path_declares_exactly_its_methods(
    openapi: OpenApiDoc, path: str, methods: set[str]
) -> None:
    declared = {m for m in openapi.document["paths"].get(path, {}) if m in HTTP_METHODS}
    assert declared == methods


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), MANAGER_OPERATIONS
)
def test_manager_operation_has_operation_id(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["operationId"] == operation_id


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), MANAGER_OPERATIONS
)
def test_manager_operation_is_tagged_managers(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["tags"] == ["managers"]


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), MANAGER_OPERATIONS
)
def test_manager_operation_requires_bearer_authentication(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["security"] == [{"bearerAuth": []}]


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), MANAGER_OPERATIONS
)
def test_manager_operation_declares_only_its_success_status_besides_validation_error(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    responses = set(openapi.operation(method, path)["responses"])
    assert responses - {"422"} == {str(status)}


def test_delete_manager_success_response_has_no_body(openapi: OpenApiDoc) -> None:
    response = openapi.operation("delete", "/managers/{managerId}")["responses"]["204"]
    assert "content" not in response


@pytest.mark.parametrize(("method", "path"), MANAGER_ID_OPERATIONS)
def test_manager_operation_path_parameter_is_required_uuid(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    parameters = openapi.operation(method, path)["parameters"]
    assert [p["name"] for p in parameters] == ["managerId"]
    (parameter,) = parameters
    assert parameter["in"] == "path"
    assert parameter["required"] is True
    _assert_uuid_string(parameter["schema"])


def test_create_manager_declares_no_parameters(openapi: OpenApiDoc) -> None:
    assert openapi.operation("post", "/managers").get("parameters", []) == []


def test_list_managers_declares_only_optional_property_id_query_parameter(
    openapi: OpenApiDoc,
) -> None:
    parameters = openapi.operation("get", "/managers")["parameters"]
    assert [p["name"] for p in parameters] == ["propertyId"]
    (parameter,) = parameters
    assert parameter["in"] == "query"
    assert parameter.get("required", False) is False
    _assert_uuid_string(nullable_inner(parameter["schema"]))


# Request and response schema references


def test_create_manager_request_body_is_manager_input(openapi: OpenApiDoc) -> None:
    assert openapi.request_schema_ref("post", "/managers") == "ManagerInput"


def test_update_manager_request_body_is_manager_input(openapi: OpenApiDoc) -> None:
    assert openapi.request_schema_ref("put", "/managers/{managerId}") == "ManagerInput"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/managers"),
        ("get", "/managers/{managerId}"),
        ("delete", "/managers/{managerId}"),
        ("post", "/managers/{managerId}/invitation"),
    ],
    ids=[
        "list_managers",
        "get_manager",
        "delete_manager",
        "regenerate_manager_invitation",
    ],
)
def test_manager_read_delete_and_regenerate_operations_take_no_request_body(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert "requestBody" not in openapi.operation(method, path)


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("post", "/managers", 201),
        ("get", "/managers/{managerId}", 200),
        ("put", "/managers/{managerId}", 200),
    ],
    ids=["create_manager", "get_manager", "update_manager"],
)
def test_single_manager_operations_respond_with_manager(
    openapi: OpenApiDoc, method: str, path: str, status: int
) -> None:
    assert openapi.response_schema_ref(method, path, status) == "Manager"


def test_list_managers_responds_with_manager_list(openapi: OpenApiDoc) -> None:
    assert openapi.response_schema_ref("get", "/managers", 200) == "ManagerList"


def test_regenerate_manager_invitation_responds_with_manager_invitation(
    openapi: OpenApiDoc,
) -> None:
    assert (
        openapi.response_schema_ref("post", "/managers/{managerId}/invitation", 201)
        == "ManagerInvitation"
    )


@pytest.mark.parametrize("name", MANAGER_COMPONENTS)
def test_manager_component_schema_is_declared(openapi: OpenApiDoc, name: str) -> None:
    assert name in openapi.components


@pytest.mark.parametrize("name", MANAGER_COMPONENTS)
@pytest.mark.parametrize("suffix", ["-Input", "-Output"])
def test_manager_component_schema_is_not_split_into_input_and_output_variants(
    openapi: OpenApiDoc, name: str, suffix: str
) -> None:
    assert f"{name}{suffix}" not in openapi.components


@pytest.mark.parametrize("name", MANAGER_COMPONENTS)
def test_manager_component_property_names_contain_no_underscore(
    openapi: OpenApiDoc, name: str
) -> None:
    offenders = [p for p in _property_names(openapi.component(name)) if "_" in p]
    assert offenders == []


# ManagerAccountStatus


def test_manager_account_status_is_string_enum_of_not_activated_and_active(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component("ManagerAccountStatus")
    assert schema["type"] == "string"
    assert sorted(schema["enum"]) == ["active", "notActivated"]
    assert len(schema["enum"]) == 2


# ManagerInput

MANAGER_INPUT_FIELDS = {"name", "phone", "propertyIds", "nickname"}
MANAGER_INPUT_REQUIRED = {"name", "phone", "propertyIds"}


@pytest.fixture
def manager_input_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("ManagerInput")


def test_manager_input_has_exactly_its_fields(
    manager_input_schema: dict[str, Any],
) -> None:
    assert _property_names(manager_input_schema) == MANAGER_INPUT_FIELDS


def test_manager_input_requires_every_field_but_the_nickname(
    manager_input_schema: dict[str, Any],
) -> None:
    assert set(manager_input_schema["required"]) == MANAGER_INPUT_REQUIRED


def test_manager_input_has_no_email_field(
    manager_input_schema: dict[str, Any],
) -> None:
    assert "email" not in _property_names(manager_input_schema)


@pytest.mark.parametrize("field", ["name", "phone"])
def test_manager_input_text_field_is_non_empty_string(
    manager_input_schema: dict[str, Any], field: str
) -> None:
    schema = manager_input_schema["properties"][field]
    assert schema["type"] == "string"
    assert schema["minLength"] == 1


def test_manager_input_nickname_is_nullable_string_without_minimum_length(
    manager_input_schema: dict[str, Any],
) -> None:
    inner = nullable_inner(manager_input_schema["properties"]["nickname"])
    assert inner["type"] == "string"
    assert "minLength" not in inner


def test_manager_input_property_ids_is_non_empty_array_of_uuid_strings(
    manager_input_schema: dict[str, Any],
) -> None:
    schema = manager_input_schema["properties"]["propertyIds"]
    assert schema["type"] == "array"
    assert schema["minItems"] == 1
    _assert_uuid_string(schema["items"])


# ManagerProperty

MANAGER_PROPERTY_FIELDS = {"id", "name", "address"}


@pytest.fixture
def manager_property_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("ManagerProperty")


def test_manager_property_has_exactly_its_fields(
    manager_property_schema: dict[str, Any],
) -> None:
    assert _property_names(manager_property_schema) == MANAGER_PROPERTY_FIELDS


def test_manager_property_requires_every_field(
    manager_property_schema: dict[str, Any],
) -> None:
    assert set(manager_property_schema["required"]) == MANAGER_PROPERTY_FIELDS


def test_manager_property_id_is_uuid_string(
    manager_property_schema: dict[str, Any],
) -> None:
    _assert_uuid_string(manager_property_schema["properties"]["id"])


@pytest.mark.parametrize("field", ["name", "address"])
def test_manager_property_text_field_is_string(
    manager_property_schema: dict[str, Any], field: str
) -> None:
    assert manager_property_schema["properties"][field]["type"] == "string"


# ManagerInvitation

MANAGER_INVITATION_FIELDS = {"url", "createdAt", "expiresAt", "expired"}


@pytest.fixture
def manager_invitation_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("ManagerInvitation")


def test_manager_invitation_has_exactly_its_fields(
    manager_invitation_schema: dict[str, Any],
) -> None:
    assert _property_names(manager_invitation_schema) == MANAGER_INVITATION_FIELDS


def test_manager_invitation_requires_every_field(
    manager_invitation_schema: dict[str, Any],
) -> None:
    assert set(manager_invitation_schema["required"]) == MANAGER_INVITATION_FIELDS


def test_manager_invitation_url_is_nullable_string(
    manager_invitation_schema: dict[str, Any],
) -> None:
    schema = manager_invitation_schema["properties"]["url"]
    assert nullable_inner(schema)["type"] == "string"


@pytest.mark.parametrize("field", ["createdAt", "expiresAt"])
def test_manager_invitation_timestamp_is_date_time_string(
    manager_invitation_schema: dict[str, Any], field: str
) -> None:
    schema = manager_invitation_schema["properties"][field]
    assert schema["type"] == "string"
    assert schema["format"] == "date-time"


def test_manager_invitation_expired_is_boolean(
    manager_invitation_schema: dict[str, Any],
) -> None:
    assert manager_invitation_schema["properties"]["expired"]["type"] == "boolean"


# Manager

MANAGER_FIELDS = {
    "id",
    "name",
    "nickname",
    "phone",
    "email",
    "accountStatus",
    "properties",
    "invitation",
}


@pytest.fixture
def manager_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component(
        openapi.response_schema_ref("get", "/managers/{managerId}", 200)
    )


def test_manager_has_exactly_its_fields(manager_schema: dict[str, Any]) -> None:
    assert _property_names(manager_schema) == MANAGER_FIELDS


def test_manager_requires_every_field(manager_schema: dict[str, Any]) -> None:
    assert set(manager_schema["required"]) == MANAGER_FIELDS


def test_manager_id_is_uuid_string(manager_schema: dict[str, Any]) -> None:
    _assert_uuid_string(manager_schema["properties"]["id"])


@pytest.mark.parametrize("field", ["name", "phone"])
def test_manager_text_field_is_string(
    manager_schema: dict[str, Any], field: str
) -> None:
    assert manager_schema["properties"][field]["type"] == "string"


@pytest.mark.parametrize("field", ["nickname", "email"])
def test_manager_nullable_text_field_is_nullable_string(
    manager_schema: dict[str, Any], field: str
) -> None:
    assert nullable_inner(manager_schema["properties"][field])["type"] == "string"


def test_manager_account_status_is_manager_account_status_enum(
    openapi: OpenApiDoc, manager_schema: dict[str, Any]
) -> None:
    schema = manager_schema["properties"]["accountStatus"]
    assert openapi.ref_name(schema) == "ManagerAccountStatus"


def test_manager_properties_is_array_of_manager_property(
    openapi: OpenApiDoc, manager_schema: dict[str, Any]
) -> None:
    schema = manager_schema["properties"]["properties"]
    assert schema["type"] == "array"
    assert openapi.ref_name(schema["items"]) == "ManagerProperty"


def test_manager_invitation_is_nullable_manager_invitation(
    openapi: OpenApiDoc, manager_schema: dict[str, Any]
) -> None:
    schema = manager_schema["properties"]["invitation"]
    assert openapi.ref_name(nullable_inner(schema)) == "ManagerInvitation"


# ManagerSummary

MANAGER_SUMMARY_FIELDS = {
    "id",
    "name",
    "nickname",
    "phone",
    "email",
    "accountStatus",
    "properties",
}


@pytest.fixture
def manager_summary_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("ManagerSummary")


def test_manager_summary_has_exactly_its_fields(
    manager_summary_schema: dict[str, Any],
) -> None:
    assert _property_names(manager_summary_schema) == MANAGER_SUMMARY_FIELDS


def test_manager_summary_requires_every_field(
    manager_summary_schema: dict[str, Any],
) -> None:
    assert set(manager_summary_schema["required"]) == MANAGER_SUMMARY_FIELDS


def test_manager_summary_leaves_out_invitation(
    manager_summary_schema: dict[str, Any],
) -> None:
    assert "invitation" not in _property_names(manager_summary_schema)


def test_manager_summary_id_is_uuid_string(
    manager_summary_schema: dict[str, Any],
) -> None:
    _assert_uuid_string(manager_summary_schema["properties"]["id"])


@pytest.mark.parametrize("field", ["name", "phone"])
def test_manager_summary_text_field_is_string(
    manager_summary_schema: dict[str, Any], field: str
) -> None:
    assert manager_summary_schema["properties"][field]["type"] == "string"


@pytest.mark.parametrize("field", ["nickname", "email"])
def test_manager_summary_nullable_text_field_is_nullable_string(
    manager_summary_schema: dict[str, Any], field: str
) -> None:
    schema = manager_summary_schema["properties"][field]
    assert nullable_inner(schema)["type"] == "string"


def test_manager_summary_account_status_is_manager_account_status_enum(
    openapi: OpenApiDoc, manager_summary_schema: dict[str, Any]
) -> None:
    schema = manager_summary_schema["properties"]["accountStatus"]
    assert openapi.ref_name(schema) == "ManagerAccountStatus"


def test_manager_summary_properties_is_array_of_manager_property(
    openapi: OpenApiDoc, manager_summary_schema: dict[str, Any]
) -> None:
    schema = manager_summary_schema["properties"]["properties"]
    assert schema["type"] == "array"
    assert openapi.ref_name(schema["items"]) == "ManagerProperty"


# ManagerList


def test_manager_list_items_is_required_array_of_manager_summary(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component(openapi.response_schema_ref("get", "/managers", 200))
    assert _property_names(schema) == {"items"}
    assert set(schema["required"]) == {"items"}
    items = schema["properties"]["items"]
    assert items["type"] == "array"
    assert openapi.ref_name(items["items"]) == "ManagerSummary"
