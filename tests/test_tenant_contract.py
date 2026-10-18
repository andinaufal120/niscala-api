"""Contract tests for the tenant and tenant-invitation endpoints."""

from typing import Any

import pytest
from conftest import (
    NOT_A_UUID,
    PROPERTY_ID,
    ROOM_ID,
    TENANT_ID,
    OpenApiDoc,
    nullable_inner,
)

TENANT_PATHS = {
    "/properties/{propertyId}/tenants": {"post", "get"},
    "/tenants/{tenantId}": {"get", "put", "delete"},
    "/tenants/{tenantId}/invitation": {"post"},
}

# (method, path, operationId, success status)
TENANT_OPERATIONS = [
    ("post", "/properties/{propertyId}/tenants", "create_tenant", 201),
    ("get", "/properties/{propertyId}/tenants", "list_tenants", 200),
    ("get", "/tenants/{tenantId}", "get_tenant", 200),
    ("put", "/tenants/{tenantId}", "update_tenant", 200),
    ("delete", "/tenants/{tenantId}", "delete_tenant", 204),
    (
        "post",
        "/tenants/{tenantId}/invitation",
        "regenerate_tenant_invitation",
        201,
    ),
]

# (method, path, path parameter name)
TENANT_PATH_PARAMETERS = [
    pytest.param(
        "post", "/properties/{propertyId}/tenants", "propertyId", id="create_tenant"
    ),
    pytest.param(
        "get", "/properties/{propertyId}/tenants", "propertyId", id="list_tenants"
    ),
    pytest.param("get", "/tenants/{tenantId}", "tenantId", id="get_tenant"),
    pytest.param("put", "/tenants/{tenantId}", "tenantId", id="update_tenant"),
    pytest.param("delete", "/tenants/{tenantId}", "tenantId", id="delete_tenant"),
    pytest.param(
        "post",
        "/tenants/{tenantId}/invitation",
        "tenantId",
        id="regenerate_tenant_invitation",
    ),
]

BILLING_CYCLES = ["weekly", "monthly", "quarterly", "semiannual", "annual"]

VALID_EMERGENCY_CONTACT = {
    "name": "Siti",
    "relationship": "Ibu",
    "phone": "081234567890",
}

SECOND_EMERGENCY_CONTACT = {
    "name": "Agus",
    "relationship": "Kakak",
    "phone": "085712345678",
}

VALID_LEASE_INPUT = {
    "startDate": "2026-11-01",
    "endDate": "2027-10-31",
    "billingCycle": "monthly",
    "rent": 1500000,
    "gracePeriodDays": 3,
}

MINIMAL_TENANT_INPUT = {"name": "Rina", "phone": "081255204471"}

MINIMAL_NEW_TENANT_INPUT = {"roomId": ROOM_ID, **MINIMAL_TENANT_INPUT}

FULL_TENANT_INPUT = {
    **MINIMAL_TENANT_INPUT,
    "occupation": "Mahasiswa",
    "emergencyContacts": [VALID_EMERGENCY_CONTACT, SECOND_EMERGENCY_CONTACT],
    "lease": VALID_LEASE_INPUT,
}

FULL_NEW_TENANT_INPUT = {"roomId": ROOM_ID, **FULL_TENANT_INPUT}

CREATE_TENANT_URL = f"/properties/{PROPERTY_ID}/tenants"
TENANT_URL = f"/tenants/{TENANT_ID}"

# Operations that take a tenant body: (method, URL, minimal valid body).
TENANT_WRITE_REQUESTS = [
    pytest.param(
        "post", CREATE_TENANT_URL, MINIMAL_NEW_TENANT_INPUT, id="create_tenant"
    ),
    pytest.param("put", TENANT_URL, MINIMAL_TENANT_INPUT, id="update_tenant"),
]

TENANT_COMPONENTS = [
    "BillingCycle",
    "TenantAccountStatus",
    "EmergencyContact",
    "LeaseInput",
    "TenantInput",
    "NewTenantInput",
    "RoomRef",
    "Lease",
    "TenantInvitation",
    "Tenant",
    "TenantSummary",
    "TenantList",
]


def _without(body: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k not in keys}


