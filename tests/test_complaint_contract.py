"""Contract tests for the complaint and complaint-category endpoints."""

from typing import Any

import pytest
from conftest import COMPLAINT_ID, NOT_A_UUID, OpenApiDoc, nullable_inner

COMPLAINT_PATHS = {
    "/complaints": {"post", "get"},
    "/complaints/{complaintId}": {"get"},
    "/complaints/{complaintId}/status-changes": {"post"},
    "/complaints/{complaintId}/classification": {"put"},
    "/complaints/{complaintId}/photo": {"put", "get"},
    "/complaint-categories": {"get"},
}

# (method, path, operationId, success status)
COMPLAINT_OPERATIONS = [
    ("post", "/complaints", "create_complaint", 201),
    ("get", "/complaints", "list_complaints", 200),
    ("get", "/complaints/{complaintId}", "get_complaint", 200),
    (
        "post",
        "/complaints/{complaintId}/status-changes",
        "change_complaint_status",
        201,
    ),
    (
        "put",
        "/complaints/{complaintId}/classification",
        "classify_complaint",
        200,
    ),
    ("put", "/complaints/{complaintId}/photo", "upload_complaint_photo", 200),
    ("get", "/complaints/{complaintId}/photo", "get_complaint_photo", 200),
    ("get", "/complaint-categories", "list_complaint_categories", 200),
]

# (method, path, path parameter name)
COMPLAINT_PATH_PARAMETERS = [
    pytest.param("get", "/complaints/{complaintId}", "complaintId", id="get_complaint"),
    pytest.param(
        "post",
        "/complaints/{complaintId}/status-changes",
        "complaintId",
        id="change_complaint_status",
    ),
    pytest.param(
        "put",
        "/complaints/{complaintId}/classification",
        "complaintId",
        id="classify_complaint",
    ),
    pytest.param(
        "put",
        "/complaints/{complaintId}/photo",
        "complaintId",
        id="upload_complaint_photo",
    ),
    pytest.param(
        "get",
        "/complaints/{complaintId}/photo",
        "complaintId",
        id="get_complaint_photo",
    ),
]

# Operations that take no path parameter.
NO_PARAMETER_OPERATIONS = [
    pytest.param("post", "/complaints", id="create_complaint"),
    pytest.param("get", "/complaints", id="list_complaints"),
    pytest.param("get", "/complaint-categories", id="list_complaint_categories"),
]

COMPLAINT_STATUSES = ["new", "inProgress", "done"]
COMPLAINT_URGENCIES = ["low", "medium", "high"]

VALID_COMPLAINT_INPUT = {"description": "The air conditioner does not cool."}
VALID_CLASSIFICATION_INPUT = {"category": "Electrical", "urgency": "high"}
VALID_STATUS_CHANGE_INPUT = {"status": "inProgress"}

COMPLAINTS_URL = "/complaints"
COMPLAINT_URL = f"/complaints/{COMPLAINT_ID}"
STATUS_CHANGES_URL = f"{COMPLAINT_URL}/status-changes"
CLASSIFICATION_URL = f"{COMPLAINT_URL}/classification"
PHOTO_URL = f"{COMPLAINT_URL}/photo"
CATEGORIES_URL = "/complaint-categories"

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 16

COMPLAINT_COMPONENTS = [
    "ComplaintStatus",
    "ComplaintUrgency",
    "ComplaintClassificationState",
    "ComplaintInput",
    "ComplaintClassificationInput",
    "AiComplaintClassification",
    "ComplaintClassification",
    "ComplaintStatusChangeInput",
    "ComplaintStatusChange",
    "PropertyRef",
    "Complaint",
    "ComplaintSummary",
    "ComplaintList",
    "ComplaintCategoryList",
]


def _without(body: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k not in keys}


def _property_names(schema: dict[str, Any]) -> set[str]:
    return set(schema.get("properties", {}))


def _assert_uuid_string(schema: dict[str, Any]) -> None:
    assert schema["type"] == "string"
    assert schema["format"] == "uuid"


def _assert_string_enum(schema: dict[str, Any], values: list[str]) -> None:
    assert schema["type"] == "string"
    assert sorted(schema["enum"]) == sorted(values)
    assert len(schema["enum"]) == len(values)


