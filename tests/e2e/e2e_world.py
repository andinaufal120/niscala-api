"""The stage of an end-to-end scenario: stubbed externals, a clock, a cast and a seed.

Everything a scenario does goes through the public HTTP API. Verification codes
come from the mailbox stub, and time moves by replacing the clock the date
rules read. Only the Admin account is inserted directly, since no endpoint
creates one.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from e2e.e2e_people import (
    BANK_ACCOUNT,
    COMPLAINT_TEXT,
    DEVICE,
    EMERGENCY_CONTACTS,
    PASSWORD,
    ROLES,
    Admin,
    InviteToken,
    Manager,
    Owner,
    Person,
    Tenant,
    check_status,
)

JOBS_PATH = "/internal/jobs/daily"
PAID_DAYS = {"monthly": 30, "yearly": 365}


class Stubs:
    """The stubbed externals of one test, with switches and assertion helpers.

    `classifier`, `summarizer`, `play`, `google`, `mailbox`, `fcm` and `files`
    are the fixtures of the shared test setup, kept under one roof.
    """

    def __init__(
        self,
        *,
        classifier,
        summarizer,
        play,
        google,
        mailbox,
        fcm,
        files,
        monkeypatch,
    ) -> None:
        self.classifier = classifier
        self.summarizer = summarizer
        self.play = play
        self.google = google
        self.mailbox = mailbox
        self.fcm = fcm
        self.files = files
        self._monkeypatch = monkeypatch
        self._purchases = 0

    # Gemini

    def classifier_unavailable(self) -> None:
        """Make every complaint classification fail."""
        from app.ai.classifier import ClassificationUnavailable

        self.classifier.error = ClassificationUnavailable("Gemini is down")

    def classifier_times_out(self) -> None:
        """Make the classifier answer later than the classification timeout."""
        self._monkeypatch.setattr(
            "app.services.complaints.CLASSIFICATION_TIMEOUT_SECONDS", 0.2
        )
        self.classifier.delay = 1.0

    def classifier_works(
        self,
        category: str = "Listrik",
        urgency: str = "high",
        suggested_action: str = "Send an electrician today.",
    ) -> None:
        """Make the classifier answer quickly with the given classification."""
        from app.schemas.complaints import AiComplaintClassification, ComplaintUrgency

        self._monkeypatch.setattr(
            "app.services.complaints.CLASSIFICATION_TIMEOUT_SECONDS", 10.0
        )
        self.classifier.error = None
        self.classifier.delay = 0.0
        self.classifier.result = AiComplaintClassification(
            category=category,
            urgency=ComplaintUrgency(urgency),
            suggested_action=suggested_action,
        )

    def summarizer_unavailable(self) -> None:
        """Make every payment pattern summary fail."""
        from app.ai.summarizer import SummaryUnavailable

        self.summarizer.error = SummaryUnavailable("Gemini is down")

    def assert_classifier_called(self, times: int) -> None:
        calls = len(self.classifier.calls)
        assert calls == times, f"expected {times} classifier calls, saw {calls}"

    # Google Play

    def play_purchase(self, owner: Person, order: dict, **fields: Any) -> str:
        """Register a purchase for an order and return its purchase token.

        By default the purchase is active, acknowledged by nobody yet, tied to
        the owner and matches the order's product, for the order's period.
        `fields` override the purchase (for example `state="PENDING"`).
        """
        self._purchases += 1
        token = fields.pop("token", f"play-token-{self._purchases}")
        days = PAID_DAYS.get(order["billingPeriod"], 30)
        values: dict[str, Any] = {
            "product_id": order["googlePlayProductId"],
            "base_plan_id": order["googlePlayBasePlanId"],
            "obfuscated_account_id": order["obfuscatedAccountId"],
            "expiry_time": datetime.now(UTC) + timedelta(days=days),
        }
        self.play.add(token, **{**values, **fields})
        return token

    def play_unreachable(self) -> None:
        """Make every Google Play call fail as if the service were down."""
        self.play.unreachable = True

    def play_reachable(self) -> None:
        self.play.unreachable = False

    def play_acknowledge_fails(self) -> None:
        """Make only the acknowledgement of purchases fail."""
        self.play.acknowledge_fails = True

    def assert_play_acknowledged(self, token: str | None = None) -> None:
        done = [acknowledged for _, acknowledged in self.play.acknowledged]
        if token is None:
            assert done, "no Play purchase was acknowledged"
        else:
            assert token in done, f"Play purchase {token} was not acknowledged: {done}"

    # Email

    def verification_code(self, email: str) -> str:
        """The latest verification code emailed to an address."""
        codes = [code for to, code in self.mailbox.codes if to.lower() == email.lower()]
        if not codes:
            raise AssertionError(f"no verification code was emailed to {email}")
        return codes[-1]

    def assert_code_emailed(self, email: str, times: int = 1) -> None:
        sent = [to for to, _ in self.mailbox.codes if to.lower() == email.lower()]
        assert len(sent) == times, f"expected {times} codes to {email}, saw {len(sent)}"

    def assert_mailbox_empty(self) -> None:
        assert self.mailbox.is_empty, f"unexpected email: {self.mailbox.codes}"

    # Firebase Cloud Messaging

    def pushes_to(self, token: str) -> list[str]:
        """The notification types pushed to a device token, oldest first."""
        return [
            message.data["type"]
            for message, _ in self.fcm.sent
            if message.token == token
        ]

    def assert_pushed(self, token: str, type_: str | None = None) -> None:
        types = self.pushes_to(token)
        assert types, f"nothing was pushed to {token}"
        if type_ is not None:
            assert type_ in types, f"{type_} was not pushed to {token}: {types}"

    def assert_not_pushed(self, token: str) -> None:
        types = self.pushes_to(token)
        assert not types, f"unexpected pushes to {token}: {types}"

    # File store

    def stored_files(self) -> dict[str, tuple[bytes, str]]:
        """Every stored file by key, as `(content, content type)`."""
        return dict(self.files.objects)

    def assert_files_stored(self, count: int) -> None:
        stored = len(self.files.objects)
        assert stored == count, f"expected {count} stored files, saw {stored}"


class Clock:
    """The date the rent rules read as today in Asia/Jakarta, and the daily jobs.

    Time moves only when a scenario says so.
    """

    def __init__(self, client, secret: str, today: date) -> None:
        self._client = client
        self._secret = secret
        self.today = today

    def set(self, day: date) -> None:
        """Make `day` today."""
        self.today = day

    def advance(self, days: int = 1) -> None:
        """Move today forward by a number of days."""
        self.today += timedelta(days=days)

    def run_daily_jobs(self) -> None:
        """Run every daily job once, as the scheduler does, for today's date."""
        response = self._client.post(
            JOBS_PATH, headers={"Authorization": f"Bearer {self._secret}"}
        )
        check_status(response, 204, "run_daily_jobs")


