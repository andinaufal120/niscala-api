"""The people of an end-to-end scenario, each driving the API with their own session.

A `Person` wraps the test client with the bearer tokens of one signed-in
session. Every request goes through the public HTTP API. The verbs return the
raw response; pass `expect=<status>` to fail the step at once, with the request
and the answer in the message, when the API answers differently.
"""

import struct
import zlib
from datetime import date
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import jwt

PASSWORD = "correct horse battery"
DEVICE = {"name": "Pixel 8", "platform": "Android 14"}
BANK_ACCOUNT = {
    "bankName": "Bank Mandiri",
    "accountNumber": "1234567890",
    "accountHolderName": "Rina Owner",
}
EMERGENCY_CONTACTS = [
    {"name": "Ibu Wati", "relationship": "Mother", "phone": "081300000001"},
    {"name": "Pak Joko", "relationship": "Father", "phone": "081300000002"},
]
COMPLAINT_TEXT = "The tap in the bathroom leaks badly."


def describe(response) -> str:
    """Name the request that produced a response, with the answer."""
    request = response.request
    return (
        f"{request.method} {request.url.path} answered "
        f"{response.status_code}: {response.text}"
    )


def check_status(response, status: int, step: str):
    """Return the response when it has the expected status, else fail the step.

    The failure is an `AssertionError` naming the step, the expected status, the
    request and the answer, so a scenario stops at the step that broke.
    """
    if response.status_code != status:
        raise AssertionError(
            f"{step} failed: expected {status}, but {describe(response)}"
        )
    return response


