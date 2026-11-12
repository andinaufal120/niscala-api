"""Scenarios of adding, viewing, editing and deleting tenants and their leases."""

from datetime import date

from e2e.e2e_auth import assert_error, raw_login
from e2e.e2e_people import EMERGENCY_CONTACTS, PASSWORD
from e2e.e2e_rent import (
    accept_another_tenancy,
    assert_field_error,
    build_site,
    edit_body,
    join,
)

TODAY = date(2026, 10, 23)


def add_tenant_raw(owner, room, **fields):
    """Send an add-tenant request as written, without the step's checks."""
    body = {
        "roomId": room["id"],
        "name": "Budi Tenant",
        "phone": "081211111111",
        "lease": {},
        "emergencyContacts": [],
    }
    body.update(fields)
    return owner.post(f"/properties/{room['propertyId']}/tenants", json=body)


def occupancy(owner, prop, number: str) -> str:
    rooms = {r["number"]: r for r in owner.rooms(prop)}
    return rooms[number]["occupancy"]


def test_management_adds_a_monthly_tenant_who_activates_and_sees_the_lease(world):
    site = build_site(world)
    owner, room = site.owner, site.rooms["A1"]
    owner.put(f"/rooms/{room['id']}", json={**room, "baseRate": 1_500_000}, expect=200)

    token = owner.add_tenant(
        room,
        "Budi Tenant",
        "081211111111",
        lease={"startDate": date(2026, 10, 10), "endDate": date(2027, 10, 9)},
    )

    record = token.record
    assert record["accountStatus"] == "notActivated"
    assert record["lease"]["billingCycle"] == "monthly"
    assert record["lease"]["rent"] == 1_500_000
    assert record["lease"]["gracePeriodDays"] == 0
    assert record["invitation"]["url"]
    assert occupancy(owner, site.melati, "A1") == "occupied"
    again = add_tenant_raw(owner, room, name="Sari Tenant")
    assert_field_error(again, 409, "ROOM_NOT_VACANT", "roomId")

    budi = world.tenant_activates(token, email="budi@example.com")

    leases = budi.leases()
    assert len(leases) == 1
    lease = leases[0]
    assert lease["tenantId"] == token.id
    assert lease["room"]["number"] == "A1"
    assert lease["room"]["id"] == room["id"]
    assert lease["property"]["name"] == "Kos Melati"
    assert lease["property"]["address"] == "Jl. Melati 5"
    assert lease["property"]["id"] == site.melati["id"]
    assert lease["startDate"] == "2026-10-10"
    assert lease["endDate"] == "2027-10-09"
    assert lease["rent"] == 1_500_000
    assert lease["billingCycle"] == "monthly"
    assert "bankAccount" not in lease["property"]
    assert "1234567890" not in str(leases)
    detail = owner.read(f"/tenants/{token.id}")
    assert detail["accountStatus"] == "active"
    assert detail["invitation"] is None
    assert detail["email"] == "budi@example.com"


def test_a_lease_that_is_not_monthly_needs_a_rent_and_failures_leave_the_room_vacant(
    world,
):
    site = build_site(world)
    owner, room = site.owner, site.rooms["A1"]

    no_rent = add_tenant_raw(
        owner, room, lease={"startDate": "2026-10-01", "billingCycle": "quarterly"}
    )
    assert_field_error(no_rent, 422, "VALIDATION_FAILED", "lease.rent")
    backwards = add_tenant_raw(
        owner, room, lease={"startDate": "2026-10-10", "endDate": "2026-10-09"}
    )
    assert_field_error(backwards, 422, "VALIDATION_FAILED", "lease.endDate")
    assert owner.tenants(site.melati) == []
    assert occupancy(owner, site.melati, "A1") == "vacant"

    token = owner.add_tenant(
        room,
        "Budi Tenant",
        "081211111111",
        lease={
            "startDate": date(2026, 10, 1),
            "billingCycle": "quarterly",
            "rent": 2_700_000,
        },
    )

    assert token.record["lease"]["billingCycle"] == "quarterly"
    assert token.record["lease"]["rent"] == 2_700_000
    assert occupancy(owner, site.melati, "A1") == "occupied"


def test_a_manager_adds_tenants_only_to_assigned_properties(world):
    site = build_site(world)
    manager = site.manager

    token = manager.add_tenant(site.rooms["A1"], "Budi Tenant", "081211111111")

    assert token.record["room"]["number"] == "A1"
    refused = add_tenant_raw(manager, site.rooms["B1"])
    assert_error(refused, 404, "PROPERTY_NOT_FOUND")
    assert occupancy(site.owner, site.anggrek, "B1") == "vacant"