def _with_lease(body: dict[str, Any], **lease: Any) -> dict[str, Any]:
    return {**body, "lease": {**VALID_LEASE_INPUT, **lease}}


def _property_names(schema: dict[str, Any]) -> set[str]:
    return set(schema.get("properties", {}))


def _assert_uuid_string(schema: dict[str, Any]) -> None:
    assert schema["type"] == "string"
    assert schema["format"] == "uuid"


def _assert_nullable_string_with_format(schema: dict[str, Any], fmt: str) -> None:
    inner = nullable_inner(schema)
    assert inner["type"] == "string"
    assert inner["format"] == fmt


# Paths, operations, tags and status codes


@pytest.mark.parametrize(("path", "methods"), TENANT_PATHS.items())
def test_tenant_path_declares_exactly_its_methods(
    openapi: OpenApiDoc, path: str, methods: set[str]
) -> None:
    declared = {
        m
        for m in openapi.document["paths"].get(path, {})
        if m in {"get", "put", "post", "delete", "patch", "options", "head", "trace"}
    }
    assert declared == methods


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), TENANT_OPERATIONS
)
def test_tenant_operation_has_operation_id(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["operationId"] == operation_id


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), TENANT_OPERATIONS
)
def test_tenant_operation_is_tagged_tenants(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    assert openapi.operation(method, path)["tags"] == ["tenants"]


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "status"), TENANT_OPERATIONS
)
def test_tenant_operation_declares_only_its_success_status_besides_validation_error(
    openapi: OpenApiDoc, method: str, path: str, operation_id: str, status: int
) -> None:
    responses = set(openapi.operation(method, path)["responses"])
    assert responses - {"422"} == {str(status)}


def test_delete_tenant_success_response_has_no_body(openapi: OpenApiDoc) -> None:
    response = openapi.operation("delete", "/tenants/{tenantId}")["responses"]["204"]
    assert "content" not in response


@pytest.mark.parametrize(("method", "path", "name"), TENANT_PATH_PARAMETERS)
def test_tenant_operation_path_parameter_is_required_uuid(
    openapi: OpenApiDoc, method: str, path: str, name: str
) -> None:
    parameters = openapi.operation(method, path)["parameters"]
    assert [p["name"] for p in parameters] == [name]
    (parameter,) = parameters
    assert parameter["in"] == "path"
    assert parameter["required"] is True
    _assert_uuid_string(parameter["schema"])


# Request and response schema references


def test_create_tenant_request_body_is_new_tenant_input(openapi: OpenApiDoc) -> None:
    assert (
        openapi.request_schema_ref("post", "/properties/{propertyId}/tenants")
        == "NewTenantInput"
    )


def test_update_tenant_request_body_is_tenant_input(openapi: OpenApiDoc) -> None:
    assert openapi.request_schema_ref("put", "/tenants/{tenantId}") == "TenantInput"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/properties/{propertyId}/tenants"),
        ("get", "/tenants/{tenantId}"),
        ("delete", "/tenants/{tenantId}"),
        ("post", "/tenants/{tenantId}/invitation"),
    ],
    ids=[
        "list_tenants",
        "get_tenant",
        "delete_tenant",
        "regenerate_tenant_invitation",
    ],
)
def test_tenant_read_delete_and_regenerate_operations_take_no_request_body(
    openapi: OpenApiDoc, method: str, path: str
) -> None:
    assert "requestBody" not in openapi.operation(method, path)


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("post", "/properties/{propertyId}/tenants", 201),
        ("get", "/tenants/{tenantId}", 200),
        ("put", "/tenants/{tenantId}", 200),
    ],
    ids=["create_tenant", "get_tenant", "update_tenant"],
)
def test_single_tenant_operations_respond_with_tenant(
    openapi: OpenApiDoc, method: str, path: str, status: int
) -> None:
    assert openapi.response_schema_ref(method, path, status) == "Tenant"


def test_list_tenants_responds_with_tenant_list(openapi: OpenApiDoc) -> None:
    assert (
        openapi.response_schema_ref("get", "/properties/{propertyId}/tenants", 200)
        == "TenantList"
    )