def jsonable(value: Any) -> Any:
    """Turn dates inside nested dicts and lists into ISO strings."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(item) for item in value]
    return value


def ident(thing: Any) -> str:
    """The id of a record returned by a step, or an id given directly."""
    if isinstance(thing, dict):
        return thing["id"]
    return str(thing)


class InviteToken(str):
    """The raw token of an invitation link.

    `record` is the tenant or manager the invitation was created with, as the
    API returned it, and `id` is its id.
    """

    record: dict

    def __new__(cls, token: str, record: dict):
        instance = super().__new__(cls, token)
        instance.record = record
        return instance

    @property
    def id(self) -> str:
        return self.record["id"]


def token_of(record: dict) -> InviteToken:
    """Read the invitation token out of the link of a tenant or manager record."""
    url = (record.get("invitation") or {}).get("url")
    if not url:
        raise AssertionError(f"the record has no usable invitation link: {record}")
    return InviteToken(url.rsplit("/", 1)[-1], record)


def _png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixel = zlib.compress(b"\x00\xff\xff\xff")
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", pixel)
        + chunk(b"IEND", b"")
    )


PNG_BYTES = _png()
# Start-of-image, a JFIF header and end-of-image: the signature the API reads.
JPG_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
)


def png_receipt() -> dict:
    """Upload arguments (`files=`) carrying a valid 1x1 PNG image."""
    return {"file": ("receipt.png", PNG_BYTES, "image/png")}


def jpg_receipt() -> dict:
    """Upload arguments (`files=`) carrying a tiny JPEG with a valid signature."""
    return {"file": ("receipt.jpg", JPG_BYTES, "image/jpeg")}


def file_receipt(kind: str = "png") -> dict:
    """Upload arguments (`files=`) for a receipt or photo of the given kind."""
    makers = {"png": png_receipt, "jpg": jpg_receipt, "jpeg": jpg_receipt}
    if kind not in makers:
        raise ValueError(f"unknown file kind {kind!r}; use png or jpg")
    return makers[kind]()


class Person:
    """One signed-in session of one account, driving the API as that person.

    `user_id` and `session_id` are UUIDs; `email` and `name` are as the account
    holds them. `cast` is the `Cast` that created the person.
    """

    role: str

    def __init__(self, cast, session: dict, password: str | None) -> None:
        account = session["account"]
        self.cast = cast
        self.name: str = account["name"]
        self.email: str = account["email"]
        self.user_id = UUID(account["id"])
        self.password = password
        self._adopt(session["accessToken"], session["refreshToken"])

    def _adopt(self, access_token: str, refresh_token: str) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        claims = jwt.decode(access_token, options={"verify_signature": False})
        self.session_id = UUID(claims["sid"])

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.email}>"

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    @property
    def namespace(self) -> SimpleNamespace:
        """An object with this person's `id`, as the Play stub expects of an owner."""
        return SimpleNamespace(id=self.user_id)

    def request(self, method: str, path: str, *, expect: int | None = None, **kwargs):
        """Send a request with this session's bearer token.

        Extra keyword arguments go to the test client (`json`, `params`,
        `files`, `headers`, ...). With `expect`, the step fails unless the
        answer has that status.
        """
        headers = {**self.headers, **kwargs.pop("headers", {})}
        response = self.cast.client.request(method, path, headers=headers, **kwargs)
        if expect is not None:
            check_status(response, expect, f"{self.email} {method} {path}")
        return response

    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs):
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs):
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs):
        return self.request("DELETE", path, **kwargs)

    def patch(self, path: str, **kwargs):
        return self.request("PATCH", path, **kwargs)

    def read(self, path: str, *, status: int = 200, **kwargs) -> Any:
        """GET a path, require the status and return the JSON body."""
        return self.get(path, expect=status, **kwargs).json()

    def refresh(self) -> None:
        """Exchange the refresh token for a new token pair and keep using it."""
        response = self.cast.client.post(
            "/auth/refresh", json={"refreshToken": self.refresh_token}
        )
        check_status(response, 200, f"{self.email} refresh")
        body = response.json()
        self._adopt(body["accessToken"], body["refreshToken"])

    def logout(self) -> None:
        """End this session."""
        self.post("/auth/logout", expect=204)

    def confirm_email(self) -> None:
        """Confirm the account email with the code the mailbox received."""
        code = self.cast.stubs.verification_code(self.email)
        self.post(
            "/auth/email-verification/confirmation", json={"code": code}, expect=200
        )

    def enable_push(self, token: str) -> None:
        """Register a device push token for this session."""
        self.put("/me/push-token", json={"token": token}, expect=204)

    def notifications(self) -> list[dict]:
        return self.read("/notifications")["items"]

    def complaints(self) -> list[dict]:
        return self.read("/complaints")["items"]

    def complaint(self, complaint: Any) -> dict:
        return self.read(f"/complaints/{ident(complaint)}")

    def rent_bills(self, **params: Any) -> list[dict]:
        return self.read("/rent-bills", params=params or None)["items"]

    def rent_bill(self, bill: Any) -> dict:
        return self.read(f"/rent-bills/{ident(bill)}")


class Staff(Person):
    """A person who runs properties: an Owner or a Manager."""

    def properties(self) -> list[dict]:
        return self.read("/properties")["items"]

    def rooms(self, prop: Any) -> list[dict]:
        return self.read(f"/properties/{ident(prop)}/rooms")["items"]

    def tenants(self, prop: Any) -> list[dict]:
        return self.read(f"/properties/{ident(prop)}/tenants")["items"]

    def add_room(
        self,
        prop: Any,
        number: str,
        *,
        base_rate: int = 1_000_000,
        facilities: list[str] | None = None,
        length_m: float | None = None,
        width_m: float | None = None,
    ) -> dict:
        """Add a room to a property and return it."""
        body: dict[str, Any] = {
            "number": number,
            "baseRate": base_rate,
            "facilities": facilities or [],
        }
        if length_m is not None:
            body["lengthM"] = length_m
        if width_m is not None:
            body["widthM"] = width_m
        response = self.post(f"/properties/{ident(prop)}/rooms", json=body)
        return check_status(response, 201, f"add_room({number!r})").json()

    def add_tenant(
        self,
        room: dict,
        name: str,
        phone: str,
        *,
        lease: dict | None = None,
        emergency_contacts: list[dict] | None = None,
        occupation: str | None = None,
    ) -> InviteToken:
        """Add a tenant to a vacant room and return the invitation token.

        `room` is a room as returned by `add_room`. `lease` uses the API field
        names (`startDate`, `endDate`, `billingCycle`, `rent`,
        `gracePeriodDays`); dates may be `date` objects. Without emergency
        contacts the tenant gives them when activating. The token's `record`
        is the tenant as the API returned it.
        """
        body: dict[str, Any] = {
            "roomId": room["id"],
            "name": name,
            "phone": phone,
            "lease": jsonable(lease or {}),
            "emergencyContacts": emergency_contacts or [],
        }
        if occupation is not None:
            body["occupation"] = occupation
        response = self.post(f"/properties/{room['propertyId']}/tenants", json=body)
        check_status(response, 201, f"add_tenant({name!r})")
        return token_of(response.json())