class Cast:
    """Story-style steps that start sessions and check each answer as they go."""

    def __init__(self, *, client, stubs: Stubs, clock: Clock, make_user) -> None:
        self.client = client
        self.stubs = stubs
        self.clock = clock
        self._make_user = make_user

    def _person(self, session: dict, password: str) -> Person:
        return ROLES[session["account"]["role"]](self, session, password)

    def owner_signs_up(
        self,
        *,
        email: str = "rina@example.com",
        name: str = "Rina Owner",
        password: str = PASSWORD,
        verified: bool = True,
        device: dict | None = None,
    ) -> Owner:
        """Register an Owner, then confirm the email with the emailed code.

        Pass `verified=False` to stop before the confirmation.
        """
        response = self.client.post(
            "/auth/register",
            json={
                "name": name,
                "email": email,
                "password": password,
                "device": device or DEVICE,
            },
        )
        session = check_status(response, 201, f"owner_signs_up({email!r})").json()
        owner = self._person(session, password)
        if verified:
            owner.confirm_email()
        return owner

    def login(self, email: str, password: str = PASSWORD) -> Person:
        """Log in with email and password and return the person of the new session."""
        response = self.client.post(
            "/auth/login",
            json={"email": email, "password": password, "device": DEVICE},
        )
        session = check_status(response, 200, f"login({email!r})").json()
        return self._person(session, password)

    def admin(
        self,
        *,
        email: str = "ade@example.com",
        name: str = "Ade Admin",
        password: str = PASSWORD,
    ) -> Admin:
        """Create an Admin account and sign it in through the login endpoint.

        No endpoint creates an Admin, so the account row is inserted directly.
        """
        from app.schemas.auth import UserRole
        from app.services.passwords import hash_password

        self._make_user(
            name=name,
            email=email,
            password_hash=hash_password(password),
            role=UserRole.ADMIN,
            email_verified=True,
        )
        return self.login(email, password)

    def _activate(
        self,
        token: str,
        role: str,
        step: str,
        *,
        email: str | None,
        name: str | None,
        password: str,
        emergency_contacts: list[dict] | None,
        verified: bool,
    ) -> Person:
        response = self.client.post("/invitations/previews", json={"token": token})
        preview = check_status(response, 200, f"{step} (preview)").json()
        if preview["status"] != "valid" or preview["role"] != role:
            raise AssertionError(
                f"{step} failed: the invitation is {preview['status']!r} "
                f"for a {preview['role']!r}, expected a valid {role!r} invitation"
            )
        name = name or preview["name"]
        body: dict[str, Any] = {
            "token": str(token),
            "name": name,
            "email": email or f"{name.lower().replace(' ', '.')}@example.com",
            "password": password,
            "device": DEVICE,
        }
        if preview["emergencyContactsRequired"]:
            body["emergencyContacts"] = emergency_contacts or EMERGENCY_CONTACTS
        response = self.client.post("/invitations/activations/password", json=body)
        session = check_status(response, 201, f"{step} (activation)").json()
        person = self._person(session, password)
        if verified:
            person.confirm_email()
        return person

    def tenant_activates(
        self,
        token: str,
        *,
        email: str | None = None,
        name: str | None = None,
        password: str = PASSWORD,
        emergency_contacts: list[dict] | None = None,
        verified: bool = True,
    ) -> Tenant:
        """Preview the invitation, activate with a password and confirm the email.

        The email defaults to the invited name as `first.last@example.com`.
        Emergency contacts are sent only when the invitation asks for them;
        default contacts are used when none are given.
        """
        return self._activate(
            token,
            "tenant",
            "tenant_activates",
            email=email,
            name=name,
            password=password,
            emergency_contacts=emergency_contacts,
            verified=verified,
        )

    def manager_activates(
        self,
        token: str,
        *,
        email: str | None = None,
        name: str | None = None,
        password: str = PASSWORD,
        verified: bool = True,
    ) -> Manager:
        """Preview the invitation, activate with a password and confirm the email."""
        return self._activate(
            token,
            "manager",
            "manager_activates",
            email=email,
            name=name,
            password=password,
            emergency_contacts=None,
            verified=verified,
        )