def test_regenerate_tenant_invitation_responds_with_tenant_invitation(
    openapi: OpenApiDoc,
) -> None:
    assert (
        openapi.response_schema_ref("post", "/tenants/{tenantId}/invitation", 201)
        == "TenantInvitation"
    )


@pytest.mark.parametrize("name", TENANT_COMPONENTS)
def test_tenant_component_schema_is_declared(openapi: OpenApiDoc, name: str) -> None:
    assert name in openapi.components


@pytest.mark.parametrize("name", TENANT_COMPONENTS)
@pytest.mark.parametrize("suffix", ["-Input", "-Output"])
def test_tenant_component_schema_is_not_split_into_input_and_output_variants(
    openapi: OpenApiDoc, name: str, suffix: str
) -> None:
    assert f"{name}{suffix}" not in openapi.components


@pytest.mark.parametrize("name", TENANT_COMPONENTS)
def test_tenant_component_property_names_contain_no_underscore(
    openapi: OpenApiDoc, name: str
) -> None:
    offenders = [p for p in _property_names(openapi.component(name)) if "_" in p]
    assert offenders == []


# BillingCycle and TenantAccountStatus


def test_billing_cycle_is_string_enum_of_its_cycles(openapi: OpenApiDoc) -> None:
    schema = openapi.component("BillingCycle")
    assert schema["type"] == "string"
    assert sorted(schema["enum"]) == sorted(BILLING_CYCLES)
    assert len(schema["enum"]) == len(BILLING_CYCLES)


