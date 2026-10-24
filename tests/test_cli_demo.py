"""The `niscala-api seed-demo` command."""

from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.schemas.auth import UserRole

DEMO = "seed-demo"
OWNER_EMAIL = "owner@example.com"
TENANT_EMAIL = "tenant@example.com"
PASSWORD = "Demo-Kost-2026!"
DEVICE = {"name": "Pixel 8", "platform": "Android 14"}


def jakarta_today() -> date:
    return datetime.now(ZoneInfo("Asia/Jakarta")).date()


def first_of_month_before(today: date, months: int) -> date:
    index = today.year * 12 + (today.month - 1) - months
    return date(index // 12, index % 12 + 1, 1)


def expected_lease_dates() -> tuple[date, date]:
    start = first_of_month_before(jakarta_today(), 2)
    return start, start.replace(year=start.year + 1)


def row_counts(database) -> dict[str, int]:
    """Row count of every table, to compare before and after a command."""
    from app.models import Base

    with Session(database) as db:
        return {
            table.name: db.execute(
                text(f'SELECT count(*) FROM "{table.name}"')
            ).scalar_one()
            for table in Base.metadata.sorted_tables
        }


def fetch_all(database, model) -> list:
    with Session(database, expire_on_commit=False) as db:
        return list(db.scalars(select(model)))


def user_by_email(database, email: str):
    from app.models import UserAccount

    with Session(database, expire_on_commit=False) as db:
        return db.scalars(
            select(UserAccount).where(UserAccount.email == email)
        ).one_or_none()


def run_demo(capsys) -> str:
    from app.cli import main

    assert main([DEMO]) == 0
    return capsys.readouterr().out


def login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post(
        "/auth/login",
        json={"email": email, "password": password, "device": DEVICE},
    )


def auth_headers(client: TestClient, email: str) -> dict[str, str]:
    response = login(client, email)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


def logins_in(output: str) -> list[str]:
    return [line for line in output.splitlines() if "@example.com" in line]


@pytest.fixture
def demo(database, capsys):
    """Run the command once and return what it printed."""
    return run_demo(capsys)


def test_it_exits_zero_and_prints_nothing_to_stderr(database, capsys):
    from app.cli import main

    assert main([DEMO]) == 0
    assert capsys.readouterr().err == ""


def test_it_prints_both_logins_and_the_property_and_room(demo):
    assert OWNER_EMAIL in demo
    assert TENANT_EMAIL in demo
    assert demo.count(PASSWORD) >= 2
    assert "Kost Melati" in demo
    assert "101" in demo


def test_each_login_is_on_its_own_line_with_its_password(demo):
    lines = logins_in(demo)
    owner_lines = [line for line in lines if OWNER_EMAIL in line]
    tenant_lines = [line for line in lines if TENANT_EMAIL in line]
    assert owner_lines
    assert tenant_lines
    assert not any(OWNER_EMAIL in line and TENANT_EMAIL in line for line in lines)
    assert demo.count(PASSWORD) >= 2


def test_the_property_name_and_room_number_are_printed_on_lines(demo):
    lines = demo.splitlines()
    assert any("Kost Melati" in line for line in lines)
    assert any("101" in line for line in lines)
    assert not any(OWNER_EMAIL in line and "Kost Melati" in line for line in lines)


def test_it_creates_one_owner_with_a_verified_email_and_the_demo_password(
    database, demo
):
    from app.services.passwords import verify_password

    owner = user_by_email(database, OWNER_EMAIL)
    assert owner.role == UserRole.OWNER
    assert owner.name == "Demo Owner"
    assert owner.email_verified is True
    assert verify_password(PASSWORD, owner.password_hash)


def test_it_creates_one_property_owned_by_the_owner(database, demo):
    from app.models import Property

    owner = user_by_email(database, OWNER_EMAIL)
    (prop,) = fetch_all(database, Property)
    assert prop.owner_id == owner.id
    assert prop.name == "Kost Melati"
    assert prop.address == "Jl. Melati No. 1, Jakarta"
    assert prop.view_only is False
    assert prop.deleted_at is None
    assert prop.bank_name is None
    assert prop.bank_account_number is None
    assert prop.bank_account_holder_name is None


def test_it_creates_one_room_with_its_size_rate_and_facilities(database, demo):
    from app.models import Property, Room

    (prop,) = fetch_all(database, Property)
    (room,) = fetch_all(database, Room)
    assert room.property_id == prop.id
    assert room.number == "101"
    assert room.base_rate == 1500000
    assert room.length_m == Decimal(3)
    assert room.width_m == Decimal(4)
    assert room.view_only is False
    assert room.deleted_at is None
    assert sorted(f.lower() for f in room.facilities) == ["ac", "wi-fi"]
    assert len(room.facilities) == 2


def test_it_creates_one_activated_tenant_with_a_verified_email_and_password(
    database, demo
):
    from app.models import Tenant
    from app.services.passwords import verify_password

    user = user_by_email(database, TENANT_EMAIL)
    (tenant,) = fetch_all(database, Tenant)
    assert user.role == UserRole.TENANT
    assert user.name == "Budi Santoso"
    assert user.email_verified is True
    assert verify_password(PASSWORD, user.password_hash)
    assert tenant.user_id == user.id
    assert tenant.phone == "081234567890"
    assert tenant.activated_at is not None
    assert tenant.deleted_at is None


def test_the_tenant_has_exactly_two_emergency_contacts_in_order(database, demo):
    from app.models import EmergencyContact

    contacts = sorted(fetch_all(database, EmergencyContact), key=lambda c: c.position)
    user = user_by_email(database, TENANT_EMAIL)
    assert len(contacts) == 2
    assert len({c.position for c in contacts}) == 2
    for contact in contacts:
        assert contact.tenant_id == user.id
        assert contact.name
        assert contact.relationship
        assert contact.phone
    assert contacts[0].name != contacts[1].name or (
        contacts[0].phone != contacts[1].phone
    )


def test_the_tenant_has_one_active_monthly_lease_started_two_months_ago(database, demo):
    from app.models import Lease, Room

    start, end = expected_lease_dates()
    user = user_by_email(database, TENANT_EMAIL)
    (room,) = fetch_all(database, Room)
    (lease,) = fetch_all(database, Lease)
    assert lease.tenant_id == user.id
    assert lease.room_id == room.id
    assert lease.billing_cycle == "monthly"
    assert lease.rent == 1500000
    assert lease.grace_period_days == 0
    assert lease.start_date == start
    assert lease.end_date == end
    assert lease.ended_at is None


def test_the_lease_dates_are_twelve_months_apart_from_the_first_of_a_month(
    database, demo
):
    from app.models import Lease

    (lease,) = fetch_all(database, Lease)
    assert lease.start_date.day == 1
    assert lease.end_date.day == 1
    months = (lease.end_date.year - lease.start_date.year) * 12 + (
        lease.end_date.month - lease.start_date.month
    )
    assert months == 12
    assert lease.start_date <= jakarta_today() < lease.end_date


def test_no_invitation_is_left_that_could_still_be_used(database, demo):
    from app.models import Invitation

    now = datetime.now(UTC)
    for invitation in fetch_all(database, Invitation):
        assert (
            invitation.used_at is not None
            or invitation.invalidated_at is not None
            or invitation.expires_at <= now
        )


def test_it_creates_nothing_beyond_the_demo_data(database, demo):
    counts = row_counts(database)
    assert counts["user_accounts"] == 2
    assert counts["properties"] == 1
    assert counts["rooms"] == 1
    assert counts["tenants"] == 1
    assert counts["leases"] == 1
    assert counts["emergency_contacts"] == 2
    assert counts["rent_bills"] == 0
    assert counts["sessions"] == 0


def test_the_owner_can_log_in_with_the_printed_password(client, database, demo):
    response = login(client, OWNER_EMAIL)
    assert response.status_code == 200, response.text
    account = response.json()["account"]
    assert account["role"] == "owner"
    assert account["emailVerified"] is True
    assert account["name"] == "Demo Owner"


def test_the_tenant_can_log_in_with_the_printed_password(client, database, demo):
    response = login(client, TENANT_EMAIL)
    assert response.status_code == 200, response.text
    account = response.json()["account"]
    assert account["role"] == "tenant"
    assert account["emailVerified"] is True
    assert account["name"] == "Budi Santoso"


def test_login_ignores_the_case_of_the_email(client, database, demo):
    assert login(client, "Owner@Example.COM").status_code == 200


def test_a_wrong_password_is_still_rejected(client, database, demo):
    response = login(client, OWNER_EMAIL, password="Wrong-Password-1!")
    assert response.status_code == 401


def test_the_tenant_account_answers_for_itself_with_the_tenant_role(
    client, database, demo
):
    headers = auth_headers(client, TENANT_EMAIL)
    response = client.get("/me", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == "tenant"
    assert body["emailVerified"] is True
    assert body["email"] == TENANT_EMAIL


def test_the_owner_account_answers_for_itself_with_the_owner_role(
    client, database, demo
):
    headers = auth_headers(client, OWNER_EMAIL)
    response = client.get("/me", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "owner"
    assert response.json()["emailVerified"] is True


def test_the_owner_sees_the_property_with_one_occupied_room(client, database, demo):
    headers = auth_headers(client, OWNER_EMAIL)
    response = client.get("/properties", headers=headers)
    assert response.status_code == 200, response.text
    (item,) = response.json()["items"]
    assert item["name"] == "Kost Melati"
    assert item["address"] == "Jl. Melati No. 1, Jakarta"
    assert item["roomCount"] == 1
    assert item["occupiedRoomCount"] == 1
    assert item["editable"] is True


def test_the_owner_sees_room_101_occupied_by_the_tenant(client, database, demo):
    headers = auth_headers(client, OWNER_EMAIL)
    (item,) = client.get("/properties", headers=headers).json()["items"]
    response = client.get(f"/properties/{item['id']}/rooms", headers=headers)
    assert response.status_code == 200, response.text
    (room,) = response.json()["items"]
    _, end = expected_lease_dates()
    assert room["number"] == "101"
    assert room["baseRate"] == 1500000
    assert room["occupancy"] == "occupied"
    assert room["lengthM"] == 3
    assert room["widthM"] == 4
    assert sorted(f.lower() for f in room["facilities"]) == ["ac", "wi-fi"]
    assert room["lease"]["tenantName"] == "Budi Santoso"
    assert room["lease"]["endDate"] == end.isoformat()
    assert room["editable"] is True


def test_the_owner_lists_the_tenant_as_active(client, database, demo):
    headers = auth_headers(client, OWNER_EMAIL)
    (item,) = client.get("/properties", headers=headers).json()["items"]
    response = client.get(f"/properties/{item['id']}/tenants", headers=headers)
    assert response.status_code == 200, response.text
    (tenant,) = response.json()["items"]
    assert tenant["name"] == "Budi Santoso"
    assert tenant["accountStatus"] == "active"
    assert tenant["room"]["number"] == "101"
    assert tenant["billingCycle"] == "monthly"
    assert tenant["leaseEndDate"] == expected_lease_dates()[1].isoformat()
    assert tenant["invitationExpiresAt"] is None


def test_the_owner_reads_the_tenant_with_its_lease_and_contacts(client, database, demo):
    headers = auth_headers(client, OWNER_EMAIL)
    (item,) = client.get("/properties", headers=headers).json()["items"]
    (summary,) = client.get(
        f"/properties/{item['id']}/tenants", headers=headers
    ).json()["items"]
    response = client.get(f"/tenants/{summary['id']}", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    start, end = expected_lease_dates()
    assert body["email"] == TENANT_EMAIL
    assert body["phone"] == "081234567890"
    assert body["accountStatus"] == "active"
    assert len(body["emergencyContacts"]) == 2
    assert body["lease"]["startDate"] == start.isoformat()
    assert body["lease"]["endDate"] == end.isoformat()
    assert body["lease"]["rent"] == 1500000
    assert body["lease"]["billingCycle"] == "monthly"
    assert body["lease"]["gracePeriodDays"] == 0
    assert body["invitation"] is None


def test_neither_account_is_blocked_for_an_unverified_email(client, database, demo):
    owner_headers = auth_headers(client, OWNER_EMAIL)
    assert client.get("/properties", headers=owner_headers).status_code == 200
    tenant_headers = auth_headers(client, TENANT_EMAIL)
    response = client.get("/me", headers=tenant_headers)
    assert response.status_code == 200
    assert response.json().get("code") != "EMAIL_NOT_VERIFIED"


def test_running_again_exits_zero_with_nothing_on_stderr(database, capsys, demo):
    from app.cli import main

    assert main([DEMO]) == 0
    assert capsys.readouterr().err == ""


def test_running_again_changes_no_rows(database, capsys, demo):
    from app.cli import main

    before = row_counts(database)
    assert main([DEMO]) == 0
    assert row_counts(database) == before


def test_running_again_keeps_the_same_rows(database, capsys, demo):
    from app.cli import main
    from app.models import Lease, Property, Room, Tenant

    ids_before = {
        model.__name__: sorted(
            str(getattr(row, "id", None) or row.user_id)
            for row in fetch_all(database, model)
        )
        for model in (Property, Room, Tenant, Lease)
    }
    owner_id = user_by_email(database, OWNER_EMAIL).id
    assert main([DEMO]) == 0
    ids_after = {
        model.__name__: sorted(
            str(getattr(row, "id", None) or row.user_id)
            for row in fetch_all(database, model)
        )
        for model in (Property, Room, Tenant, Lease)
    }
    assert ids_after == ids_before
    assert user_by_email(database, OWNER_EMAIL).id == owner_id


def test_running_again_prints_the_same_two_logins(database, capsys, demo):
    from app.cli import main

    assert main([DEMO]) == 0
    second = capsys.readouterr().out
    assert logins_in(second) == logins_in(demo)
    assert second.count(PASSWORD) >= 2
    assert "Kost Melati" in second
    assert "101" in second


@pytest.mark.parametrize("email", [OWNER_EMAIL, TENANT_EMAIL])
def test_running_again_does_not_reset_a_changed_password(database, capsys, demo, email):
    from app.cli import main
    from app.models import UserAccount
    from app.services.passwords import hash_password

    changed = hash_password("Another-Secret-7!")
    with Session(database) as db:
        user = db.scalars(select(UserAccount).where(UserAccount.email == email)).one()
        user.password_hash = changed
        db.commit()
    assert main([DEMO]) == 0
    assert user_by_email(database, email).password_hash == changed


def test_a_changed_password_still_logs_in_after_running_again(
    client, database, capsys, demo
):
    from app.cli import main
    from app.models import UserAccount
    from app.services.passwords import hash_password

    with Session(database) as db:
        user = db.scalars(
            select(UserAccount).where(UserAccount.email == OWNER_EMAIL)
        ).one()
        user.password_hash = hash_password("Another-Secret-7!")
        db.commit()
    main([DEMO])
    assert login(client, OWNER_EMAIL, "Another-Secret-7!").status_code == 200
    assert login(client, OWNER_EMAIL, PASSWORD).status_code == 401


def test_running_a_third_time_still_changes_nothing(database, capsys, demo):
    from app.cli import main

    before = row_counts(database)
    assert main([DEMO]) == 0
    assert main([DEMO]) == 0
    assert row_counts(database) == before


def test_existing_accounts_are_found_ignoring_the_case_of_the_email(
    database, capsys, demo
):
    from app.cli import main

    with database.begin() as connection:
        connection.execute(
            text("UPDATE user_accounts SET email = upper(email)"),
        )
    before = row_counts(database)
    assert main([DEMO]) == 0
    assert row_counts(database) == before
    assert capsys.readouterr().err == ""


def conflict_message(capsys, email: str) -> None:
    captured = capsys.readouterr()
    assert captured.out == ""
    lines = captured.err.strip().splitlines()
    assert len(lines) == 1
    assert email in lines[0].lower()


@pytest.mark.parametrize("role", [UserRole.TENANT, UserRole.MANAGER, UserRole.ADMIN])
def test_an_owner_email_held_by_another_role_fails_without_saving(
    database, make_user, capsys, role
):
    from app.cli import main

    make_user(email=OWNER_EMAIL, role=role)
    before = row_counts(database)
    assert main([DEMO]) == 1
    conflict_message(capsys, OWNER_EMAIL)
    assert row_counts(database) == before


@pytest.mark.parametrize("role", [UserRole.OWNER, UserRole.MANAGER, UserRole.ADMIN])
def test_a_tenant_email_held_by_another_role_fails_without_saving(
    database, make_user, capsys, role
):
    from app.cli import main

    make_user(email=TENANT_EMAIL, role=role)
    before = row_counts(database)
    assert main([DEMO]) == 1
    conflict_message(capsys, TENANT_EMAIL)
    assert row_counts(database) == before


@pytest.mark.parametrize("role", [UserRole.OWNER, UserRole.MANAGER, UserRole.ADMIN])
def test_a_tenant_email_held_by_another_account_fails_when_the_owner_exists(
    database, make_user, capsys, role
):
    from app.cli import main

    make_user(email=OWNER_EMAIL, name="Demo Owner")
    make_user(email=TENANT_EMAIL, role=role)
    before = row_counts(database)
    assert main([DEMO]) == 1
    conflict_message(capsys, TENANT_EMAIL)
    assert row_counts(database) == before


def test_a_conflicting_owner_email_is_found_ignoring_case(database, make_user, capsys):
    from app.cli import main

    make_user(email=OWNER_EMAIL, role=UserRole.MANAGER)
    with database.begin() as connection:
        connection.execute(text("UPDATE user_accounts SET email = upper(email)"))
    before = row_counts(database)
    assert main([DEMO]) == 1
    conflict_message(capsys, OWNER_EMAIL)
    assert row_counts(database) == before


def test_a_conflicting_tenant_email_is_found_ignoring_case(database, make_user, capsys):
    from app.cli import main

    make_user(email=TENANT_EMAIL, role=UserRole.OWNER)
    with database.begin() as connection:
        connection.execute(text("UPDATE user_accounts SET email = upper(email)"))
    before = row_counts(database)
    assert main([DEMO]) == 1
    conflict_message(capsys, TENANT_EMAIL)
    assert row_counts(database) == before


def test_a_conflict_leaves_other_accounts_untouched(database, make_user, capsys):
    from app.cli import main

    other = make_user(email=OWNER_EMAIL, role=UserRole.MANAGER, name="Mira")
    main([DEMO])
    row = user_by_email(database, OWNER_EMAIL)
    assert (row.id, row.name, row.role) == (other.id, "Mira", UserRole.MANAGER)


def test_demo_data_is_added_next_to_unrelated_accounts(database, make_user, capsys):
    from app.cli import main

    other = make_user(email="someone@example.com")
    assert main([DEMO]) == 0
    assert user_by_email(database, "someone@example.com").id == other.id
    assert user_by_email(database, OWNER_EMAIL) is not None
    assert user_by_email(database, TENANT_EMAIL) is not None


def test_an_argument_is_a_usage_error(database, capsys):
    from app.cli import main

    with pytest.raises(SystemExit) as exit_info:
        main([DEMO, "extra"])
    assert exit_info.value.code == 2
    assert row_counts(database)["user_accounts"] == 0


def test_an_unknown_option_is_a_usage_error(database):
    from app.cli import main

    with pytest.raises(SystemExit) as exit_info:
        main([DEMO, "--days", "3"])
    assert exit_info.value.code == 2


def test_the_help_lists_the_command_beside_the_existing_ones(capsys):
    from app.cli import main

    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert DEMO in out
    assert "grant-subscription" in out
    assert "seed-rent-bills" in out


def test_the_existing_commands_still_work_after_seeding(database, capsys, demo):
    from app.cli import main

    assert main(["grant-subscription", OWNER_EMAIL, "pro"]) == 0
    assert main(["seed-rent-bills", TENANT_EMAIL]) == 0


def test_the_demo_tenant_gets_rent_bills_for_its_lease(database, capsys, demo):
    from app.cli import main
    from app.models import RentBill

    capsys.readouterr()
    assert main(["seed-rent-bills", TENANT_EMAIL]) == 0
    bills = sorted(fetch_all(database, RentBill), key=lambda b: b.period_start)
    start, _ = expected_lease_dates()
    assert bills[0].period_start == start
    assert len(bills) == 3
    assert all(b.amount == 1500000 for b in bills)