def test_management_lists_tenants_in_room_order_and_reads_a_detail_with_next_bill_date(
    world,
):
    world.clock.set(TODAY)
    site = build_site(world, melati_rooms=("10", "2", "1"), anggrek_rooms=("B1",))
    owner = site.owner
    owner.add_tenant(
        site.rooms["10"],
        "Tia Tenant",
        "081211111111",
        lease={"startDate": date(2026, 1, 31)},
    )
    weekly = owner.add_tenant(
        site.rooms["2"],
        "Wati Tenant",
        "081211111112",
        lease={
            "startDate": date(2026, 10, 20),
            "billingCycle": "weekly",
            "rent": 300_000,
        },
    )
    ended = owner.add_tenant(
        site.rooms["1"],
        "Edo Tenant",
        "081211111113",
        lease={"startDate": date(2026, 9, 1), "endDate": date(2026, 10, 15)},
    )
    undated = add_tenant_raw(owner, site.rooms["B1"], name="Nia Tenant")
    assert undated.status_code == 201

    listed = owner.tenants(site.melati)

    assert [t["room"]["number"] for t in listed] == ["1", "2", "10"]
    assert [t["name"] for t in listed] == ["Edo Tenant", "Wati Tenant", "Tia Tenant"]
    assert {t["accountStatus"] for t in listed} == {"notActivated"}
    assert all(t["invitationExpiresAt"] for t in listed)
    assert listed[1]["billingCycle"] == "weekly"
    assert listed[0]["leaseEndDate"] == "2026-10-15"
    assert [t["room"]["number"] for t in site.manager.tenants(site.melati)] == [
        "1",
        "2",
        "10",
    ]
    assert_error(
        site.manager.get(f"/properties/{site.anggrek['id']}/tenants"),
        404,
        "PROPERTY_NOT_FOUND",
    )

    monthly = owner.read(f"/tenants/{listed[2]['id']}")
    assert monthly["lease"]["nextBillDate"] == "2026-10-31"
    assert monthly["invitation"]["url"]
    assert monthly["invitation"]["expired"] is False
    assert owner.read(f"/tenants/{weekly.id}")["lease"]["nextBillDate"] == "2026-10-27"
    assert owner.read(f"/tenants/{ended.id}")["lease"]["nextBillDate"] is None
    assert owner.tenants(site.anggrek)[0]["name"] == "Nia Tenant"
    assert undated.json()["lease"]["startDate"] is None
    assert undated.json()["lease"]["nextBillDate"] is None


def test_next_bill_date_moves_with_the_clock(world):
    world.clock.set(TODAY)
    site = build_site(world)
    owner = site.owner
    token = owner.add_tenant(
        site.rooms["A1"],
        "Budi Tenant",
        "081211111111",
        lease={"startDate": date(2026, 1, 31)},
    )

    assert owner.read(f"/tenants/{token.id}")["lease"]["nextBillDate"] == "2026-10-31"
    world.clock.set(date(2026, 10, 31))
    assert owner.read(f"/tenants/{token.id}")["lease"]["nextBillDate"] == "2026-11-30"
    world.clock.set(date(2026, 11, 30))
    assert owner.read(f"/tenants/{token.id}")["lease"]["nextBillDate"] == "2026-12-31"


def test_an_unknown_or_foreign_tenant_is_not_found(world):
    site = build_site(world)
    token = site.owner.add_tenant(site.rooms["A1"], "Budi Tenant", "081211111111")
    stranger = world.owner_signs_up(email="other@example.com", name="Other Owner")

    assert_error(stranger.get(f"/tenants/{token.id}"), 404, "TENANT_NOT_FOUND")
    assert_error(
        site.manager.get(
            f"/tenants/{site.owner.add_tenant(site.rooms['B1'], 'Sari Tenant', '081211111112').id}"
        ),
        404,
        "TENANT_NOT_FOUND",
    )
    assert site.manager.read(f"/tenants/{token.id}")["name"] == "Budi Tenant"