def test_tenant_account_status_is_string_enum_of_not_activated_and_active(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component("TenantAccountStatus")
    assert schema["type"] == "string"
    assert sorted(schema["enum"]) == ["active", "notActivated"]
    assert len(schema["enum"]) == 2


# EmergencyContact

EMERGENCY_CONTACT_FIELDS = {"name", "relationship", "phone"}


@pytest.fixture
def emergency_contact_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("EmergencyContact")


def test_emergency_contact_has_exactly_its_fields(
    emergency_contact_schema: dict[str, Any],
) -> None:
    assert _property_names(emergency_contact_schema) == EMERGENCY_CONTACT_FIELDS


def test_emergency_contact_requires_every_field(
    emergency_contact_schema: dict[str, Any],
) -> None:
    assert set(emergency_contact_schema["required"]) == EMERGENCY_CONTACT_FIELDS


@pytest.mark.parametrize("field", sorted(EMERGENCY_CONTACT_FIELDS))
def test_emergency_contact_field_is_non_empty_string(
    emergency_contact_schema: dict[str, Any], field: str
) -> None:
    schema = emergency_contact_schema["properties"][field]
    assert schema["type"] == "string"
    assert schema["minLength"] == 1


# LeaseInput


@pytest.fixture
def lease_input_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("LeaseInput")


def test_lease_input_has_exactly_its_fields(lease_input_schema: dict[str, Any]) -> None:
    assert _property_names(lease_input_schema) == {
        "startDate",
        "endDate",
        "billingCycle",
        "rent",
        "gracePeriodDays",
    }


def test_lease_input_requires_no_field(lease_input_schema: dict[str, Any]) -> None:
    assert lease_input_schema.get("required", []) == []


@pytest.mark.parametrize("field", ["startDate", "endDate"])
def test_lease_input_date_is_optional_nullable_date_string(
    lease_input_schema: dict[str, Any], field: str
) -> None:
    _assert_nullable_string_with_format(lease_input_schema["properties"][field], "date")


def test_lease_input_billing_cycle_is_billing_cycle_defaulting_to_monthly(
    openapi: OpenApiDoc, lease_input_schema: dict[str, Any]
) -> None:
    schema = lease_input_schema["properties"]["billingCycle"]
    assert openapi.ref_name(schema) == "BillingCycle"
    assert schema["default"] == "monthly"


def test_lease_input_rent_is_optional_nullable_positive_integer(
    lease_input_schema: dict[str, Any],
) -> None:
    inner = nullable_inner(lease_input_schema["properties"]["rent"])
    assert inner["type"] == "integer"
    assert inner["exclusiveMinimum"] == 0


def test_lease_input_grace_period_days_is_non_negative_integer_defaulting_to_zero(
    lease_input_schema: dict[str, Any],
) -> None:
    schema = lease_input_schema["properties"]["gracePeriodDays"]
    assert schema["type"] == "integer"
    assert schema["minimum"] == 0
    assert schema["default"] == 0


# TenantInput and NewTenantInput

TENANT_INPUT_FIELDS = {"name", "phone", "occupation", "emergencyContacts", "lease"}


@pytest.fixture(params=["TenantInput", "NewTenantInput"])
def any_tenant_input_schema(
    request: pytest.FixtureRequest, openapi: OpenApiDoc
) -> dict[str, Any]:
    return openapi.component(request.param)


def test_tenant_input_has_exactly_its_fields(openapi: OpenApiDoc) -> None:
    assert _property_names(openapi.component("TenantInput")) == TENANT_INPUT_FIELDS


def test_tenant_input_leaves_out_room_id(openapi: OpenApiDoc) -> None:
    assert "roomId" not in _property_names(openapi.component("TenantInput"))


def test_tenant_input_requires_only_name_and_phone(openapi: OpenApiDoc) -> None:
    assert set(openapi.component("TenantInput")["required"]) == {"name", "phone"}


def test_new_tenant_input_has_tenant_input_fields_plus_room_id(
    openapi: OpenApiDoc,
) -> None:
    assert _property_names(openapi.component("NewTenantInput")) == {
        *TENANT_INPUT_FIELDS,
        "roomId",
    }


def test_new_tenant_input_requires_only_room_id_name_and_phone(
    openapi: OpenApiDoc,
) -> None:
    assert set(openapi.component("NewTenantInput")["required"]) == {
        "roomId",
        "name",
        "phone",
    }


def test_new_tenant_input_room_id_is_uuid_string(openapi: OpenApiDoc) -> None:
    _assert_uuid_string(openapi.component("NewTenantInput")["properties"]["roomId"])


@pytest.mark.parametrize("field", ["name", "phone"])
def test_tenant_input_text_field_is_non_empty_string(
    any_tenant_input_schema: dict[str, Any], field: str
) -> None:
    schema = any_tenant_input_schema["properties"][field]
    assert schema["type"] == "string"
    assert schema["minLength"] == 1


def test_tenant_input_occupation_is_optional_nullable_string(
    any_tenant_input_schema: dict[str, Any],
) -> None:
    schema = any_tenant_input_schema["properties"]["occupation"]
    assert nullable_inner(schema)["type"] == "string"
    assert "occupation" not in any_tenant_input_schema["required"]


def test_tenant_input_emergency_contacts_is_bounded_array_defaulting_to_empty(
    openapi: OpenApiDoc, any_tenant_input_schema: dict[str, Any]
) -> None:
    schema = any_tenant_input_schema["properties"]["emergencyContacts"]
    assert schema["type"] == "array"
    assert openapi.ref_name(schema["items"]) == "EmergencyContact"
    assert schema["maxItems"] == 4
    assert schema["default"] == []
    assert "emergencyContacts" not in any_tenant_input_schema["required"]


def test_tenant_input_lease_is_optional_lease_input(
    openapi: OpenApiDoc, any_tenant_input_schema: dict[str, Any]
) -> None:
    schema = any_tenant_input_schema["properties"]["lease"]
    assert openapi.ref_name(schema) == "LeaseInput"
    assert "lease" not in any_tenant_input_schema["required"]


# Tenant

TENANT_FIELDS = {
    "id",
    "name",
    "phone",
    "email",
    "occupation",
    "accountStatus",
    "room",
    "lease",
    "emergencyContacts",
    "invitation",
}


@pytest.fixture
def tenant_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component(
        openapi.response_schema_ref("get", "/tenants/{tenantId}", 200)
    )


def test_tenant_has_exactly_its_fields(tenant_schema: dict[str, Any]) -> None:
    assert _property_names(tenant_schema) == TENANT_FIELDS


def test_tenant_requires_every_field(tenant_schema: dict[str, Any]) -> None:
    assert set(tenant_schema["required"]) == TENANT_FIELDS


def test_tenant_id_is_uuid_string(tenant_schema: dict[str, Any]) -> None:
    _assert_uuid_string(tenant_schema["properties"]["id"])


@pytest.mark.parametrize("field", ["name", "phone"])
def test_tenant_text_field_is_string(tenant_schema: dict[str, Any], field: str) -> None:
    assert tenant_schema["properties"][field]["type"] == "string"


@pytest.mark.parametrize("field", ["email", "occupation"])
def test_tenant_optional_text_field_is_nullable_string(
    tenant_schema: dict[str, Any], field: str
) -> None:
    assert nullable_inner(tenant_schema["properties"][field])["type"] == "string"


def test_tenant_account_status_is_tenant_account_status_enum(
    openapi: OpenApiDoc, tenant_schema: dict[str, Any]
) -> None:
    schema = tenant_schema["properties"]["accountStatus"]
    assert openapi.ref_name(schema) == "TenantAccountStatus"


def test_tenant_room_is_room_ref(
    openapi: OpenApiDoc, tenant_schema: dict[str, Any]
) -> None:
    assert openapi.ref_name(tenant_schema["properties"]["room"]) == "RoomRef"


def test_tenant_lease_is_lease(
    openapi: OpenApiDoc, tenant_schema: dict[str, Any]
) -> None:
    assert openapi.ref_name(tenant_schema["properties"]["lease"]) == "Lease"


def test_tenant_emergency_contacts_is_array_of_emergency_contact(
    openapi: OpenApiDoc, tenant_schema: dict[str, Any]
) -> None:
    schema = tenant_schema["properties"]["emergencyContacts"]
    assert schema["type"] == "array"
    assert openapi.ref_name(schema["items"]) == "EmergencyContact"


def test_tenant_invitation_is_nullable_tenant_invitation(
    openapi: OpenApiDoc, tenant_schema: dict[str, Any]
) -> None:
    schema = tenant_schema["properties"]["invitation"]
    assert openapi.ref_name(nullable_inner(schema)) == "TenantInvitation"


# RoomRef


@pytest.fixture
def room_ref_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("RoomRef")


def test_room_ref_has_exactly_id_and_number(room_ref_schema: dict[str, Any]) -> None:
    assert _property_names(room_ref_schema) == {"id", "number"}


def test_room_ref_requires_id_and_number(room_ref_schema: dict[str, Any]) -> None:
    assert set(room_ref_schema["required"]) == {"id", "number"}


def test_room_ref_id_is_uuid_string(room_ref_schema: dict[str, Any]) -> None:
    _assert_uuid_string(room_ref_schema["properties"]["id"])


def test_room_ref_number_is_string(room_ref_schema: dict[str, Any]) -> None:
    assert room_ref_schema["properties"]["number"]["type"] == "string"


# Lease

LEASE_FIELDS = {
    "startDate",
    "endDate",
    "rent",
    "billingCycle",
    "gracePeriodDays",
    "nextBillDate",
}


@pytest.fixture
def lease_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("Lease")


def test_lease_has_exactly_its_fields(lease_schema: dict[str, Any]) -> None:
    assert _property_names(lease_schema) == LEASE_FIELDS


def test_lease_requires_every_field(lease_schema: dict[str, Any]) -> None:
    assert set(lease_schema["required"]) == LEASE_FIELDS


@pytest.mark.parametrize("field", ["startDate", "endDate", "nextBillDate"])
def test_lease_date_is_nullable_date_string(
    lease_schema: dict[str, Any], field: str
) -> None:
    _assert_nullable_string_with_format(lease_schema["properties"][field], "date")


@pytest.mark.parametrize("field", ["rent", "gracePeriodDays"])
def test_lease_number_field_is_integer(
    lease_schema: dict[str, Any], field: str
) -> None:
    assert lease_schema["properties"][field]["type"] == "integer"


def test_lease_billing_cycle_is_billing_cycle_enum(
    openapi: OpenApiDoc, lease_schema: dict[str, Any]
) -> None:
    schema = lease_schema["properties"]["billingCycle"]
    assert openapi.ref_name(schema) == "BillingCycle"


# TenantInvitation

TENANT_INVITATION_FIELDS = {"url", "createdAt", "expiresAt", "expired"}


@pytest.fixture
def tenant_invitation_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("TenantInvitation")


def test_tenant_invitation_has_exactly_its_fields(
    tenant_invitation_schema: dict[str, Any],
) -> None:
    assert _property_names(tenant_invitation_schema) == TENANT_INVITATION_FIELDS


def test_tenant_invitation_requires_every_field(
    tenant_invitation_schema: dict[str, Any],
) -> None:
    assert set(tenant_invitation_schema["required"]) == TENANT_INVITATION_FIELDS


def test_tenant_invitation_url_is_nullable_string(
    tenant_invitation_schema: dict[str, Any],
) -> None:
    schema = tenant_invitation_schema["properties"]["url"]
    assert nullable_inner(schema)["type"] == "string"


@pytest.mark.parametrize("field", ["createdAt", "expiresAt"])
def test_tenant_invitation_timestamp_is_date_time_string(
    tenant_invitation_schema: dict[str, Any], field: str
) -> None:
    schema = tenant_invitation_schema["properties"][field]
    assert schema["type"] == "string"
    assert schema["format"] == "date-time"


def test_tenant_invitation_expired_is_boolean(
    tenant_invitation_schema: dict[str, Any],
) -> None:
    assert tenant_invitation_schema["properties"]["expired"]["type"] == "boolean"


# TenantSummary

TENANT_SUMMARY_FIELDS = {
    "id",
    "name",
    "room",
    "accountStatus",
    "billingCycle",
    "leaseEndDate",
    "invitationExpiresAt",
}


@pytest.fixture
def tenant_summary_schema(openapi: OpenApiDoc) -> dict[str, Any]:
    return openapi.component("TenantSummary")


def test_tenant_summary_has_exactly_its_fields(
    tenant_summary_schema: dict[str, Any],
) -> None:
    assert _property_names(tenant_summary_schema) == TENANT_SUMMARY_FIELDS


def test_tenant_summary_requires_every_field(
    tenant_summary_schema: dict[str, Any],
) -> None:
    assert set(tenant_summary_schema["required"]) == TENANT_SUMMARY_FIELDS


@pytest.mark.parametrize("field", ["phone", "email", "emergencyContacts", "invitation"])
def test_tenant_summary_leaves_out_detail_only_field(
    tenant_summary_schema: dict[str, Any], field: str
) -> None:
    assert field not in _property_names(tenant_summary_schema)


def test_tenant_summary_id_is_uuid_string(
    tenant_summary_schema: dict[str, Any],
) -> None:
    _assert_uuid_string(tenant_summary_schema["properties"]["id"])


def test_tenant_summary_name_is_string(tenant_summary_schema: dict[str, Any]) -> None:
    assert tenant_summary_schema["properties"]["name"]["type"] == "string"


def test_tenant_summary_room_is_room_ref(
    openapi: OpenApiDoc, tenant_summary_schema: dict[str, Any]
) -> None:
    assert openapi.ref_name(tenant_summary_schema["properties"]["room"]) == "RoomRef"


def test_tenant_summary_account_status_is_tenant_account_status_enum(
    openapi: OpenApiDoc, tenant_summary_schema: dict[str, Any]
) -> None:
    schema = tenant_summary_schema["properties"]["accountStatus"]
    assert openapi.ref_name(schema) == "TenantAccountStatus"


def test_tenant_summary_billing_cycle_is_billing_cycle_enum(
    openapi: OpenApiDoc, tenant_summary_schema: dict[str, Any]
) -> None:
    schema = tenant_summary_schema["properties"]["billingCycle"]
    assert openapi.ref_name(schema) == "BillingCycle"


def test_tenant_summary_lease_end_date_is_nullable_date_string(
    tenant_summary_schema: dict[str, Any],
) -> None:
    _assert_nullable_string_with_format(
        tenant_summary_schema["properties"]["leaseEndDate"], "date"
    )


def test_tenant_summary_invitation_expires_at_is_nullable_date_time_string(
    tenant_summary_schema: dict[str, Any],
) -> None:
    _assert_nullable_string_with_format(
        tenant_summary_schema["properties"]["invitationExpiresAt"], "date-time"
    )


# TenantList


def test_tenant_list_items_is_required_array_of_tenant_summary(
    openapi: OpenApiDoc,
) -> None:
    schema = openapi.component(
        openapi.response_schema_ref("get", "/properties/{propertyId}/tenants", 200)
    )
    assert _property_names(schema) == {"items"}
    assert set(schema["required"]) == {"items"}
    items = schema["properties"]["items"]
    assert items["type"] == "array"
    assert openapi.ref_name(items["items"]) == "TenantSummary"


# Runtime: valid requests reach the not-implemented stub


@pytest.fixture
def owner_headers(database, make_user, sign_in) -> dict[str, str]:
    return sign_in(make_user()).headers


@pytest.fixture
def owner_property_id(database, make_user, sign_in, make_property):
    """The id of a property of the signed-in owner, plus the owner's headers."""
    owner = make_user()
    return str(make_property(owner).id), sign_in(owner).headers


def _live(url: str, property_id: str) -> str:
    return url.replace(PROPERTY_ID, property_id)


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        pytest.param(
            "put", TENANT_URL, MINIMAL_TENANT_INPUT, id="update_tenant_minimal"
        ),
        pytest.param("put", TENANT_URL, FULL_TENANT_INPUT, id="update_tenant_full"),
        pytest.param("delete", TENANT_URL, None, id="delete_tenant"),
        pytest.param(
            "post",
            f"{TENANT_URL}/invitation",
            None,
            id="regenerate_tenant_invitation",
        ),
    ],
)
def test_valid_tenant_request_responds_not_implemented(
    client, method: str, url: str, body: dict[str, Any] | None
) -> None:
    response = client.request(method, url, json=body)
    assert response.status_code == 501


