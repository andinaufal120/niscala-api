"""Scenarios of inviting, activating and accepting Tenants and Managers."""

from e2e.e2e_auth import (
    activation_body,
    assert_error,
    expire_invitation,
    person_from,
    preview,
    raw_login,
)
from e2e.e2e_people import EMERGENCY_CONTACTS, PASSWORD, token_of


def tenant_kinds(notifications: list[dict]) -> list[str]:
    return [n["type"] for n in notifications]


def regenerate(owner, record_id: str, kind: str = "tenants"):
    """Regenerate the invitation link of a tenant or manager and return its token."""
    response = owner.post(f"/{kind}/{record_id}/invitation")
    assert response.status_code in (200, 201), response.text
    return token_of({"id": record_id, "invitation": response.json()})


def test_tenant_is_invited_activates_confirms_the_email_and_logs_in(world, database):
    owner = world.owner_signs_up(email="rina@example.com", name="Rina Owner")
    melati = owner.add_property("Kos Melati", address="Jl. Melati 5")
    room = owner.add_room(melati, "A1")
    token = owner.add_tenant(room, "Budi Tenant", "081211111111")

    previewed = preview(world, token)
    assert previewed.status_code == 200, previewed.text
    body = previewed.json()
    assert body["status"] == "valid"
    assert body["role"] == "tenant"
    assert body["inviterName"] == "Rina Owner"
    assert body["properties"] == [{"name": "Kos Melati", "address": "Jl. Melati 5"}]
    assert body["roomNumber"] == "A1"
    assert body["name"] == "Budi Tenant"
    assert body["emergencyContactsRequired"] is True

    one_contact = world.client.post(
        "/invitations/activations/password",
        json=activation_body(
            token,
            name="Budi Tenant",
            email="budi@example.com",
            password=PASSWORD,
            emergencyContacts=EMERGENCY_CONTACTS[:1],
        ),
    )
    assert_error(one_contact, 422, "VALIDATION_FAILED")
    assert preview(world, token).json()["status"] == "valid"

    activated = world.client.post(
        "/invitations/activations/password",
        json=activation_body(
            token,
            name="Budi Santoso",
            email="budi@example.com",
            password=PASSWORD,
            emergencyContacts=EMERGENCY_CONTACTS,
        ),
    )
    budi = person_from(world, activated, password=PASSWORD)
    assert budi.role == "tenant"
    assert budi.name == "Budi Santoso"
    assert budi.email == "budi@example.com"
    assert budi.read("/me")["emailVerified"] is False
    assert_error(budi.get("/me/leases"), 403, "EMAIL_NOT_VERIFIED")

    budi.confirm_email()

    leases = budi.leases()
    assert len(leases) == 1
    assert leases[0]["room"]["number"] == "A1"
    assert leases[0]["property"]["name"] == "Kos Melati"
    assert "tenantActivated" in tenant_kinds(owner.notifications())
    listed = owner.read(f"/tenants/{token.id}")
    assert listed["emergencyContacts"] == EMERGENCY_CONTACTS
    assert listed["email"] == "budi@example.com"

    budi.logout()
    again = world.login("budi@example.com")
    assert again.user_id == budi.user_id
    assert len(again.leases()) == 1

    used = preview(world, token)
    assert used.status_code == 200
    assert used.json()["status"] == "used"
    second_use = world.client.post(
        "/invitations/activations/password",
        json=activation_body(
            token,
            name="Budi Santoso",
            email="other@example.com",
            password=PASSWORD,
            emergencyContacts=EMERGENCY_CONTACTS,
        ),
    )
    assert_error(second_use, 409, "INVITATION_USED")
    assert_error(
        raw_login(world, "other@example.com", PASSWORD), 401, "INVALID_CREDENTIALS"
    )