def test_the_name_of_an_invited_tenant_can_change_but_not_once_active(world):
    site = build_site(world)
    owner = site.owner
    token = owner.add_tenant(site.rooms["A1"], "Budi Tenant", "081211111111")

    detail = owner.read(f"/tenants/{token.id}")
    renamed = owner.put(
        f"/tenants/{token.id}", json=edit_body(detail, name="Budi Santoso"), expect=200
    ).json()
    assert renamed["name"] == "Budi Santoso"
    assert renamed["version"] == detail["version"] + 1

    world.tenant_activates(token, email="budi@example.com")

    detail = owner.read(f"/tenants/{token.id}")
    locked = owner.put(f"/tenants/{token.id}", json=edit_body(detail, name="Budi Lain"))
    assert_field_error(locked, 422, "TENANT_NAME_NOT_EDITABLE", "name")
    assert owner.read(f"/tenants/{token.id}")["name"] == "Budi Santoso"
    phone = owner.put(
        f"/tenants/{token.id}",
        json=edit_body(detail, phone="081299999999", occupation="Student"),
        expect=200,
    ).json()
    assert phone["phone"] == "081299999999"
    assert phone["occupation"] == "Student"
    assert phone["name"] == "Budi Santoso"
    emptied = owner.put(
        f"/tenants/{token.id}", json=edit_body(detail, emergencyContacts=[])
    )
    assert_field_error(emptied, 422, "VALIDATION_FAILED", "emergencyContacts")
    assert owner.read(f"/tenants/{token.id}")["emergencyContacts"] == EMERGENCY_CONTACTS


def test_a_rent_change_applies_from_the_next_bill_and_existing_bills_keep_their_rent(
    world,
):
    world.clock.set(TODAY)
    site = build_site(world)
    owner = site.owner
    token = owner.add_tenant(
        site.rooms["A1"],
        "Budi Tenant",
        "081211111111",
        lease={"startDate": date(2026, 10, 1), "gracePeriodDays": 2},
    )
    budi = world.tenant_activates(token, email="budi@example.com")
    world.clock.run_daily_jobs()
    assert [b["amount"] for b in budi.rent_bills()] == [1_000_000]

    detail = owner.read(f"/tenants/{token.id}")
    owner.put(
        f"/tenants/{token.id}",
        json=edit_body(detail, lease={"rent": 1_200_000}),
        expect=200,
    )

    assert owner.read(f"/tenants/{token.id}")["lease"]["rent"] == 1_200_000
    assert budi.leases()[0]["rent"] == 1_200_000
    assert [b["amount"] for b in budi.rent_bills()] == [1_000_000]
    world.clock.run_daily_jobs()
    assert [b["amount"] for b in budi.rent_bills()] == [1_000_000]

    world.clock.set(date(2026, 11, 1))
    world.clock.run_daily_jobs()

    bills = budi.rent_bills()
    assert [b["periodStart"] for b in bills] == ["2026-11-01", "2026-10-01"]
    assert [b["amount"] for b in bills] == [1_200_000, 1_000_000]
    assert [b["dueDate"] for b in bills] == ["2026-11-03", "2026-10-03"]


def test_a_billing_cycle_change_applies_from_the_next_bill(world):
    world.clock.set(TODAY)
    site = build_site(world)
    owner = site.owner
    token = owner.add_tenant(
        site.rooms["A1"],
        "Budi Tenant",
        "081211111111",
        lease={"startDate": date(2026, 10, 1)},
    )
    budi = world.tenant_activates(token, email="budi@example.com")
    world.clock.run_daily_jobs()
    detail = owner.read(f"/tenants/{token.id}")
    owner.put(
        f"/tenants/{token.id}",
        json=edit_body(detail, lease={"billingCycle": "quarterly", "rent": 2_700_000}),
        expect=200,
    )

    first = budi.rent_bills()[0]
    assert (first["periodStart"], first["periodEnd"], first["amount"]) == (
        "2026-10-01",
        "2026-10-31",
        1_000_000,
    )
    world.clock.set(date(2026, 11, 1))
    world.clock.run_daily_jobs()
    assert len(budi.rent_bills()) == 1

    world.clock.set(date(2027, 1, 1))
    world.clock.run_daily_jobs()

    bills = budi.rent_bills()
    assert [b["periodStart"] for b in bills] == ["2027-01-01", "2026-10-01"]
    assert (bills[0]["periodEnd"], bills[0]["amount"]) == ("2027-03-31", 2_700_000)
    assert bills[1]["amount"] == 1_000_000