@pytest.mark.parametrize(("method", "url", "base"), TENANT_WRITE_REQUESTS)
@pytest.mark.parametrize(
    "extra",
    [
        pytest.param({"occupation": None}, id="occupation_null"),
        pytest.param({"occupation": "Karyawan"}, id="occupation_set"),
        pytest.param({"emergencyContacts": []}, id="no_emergency_contacts"),
        pytest.param(
            {
                "emergencyContacts": [
                    VALID_EMERGENCY_CONTACT,
                    SECOND_EMERGENCY_CONTACT,
                ]
            },
            id="two_emergency_contacts",
        ),
        pytest.param(
            {"emergencyContacts": [VALID_EMERGENCY_CONTACT] * 4},
            id="four_emergency_contacts",
        ),
        pytest.param({"lease": {}}, id="lease_empty_object"),
        pytest.param(
            {
                "lease": {
                    "startDate": None,
                    "endDate": None,
                    "rent": None,
                }
            },
            id="lease_nullable_fields_null",
        ),
        pytest.param({"lease": {"rent": 1}}, id="lease_rent_one"),
        pytest.param({"lease": {"gracePeriodDays": 0}}, id="lease_grace_period_zero"),
        *(
            pytest.param(
                {"lease": {**VALID_LEASE_INPUT, "billingCycle": cycle}},
                id=f"lease_billing_cycle_{cycle}",
            )
            for cycle in BILLING_CYCLES
        ),
        pytest.param(
            {
                "emergencyContacts": [
                    {"name": "S", "relationship": "I", "phone": "081234567890"}
                ]
                * 2
            },
            id="single_character_emergency_contact_name_and_relationship",
        ),
    ],
)
def test_tenant_input_edge_body_is_accepted(
    client,
    owner_property_id,
    method: str,
    url: str,
    base: dict[str, Any],
    extra: dict[str, Any],
) -> None:
    property_id, headers = owner_property_id
    response = client.request(
        method, _live(url, property_id), json={**base, **extra}, headers=headers
    )
    # Adding a tenant gets past validation to the unknown room; editing is a stub.
    assert response.status_code == {"post": 404, "put": 501}[method]


