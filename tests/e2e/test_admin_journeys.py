"""Scenarios of an Admin managing user accounts."""

from datetime import UTC, datetime, timedelta

import pytest

from e2e.e2e_auth import raw_login, token_in
from e2e.e2e_rent import assert_field_error
from e2e.e2e_world import MELATI

ACCOUNTS = "/user-accounts"


def error(response, status: int, code: str, field: str | None = None) -> dict:
    return assert_field_error(response, status, code, field)


def account_path(person_or_id) -> str:
    return f"{ACCOUNTS}/{getattr(person_or_id, 'user_id', person_or_id)}"


def edit(name: str, email: str, status: str = "active") -> dict:
    return {"name": name, "email": email, "status": status}


def if_match(version: int) -> dict:
    return {"If-Match": f'"{version}"'}


def listed(admin, **params) -> dict[str, dict]:
    """The listed accounts by email."""
    items = admin.read(ACCOUNTS, params=params or None)["items"]
    return {item["email"]: item for item in items}


def confirm_email_change(world, token: str):
    return world.client.post("/auth/email-changes", json={"token": token})


def parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text)


# Finding and reading accounts


def test_admin_finds_accounts_of_every_role_and_reads_what_each_is_linked_to(
    seeded_world, world
):
    owner, manager, budi = seeded_world.owner, seeded_world.manager, seeded_world.budi
    admin = world.admin()

    everyone = listed(admin)

    assert sorted(everyone) == [
        "ade@example.com",
        "budi@example.com",
        "mira@example.com",
        "rina@example.com",
        "sari@example.com",
    ]
    assert {
        email: (a["name"], a["role"], a["status"]) for email, a in everyone.items()
    } == {
        "ade@example.com": ("Ade Admin", "admin", "active"),
        "budi@example.com": ("Budi Tenant", "tenant", "active"),
        "mira@example.com": ("Mira Manager", "manager", "active"),
        "rina@example.com": ("Rina Owner", "owner", "active"),
        "sari@example.com": ("Sari Tenant", "tenant", "active"),
    }
    assert all(a["version"] == 1 for a in everyone.values())
    assert sorted(listed(admin, email="RINA")) == ["rina@example.com"]
    assert sorted(listed(admin, email="ri")) == ["rina@example.com", "sari@example.com"]
    assert sorted(listed(admin, email="@Example.COM")) == sorted(everyone)
    assert listed(admin, email="nobody") == {}
    assert sorted(listed(admin, role="tenant")) == [
        "budi@example.com",
        "sari@example.com",
    ]
    assert sorted(listed(admin, role="manager")) == ["mira@example.com"]
    assert sorted(listed(admin, role="admin")) == ["ade@example.com"]
    assert sorted(listed(admin, email="a", role="tenant")) == [
        "budi@example.com",
        "sari@example.com",
    ]
    assert listed(admin, email="mira", role="tenant") == {}
    assert "Dewi Tenant" not in {a["name"] for a in everyone.values()}

    rina = admin.read(account_path(owner))
    assert rina["email"] == "rina@example.com"
    assert rina["role"] == "owner"
    assert rina["status"] == "active"
    assert rina["version"] == 1
    assert rina["loginMethods"] == ["password"]
    assert rina["pendingEmail"] is None
    assert rina["pendingEmailExpiresAt"] is None
    assert rina["registeredAt"]
    assert rina["lastLoginAt"]
    assert sorted(p["name"] for p in rina["properties"]) == [
        "Kos Anggrek",
        "Kos Melati",
    ]
    assert rina["activeLeaseCount"] == 3
    assert rina["tenancies"] == []

    mira = admin.read(account_path(manager))
    assert [p["name"] for p in mira["properties"]] == [MELATI]
    assert mira["activeLeaseCount"] == 0
    assert mira["tenancies"] == []

    budi_detail = admin.read(account_path(budi))
    assert budi_detail["properties"] == []
    assert budi_detail["activeLeaseCount"] == 1
    assert budi_detail["tenancies"] == [
        {"propertyName": MELATI, "roomNumber": "A1", "leaseEndDate": None}
    ]

    ade = admin.read(account_path(admin))
    assert ade["role"] == "admin"
    assert ade["properties"] == []
    assert ade["activeLeaseCount"] == 0

    error(
        admin.get(account_path("6c1f5f7e-2a9d-4b0e-9f43-8d6a1c2b3e4f")),
        404,
        "USER_ACCOUNT_NOT_FOUND",
    )
    error(
        admin.get(account_path(seeded_world.dewi_token.id)),
        404,
        "USER_ACCOUNT_NOT_FOUND",
    )