def test_a_regenerated_link_replaces_the_old_one_and_an_expired_link_is_refused(
    world, database
):
    owner = world.owner_signs_up()
    melati = owner.add_property("Kos Melati")
    room = owner.add_room(melati, "A1")
    first = owner.add_tenant(room, "Budi Tenant", "081211111111")

    second = regenerate(owner, first.id)

    assert second != first
    assert preview(world, first).json()["status"] == "used"
    stale = world.client.post(
        "/invitations/activations/password",
        json=activation_body(
            first,
            name="Budi Tenant",
            email="budi@example.com",
            password=PASSWORD,
            emergencyContacts=EMERGENCY_CONTACTS,
        ),
    )
    assert_error(stale, 409, "INVITATION_USED")
    assert preview(world, second).json()["status"] == "valid"

    expire_invitation(database, second)

    expired = preview(world, second)
    assert expired.status_code == 200
    assert expired.json()["status"] == "expired"
    refused = world.client.post(
        "/invitations/activations/password",
        json=activation_body(
            second,
            name="Budi Tenant",
            email="budi@example.com",
            password=PASSWORD,
            emergencyContacts=EMERGENCY_CONTACTS,
        ),
    )
    assert_error(refused, 409, "INVITATION_EXPIRED")
    detail = owner.read(f"/tenants/{first.id}")
    assert detail["invitation"]["expired"] is True

    third = regenerate(owner, first.id)

    budi = world.tenant_activates(third, email="budi@example.com")
    assert len(budi.leases()) == 1
    assert_error(
        owner.post(f"/tenants/{first.id}/invitation"), 409, "TENANT_ALREADY_ACTIVE"
    )


def test_an_unknown_invitation_link_is_not_found_everywhere(world):
    world.owner_signs_up()

    assert_error(preview(world, "nonsense"), 404, "INVITATION_NOT_FOUND")
    assert_error(
        world.client.post(
            "/invitations/activations/password",
            json=activation_body(
                "nonsense",
                name="Budi Tenant",
                email="budi@example.com",
                password=PASSWORD,
                emergencyContacts=EMERGENCY_CONTACTS,
            ),
        ),
        404,
        "INVITATION_NOT_FOUND",
    )


def test_activating_with_an_email_that_is_taken_is_refused_and_keeps_the_link(world):
    world.owner_signs_up(email="rina@example.com")
    owner = world.login("rina@example.com")
    melati = owner.add_property("Kos Melati")
    room = owner.add_room(melati, "A1")
    token = owner.add_tenant(room, "Budi Tenant", "081211111111")

    refused = world.client.post(
        "/invitations/activations/password",
        json=activation_body(
            token,
            name="Budi Tenant",
            email="RINA@example.com",
            password=PASSWORD,
            emergencyContacts=EMERGENCY_CONTACTS,
        ),
    )

    body = assert_error(refused, 409, "EMAIL_ALREADY_REGISTERED")
    assert body["field"] == "email"
    assert preview(world, token).json()["status"] == "valid"
    assert world.tenant_activates(token, email="budi@example.com").leases()


def test_a_deleted_tenant_invitation_is_not_found(world):
    owner = world.owner_signs_up()
    melati = owner.add_property("Kos Melati")
    room = owner.add_room(melati, "A1")
    token = owner.add_tenant(room, "Budi Tenant", "081211111111")

    owner.delete(f"/tenants/{token.id}", expect=204)

    assert_error(preview(world, token), 404, "INVITATION_NOT_FOUND")


def test_manager_is_invited_for_one_property_activates_and_sees_only_that_property(
    world,
):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    melati = owner.add_property("Kos Melati", address="Jl. Melati 5")
    owner.add_property("Kos Anggrek", address="Jl. Anggrek 7")
    token = owner.add_manager([melati], name="Mira Manager", phone="081200000001")

    body = preview(world, token).json()
    assert body["status"] == "valid"
    assert body["role"] == "manager"
    assert body["name"] == "Mira Manager"
    assert body["inviterName"] == "Rina Owner"
    assert body["properties"] == [{"name": "Kos Melati", "address": "Jl. Melati 5"}]
    assert body["emergencyContactsRequired"] is False
    assert owner.read(f"/managers/{token.id}")["invitation"]["url"]

    manager = world.manager_activates(token, email="mira@example.com")

    assert [p["name"] for p in manager.properties()] == ["Kos Melati"]
    assert "managerActivated" in tenant_kinds(owner.notifications())
    assert_error(
        manager.get(f"/managers/{token.id}"),
        403,
        "FORBIDDEN",
    )
    assert owner.read(f"/managers/{token.id}")["email"] == "mira@example.com"
    again = world.client.post(
        "/invitations/activations/password",
        json=activation_body(
            token, name="Mira", email="mira2@example.com", password=PASSWORD
        ),
    )
    assert_error(again, 409, "INVITATION_USED")
    assert_error(
        owner.post(f"/managers/{token.id}/invitation"), 409, "MANAGER_ALREADY_ACTIVE"
    )