# Paths, operations, tags and status codes


@pytest.mark.parametrize(("path", "methods"), COMPLAINT_PATHS.items())
def test_complaint_path_declares_exactly_its_methods(
    openapi: OpenApiDoc, path: str, methods: set[str]
) -> None:
    declared = {
        m
        for m in openapi.document["paths"].get(path, {})
        if m in {"get", "put", "post", "delete", "patch", "options", "head", "trace"}
    }
    assert declared == methods


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), COMPLAINT_OPERATIONS
)
def test_complaint_operation_has_operation_id(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["operationId"] == operation_id


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), COMPLAINT_OPERATIONS
)
def test_complaint_operation_is_tagged_complaints(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["tags"] == ["complaints"]


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), COMPLAINT_OPERATIONS
)
def test_complaint_operation_declares_only_its_success_status_besides_validation_error(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    responses = set(openapi.operation(method, path)["responses"])
    assert responses - {"422"} == {str(status)}


@pytest.mark.parametrize(("method", "path", "name"), COMPLAINT_PATH_PARAMETERS)
def test_complaint_operation_path_parameter_is_required_uuid(
    openapi: OpenApiDoc, method: str, path: str, name: str
) -> None:
    parameters = openapi.operation(method, path)["parameters"]
    assert [p["name"] for p in parameters] == [name]
    (parameter,) = parameters
    assert parameter["in"] == "path"
    assert parameter["required"] is True
    _assert_uuid_string(parameter["schema"])


@pytest.mark.parametrize(("method", "path"), NO_PARAMETER_OPERATIONS)
def test_collection_operation_declares_no_parameters(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert openapi.operation(method, path).get("parameters", []) == []


# Request and response schema references


@pytest.mark.parametrize(
    ("method", "path", "schema"),
    [
        ("post", "/complaints", "ComplaintInput"),
        (
            "post",
            "/complaints/{complaintId}/status-changes",
            "ComplaintStatusChangeInput",
        ),
        (
            "put",
            "/complaints/{complaintId}/classification",
            "ComplaintClassificationInput",
        ),
    ],
    ids=["create_complaint", "change_complaint_status", "classify_complaint"],
)
def test_complaint_write_operation_request_body_schema(
    openapi: OpenApiDoc, method: str, path: str, schema: str
) -> None:
    assert openapi.request_schema_ref(method, path) == schema


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/complaints"),
        ("get", "/complaints/{complaintId}"),
        ("get", "/complaints/{complaintId}/photo"),
        ("get", "/complaint-categories"),
    ],
    ids=[
        "list_complaints",
        "get_complaint",
        "get_complaint_photo",
        "list_complaint_categories",
    ],
)
def test_complaint_read_operations_take_no_request_body(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert "requestBody" not in openapi.operation(method, path)


@pytest.mark.parametrize(
    ("method", "path", "status", "schema"),
    [
        ("post", "/complaints", 201, "Complaint"),
        ("get", "/complaints", 200, "ComplaintList"),
        ("get", "/complaints/{complaintId}", 200, "Complaint"),
        ("post", "/complaints/{complaintId}/status-changes", 201, "Complaint"),
        ("put", "/complaints/{complaintId}/classification", 200, "Complaint"),
        ("put", "/complaints/{complaintId}/photo", 200, "Complaint"),
        ("get", "/complaint-categories", 200, "ComplaintCategoryList"),
    ],
    ids=[
        "create_complaint",
        "list_complaints",
        "get_complaint",
        "change_complaint_status",
        "classify_complaint",
        "upload_complaint_photo",
        "list_complaint_categories",
    ],
)
def test_complaint_operation_response_schema(
    openapi: OpenApiDoc, method: str, path: str, status: int, schema: str
) -> None:
    assert openapi.response_schema_ref(method, path, status) == schema


# Photo upload and download


def test_upload_complaint_photo_requires_multipart_form_data_body(
    openapi: OpenApiDoc,
) -> None:
    body = openapi.operation("put", "/complaints/{complaintId}/photo")["requestBody"]
    assert body["required"] is True
    assert set(body["content"]) == {"multipart/form-data"}


@pytest.fixture
def photo_form_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    body = openapi.operation("put", "/complaints/{complaintId}/photo")["requestBody"]
    return openapi.resolve(body["content"]["multipart/form-data"]["schema"])


def test_upload_complaint_photo_form_has_exactly_the_file_field(
    photo_form_schema: dict[str, Any],
) -> None:
    assert _property_names(photo_form_schema) == {"file"}


def test_upload_complaint_photo_form_requires_the_file_field(
    photo_form_schema: dict[str, Any],
) -> None:
    assert set(photo_form_schema["required"]) == {"file"}


def test_upload_complaint_photo_file_field_is_binary_string(
    photo_form_schema: dict[str, Any],
) -> None:
    schema = photo_form_schema["properties"]["file"]
    assert schema["type"] == "string"
    assert schema["format"] == "binary"


def test_get_complaint_photo_responds_with_jpeg_and_png_images_only(
    openapi: OpenApiDoc,
) -> None:
    responses = openapi.operation("get", "/complaints/{complaintId}/photo")["responses"]
    assert set(responses["200"]["content"]) == {"image/jpeg", "image/png"}


@pytest.mark.parametrize("content_type", ["image/jpeg", "image/png"])
def test_get_complaint_photo_image_response_is_binary(
    openapi: OpenApiDoc, content_type: str
) -> None:
    responses = openapi.operation("get", "/complaints/{complaintId}/photo")["responses"]
    schema = responses["200"]["content"][content_type].get("schema", {})
    assert "$ref" not in schema
    assert schema.get("format", "binary") == "binary"


@pytest.mark.parametrize("name", COMPLAINT_COMPONENTS)
def test_complaint_component_schema_is_declared(openapi: OpenApiDoc, name: str) -> None:
    assert name in openapi.components


@pytest.mark.parametrize("name", COMPLAINT_COMPONENTS)
@pytest.mark.parametrize("suffix", ["-Input", "-Output"])
def test_complaint_component_schema_is_not_split_into_input_and_output_variants(
    openapi: OpenApiDoc, name: str, suffix: str
) -> None:
    assert f"{name}{suffix}" not in openapi.components


@pytest.mark.parametrize("name", COMPLAINT_COMPONENTS)
def test_complaint_component_property_names_contain_no_underscore(
    openapi: OpenApiDoc, name: str
) -> None:
    offenders = [p for p in _property_names(openapi.component(name)) if "_" in p]
    assert offenders == []


# Enums


def test_complaint_status_is_string_enum_of_its_statuses(openapi: OpenApiDoc) -> None:
    _assert_string_enum(openapi.component("ComplaintStatus"), COMPLAINT_STATUSES)


def test_complaint_urgency_is_string_enum_of_its_levels(openapi: OpenApiDoc) -> None:
    _assert_string_enum(openapi.component("ComplaintUrgency"), COMPLAINT_URGENCIES)


def test_complaint_classification_state_is_string_enum_of_its_states(
    openapi: OpenApiDoc,
) -> None:
    _assert_string_enum(
        openapi.component("ComplaintClassificationState"),
        ["awaitingClassification", "notClassified", "classifying"],
    )


# ComplaintInput


def test_complaint_input_has_only_required_description(openapi: OpenApiDoc) -> None:
    schema = openapi.component("ComplaintInput")
    assert _property_names(schema) == {"description"}
    assert set(schema["required"]) == {"description"}


def test_complaint_input_description_is_string_of_at_least_ten_characters(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component("ComplaintInput")["properties"]["description"]
    assert schema["type"] == "string"
    assert schema["minLength"] == 10


# ComplaintClassificationInput


@pytest.fixture
def classification_input_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("ComplaintClassificationInput")


def test_classification_input_has_exactly_category_and_urgency(
    classification_input_schema: dict[str, Any],
) -> None:
    assert _property_names(classification_input_schema) == {"category", "urgency"}


def test_classification_input_requires_every_field(
    classification_input_schema: dict[str, Any],
) -> None:
    assert set(classification_input_schema["required"]) == {"category", "urgency"}


def test_classification_input_category_is_non_empty_string(
    classification_input_schema: dict[str, Any],
) -> None:
    schema = classification_input_schema["properties"]["category"]
    assert schema["type"] == "string"
    assert schema["minLength"] == 1


def test_classification_input_urgency_is_complaint_urgency(
    openapi: OpenApiDoc, classification_input_schema: dict[str, Any]
) -> None:
    schema = classification_input_schema["properties"]["urgency"]
    assert openapi.ref_name(schema) == "ComplaintUrgency"


# ComplaintClassification

CLASSIFICATION_FIELDS = {
    "category",
    "urgency",
    "suggestedAction",
    "classifiedByName",
    "originalAiClassification",
}


@pytest.fixture
def classification_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("ComplaintClassification")


def test_classification_has_exactly_its_fields(
    classification_schema: dict[str, Any],
) -> None:
    assert _property_names(classification_schema) == CLASSIFICATION_FIELDS


def test_classification_requires_every_field(
    classification_schema: dict[str, Any],
) -> None:
    assert set(classification_schema["required"]) == CLASSIFICATION_FIELDS


def test_classification_category_is_string(
    classification_schema: dict[str, Any],
) -> None:
    assert classification_schema["properties"]["category"]["type"] == "string"


def test_classification_urgency_is_complaint_urgency(
    openapi: OpenApiDoc, classification_schema: dict[str, Any]
) -> None:
    schema = classification_schema["properties"]["urgency"]
    assert openapi.ref_name(schema) == "ComplaintUrgency"


def test_classification_suggested_action_is_nullable_string(
    classification_schema: dict[str, Any],
) -> None:
    schema = classification_schema["properties"]["suggestedAction"]
    assert nullable_inner(schema)["type"] == "string"


def test_classification_classified_by_name_is_nullable_string(
    classification_schema: dict[str, Any],
) -> None:
    schema = classification_schema["properties"]["classifiedByName"]
    assert nullable_inner(schema)["type"] == "string"


def test_classification_original_ai_classification_is_nullable_ai_classification(
    openapi: OpenApiDoc, classification_schema: dict[str, Any]
) -> None:
    schema = classification_schema["properties"]["originalAiClassification"]
    assert openapi.ref_name(nullable_inner(schema)) == "AiComplaintClassification"


# AiComplaintClassification

AI_CLASSIFICATION_FIELDS = {"category", "urgency", "suggestedAction"}


@pytest.fixture
def ai_classification_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("AiComplaintClassification")


def test_ai_classification_has_exactly_its_fields(
    ai_classification_schema: dict[str, Any],
) -> None:
    assert _property_names(ai_classification_schema) == AI_CLASSIFICATION_FIELDS


def test_ai_classification_requires_every_field(
    ai_classification_schema: dict[str, Any],
) -> None:
    assert set(ai_classification_schema["required"]) == AI_CLASSIFICATION_FIELDS


def test_ai_classification_category_is_string(
    ai_classification_schema: dict[str, Any],
) -> None:
    assert ai_classification_schema["properties"]["category"]["type"] == "string"


def test_ai_classification_urgency_is_complaint_urgency(
    openapi: OpenApiDoc, ai_classification_schema: dict[str, Any]
) -> None:
    schema = ai_classification_schema["properties"]["urgency"]
    assert openapi.ref_name(schema) == "ComplaintUrgency"


def test_ai_classification_suggested_action_is_non_nullable_string(
    ai_classification_schema: dict[str, Any],
) -> None:
    schema = ai_classification_schema["properties"]["suggestedAction"]
    assert schema["type"] == "string"
    assert "anyOf" not in schema


# ComplaintStatusChangeInput


@pytest.fixture
def status_change_input_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("ComplaintStatusChangeInput")


def test_status_change_input_has_exactly_status_and_handling_note(
    status_change_input_schema: dict[str, Any],
) -> None:
    assert _property_names(status_change_input_schema) == {"status", "handlingNote"}


def test_status_change_input_requires_only_status(
    status_change_input_schema: dict[str, Any],
) -> None:
    assert set(status_change_input_schema["required"]) == {"status"}


def test_status_change_input_status_is_complaint_status(
    openapi: OpenApiDoc, status_change_input_schema: dict[str, Any]
) -> None:
    schema = status_change_input_schema["properties"]["status"]
    assert openapi.ref_name(schema) == "ComplaintStatus"


def test_status_change_input_handling_note_is_optional_nullable_string(
    status_change_input_schema: dict[str, Any],
) -> None:
    schema = status_change_input_schema["properties"]["handlingNote"]
    assert nullable_inner(schema)["type"] == "string"
    assert "handlingNote" not in status_change_input_schema["required"]


# ComplaintStatusChange

STATUS_CHANGE_FIELDS = {"status", "handlingNote", "changedAt"}


@pytest.fixture
def status_change_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("ComplaintStatusChange")


def test_status_change_has_exactly_its_fields(
    status_change_schema: dict[str, Any],
) -> None:
    assert _property_names(status_change_schema) == STATUS_CHANGE_FIELDS


def test_status_change_requires_every_field(
    status_change_schema: dict[str, Any],
) -> None:
    assert set(status_change_schema["required"]) == STATUS_CHANGE_FIELDS


def test_status_change_status_is_complaint_status(
    openapi: OpenApiDoc, status_change_schema: dict[str, Any]
) -> None:
    schema = status_change_schema["properties"]["status"]
    assert openapi.ref_name(schema) == "ComplaintStatus"


def test_status_change_handling_note_is_nullable_string(
    status_change_schema: dict[str, Any],
) -> None:
    schema = status_change_schema["properties"]["handlingNote"]
    assert nullable_inner(schema)["type"] == "string"


def test_status_change_changed_at_is_date_time_string(
    status_change_schema: dict[str, Any],
) -> None:
    schema = status_change_schema["properties"]["changedAt"]
    assert schema["type"] == "string"
    assert schema["format"] == "date-time"


# PropertyRef


@pytest.fixture
def property_ref_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("PropertyRef")


def test_property_ref_has_exactly_id_and_name(
    property_ref_schema: dict[str, Any],
) -> None:
    assert _property_names(property_ref_schema) == {"id", "name"}


def test_property_ref_requires_id_and_name(
    property_ref_schema: dict[str, Any],
) -> None:
    assert set(property_ref_schema["required"]) == {"id", "name"}


def test_property_ref_id_is_uuid_string(property_ref_schema: dict[str, Any]) -> None:
    _assert_uuid_string(property_ref_schema["properties"]["id"])


def test_property_ref_name_is_string(property_ref_schema: dict[str, Any]) -> None:
    assert property_ref_schema["properties"]["name"]["type"] == "string"


# Complaint and ComplaintSummary

SUMMARY_FIELDS = {
    "id",
    "description",
    "status",
    "property",
    "room",
    "tenantName",
    "createdAt",
    "classification",
    "classificationState",
    "classificationWithheld",
    "hasPhoto",
}

COMPLAINT_FIELDS = {*SUMMARY_FIELDS, "statusChanges"}


@pytest.fixture(params=["Complaint", "ComplaintSummary"])
def any_complaint_schema(
    request: pytest.FixtureRequest, openapi: OpenApiDoc
) -> dict[str, Any]:
    return openapi.component(request.param)


def test_complaint_has_exactly_its_fields(openapi: OpenApiDoc) -> None:
    assert _property_names(openapi.component("Complaint")) == COMPLAINT_FIELDS


def test_complaint_requires_every_field(openapi: OpenApiDoc) -> None:
    assert set(openapi.component("Complaint")["required"]) == COMPLAINT_FIELDS


def test_complaint_summary_has_exactly_the_complaint_fields_without_status_changes(
    openapi: OpenApiDoc,
) -> None:
    assert _property_names(openapi.component("ComplaintSummary")) == SUMMARY_FIELDS


def test_complaint_summary_requires_every_field(openapi: OpenApiDoc) -> None:
    assert set(openapi.component("ComplaintSummary")["required"]) == SUMMARY_FIELDS


def test_complaint_id_is_uuid_string(any_complaint_schema: dict[str, Any]) -> None:
    _assert_uuid_string(any_complaint_schema["properties"]["id"])


@pytest.mark.parametrize("field", ["description", "tenantName"])
def test_complaint_text_field_is_string(
    any_complaint_schema: dict[str, Any], field: str
) -> None:
    assert any_complaint_schema["properties"][field]["type"] == "string"


def test_complaint_status_is_complaint_status(
    openapi: OpenApiDoc, any_complaint_schema: dict[str, Any]
) -> None:
    schema = any_complaint_schema["properties"]["status"]
    assert openapi.ref_name(schema) == "ComplaintStatus"


def test_complaint_property_is_property_ref(
    openapi: OpenApiDoc, any_complaint_schema: dict[str, Any]
) -> None:
    schema = any_complaint_schema["properties"]["property"]
    assert openapi.ref_name(schema) == "PropertyRef"


def test_complaint_room_is_room_ref(
    openapi: OpenApiDoc, any_complaint_schema: dict[str, Any]
) -> None:
    assert openapi.ref_name(any_complaint_schema["properties"]["room"]) == "RoomRef"


def test_complaint_created_at_is_date_time_string(
    any_complaint_schema: dict[str, Any],
) -> None:
    schema = any_complaint_schema["properties"]["createdAt"]
    assert schema["type"] == "string"
    assert schema["format"] == "date-time"


def test_complaint_classification_is_nullable_complaint_classification(
    openapi: OpenApiDoc, any_complaint_schema: dict[str, Any]
) -> None:
    schema = any_complaint_schema["properties"]["classification"]
    assert openapi.ref_name(nullable_inner(schema)) == "ComplaintClassification"


def test_complaint_classification_state_is_nullable_complaint_classification_state(
    openapi: OpenApiDoc, any_complaint_schema: dict[str, Any]
) -> None:
    schema = any_complaint_schema["properties"]["classificationState"]
    assert openapi.ref_name(nullable_inner(schema)) == "ComplaintClassificationState"


def test_complaint_classification_withheld_is_boolean(
    any_complaint_schema: dict[str, Any],
) -> None:
    schema = any_complaint_schema["properties"]["classificationWithheld"]
    assert schema["type"] == "boolean"


def test_complaint_has_photo_is_boolean(
    any_complaint_schema: dict[str, Any],
) -> None:
    assert any_complaint_schema["properties"]["hasPhoto"]["type"] == "boolean"


def test_complaint_status_changes_is_array_of_complaint_status_change(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component("Complaint")["properties"]["statusChanges"]
    assert schema["type"] == "array"
    assert openapi.ref_name(schema["items"]) == "ComplaintStatusChange"


# ComplaintList and ComplaintCategoryList


def test_complaint_list_items_is_required_array_of_complaint_summary(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component("ComplaintList")
    assert _property_names(schema) == {"items"}
    assert set(schema["required"]) == {"items"}
    items = schema["properties"]["items"]
    assert items["type"] == "array"
    assert openapi.ref_name(items["items"]) == "ComplaintSummary"


def test_complaint_category_list_items_is_required_array_of_strings(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component("ComplaintCategoryList")
    assert _property_names(schema) == {"items"}
    assert set(schema["required"]) == {"items"}
    items = schema["properties"]["items"]
    assert items["type"] == "array"
    assert items["items"]["type"] == "string"


# Runtime: valid requests reach the not-implemented stub


@pytest.fixture
def tenant_headers(make_user, sign_in) -> dict[str, str]:
    from app.schemas.auth import UserRole

    return sign_in(make_user(role=UserRole.TENANT)).headers


@pytest.fixture
def owner_headers(make_user, sign_in) -> dict[str, str]:
    return sign_in(make_user()).headers


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        pytest.param("get", PHOTO_URL, None, id="get_photo"),
    ],
)
def test_valid_complaint_request_responds_not_implemented(
    client, method: str, url: str, body: dict[str, Any] | None
) -> None:
    response = client.request(method, url, json=body)
    assert response.status_code == 501


@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [
        pytest.param("photo.png", PNG_BYTES, "image/png", id="png"),
        pytest.param("photo.jpg", JPEG_BYTES, "image/jpeg", id="jpeg"),
    ],
)
def test_valid_complaint_photo_upload_responds_not_implemented(
    client, filename: str, content: bytes, content_type: str
) -> None:
    response = client.put(PHOTO_URL, files={"file": (filename, content, content_type)})
    assert response.status_code == 501


# Runtime: invalid requests are rejected with a validation error


@pytest.mark.parametrize(
    "description",
    [
        pytest.param("", id="empty"),
        pytest.param("123456789", id="nine_characters"),
        pytest.param("          ", id="only_whitespace"),
        pytest.param("   123456789   ", id="nine_characters_after_trimming"),
        pytest.param("\n\tshort\n\t", id="short_with_surrounding_whitespace"),
    ],
)
def test_too_short_complaint_description_is_rejected_with_validation_error(
    client, tenant_headers: dict[str, str], description: str
) -> None:
    response = client.post(
        COMPLAINTS_URL, json={"description": description}, headers=tenant_headers
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="empty_object"),
        pytest.param({"description": None}, id="null_description"),
        pytest.param({"description": 1234567890}, id="numeric_description"),
        pytest.param({"description": ["a" * 10]}, id="array_description"),
    ],
)
def test_invalid_complaint_input_is_rejected_with_validation_error(
    client, tenant_headers: dict[str, str], body: dict[str, Any]
) -> None:
    response = client.post(COMPLAINTS_URL, json=body, headers=tenant_headers)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="empty_object"),
        pytest.param(
            _without(VALID_CLASSIFICATION_INPUT, "category"), id="no_category"
        ),
        pytest.param(_without(VALID_CLASSIFICATION_INPUT, "urgency"), id="no_urgency"),
        pytest.param(
            {**VALID_CLASSIFICATION_INPUT, "category": ""}, id="empty_category"
        ),
        pytest.param(
            {**VALID_CLASSIFICATION_INPUT, "category": None}, id="null_category"
        ),
        pytest.param(
            {**VALID_CLASSIFICATION_INPUT, "urgency": None}, id="null_urgency"
        ),
        pytest.param(
            {**VALID_CLASSIFICATION_INPUT, "urgency": "critical"}, id="unknown_urgency"
        ),
        pytest.param(
            {**VALID_CLASSIFICATION_INPUT, "urgency": "HIGH"}, id="wrong_case_urgency"
        ),
    ],
)
def test_invalid_classification_is_rejected_with_validation_error(
    client, owner_headers: dict[str, str], body: dict[str, Any]
) -> None:
    response = client.put(CLASSIFICATION_URL, json=body, headers=owner_headers)
    assert response.status_code == 422


