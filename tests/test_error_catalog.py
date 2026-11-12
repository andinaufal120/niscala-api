"""The catalog of error codes and which operation can answer which code."""

import ast
import re
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parent.parent / "src" / "app"

ALLOWED_STATUSES = {401, 403, 404, 409, 422, 429, 500, 503}

# Written by hand from the table of error codes, not read from the code.
SPEC_CODES = {
    "ACCESS_TOKEN_INVALID": 401,
    "GOOGLE_TOKEN_INVALID": 401,
    "INVALID_CREDENTIALS": 401,
    "REFRESH_TOKEN_INVALID": 401,
    "UNAUTHORIZED": 401,
    "ACCOUNT_INACTIVE": 403,
    "EMAIL_NOT_VERIFIED": 403,
    "FORBIDDEN": 403,
    "NO_ACTIVE_LEASE": 403,
    "PASSWORD_LOGIN_REQUIRED": 403,
    "PROPERTY_LIMIT_REACHED": 403,
    "PROPERTY_READ_ONLY": 403,
    "REAUTHENTICATION_REQUIRED": 403,
    "ROOM_LIMIT_REACHED": 403,
    "ROOM_READ_ONLY": 403,
    "COMPLAINT_NOT_FOUND": 404,
    "EMAIL_CHANGE_NOT_FOUND": 404,
    "INVITATION_NOT_FOUND": 404,
    "MANAGER_NOT_FOUND": 404,
    "NOTIFICATION_NOT_FOUND": 404,
    "NOT_FOUND": 404,
    "PASSWORD_RESET_NOT_FOUND": 404,
    "PHOTO_NOT_FOUND": 404,
    "PROPERTY_NOT_FOUND": 404,
    "RECEIPT_NOT_FOUND": 404,
    "RENT_BILL_NOT_FOUND": 404,
    "ROOM_NOT_FOUND": 404,
    "SESSION_NOT_FOUND": 404,
    "SUBSCRIPTION_ORDER_NOT_FOUND": 404,
    "TENANT_NOT_FOUND": 404,
    "USER_ACCOUNT_NOT_FOUND": 404,
    "CANNOT_MODIFY_OWN_ACCOUNT": 409,
    "COMPLAINT_NOT_NEW": 409,
    "COMPLAINT_STATUS_NOT_NEXT": 409,
    "EMAIL_ALREADY_REGISTERED": 409,
    "EMAIL_ALREADY_VERIFIED": 409,
    "EMAIL_CHANGE_EXPIRED": 409,
    "EMAIL_CHANGE_USED": 409,
    "GOOGLE_ACCOUNT_ALREADY_REGISTERED": 409,
    "GOOGLE_ALREADY_LINKED": 409,
    "GOOGLE_NOT_LINKED": 409,
    "INVITATION_EXPIRED": 409,
    "INVITATION_ROLE_MISMATCH": 409,
    "INVITATION_USED": 409,
    "MANAGER_ALREADY_ACTIVE": 409,
    "MANAGER_ALREADY_ADDED": 409,
    "OWNER_HAS_ACTIVE_LEASE": 409,
    "PASSWORD_ALREADY_SET": 409,
    "PASSWORD_NOT_SET": 409,
    "PASSWORD_RESET_EXPIRED": 409,
    "PASSWORD_RESET_USED": 409,
    "PROPERTY_BANK_ACCOUNT_MISSING": 409,
    "PROPERTY_HAS_ACTIVE_LEASE": 409,
    "PROPERTY_NAME_TAKEN": 409,
    "PURCHASE_TOKEN_IN_USE": 409,
    "RENT_BILL_NOT_AWAITING_VERIFICATION": 409,
    "RENT_BILL_NOT_PAYABLE": 409,
    "RENT_BILL_NOT_UPLOADABLE": 409,
    "ROOM_HAS_ACTIVE_LEASE": 409,
    "ROOM_NOT_VACANT": 409,
    "RESOURCE_VERSION_CONFLICT": 409,
    "ROOM_NUMBER_TAKEN": 409,
    "SESSION_IS_CURRENT": 409,
    "SUBSCRIPTION_NOT_AN_UPGRADE": 409,
    "SUBSCRIPTION_ORDER_CLOSED": 409,
    "TENANT_ALREADY_ACTIVE": 409,
    "TENANT_HAS_ACTIVE_LEASE": 409,
    "USER_ACCOUNT_DELETED": 409,
    "COMPLAINT_CATEGORY_INVALID": 422,
    "CURRENT_PASSWORD_INCORRECT": 422,
    "GOOGLE_ACCOUNT_MISMATCH": 422,
    "GOOGLE_EMAIL_UNVERIFIED": 422,
    "KEPT_PROPERTIES_INVALID": 422,
    "KEPT_ROOMS_INVALID": 422,
    "MANAGER_NAME_NOT_EDITABLE": 422,
    "NOTIFICATION_CATEGORIES_INVALID": 422,
    "PASSWORD_INCORRECT": 422,
    "PASSWORD_TOO_COMMON": 422,
    "PASSWORD_UNCHANGED": 422,
    "PHOTO_TOO_LARGE": 422,
    "PHOTO_TYPE_INVALID": 422,
    "PURCHASE_PRODUCT_MISMATCH": 422,
    "PURCHASE_TOKEN_INVALID": 422,
    "REASON_REQUIRED": 422,
    "RECEIPT_TOO_LARGE": 422,
    "RECEIPT_TYPE_INVALID": 422,
    "RECEIVED_ON_IN_FUTURE": 422,
    "STATUS_UNCHANGED": 422,
    "SUBSCRIPTION_NOT_A_DOWNGRADE": 422,
    "TENANT_NAME_NOT_EDITABLE": 422,
    "VALIDATION_FAILED": 422,
    "VERIFICATION_CODE_EXPIRED": 422,
    "VERIFICATION_CODE_INVALID": 422,
    "TOO_MANY_ATTEMPTS": 429,
    "TOO_MANY_LOGIN_ATTEMPTS": 429,
    "VERIFICATION_CODE_TOO_SOON": 429,
    "INTERNAL_ERROR": 500,
    "JOBS_FAILED": 500,
    "GOOGLE_PLAY_UNREACHABLE": 503,
}