def test_an_existing_manager_accepts_an_invitation_of_another_owner(world):
    first_owner = world.owner_signs_up(email="rina@example.com", name="Rina Owner")
    melati = first_owner.add_property("Kos Melati")
    manager = world.manager_activates(
        first_owner.add_manager([melati], name="Mira Manager"), email="mira@example.com"
    )
    second_owner = world.owner_signs_up(email="omar@example.com", name="Omar Owner")
    kenanga = second_owner.add_property("Kos Kenanga", address="Jl. Kenanga 9")
    token = second_owner.add_manager([kenanga], name="Mira M", phone="081200000002")
    assert [p["name"] for p in manager.properties()] == ["Kos Melati"]

    checked = manager.post("/invitations/acceptance-previews", json={"token": token})
    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert body["canAccept"] is True
    assert body["blocker"] is None
    assert body["accountName"] == "Mira Manager"
    assert body["accountEmail"] == "mira@example.com"
    assert body["accountRole"] == "manager"
    assert body["invitation"]["status"] == "valid"
    assert body["invitation"]["inviterName"] == "Omar Owner"
    assert [p["name"] for p in body["invitation"]["properties"]] == ["Kos Kenanga"]

    accepted = manager.post("/invitations/acceptances", json={"token": token})
    assert accepted.status_code < 300, accepted.text

    assert sorted(p["name"] for p in manager.properties()) == [
        "Kos Kenanga",
        "Kos Melati",
    ]
    assert "managerActivated" in tenant_kinds(second_owner.notifications())
    assert [m["id"] for m in second_owner.managers()] == [token.id]
    assert second_owner.read(f"/managers/{token.id}")["email"] == "mira@example.com"
    assert len(first_owner.managers()) == 1

    again = manager.post("/invitations/acceptances", json={"token": token})
    assert_error(again, 409, "INVITATION_USED")
    used_preview = manager.post(
        "/invitations/acceptance-previews", json={"token": token}
    )
    assert used_preview.status_code == 200
    assert used_preview.json()["canAccept"] is False
    assert used_preview.json()["invitation"]["status"] == "used"


def test_a_manager_cannot_accept_a_second_invitation_from_an_owner_they_work_for(
    world,
):
    owner = world.owner_signs_up()
    melati = owner.add_property("Kos Melati")
    owner.subscribe("basic")
    anggrek = owner.add_property("Kos Anggrek")
    manager = world.manager_activates(
        owner.add_manager([melati], name="Mira Manager"), email="mira@example.com"
    )
    token = owner.add_manager([anggrek], name="Mira Again", phone="081200000009")

    refused = manager.post("/invitations/acceptances", json={"token": token})

    assert_error(refused, 409, "MANAGER_ALREADY_ADDED")
    assert [p["name"] for p in manager.properties()] == ["Kos Melati"]
    assert preview(world, token).json()["status"] == "valid"


def test_an_account_of_another_role_cannot_accept_a_manager_invitation(world):
    owner = world.owner_signs_up(email="rina@example.com")
    melati = owner.add_property("Kos Melati")
    room = owner.add_room(melati, "A1")
    budi = world.tenant_activates(
        owner.add_tenant(room, "Budi Tenant", "081211111111"), email="budi@example.com"
    )
    token = owner.add_manager([melati], name="Mira Manager")

    checked = budi.post("/invitations/acceptance-previews", json={"token": token})
    assert checked.status_code == 200, checked.text
    assert checked.json()["canAccept"] is False
    assert checked.json()["blocker"] == "roleMismatch"
    assert checked.json()["accountRole"] == "tenant"

    refused = budi.post("/invitations/acceptances", json={"token": token})

    assert_error(refused, 409, "INVITATION_ROLE_MISMATCH")
    assert preview(world, token).json()["status"] == "valid"
    assert world.manager_activates(token, email="mira@example.com").properties()


