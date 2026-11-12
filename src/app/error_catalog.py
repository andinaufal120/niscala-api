"""The catalog of error codes and which operation can answer which code.

`ERROR_STATUS` maps every error code to its HTTP status. Every code raised with
`ApiError` must be in it, with the same status.

`ROUTE_ERRORS` maps each operation, keyed by (METHOD, OpenAPI path), to the
codes it can answer. The OpenAPI document is built from it.
"""

# Prefixes shared by most operations.
SESSION = ("ACCESS_TOKEN_INVALID", "EMAIL_NOT_VERIFIED")
STAFF = SESSION + ("FORBIDDEN",)
INVALID = ("VALIDATION_FAILED",)
INVITATION_ACTIVATION = ("INVITATION_NOT_FOUND", "EMAIL_ALREADY_REGISTERED")
PASSWORD_RESET = (
    "PASSWORD_RESET_NOT_FOUND",
    "PASSWORD_RESET_EXPIRED",
    "PASSWORD_RESET_USED",
)
READ_ONLY = ("PROPERTY_READ_ONLY", "ROOM_READ_ONLY")
GOOGLE_SIGN_IN = ("GOOGLE_TOKEN_INVALID",)
PROPERTY_SCOPED = STAFF + ("PROPERTY_NOT_FOUND",)
RENT_BILL_SCOPED = STAFF + ("RENT_BILL_NOT_FOUND",)
RENT_BILL_AWAITING = RENT_BILL_SCOPED + ("RENT_BILL_NOT_AWAITING_VERIFICATION",)
COMPLAINT_SCOPED = STAFF + ("COMPLAINT_NOT_FOUND",)
MANAGER_SCOPED = STAFF + ("MANAGER_NOT_FOUND",)
USER_ACCOUNT_SCOPED = STAFF + ("USER_ACCOUNT_NOT_FOUND",)
SUBSCRIPTION_ORDER_SCOPED = STAFF + ("SUBSCRIPTION_ORDER_NOT_FOUND",)
TENANT_SCOPED = PROPERTY_SCOPED + ("TENANT_NOT_FOUND",)