# Served only by paths that are not in the OpenAPI document.
NOT_PER_OPERATION = {"NOT_FOUND", "UNAUTHORIZED", "JOBS_FAILED"}


@pytest.fixture(scope="module")
def catalog():
    from app import error_catalog

    return error_catalog


def source_trees():
    for path in sorted(SOURCE.rglob("*.py")):
        yield path, ast.parse(path.read_text())


def api_error_literals() -> list[tuple[Path, int, str, int]]:
    """Every `ApiError(<int>, "<CODE>", ...)` with a literal status and code."""
    found = []
    for path, tree in source_trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name != "ApiError" or len(node.args) < 2:
                continue
            status, code = node.args[0], node.args[1]
            if (
                isinstance(status, ast.Constant)
                and isinstance(status.value, int)
                and isinstance(code, ast.Constant)
                and isinstance(code.value, str)
            ):
                found.append((path, status.value, code.value, node.lineno))
    return found


def test_the_status_table_holds_exactly_the_documented_codes(catalog):
    assert set(catalog.ERROR_STATUS) == set(SPEC_CODES)
    assert len(catalog.ERROR_STATUS) == 99


@pytest.mark.parametrize(("code", "status"), sorted(SPEC_CODES.items()))
def test_each_code_maps_to_its_documented_status(catalog, code, status):
    assert catalog.ERROR_STATUS[code] == status


def test_the_status_table_uses_only_known_statuses(catalog):
    assert set(catalog.ERROR_STATUS.values()) <= ALLOWED_STATUSES


def test_codes_are_upper_snake_case(catalog):
    for code in catalog.ERROR_STATUS:
        assert re.fullmatch(r"[A-Z][A-Z0-9]*(_[A-Z0-9]+)*", code), code


def test_validation_and_unexpected_failures_are_in_the_table(catalog):
    assert catalog.ERROR_STATUS["VALIDATION_FAILED"] == 422
    assert catalog.ERROR_STATUS["INTERNAL_ERROR"] == 500


@pytest.mark.parametrize(
    ("code", "status"),
    [("NOT_FOUND", 404), ("UNAUTHORIZED", 401), ("JOBS_FAILED", 500)],
)
def test_codes_that_no_declared_operation_raises_are_still_in_the_table(
    catalog, code, status
):
    assert catalog.ERROR_STATUS[code] == status


def test_routes_are_keyed_by_upper_case_method_and_path_template(catalog):
    assert catalog.ROUTE_ERRORS
    for method, path in catalog.ROUTE_ERRORS:
        assert method == method.upper()
        assert method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
        assert path.startswith("/")


def test_route_codes_are_tuples_of_known_codes_without_repeats(catalog):
    for key, codes in catalog.ROUTE_ERRORS.items():
        assert isinstance(codes, tuple), key
        assert len(set(codes)) == len(codes), key
        unknown = set(codes) - set(catalog.ERROR_STATUS)
        assert not unknown, (key, unknown)


def test_the_routes_are_exactly_the_operations_of_the_document(catalog, app):
    document = app.openapi()
    operations = {
        (method.upper(), path)
        for path, item in document["paths"].items()
        for method in item
    }
    assert len(operations) == 87
    assert set(catalog.ROUTE_ERRORS) == operations


def test_codes_without_a_public_path_are_not_attached_to_operations(catalog):
    used = {code for codes in catalog.ROUTE_ERRORS.values() for code in codes}
    assert not used & NOT_PER_OPERATION


def test_every_other_code_is_answered_by_some_operation(catalog):
    used = {code for codes in catalog.ROUTE_ERRORS.values() for code in codes}
    assert set(SPEC_CODES) - NOT_PER_OPERATION - used == set()


def test_literal_api_errors_use_a_documented_code_and_status(catalog):
    literals = api_error_literals()
    assert literals
    problems = []
    for path, status, code, line in literals:
        if code not in catalog.ERROR_STATUS:
            problems.append(f"{path.name}:{line} {code} is missing")
        elif catalog.ERROR_STATUS[code] != status:
            problems.append(
                f"{path.name}:{line} {code} is {status} in code but "
                f"{catalog.ERROR_STATUS[code]} in the catalog"
            )
    assert not problems, "\n".join(problems)


def test_the_lock_check_default_code_is_a_429_in_the_catalog(catalog):
    defaults = []
    for _path, tree in source_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "ensure_not_locked":
                defaults += [
                    d.value for d in node.args.defaults if isinstance(d, ast.Constant)
                ]
    assert defaults == ["TOO_MANY_LOGIN_ATTEMPTS"]
    assert catalog.ERROR_STATUS["TOO_MANY_LOGIN_ATTEMPTS"] == 429


def test_codes_passed_to_the_lock_check_are_429_in_the_catalog(catalog):
    passed = set()
    for _path, tree in source_trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name == "ensure_not_locked" and len(node.args) >= 3:
                arg = node.args[2]
                assert isinstance(arg, ast.Constant)
                passed.add(arg.value)
    assert "TOO_MANY_ATTEMPTS" in passed
    for code in passed:
        assert catalog.ERROR_STATUS[code] == 429