def test_an_owner_cannot_accept_a_tenant_invitation(world):
    owner = world.owner_signs_up(email="rina@example.com")
    melati = owner.add_property("Kos Melati")
    room = owner.add_room(melati, "A1")
    token = owner.add_tenant(room, "Budi Tenant", "081211111111")

    refused = owner.post(
        "/invitations/acceptances",
        json={"token": token, "emergencyContacts": EMERGENCY_CONTACTS},
    )

    assert_error(refused, 409, "INVITATION_ROLE_MISMATCH")
    assert owner.properties()


def test_acceptance_checks_the_link_before_the_role(world, database):
    owner = world.owner_signs_up(email="rina@example.com")
    melati = owner.add_property("Kos Melati")
    room = owner.add_room(melati, "A1")
    budi = world.tenant_activates(
        owner.add_tenant(room, "Budi Tenant", "081211111111"), email="budi@example.com"
    )
    token = owner.add_manager([melati], name="Mira Manager")
    expire_invitation(database, token)

    expired = budi.post("/invitations/acceptances", json={"token": token})

    assert_error(expired, 409, "INVITATION_EXPIRED")
    assert_error(
        budi.post("/invitations/acceptances", json={"token": "nonsense"}),
        404,
        "INVITATION_NOT_FOUND",
    )


def test_one_tenant_account_rents_in_two_places_from_two_owners(world):
    first_owner = world.owner_signs_up(email="rina@example.com", name="Rina Owner")
    melati = first_owner.add_property("Kos Melati", address="Jl. Melati 5")
    first_room = first_owner.add_room(melati, "A1", base_rate=1_200_000)
    budi = world.tenant_activates(
        first_owner.add_tenant(first_room, "Budi Tenant", "081211111111"),
        email="budi@example.com",
    )
    second_owner = world.owner_signs_up(email="omar@example.com", name="Omar Owner")
    kenanga = second_owner.add_property("Kos Kenanga", address="Jl. Kenanga 9")
    second_room = second_owner.add_room(kenanga, "K7", base_rate=900_000)
    token = second_owner.add_tenant(second_room, "Budi T", "081299999999")

    checked = budi.post("/invitations/acceptance-previews", json={"token": token})
    assert checked.status_code == 200, checked.text
    assert checked.json()["canAccept"] is True
    assert checked.json()["invitation"]["roomNumber"] == "K7"
    assert checked.json()["invitation"]["emergencyContactsRequired"] is True

    one_contact = budi.post(
        "/invitations/acceptances",
        json={"token": token, "emergencyContacts": EMERGENCY_CONTACTS[:1]},
    )
    assert_error(one_contact, 422, "VALIDATION_FAILED")
    accepted = budi.post(
        "/invitations/acceptances",
        json={"token": token, "emergencyContacts": EMERGENCY_CONTACTS},
    )
    assert accepted.status_code < 300, accepted.text

    leases = budi.leases()
    assert [
        (lease["property"]["name"], lease["room"]["number"]) for lease in leases
    ] == [
        ("Kos Kenanga", "K7"),
        ("Kos Melati", "A1"),
    ]
    assert {lease["rent"] for lease in leases} == {1_200_000, 900_000}
    assert budi.name == "Budi Tenant"
    assert budi.read("/me")["name"] == "Budi Tenant"
    assert [t["name"] for t in second_owner.tenants(kenanga)] == ["Budi Tenant"]
    assert "tenantActivated" in tenant_kinds(second_owner.notifications())
    assert second_owner.read(f"/tenants/{token.id}")["phone"] == "081299999999"
    assert len(first_owner.tenants(melati)) == 1

    assert_error(
        budi.post("/invitations/acceptances", json={"token": token}),
        409,
        "INVITATION_USED",
    )
    assert len(budi.leases()) == 2
    assert world.login("budi@example.com", PASSWORD).leases() == leases