ERROR_STATUS: dict[str, int] = {
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

ROUTE_ERRORS: dict[tuple[str, str], tuple[str, ...]] = {
    ("POST", "/auth/email-changes"): (
        "EMAIL_CHANGE_NOT_FOUND",
        "EMAIL_ALREADY_REGISTERED",
        "EMAIL_CHANGE_EXPIRED",
        "EMAIL_CHANGE_USED",
        *INVALID,
    ),
    ("POST", "/auth/email-verification"): (
        "ACCESS_TOKEN_INVALID",
        "EMAIL_ALREADY_VERIFIED",
        "VERIFICATION_CODE_TOO_SOON",
    ),
    ("POST", "/auth/email-verification/confirmation"): (
        "ACCESS_TOKEN_INVALID",
        "EMAIL_ALREADY_VERIFIED",
        *INVALID,
        "VERIFICATION_CODE_EXPIRED",
        "VERIFICATION_CODE_INVALID",
    ),
    ("POST", "/auth/login"): (
        "INVALID_CREDENTIALS",
        "ACCOUNT_INACTIVE",
        *INVALID,
        "TOO_MANY_LOGIN_ATTEMPTS",
    ),
    ("POST", "/auth/login/google"): (
        *GOOGLE_SIGN_IN,
        "INVALID_CREDENTIALS",
        "ACCOUNT_INACTIVE",
        *INVALID,
    ),
    ("POST", "/auth/logout"): ("ACCESS_TOKEN_INVALID",),
    ("POST", "/auth/password-reset-previews"): (*PASSWORD_RESET, *INVALID),
    ("POST", "/auth/password-reset-requests"): INVALID,
    ("POST", "/auth/password-resets"): (
        *PASSWORD_RESET,
        "PASSWORD_TOO_COMMON",
        *INVALID,
    ),
    ("POST", "/auth/refresh"): ("REFRESH_TOKEN_INVALID", *INVALID),
    ("POST", "/auth/register"): (
        "EMAIL_ALREADY_REGISTERED",
        "PASSWORD_TOO_COMMON",
        *INVALID,
        "VERIFICATION_CODE_TOO_SOON",
    ),
    ("POST", "/auth/register/google"): (
        *GOOGLE_SIGN_IN,
        "EMAIL_ALREADY_REGISTERED",
        "GOOGLE_ACCOUNT_ALREADY_REGISTERED",
        "GOOGLE_EMAIL_UNVERIFIED",
        *INVALID,
    ),
    ("GET", "/complaint-categories"): SESSION,
    ("GET", "/complaints"): STAFF,
    ("POST", "/complaints"): STAFF
    + ("NO_ACTIVE_LEASE", "COMPLAINT_NOT_FOUND", "ROOM_NOT_FOUND", *INVALID),
    ("GET", "/complaints/{complaintId}"): COMPLAINT_SCOPED + INVALID,
    ("PUT", "/complaints/{complaintId}/classification"): COMPLAINT_SCOPED
    + ("COMPLAINT_CATEGORY_INVALID", *INVALID),
    ("GET", "/complaints/{complaintId}/photo"): COMPLAINT_SCOPED
    + ("PHOTO_NOT_FOUND", *INVALID, "INTERNAL_ERROR"),
    ("PUT", "/complaints/{complaintId}/photo"): COMPLAINT_SCOPED
    + ("COMPLAINT_NOT_NEW", "PHOTO_TOO_LARGE", "PHOTO_TYPE_INVALID", *INVALID),
    ("POST", "/complaints/{complaintId}/status-changes"): COMPLAINT_SCOPED
    + ("COMPLAINT_STATUS_NOT_NEXT", *INVALID),
    ("GET", "/health"): (),
    ("POST", "/invitations/acceptance-previews"): SESSION
    + ("INVITATION_NOT_FOUND", *INVALID),
    ("POST", "/invitations/acceptances"): SESSION
    + (
        "INVITATION_NOT_FOUND",
        "INVITATION_EXPIRED",
        "INVITATION_ROLE_MISMATCH",
        "INVITATION_USED",
        "MANAGER_ALREADY_ADDED",
        *INVALID,
    ),
    ("POST", "/invitations/activations/google"): (
        *GOOGLE_SIGN_IN,
        *INVITATION_ACTIVATION,
        "GOOGLE_ACCOUNT_ALREADY_REGISTERED",
        "INVITATION_EXPIRED",
        "INVITATION_USED",
        "GOOGLE_EMAIL_UNVERIFIED",
        *INVALID,
    ),
    ("POST", "/invitations/activations/password"): (
        *INVITATION_ACTIVATION,
        "INVITATION_EXPIRED",
        "INVITATION_USED",
        "PASSWORD_TOO_COMMON",
        *INVALID,
        "VERIFICATION_CODE_TOO_SOON",
    ),
    ("POST", "/invitations/previews"): ("INVITATION_NOT_FOUND", *INVALID),
    ("GET", "/managers"): PROPERTY_SCOPED + INVALID,
    ("POST", "/managers"): PROPERTY_SCOPED + INVALID,
    ("DELETE", "/managers/{managerId}"): MANAGER_SCOPED + INVALID,
    ("GET", "/managers/{managerId}"): MANAGER_SCOPED + INVALID,
    ("PUT", "/managers/{managerId}"): MANAGER_SCOPED
    + ("PROPERTY_NOT_FOUND", "MANAGER_NAME_NOT_EDITABLE", *INVALID),
    ("POST", "/managers/{managerId}/invitation"): MANAGER_SCOPED
    + ("MANAGER_ALREADY_ACTIVE", *INVALID),
    ("GET", "/me"): ("ACCESS_TOKEN_INVALID",),
    ("POST", "/me/google-link"): (
        "ACCESS_TOKEN_INVALID",
        *GOOGLE_SIGN_IN,
        "EMAIL_NOT_VERIFIED",
        "PASSWORD_LOGIN_REQUIRED",
        "GOOGLE_ACCOUNT_ALREADY_REGISTERED",
        "GOOGLE_ALREADY_LINKED",
        "GOOGLE_EMAIL_UNVERIFIED",
        *INVALID,
    ),
    ("GET", "/me/leases"): STAFF,
    ("POST", "/me/local-password"): (
        "ACCESS_TOKEN_INVALID",
        *GOOGLE_SIGN_IN,
        "EMAIL_NOT_VERIFIED",
        "GOOGLE_NOT_LINKED",
        "PASSWORD_ALREADY_SET",
        "GOOGLE_ACCOUNT_MISMATCH",
        "PASSWORD_TOO_COMMON",
        *INVALID,
    ),
    ("GET", "/me/notification-settings"): STAFF,
    ("PUT", "/me/notification-settings"): STAFF
    + ("NOTIFICATION_CATEGORIES_INVALID", *INVALID),
    ("POST", "/me/password-changes"): SESSION
    + (
        "PASSWORD_NOT_SET",
        "CURRENT_PASSWORD_INCORRECT",
        "PASSWORD_TOO_COMMON",
        "PASSWORD_UNCHANGED",
        *INVALID,
        "TOO_MANY_ATTEMPTS",
    ),
    ("PUT", "/me/push-token"): STAFF + INVALID,
    ("POST", "/me/reauthentication/google"): (
        "ACCESS_TOKEN_INVALID",
        *GOOGLE_SIGN_IN,
        "EMAIL_NOT_VERIFIED",
        "GOOGLE_NOT_LINKED",
        "GOOGLE_ACCOUNT_MISMATCH",
        *INVALID,
        "TOO_MANY_LOGIN_ATTEMPTS",
    ),
    ("POST", "/me/reauthentication/password"): SESSION
    + ("PASSWORD_NOT_SET", "PASSWORD_INCORRECT", *INVALID, "TOO_MANY_LOGIN_ATTEMPTS"),
    ("DELETE", "/me/sessions"): SESSION,
    ("GET", "/me/sessions"): SESSION,
    ("DELETE", "/me/sessions/{sessionId}"): SESSION
    + ("SESSION_NOT_FOUND", "SESSION_IS_CURRENT", *INVALID),
    ("GET", "/notifications"): STAFF,
    ("POST", "/notifications/read-all"): STAFF,
    ("POST", "/notifications/{notificationId}/read"): STAFF
    + ("NOTIFICATION_NOT_FOUND", *INVALID),
    ("GET", "/occupancy-dashboard"): STAFF,
    ("GET", "/properties"): STAFF,
    ("POST", "/properties"): STAFF
    + ("PROPERTY_LIMIT_REACHED", "PROPERTY_NAME_TAKEN", *INVALID),
    ("DELETE", "/properties/{propertyId}"): PROPERTY_SCOPED
    + ("PROPERTY_HAS_ACTIVE_LEASE", *INVALID),
    ("GET", "/properties/{propertyId}"): PROPERTY_SCOPED + INVALID,
    ("PUT", "/properties/{propertyId}"): STAFF
    + (
        "PROPERTY_READ_ONLY",
        "REAUTHENTICATION_REQUIRED",
        "PROPERTY_NOT_FOUND",
        "PROPERTY_NAME_TAKEN",
        *INVALID,
    ),
    ("GET", "/properties/{propertyId}/facility-suggestions"): PROPERTY_SCOPED + INVALID,
    ("GET", "/properties/{propertyId}/payment-overview"): PROPERTY_SCOPED + INVALID,
    ("GET", "/properties/{propertyId}/payment-patterns"): PROPERTY_SCOPED + INVALID,
    ("GET", "/properties/{propertyId}/rooms"): PROPERTY_SCOPED + INVALID,
    ("POST", "/properties/{propertyId}/rooms"): STAFF
    + (
        "PROPERTY_READ_ONLY",
        "ROOM_LIMIT_REACHED",
        "PROPERTY_NOT_FOUND",
        "ROOM_NUMBER_TAKEN",
        *INVALID,
    ),
    ("GET", "/properties/{propertyId}/tenants"): PROPERTY_SCOPED + INVALID,
    ("POST", "/properties/{propertyId}/tenants"): STAFF
    + (*READ_ONLY, "PROPERTY_NOT_FOUND", "ROOM_NOT_FOUND", "ROOM_NOT_VACANT", *INVALID),
    ("GET", "/rent-bills"): STAFF + INVALID,
    ("GET", "/rent-bills/{rentBillId}"): RENT_BILL_SCOPED + INVALID,
    ("POST", "/rent-bills/{rentBillId}/cash-payment"): RENT_BILL_SCOPED
    + ("RENT_BILL_NOT_PAYABLE", "RECEIVED_ON_IN_FUTURE", *INVALID),
    ("GET", "/rent-bills/{rentBillId}/receipt"): STAFF
    + ("RECEIPT_NOT_FOUND", "RENT_BILL_NOT_FOUND", *INVALID, "INTERNAL_ERROR"),
    ("PUT", "/rent-bills/{rentBillId}/receipt"): RENT_BILL_SCOPED
    + (
        "PROPERTY_BANK_ACCOUNT_MISSING",
        "RENT_BILL_NOT_UPLOADABLE",
        "RECEIPT_TOO_LARGE",
        "RECEIPT_TYPE_INVALID",
        *INVALID,
    ),
    ("POST", "/rent-bills/{rentBillId}/rejection"): RENT_BILL_AWAITING
    + ("REASON_REQUIRED", *INVALID),
    ("POST", "/rent-bills/{rentBillId}/status-changes"): RENT_BILL_SCOPED
    + ("REASON_REQUIRED", "RECEIVED_ON_IN_FUTURE", "STATUS_UNCHANGED", *INVALID),
    ("POST", "/rent-bills/{rentBillId}/verification"): RENT_BILL_AWAITING + INVALID,
    ("DELETE", "/rooms/{roomId}"): STAFF
    + ("ROOM_NOT_FOUND", "ROOM_HAS_ACTIVE_LEASE", *INVALID),
    ("GET", "/rooms/{roomId}"): STAFF + ("ROOM_NOT_FOUND", *INVALID),
    ("PUT", "/rooms/{roomId}"): STAFF
    + (*READ_ONLY, "ROOM_NOT_FOUND", "ROOM_NUMBER_TAKEN", *INVALID),
    ("GET", "/subscription"): STAFF,
    ("GET", "/subscription-plans"): STAFF,
    ("POST", "/subscription/orders"): STAFF + ("SUBSCRIPTION_NOT_AN_UPGRADE", *INVALID),
    ("GET", "/subscription/orders/{orderId}"): SUBSCRIPTION_ORDER_SCOPED + INVALID,
    ("POST", "/subscription/orders/{orderId}/purchase-verification"): (
        SUBSCRIPTION_ORDER_SCOPED
        + (
            "PURCHASE_TOKEN_IN_USE",
            "SUBSCRIPTION_ORDER_CLOSED",
            "PURCHASE_PRODUCT_MISMATCH",
            "PURCHASE_TOKEN_INVALID",
            *INVALID,
            "GOOGLE_PLAY_UNREACHABLE",
        )
    ),
    ("DELETE", "/subscription/scheduled-downgrade"): STAFF,
    ("PUT", "/subscription/scheduled-downgrade"): STAFF
    + (
        "KEPT_PROPERTIES_INVALID",
        "KEPT_ROOMS_INVALID",
        "SUBSCRIPTION_NOT_A_DOWNGRADE",
        *INVALID,
    ),
    ("DELETE", "/tenants/{tenantId}"): STAFF
    + (*READ_ONLY, "PROPERTY_NOT_FOUND", "TENANT_NOT_FOUND", *INVALID),
    ("GET", "/tenants/{tenantId}"): TENANT_SCOPED + INVALID,
    ("PUT", "/tenants/{tenantId}"): STAFF
    + (
        *READ_ONLY,
        "PROPERTY_NOT_FOUND",
        "TENANT_NOT_FOUND",
        "TENANT_NAME_NOT_EDITABLE",
        *INVALID,
    ),
    ("POST", "/tenants/{tenantId}/invitation"): TENANT_SCOPED
    + ("TENANT_ALREADY_ACTIVE", *INVALID),
    ("GET", "/user-accounts"): STAFF + INVALID,
    ("DELETE", "/user-accounts/{userAccountId}"): USER_ACCOUNT_SCOPED
    + (
        "CANNOT_MODIFY_OWN_ACCOUNT",
        "OWNER_HAS_ACTIVE_LEASE",
        "TENANT_HAS_ACTIVE_LEASE",
        "USER_ACCOUNT_DELETED",
        *INVALID,
    ),
    ("GET", "/user-accounts/{userAccountId}"): USER_ACCOUNT_SCOPED + INVALID,
    ("PUT", "/user-accounts/{userAccountId}"): USER_ACCOUNT_SCOPED
    + (
        "CANNOT_MODIFY_OWN_ACCOUNT",
        "EMAIL_ALREADY_REGISTERED",
        "USER_ACCOUNT_DELETED",
        *INVALID,
    ),
}