class Owner(Staff):
    """A signed-in Owner."""

    role = "owner"

    def add_property(
        self,
        name: str,
        *,
        address: str = "Jl. Melati 5",
        bank_account: dict | None = None,
    ) -> dict:
        """Add a property, with a bank account when given, and return it."""
        body: dict[str, Any] = {"name": name, "address": address}
        if bank_account is not None:
            body["bankAccount"] = bank_account
        response = self.post("/properties", json=body)
        return check_status(response, 201, f"add_property({name!r})").json()

    def add_manager(
        self,
        property_ids: list[Any],
        *,
        name: str = "Mira Manager",
        phone: str = "081200000001",
        nickname: str | None = None,
    ) -> InviteToken:
        """Add a manager for the given properties and return the invitation token.

        Properties may be records returned by `add_property` or ids.
        """
        body: dict[str, Any] = {
            "name": name,
            "phone": phone,
            "propertyIds": [ident(prop) for prop in property_ids],
        }
        if nickname is not None:
            body["nickname"] = nickname
        response = self.post("/managers", json=body)
        check_status(response, 201, f"add_manager({name!r})")
        return token_of(response.json())

    def managers(self) -> list[dict]:
        return self.read("/managers")["items"]

    def subscription(self) -> dict:
        return self.read("/subscription")

    def subscribe(self, plan: str = "basic", period: str = "monthly") -> dict:
        """Buy a plan through the subscription endpoints and return the subscription.

        Starts an order, lets the Play stub know a matching purchase, and
        verifies the purchase token. Fails the step when the order does not
        succeed.
        """
        response = self.post(
            "/subscription/orders", json={"planCode": plan, "billingPeriod": period}
        )
        order = check_status(response, 201, f"subscribe({plan!r}) order").json()
        token = self.cast.stubs.play_purchase(self, order)
        response = self.post(
            f"/subscription/orders/{order['id']}/purchase-verification",
            json={"purchaseToken": token},
        )
        verified = check_status(response, 200, f"subscribe({plan!r}) purchase").json()
        if verified["status"] != "succeeded":
            raise AssertionError(
                f"subscribe({plan!r}) failed: the order ended as "
                f"{verified['status']!r}, not 'succeeded'"
            )
        return self.subscription()


class Manager(Staff):
    """A signed-in Manager."""

    role = "manager"


class Tenant(Person):
    """A signed-in Tenant."""

    role = "tenant"

    def leases(self) -> list[dict]:
        return self.read("/me/leases")["items"]

    def submit_complaint(self, room: Any, description: str = COMPLAINT_TEXT) -> dict:
        """Submit a complaint about a room of the tenant and return it."""
        response = self.post(
            "/complaints", json={"description": description, "roomId": ident(room)}
        )
        return check_status(response, 201, "submit_complaint").json()

    def upload_receipt(self, bill: Any, receipt: dict | None = None) -> dict:
        """Send a transfer receipt (a PNG unless given) for a bill and return the bill."""
        response = self.put(
            f"/rent-bills/{ident(bill)}/receipt", files=receipt or png_receipt()
        )
        return check_status(response, 200, "upload_receipt").json()


class Admin(Person):
    """A signed-in Admin."""

    role = "admin"


ROLES = {cls.role: cls for cls in (Owner, Manager, Tenant, Admin)}