# The world built by `build_seed`. Names, emails and numbers never change.
OWNER_EMAIL = "rina@example.com"
MANAGER_EMAIL = "mira@example.com"
BUDI_EMAIL = "budi@example.com"
SARI_EMAIL = "sari@example.com"
MELATI = "Kos Melati"
ANGGREK = "Kos Anggrek"
ROOM_RATES = {"A1": 1_200_000, "A2": 1_000_000, "A3": 1_000_000}
ANGGREK_RATES = {"B1": 800_000, "B2": 800_000}


@dataclass
class SeededWorld:
    """The documented world, with handles to everything in it.

    One Owner on the Basic plan with two properties (`melati` has a bank
    account, `anggrek` has none); rooms A1 to A3 in Melati and B1 and B2 in
    Anggrek (`rooms` by number); tenants Budi (A1) and Sari (A2), both
    activated, and Dewi (B1), invited only (`dewi_token`); Manager Mira,
    assigned to Melati; one complaint by Budi (`complaint`); and the three rent
    bills the daily job issued on `date`.
    """

    owner: Owner
    manager: Manager
    budi: Tenant
    sari: Tenant
    dewi_token: InviteToken
    melati: dict
    anggrek: dict
    rooms: dict[str, dict]
    complaint: dict
    date: date


def build_seed(world: Cast) -> SeededWorld:
    """Build the documented world through the steps of a `Cast`."""
    today = world.clock.today
    first_of_month = today.replace(day=1)
    owner = world.owner_signs_up(email=OWNER_EMAIL, name="Rina Owner")
    owner.subscribe("basic")
    melati = owner.add_property(
        MELATI, address="Jl. Melati 5", bank_account=BANK_ACCOUNT
    )
    anggrek = owner.add_property(ANGGREK, address="Jl. Anggrek 7")
    rooms = {
        number: owner.add_room(melati, number, base_rate=rate)
        for number, rate in ROOM_RATES.items()
    }
    rooms |= {
        number: owner.add_room(anggrek, number, base_rate=rate)
        for number, rate in ANGGREK_RATES.items()
    }

    manager = world.manager_activates(
        owner.add_manager([melati], name="Mira Manager", phone="081200000001"),
        email=MANAGER_EMAIL,
    )
    budi = world.tenant_activates(
        owner.add_tenant(
            rooms["A1"],
            "Budi Tenant",
            "081211111111",
            lease={"startDate": first_of_month},
        ),
        email=BUDI_EMAIL,
    )
    sari = world.tenant_activates(
        owner.add_tenant(
            rooms["A2"],
            "Sari Tenant",
            "081222222222",
            lease={
                "startDate": first_of_month + timedelta(days=9),
                "gracePeriodDays": 5,
            },
        ),
        email=SARI_EMAIL,
    )
    dewi_token = owner.add_tenant(
        rooms["B1"],
        "Dewi Tenant",
        "081233333333",
        lease={"startDate": first_of_month + timedelta(days=14)},
    )
    complaint = budi.submit_complaint(rooms["A1"], COMPLAINT_TEXT)
    world.clock.run_daily_jobs()
    return SeededWorld(
        owner=owner,
        manager=manager,
        budi=budi,
        sari=sari,
        dewi_token=dewi_token,
        melati=melati,
        anggrek=anggrek,
        rooms=rooms,
        complaint=complaint,
        date=today,
    )