# Runtime: invalid requests are rejected with a validation error


@pytest.mark.parametrize(("method", "url", "base"), TENANT_WRITE_REQUESTS)
@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda b: _without(b, "name"), id="missing_name"),
        pytest.param(lambda b: {**b, "name": ""}, id="empty_name"),
        pytest.param(lambda b: _without(b, "phone"), id="missing_phone"),
        pytest.param(lambda b: {**b, "phone": ""}, id="empty_phone"),
        pytest.param(lambda b: _with_lease(b, rent=0), id="lease_rent_zero"),
        pytest.param(lambda b: _with_lease(b, rent=-1), id="lease_rent_negative"),
        pytest.param(lambda b: _with_lease(b, rent=1500.5), id="lease_rent_fraction"),
        pytest.param(
            lambda b: _with_lease(b, gracePeriodDays=-1),
            id="lease_grace_period_negative",
        ),
        pytest.param(
            lambda b: _with_lease(b, billingCycle="biweekly"),
            id="lease_billing_cycle_unknown",
        ),
        pytest.param(
            lambda b: _with_lease(b, startDate="2026-13-01"),
            id="lease_start_date_invalid",
        ),
        pytest.param(
            lambda b: _with_lease(b, endDate="not-a-date"),
            id="lease_end_date_invalid",
        ),
        pytest.param(
            lambda b: {**b, "emergencyContacts": [VALID_EMERGENCY_CONTACT] * 5},
            id="five_emergency_contacts",
        ),
        pytest.param(
            lambda b: {
                **b,
                "emergencyContacts": [
                    VALID_EMERGENCY_CONTACT,
                    _without(VALID_EMERGENCY_CONTACT, "relationship"),
                ],
            },
            id="emergency_contact_missing_relationship",
        ),
        pytest.param(
            lambda b: {
                **b,
                "emergencyContacts": [
                    VALID_EMERGENCY_CONTACT,
                    {**VALID_EMERGENCY_CONTACT, "name": ""},
                ],
            },
            id="emergency_contact_empty_name",
        ),
        pytest.param(
            lambda b: {**b, "emergencyContacts": VALID_EMERGENCY_CONTACT},
            id="emergency_contacts_not_array",
        ),
        pytest.param(lambda b: {}, id="empty_object"),
    ],
)
def test_invalid_tenant_input_is_rejected_with_validation_error(
    client, owner_property_id, method: str, url: str, base: dict[str, Any], change
) -> None:
    property_id, headers = owner_property_id
    response = client.request(
        method, _live(url, property_id), json=change(base), headers=headers
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            _without(MINIMAL_NEW_TENANT_INPUT, "roomId"), id="missing_room_id"
        ),
        pytest.param(
            {**MINIMAL_NEW_TENANT_INPUT, "roomId": NOT_A_UUID}, id="non_uuid_room_id"
        ),
        pytest.param({**MINIMAL_NEW_TENANT_INPUT, "roomId": None}, id="null_room_id"),
    ],
)
def test_invalid_room_id_on_create_tenant_is_rejected_with_validation_error(
    client, owner_property_id, body: dict[str, Any]
) -> None:
    property_id, headers = owner_property_id
    response = client.post(
        _live(CREATE_TENANT_URL, property_id), json=body, headers=headers
    )
    assert response.status_code == 422