def test_a_lease_end_before_the_start_is_refused_when_editing(world):
    site = build_site(world)
    owner = site.owner
    token = owner.add_tenant(
        site.rooms["A1"],
        "Budi Tenant",
        "081211111111",
        lease={"startDate": date(2026, 10, 10)},
    )
    detail = owner.read(f"/tenants/{token.id}")

    response = owner.put(
        f"/tenants/{token.id}",
        json=edit_body(detail, lease={"endDate": "2026-10-09"}),
    )

    assert_field_error(response, 422, "VALIDATION_FAILED", "lease.endDate")
    assert owner.read(f"/tenants/{token.id}")["lease"]["endDate"] is None


def test_deleting_a_tenant_ends_the_lease_frees_the_room_and_keeps_the_payment_history(
    world,
):
    world.clock.set(TODAY)
    site = build_site(world)
    owner = site.owner
    budi = join(
        world, owner, site.rooms["A1"], "Budi Tenant", lease={"startDate": TODAY}
    )
    world.clock.run_daily_jobs()
    bill = budi.rent_bills()[0]
    budi.upload_receipt(bill)
    owner.post(f"/rent-bills/{bill['id']}/verification", expect=200)
    tenant_id = budi.leases()[0]["tenantId"]
    stale_access = budi.access_token

    owner.delete(f"/tenants/{tenant_id}", expect=204)

    assert occupancy(owner, site.melati, "A1") == "vacant"
    assert owner.tenants(site.melati) == []
    assert_error(owner.get(f"/tenants/{tenant_id}"), 404, "TENANT_NOT_FOUND")
    assert_error(owner.delete(f"/tenants/{tenant_id}"), 404, "TENANT_NOT_FOUND")
    assert_error(
        world.client.get(
            "/me/leases", headers={"Authorization": f"Bearer {stale_access}"}
        ),
        401,
        "ACCESS_TOKEN_INVALID",
    )
    assert_error(
        raw_login(world, "budi.tenant@example.com", PASSWORD),
        401,
        "INVALID_CREDENTIALS",
    )
    history = [b for b in owner.rent_bills() if b["tenant"]["name"] == "Budi Tenant"]
    assert [b["payment"]["status"] for b in history] == ["paid"]
    assert owner.rent_bill(history[0])["statusChanges"]
    world.clock.advance(40)
    world.clock.run_daily_jobs()
    assert len(owner.rent_bills()) == 1

    sari = join(world, owner, site.rooms["A1"], "Sari Tenant")
    assert [lease["room"]["number"] for lease in sari.leases()] == ["A1"]


def test_deleting_a_tenant_who_never_activated_voids_the_invitation(world):
    site = build_site(world)
    token = site.owner.add_tenant(site.rooms["A1"], "Budi Tenant", "081211111111")

    site.owner.delete(f"/tenants/{token.id}", expect=204)

    response = world.client.post("/invitations/previews", json={"token": str(token)})
    assert_error(response, 404, "INVITATION_NOT_FOUND")
    assert site.owner.tenants(site.melati) == []


def test_a_tenant_with_two_tenancies_stays_signed_in_when_one_is_deleted(world):
    world.clock.set(TODAY)
    site = build_site(world)
    owner = site.owner
    budi = join(
        world, owner, site.rooms["A1"], "Budi Tenant", lease={"startDate": TODAY}
    )
    second_id = accept_another_tenancy(
        owner, site.rooms["B1"], budi, lease={"startDate": TODAY}
    )
    by_property = {lease["property"]["name"]: lease for lease in budi.leases()}
    assert sorted(by_property) == ["Kos Anggrek", "Kos Melati"]
    first_id = by_property["Kos Melati"]["tenantId"]
    assert by_property["Kos Anggrek"]["tenantId"] == second_id

    owner.delete(f"/tenants/{first_id}", expect=204)

    remaining = budi.leases()
    assert [lease["tenantId"] for lease in remaining] == [second_id]
    assert remaining[0]["property"]["name"] == "Kos Anggrek"
    assert occupancy(owner, site.melati, "A1") == "vacant"
    again = world.login("budi.tenant@example.com")
    assert [lease["tenantId"] for lease in again.leases()] == [second_id]

    owner.delete(f"/tenants/{second_id}", expect=204)

    assert_error(budi.get("/me/leases"), 401, "ACCESS_TOKEN_INVALID")
    assert_error(
        raw_login(world, "budi.tenant@example.com", PASSWORD),
        401,
        "INVALID_CREDENTIALS",
    )