def test_a_login_shows_as_the_last_login_without_changing_the_account(
    seeded_world, world
):
    owner = seeded_world.owner
    admin = world.admin()
    before = admin.read(account_path(owner))

    world.login(owner.email)

    after = admin.read(account_path(owner))
    assert parse_time(after["lastLoginAt"]) > parse_time(before["lastLoginAt"])
    assert after["version"] == before["version"]
    assert listed(admin)[owner.email]["version"] == before["version"]


def test_only_admins_can_use_the_account_endpoints(seeded_world, world):
    admin = world.admin()
    target = account_path(seeded_world.budi)
    body = edit("Budi Tenant", seeded_world.budi.email)

    for person in (seeded_world.owner, seeded_world.manager, seeded_world.budi):
        requests = [
            person.get(ACCOUNTS),
            person.get(target),
            person.put(target, json=body),
            person.delete(target),
        ]
        for response in requests:
            error(response, 403, "FORBIDDEN")
    anonymous = world.client.get(ACCOUNTS)
    assert anonymous.status_code == 401
    assert anonymous.json()["code"] == "ACCESS_TOKEN_INVALID"
    assert admin.read(target)["name"] == "Budi Tenant"
    assert seeded_world.budi.leases()


# Editing


def test_admin_renames_an_account_and_cannot_take_an_email_that_belongs_to_another(
    seeded_world, world
):
    budi = seeded_world.budi
    admin = world.admin()
    path = account_path(budi)

    renamed = admin.put(path, json=edit("Budi Santoso", budi.email))

    assert renamed.status_code == 200, renamed.text
    body = renamed.json()
    assert body["name"] == "Budi Santoso"
    assert body["email"] == "budi@example.com"
    assert body["version"] == 2
    assert body["status"] == "active"
    assert listed(admin)["budi@example.com"]["name"] == "Budi Santoso"
    assert budi.leases()

    for taken in ("sari@example.com", "SARI@Example.com", "ade@example.com"):
        response = admin.put(path, json=edit("Budi Pindah", taken))
        error(response, 409, "EMAIL_ALREADY_REGISTERED", "email")
    refused_status = admin.put(path, json=edit("Budi Santoso", budi.email, "deleted"))
    assert refused_status.status_code == 422
    assert refused_status.json()["code"] == "VALIDATION_FAILED"
    unchanged = admin.read(path)
    assert unchanged["name"] == "Budi Santoso"
    assert unchanged["email"] == "budi@example.com"
    assert unchanged["version"] == 2
    assert unchanged["pendingEmail"] is None
    assert world.stubs.mailbox.links == []
    assert world.stubs.mailbox.notices == []

    error(
        admin.put(
            account_path("6c1f5f7e-2a9d-4b0e-9f43-8d6a1c2b3e4f"),
            json=edit("Nobody", "nobody@example.com"),
        ),
        404,
        "USER_ACCOUNT_NOT_FOUND",
    )