@pytest.mark.parametrize(("method", "url", "base"), TENANT_WRITE_REQUESTS)
def test_tenant_write_without_body_is_rejected_with_validation_error(
    client, owner_property_id, method: str, url: str, base: dict[str, Any]
) -> None:
    property_id, headers = owner_property_id
    response = client.request(method, _live(url, property_id), headers=headers)
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        pytest.param(
            "post",
            f"/properties/{NOT_A_UUID}/tenants",
            MINIMAL_NEW_TENANT_INPUT,
            id="create_tenant",
        ),
        pytest.param(
            "get", f"/properties/{NOT_A_UUID}/tenants", None, id="list_tenants"
        ),
        pytest.param("get", f"/tenants/{NOT_A_UUID}", None, id="get_tenant"),
        pytest.param(
            "put", f"/tenants/{NOT_A_UUID}", MINIMAL_TENANT_INPUT, id="update_tenant"
        ),
        pytest.param("delete", f"/tenants/{NOT_A_UUID}", None, id="delete_tenant"),
        pytest.param(
            "post",
            f"/tenants/{NOT_A_UUID}/invitation",
            None,
            id="regenerate_tenant_invitation",
        ),
    ],
)
def test_non_uuid_tenant_path_id_is_rejected_with_validation_error(
    client, owner_headers, method: str, url: str, body: dict[str, Any] | None
) -> None:
    response = client.request(method, url, json=body, headers=owner_headers)
    assert response.status_code == 422