def test_complaint_submission_without_body_is_rejected_with_validation_error(
    client, tenant_headers: dict[str, str]
) -> None:
    response = client.post(COMPLAINTS_URL, headers=tenant_headers)
    assert response.status_code == 422


def test_non_uuid_complaint_id_in_detail_is_rejected_with_validation_error(
    client, tenant_headers: dict[str, str]
) -> None:
    response = client.get(f"/complaints/{NOT_A_UUID}", headers=tenant_headers)
    assert response.status_code == 422


def test_classification_without_body_is_rejected_with_validation_error(
    client, owner_headers: dict[str, str]
) -> None:
    response = client.put(CLASSIFICATION_URL, headers=owner_headers)
    assert response.status_code == 422


def test_non_uuid_complaint_id_in_photo_upload_is_rejected_with_validation_error(
    client,
) -> None:
    response = client.put(
        f"/complaints/{NOT_A_UUID}/photo",
        files={"file": ("photo.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 422


def test_complaint_photo_upload_without_file_is_rejected_with_validation_error(
    client,
) -> None:
    assert client.put(PHOTO_URL).status_code == 422


def test_complaint_photo_upload_with_wrong_form_field_is_rejected_with_validation_error(
    client,
) -> None:
    response = client.put(
        PHOTO_URL, files={"photo": ("photo.png", PNG_BYTES, "image/png")}
    )
    assert response.status_code == 422


def test_non_uuid_complaint_id_in_photo_download_is_rejected_with_validation_error(
    client,
) -> None:
    assert client.get(f"/complaints/{NOT_A_UUID}/photo").status_code == 422


def test_non_uuid_complaint_id_in_classification_is_rejected_with_validation_error(
    client, owner_headers: dict[str, str]
) -> None:
    response = client.put(
        f"/complaints/{NOT_A_UUID}/classification",
        json=VALID_CLASSIFICATION_INPUT,
        headers=owner_headers,
    )
    assert response.status_code == 422