def test_a_new_email_stays_pending_until_its_link_is_confirmed(seeded_world, world):
    owner = seeded_world.owner
    admin = world.admin()
    path = account_path(owner)

    response = admin.put(path, json=edit("Rina Owner", "Rina.Baru@Example.com"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == "rina@example.com"
    assert body["pendingEmail"] == "rina.baru@example.com"
    expires = parse_time(body["pendingEmailExpiresAt"]) - datetime.now(UTC)
    assert timedelta(days=6, hours=23) < expires <= timedelta(days=7)
    mailbox = world.stubs.mailbox
    assert [to for to, _ in mailbox.links] == ["rina.baru@example.com"]
    assert mailbox.notices == [("rina@example.com", "rina.baru@example.com")]
    assert listed(admin)["rina@example.com"]["name"] == "Rina Owner"
    assert owner.get("/properties").status_code == 200
    assert world.login("rina@example.com").user_id == owner.user_id
    assert (
        raw_login(world, "rina.baru@example.com", "correct horse battery").status_code
        == 401
    )

    token = token_in(mailbox.links[0][1])
    confirmed = confirm_email_change(world, token)

    assert confirmed.status_code in (200, 204), confirmed.text
    detail = admin.read(path)
    assert detail["email"] == "rina.baru@example.com"
    assert detail["pendingEmail"] is None
    assert detail["pendingEmailExpiresAt"] is None
    assert world.login("rina.baru@example.com").user_id == owner.user_id
    error(
        raw_login(world, "rina@example.com", "correct horse battery"),
        401,
        "INVALID_CREDENTIALS",
    )
    error(confirm_email_change(world, token), 409, "EMAIL_CHANGE_USED")
    error(confirm_email_change(world, "no-such-token"), 404, "EMAIL_CHANGE_NOT_FOUND")


def test_a_newer_request_or_the_current_email_cancels_the_pending_change(
    seeded_world, world
):
    owner = seeded_world.owner
    admin = world.admin()
    path = account_path(owner)
    mailbox = world.stubs.mailbox

    admin.put(path, json=edit("Rina Owner", "first@example.com"), expect=200)
    admin.put(path, json=edit("Rina Owner", "second@example.com"), expect=200)

    assert admin.read(path)["pendingEmail"] == "second@example.com"
    first, second = (token_in(url) for _, url in mailbox.links)
    error(confirm_email_change(world, first), 409, "EMAIL_CHANGE_USED")

    cancelled = admin.put(path, json=edit("Rina Owner", "RINA@example.com"))

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["pendingEmail"] is None
    assert cancelled.json()["pendingEmailExpiresAt"] is None
    assert len(mailbox.links) == 2
    assert len(mailbox.notices) == 2
    error(confirm_email_change(world, second), 409, "EMAIL_CHANGE_USED")
    assert admin.read(path)["email"] == "rina@example.com"


def test_a_pending_email_that_another_account_registers_first_cannot_be_confirmed(
    seeded_world, world
):
    owner = seeded_world.owner
    admin = world.admin()
    path = account_path(owner)
    admin.put(path, json=edit("Rina Owner", "contested@example.com"), expect=200)
    token = token_in(world.stubs.mailbox.links[0][1])

    world.owner_signs_up(email="contested@example.com", name="Other Owner")

    error(confirm_email_change(world, token), 409, "EMAIL_ALREADY_REGISTERED", "email")
    detail = admin.read(path)
    assert detail["email"] == "rina@example.com"
    assert detail["pendingEmail"] == "contested@example.com"
    error(confirm_email_change(world, token), 409, "EMAIL_ALREADY_REGISTERED", "email")


def test_deactivating_an_account_ends_its_sessions_and_reactivating_lets_it_back_in(
    seeded_world, world
):
    owner, budi = seeded_world.owner, seeded_world.budi
    admin = world.admin()
    path = account_path(budi)
    phone = world.login(budi.email)
    assert phone.leases()

    deactivated = admin.put(path, json=edit("Budi Tenant", budi.email, "inactive"))

    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["status"] == "inactive"
    assert deactivated.json()["version"] == 2
    assert listed(admin)[budi.email]["status"] == "inactive"
    for session in (budi, phone):
        refused = session.get("/me/leases")
        error(refused, 401, "ACCESS_TOKEN_INVALID")
    refresh = world.client.post(
        "/auth/refresh", json={"refreshToken": budi.refresh_token}
    )
    assert refresh.status_code == 401
    error(
        raw_login(world, budi.email, "correct horse battery"), 403, "ACCOUNT_INACTIVE"
    )
    error(raw_login(world, budi.email, "wrong password"), 401, "INVALID_CREDENTIALS")
    assert sorted(listed(admin, role="tenant")) == [
        "budi@example.com",
        "sari@example.com",
    ]

    world.clock.set(world.clock.today.replace(month=11, day=1))
    world.clock.run_daily_jobs()
    bills = [b for b in owner.rent_bills() if b["tenant"]["name"] == "Budi Tenant"]
    assert sorted(b["periodStart"] for b in bills) == ["2026-10-01", "2026-11-01"]
    assert "Budi Tenant" in [t["name"] for t in owner.tenants(seeded_world.melati)]

    reactivated = admin.put(path, json=edit("Budi Tenant", budi.email, "active"))

    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["status"] == "active"
    assert reactivated.json()["version"] == 3
    back = world.login(budi.email)
    assert [lease["room"]["number"] for lease in back.leases()] == ["A1"]
    assert len(back.rent_bills()) == 2
    assert budi.get("/me/leases").status_code == 401


def test_an_admin_cannot_deactivate_or_delete_themselves_but_can_manage_other_admins(
    world,
):
    admin = world.admin()
    colleague = world.admin(email="omar.admin@example.com", name="Omar Admin")
    own = account_path(admin)

    error(
        admin.put(own, json=edit("Ade Admin", admin.email, "inactive")),
        409,
        "CANNOT_MODIFY_OWN_ACCOUNT",
    )
    error(admin.delete(own), 409, "CANNOT_MODIFY_OWN_ACCOUNT")
    assert admin.read(own)["status"] == "active"
    assert admin.read(own)["version"] == 1
    assert admin.get("/me/sessions").status_code == 200

    renamed = admin.put(own, json=edit("Ade Administrator", admin.email))
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Ade Administrator"
    own_email = admin.put(own, json=edit("Ade Administrator", "ade.baru@example.com"))
    assert own_email.status_code == 200, own_email.text
    assert own_email.json()["pendingEmail"] == "ade.baru@example.com"
    assert own_email.json()["email"] == "ade@example.com"
    assert world.stubs.mailbox.links[-1][0] == "ade.baru@example.com"

    other = account_path(colleague)
    deactivated = admin.put(other, json=edit("Omar Admin", colleague.email, "inactive"))
    assert deactivated.status_code == 200, deactivated.text
    assert colleague.get("/me/sessions").status_code == 401
    error(
        raw_login(world, colleague.email, "correct horse battery"),
        403,
        "ACCOUNT_INACTIVE",
    )

    assert admin.delete(other).status_code == 204
    assert colleague.email not in listed(admin)
    assert listed(admin, includeDeleted="true")[colleague.email]["status"] == "deleted"
    error(admin.delete(other), 409, "USER_ACCOUNT_DELETED")


# Deleting


def test_a_tenant_with_an_active_lease_cannot_be_deleted_until_the_lease_ends(
    seeded_world, world
):
    owner, budi, sari = seeded_world.owner, seeded_world.budi, seeded_world.sari
    admin = world.admin()

    error(admin.delete(account_path(budi)), 409, "TENANT_HAS_ACTIVE_LEASE")
    error(admin.delete(account_path(sari)), 409, "TENANT_HAS_ACTIVE_LEASE")

    assert budi.leases()
    assert listed(admin)[budi.email]["status"] == "active"
    record = next(
        t for t in owner.tenants(seeded_world.melati) if t["name"] == "Budi Tenant"
    )
    assert owner.delete(f"/tenants/{record['id']}").status_code == 204

    assert budi.get("/me/leases").status_code == 401
    assert budi.email not in listed(admin)
    assert listed(admin, includeDeleted="true")[budi.email]["status"] == "deleted"
    error(admin.delete(account_path(budi)), 409, "USER_ACCOUNT_DELETED")
    assert sari.leases()


def test_deleting_an_owner_waits_for_the_leases_to_end_then_archives_everything(
    seeded_world, world
):
    owner, manager = seeded_world.owner, seeded_world.manager
    budi, sari = seeded_world.budi, seeded_world.sari
    admin = world.admin()
    path = account_path(owner)

    error(admin.delete(path), 409, "OWNER_HAS_ACTIVE_LEASE")

    assert owner.get("/properties").status_code == 200
    assert admin.read(path)["status"] == "active"
    assert len(owner.properties()) == 2
    for melati_or_anggrek in (seeded_world.melati, seeded_world.anggrek):
        for tenant in owner.tenants(melati_or_anggrek):
            owner.delete(f"/tenants/{tenant['id']}", expect=204)
    assert budi.email not in listed(admin)
    assert sari.email not in listed(admin)

    deleted = admin.delete(path)

    assert deleted.status_code == 204
    error(owner.get("/properties"), 401, "ACCESS_TOKEN_INVALID")
    error(
        raw_login(world, owner.email, "correct horse battery"),
        401,
        "INVALID_CREDENTIALS",
    )
    assert manager.properties() == []
    assert owner.email not in listed(admin)
    assert owner.email not in listed(admin, role="owner")
    with_deleted = listed(admin, role="owner", includeDeleted="true")
    assert list(with_deleted) == [owner.email]
    assert with_deleted[owner.email]["status"] == "deleted"
    detail = admin.read(path)
    assert detail["status"] == "deleted"
    assert detail["properties"] == []
    error(
        admin.put(path, json=edit("Rina Owner", owner.email)),
        409,
        "USER_ACCOUNT_DELETED",
    )
    error(
        admin.put(path, json=edit("Rina Owner", owner.email), headers=if_match(99)),
        409,
        "USER_ACCOUNT_DELETED",
    )
    error(admin.delete(path), 409, "USER_ACCOUNT_DELETED")

    registration = world.client.post(
        "/auth/register",
        json={
            "name": "Rina Again",
            "email": owner.email,
            "password": "correct horse battery",
            "device": {"name": "Pixel 8", "platform": "Android 14"},
        },
    )
    error(registration, 409, "EMAIL_ALREADY_REGISTERED", "email")
    error(
        admin.put(account_path(manager), json=edit("Mira Manager", owner.email)),
        409,
        "EMAIL_ALREADY_REGISTERED",
        "email",
    )


def test_deleting_a_manager_revokes_the_assignments_and_ends_the_sessions(
    seeded_world, world
):
    owner, manager = seeded_world.owner, seeded_world.manager
    admin = world.admin()
    assert [m["name"] for m in owner.managers()] == ["Mira Manager"]

    deleted = admin.delete(account_path(manager))

    assert deleted.status_code == 204
    error(manager.get("/properties"), 401, "ACCESS_TOKEN_INVALID")
    error(
        raw_login(world, manager.email, "correct horse battery"),
        401,
        "INVALID_CREDENTIALS",
    )
    assert owner.managers() == []
    assert owner.read(f"/properties/{seeded_world.melati['id']}")["managers"] == []
    assert len(owner.complaints()) == 1
    assert manager.email not in listed(admin)
    assert listed(admin, includeDeleted="true")[manager.email]["status"] == "deleted"


# Concurrent edits


def test_two_admin_devices_editing_one_account_cannot_overwrite_each_other(
    seeded_world, world
):
    owner = seeded_world.owner
    phone = world.admin()
    laptop = world.login(phone.email)
    path = account_path(owner)
    mailbox = world.stubs.mailbox
    seen_on_phone, seen_on_laptop = phone.read(path), laptop.read(path)
    version = seen_on_phone["version"]
    assert seen_on_laptop["version"] == version

    first = phone.put(
        path,
        json=edit("Rina Pemilik", owner.email),
        headers=if_match(version),
    )

    assert first.status_code == 200, first.text
    assert first.json()["version"] == version + 1
    assert first.json()["name"] == "Rina Pemilik"

    stale = laptop.put(
        path,
        json=edit("Rina Lama", "rina.lama@example.com", "inactive"),
        headers=if_match(version),
    )

    error(stale, 409, "RESOURCE_VERSION_CONFLICT")
    reloaded = laptop.read(path)
    assert reloaded["version"] == version + 1
    assert reloaded["name"] == "Rina Pemilik"
    assert reloaded["status"] == "active"
    assert reloaded["pendingEmail"] is None
    assert mailbox.links == []
    assert mailbox.notices == []
    assert owner.get("/properties").status_code == 200

    retried = laptop.put(
        path,
        json=edit("Rina Pemilik", "rina.lama@example.com"),
        headers=if_match(reloaded["version"]),
    )

    assert retried.status_code == 200, retried.text
    assert retried.json()["version"] == version + 2
    assert retried.json()["pendingEmail"] == "rina.lama@example.com"
    assert [to for to, _ in mailbox.links] == ["rina.lama@example.com"]
    assert [to for to, _ in mailbox.notices] == ["rina@example.com"]

    blind = phone.put(path, json=edit("Rina Tanpa Header", owner.email))

    assert blind.status_code == 200, blind.text
    assert blind.json()["version"] == version + 3
    assert blind.json()["name"] == "Rina Tanpa Header"
    assert blind.json()["pendingEmail"] is None

    same_values = phone.put(path, json=edit("Rina Tanpa Header", owner.email))
    assert same_values.status_code == 200, same_values.text
    assert same_values.json()["version"] == version + 4
    assert same_values.json()["name"] == "Rina Tanpa Header"

    world.login(owner.email)
    assert phone.read(path)["version"] == version + 4
    assert listed(phone)[owner.email]["version"] == version + 4


@pytest.mark.parametrize("header", ["3", '"abc"', 'W/"3"', '""'])
def test_a_version_that_is_not_a_quoted_whole_number_is_refused_before_anything_changes(
    seeded_world, world, header
):
    owner = seeded_world.owner
    admin = world.admin()
    path = account_path(owner)

    response = admin.put(
        path,
        json=edit("Rina Lain", owner.email),
        headers={"If-Match": header},
    )

    error(response, 422, "VALIDATION_FAILED", "ifMatch")
    unchanged = admin.read(path)
    assert unchanged["name"] == "Rina Owner"
    assert unchanged["version"] == 1
