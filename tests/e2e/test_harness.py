"""Tests of the end-to-end harness itself: its steps, stubs, clock and seed."""

from datetime import date
from uuid import UUID

import pytest

from e2e.e2e_people import (
    BANK_ACCOUNT,
    PASSWORD,
    Admin,
    InviteToken,
    Manager,
    Owner,
    Tenant,
    file_receipt,
    jpg_receipt,
    png_receipt,
)
from e2e.e2e_world import ANGGREK, BUDI_EMAIL, MELATI, OWNER_EMAIL, Clock


def names(items: list[dict]) -> list[str]:
    return sorted(item["name"] for item in items)


# Signing up and signing in


def test_owner_signs_up_with_a_confirmed_email_and_a_usable_session(world):
    owner = world.owner_signs_up(email="rina@example.com", name="Rina Owner")

    assert isinstance(owner, Owner)
    assert owner.email == "rina@example.com"
    assert owner.name == "Rina Owner"
    assert isinstance(owner.user_id, UUID)
    assert isinstance(owner.session_id, UUID)
    assert owner.properties() == []
    world.stubs.assert_code_emailed("rina@example.com")


def test_owner_who_skips_confirmation_cannot_add_a_property(world):
    owner = world.owner_signs_up(verified=False)

    response = owner.post("/properties", json={"name": "Kos Melati", "address": "x"})

    assert response.status_code == 403
    assert response.json()["code"] == "EMAIL_NOT_VERIFIED"


def test_requests_without_a_session_are_refused(world):
    world.owner_signs_up()

    assert world.client.get("/properties").status_code == 401


def test_person_sends_its_own_bearer_token_on_every_verb(world):
    owner = world.owner_signs_up()

    assert owner.get("/properties").status_code == 200
    assert owner.post("/properties", json={}).status_code == 422
    assert owner.put("/me/push-token", json={"token": "t"}).status_code == 204
    other = world.login(owner.email)
    assert owner.delete(f"/me/sessions/{other.session_id}").status_code == 204
    assert other.get("/properties").status_code == 401
    assert owner.patch("/properties").status_code in (401, 405)


def test_refresh_keeps_the_session_working_and_retires_the_old_refresh_token(world):
    owner = world.owner_signs_up()
    old_refresh_token = owner.refresh_token
    old_session_id = owner.session_id

    owner.refresh()

    assert owner.refresh_token != old_refresh_token
    assert owner.session_id == old_session_id
    assert owner.properties() == []
    again = world.client.post("/auth/refresh", json={"refreshToken": old_refresh_token})
    assert again.status_code != 200


def test_login_starts_a_new_session_of_the_same_account(world):
    first = world.owner_signs_up()

    second = world.login(first.email, PASSWORD)

    assert isinstance(second, Owner)
    assert second.user_id == first.user_id
    assert second.session_id != first.session_id


def test_login_with_a_wrong_password_fails_the_step_with_the_answer(world):
    owner = world.owner_signs_up()

    with pytest.raises(AssertionError) as failure:
        world.login(owner.email, "not the password")

    message = str(failure.value)
    assert "login" in message
    assert "expected 200" in message
    assert "POST /auth/login" in message
    assert "INVALID_CREDENTIALS" in message


def test_admin_is_signed_in_through_the_login_endpoint(world):
    admin = world.admin()

    assert isinstance(admin, Admin)
    assert admin.email == "ade@example.com"
    assert admin.get("/me/sessions").status_code == 200
    assert admin.get("/properties").status_code == 403


def test_logout_ends_the_session(world):
    owner = world.owner_signs_up()

    owner.logout()

    assert owner.get("/properties").status_code == 401


# Steps that build the world


def test_owner_adds_properties_with_and_without_a_bank_account(world):
    owner = world.owner_signs_up()
    owner.subscribe("basic")

    with_bank = owner.add_property("Kos Melati", bank_account=BANK_ACCOUNT)
    without = owner.add_property("Kos Anggrek")

    assert with_bank["bankAccount"] == BANK_ACCOUNT
    assert without["bankAccount"] is None
    assert names(owner.properties()) == ["Kos Anggrek", "Kos Melati"]


def test_owner_adds_rooms_to_a_property(world):
    owner = world.owner_signs_up()
    prop = owner.add_property("Kos Melati")

    room = owner.add_room(
        prop, "A1", base_rate=900_000, facilities=["ac"], length_m=3, width_m=4
    )

    assert room["number"] == "A1"
    assert room["baseRate"] == 900_000
    assert room["propertyId"] == prop["id"]
    assert room["occupancy"] == "vacant"
    assert [r["number"] for r in owner.rooms(prop)] == ["A1"]


def test_owner_adds_a_tenant_and_gets_the_invitation_token(world):
    owner = world.owner_signs_up()
    prop = owner.add_property("Kos Melati")
    room = owner.add_room(prop, "A1")

    token = owner.add_tenant(
        room,
        "Budi Tenant",
        "081211111111",
        lease={"startDate": date(2026, 10, 1), "gracePeriodDays": 3},
    )

    assert isinstance(token, InviteToken)
    assert token == token.record["invitation"]["url"].rsplit("/", 1)[-1]
    assert token.id == token.record["id"]
    assert token.record["accountStatus"] == "notActivated"
    assert token.record["lease"]["startDate"] == "2026-10-01"
    assert token.record["lease"]["gracePeriodDays"] == 3
    assert token.record["lease"]["rent"] == 1_000_000
    preview = world.client.post("/invitations/previews", json={"token": token})
    assert preview.json()["status"] == "valid"


def test_tenant_activates_with_the_invitation_and_gets_a_usable_session(world):
    owner = world.owner_signs_up()
    room = owner.add_room(owner.add_property("Kos Melati"), "A1")
    token = owner.add_tenant(room, "Budi Tenant", "081211111111")

    tenant = world.tenant_activates(token, email="budi@example.com")

    assert isinstance(tenant, Tenant)
    assert tenant.email == "budi@example.com"
    assert tenant.name == "Budi Tenant"
    assert [lease["room"]["number"] for lease in tenant.leases()] == ["A1"]
    assert owner.tenants(room["propertyId"])[0]["accountStatus"] == "active"
    world.stubs.assert_code_emailed("budi@example.com")


def test_tenant_activation_defaults_the_email_to_the_invited_name(world):
    owner = world.owner_signs_up()
    room = owner.add_room(owner.add_property("Kos Melati"), "A1")
    token = owner.add_tenant(room, "Budi Tenant", "081211111111")

    tenant = world.tenant_activates(token)

    assert tenant.email == "budi.tenant@example.com"


def test_an_invitation_cannot_be_activated_twice(world):
    owner = world.owner_signs_up()
    room = owner.add_room(owner.add_property("Kos Melati"), "A1")
    token = owner.add_tenant(room, "Budi Tenant", "081211111111")
    world.tenant_activates(token, email="budi@example.com")

    with pytest.raises(AssertionError, match="tenant_activates.*used"):
        world.tenant_activates(token, email="other@example.com")


def test_activating_an_unknown_invitation_fails_the_step_with_the_answer(world):
    with pytest.raises(AssertionError) as failure:
        world.tenant_activates("no-such-token")

    message = str(failure.value)
    assert "tenant_activates" in message
    assert "expected 200" in message
    assert "404" in message
    assert "INVITATION_NOT_FOUND" in message


def test_a_manager_invitation_is_not_a_tenant_invitation(world):
    owner = world.owner_signs_up()
    prop = owner.add_property("Kos Melati")
    token = owner.add_manager([prop])

    with pytest.raises(AssertionError, match="tenant_activates.*manager"):
        world.tenant_activates(token)


def test_owner_adds_a_manager_who_activates_and_sees_only_assigned_properties(world):
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    assigned = owner.add_property("Kos Melati")
    owner.add_property("Kos Anggrek")

    token = owner.add_manager([assigned], name="Mira Manager")
    manager = world.manager_activates(token, email="mira@example.com")

    assert isinstance(manager, Manager)
    assert manager.email == "mira@example.com"
    assert [p["name"] for p in manager.properties()] == ["Kos Melati"]
    listed = owner.managers()
    assert [m["name"] for m in listed] == ["Mira Manager"]
    assert listed[0]["accountStatus"] == "active"


def test_a_step_that_the_api_refuses_fails_with_the_request_and_answer(world):
    owner = world.owner_signs_up()
    owner.add_property("Kos Melati")

    with pytest.raises(AssertionError) as failure:
        owner.add_property("Kos Melati")

    message = str(failure.value)
    assert "add_property('Kos Melati')" in message
    assert "expected 201" in message
    assert "POST /properties" in message


def test_the_expect_argument_fails_a_request_that_answers_differently(world):
    owner = world.owner_signs_up()

    with pytest.raises(AssertionError, match="expected 404.*GET /properties.*200"):
        owner.get("/properties", expect=404)

    assert owner.get("/properties", expect=200).status_code == 200


# Subscriptions through the Play stub


def test_subscribe_buys_a_plan_through_the_real_subscription_endpoints(world):
    owner = world.owner_signs_up()
    assert owner.subscription()["planCode"] == "free"

    subscription = owner.subscribe("basic")

    assert subscription["planCode"] == "basic"
    assert subscription["status"] == "active"
    assert subscription["billingPeriod"] == "monthly"
    assert subscription["openOrder"] is None
    assert len(world.stubs.play.purchases) == 1
    world.stubs.assert_play_acknowledged()


def test_subscribe_can_upgrade_to_a_yearly_pro_plan(world):
    owner = world.owner_signs_up()
    owner.subscribe("basic")

    subscription = owner.subscribe("pro", "yearly")

    assert subscription["planCode"] == "pro"
    assert subscription["billingPeriod"] == "yearly"
    assert len(world.stubs.play.purchases) == 2


def test_subscribe_fails_loudly_when_google_play_is_unreachable(world):
    owner = world.owner_signs_up()
    world.stubs.play_unreachable()

    with pytest.raises(AssertionError) as failure:
        owner.subscribe("basic")

    message = str(failure.value)
    assert "subscribe('basic')" in message
    assert "503" in message
    assert "GOOGLE_PLAY_UNREACHABLE" in message
    assert owner.subscription()["planCode"] == "free"


def test_subscribe_works_again_once_google_play_is_reachable(world):
    owner = world.owner_signs_up()
    world.stubs.play_unreachable()
    world.stubs.play_reachable()

    assert owner.subscribe("basic")["planCode"] == "basic"


def test_subscribe_fails_loudly_when_the_acknowledgement_fails(world):
    owner = world.owner_signs_up()
    world.stubs.play_acknowledge_fails()

    with pytest.raises(AssertionError, match=r"subscribe\('basic'\).*503"):
        owner.subscribe("basic")

    assert owner.subscription()["planCode"] == "free"


def test_a_purchase_that_is_still_pending_does_not_succeed_the_order(world):
    owner = world.owner_signs_up()
    order = owner.post(
        "/subscription/orders",
        json={"planCode": "basic", "billingPeriod": "monthly"},
        expect=201,
    ).json()
    token = world.stubs.play_purchase(owner, order, state="PENDING")

    verified = owner.post(
        f"/subscription/orders/{order['id']}/purchase-verification",
        json={"purchaseToken": token},
        expect=200,
    ).json()

    assert verified["status"] == "awaitingPayment"
    assert owner.subscription()["planCode"] == "free"


# Receipts


def test_receipt_helpers_give_images_the_api_accepts(seeded_world, world):
    budi, sari = seeded_world.budi, seeded_world.sari

    first = budi.upload_receipt(budi.rent_bills()[0], png_receipt())
    second = sari.upload_receipt(sari.rent_bills()[0], jpg_receipt())

    assert first["payment"]["status"] == "awaitingVerification"
    assert second["payment"]["status"] == "awaitingVerification"
    assert sorted(
        content_type for _, content_type in world.stubs.stored_files().values()
    ) == [
        "image/jpeg",
        "image/png",
    ]
    world.stubs.assert_files_stored(2)
    assert budi.get(f"/rent-bills/{first['id']}/receipt").headers["content-type"] == (
        "image/png"
    )


def test_file_receipt_picks_the_image_kind_and_refuses_others(world):
    assert file_receipt("png")["file"][2] == "image/png"
    assert file_receipt("jpg")["file"][2] == "image/jpeg"
    assert file_receipt("jpeg")["file"][2] == "image/jpeg"
    with pytest.raises(ValueError, match="gif"):
        file_receipt("gif")


def test_a_receipt_for_a_property_without_a_bank_account_fails_the_step(
    seeded_world, world
):
    dewi = world.tenant_activates(seeded_world.dewi_token, email="dewi@example.com")

    with pytest.raises(AssertionError, match="upload_receipt.*expected 200.*409"):
        dewi.upload_receipt(dewi.rent_bills()[0])


def test_verifying_an_uploaded_receipt_marks_the_bill_paid(seeded_world):
    budi, owner = seeded_world.budi, seeded_world.owner
    bill = budi.upload_receipt(budi.rent_bills()[0])

    paid = owner.post(f"/rent-bills/{bill['id']}/verification", expect=200).json()

    assert paid["payment"]["status"] == "paid"
    assert paid["payment"]["method"] == "transfer"


# The seeded world


def test_the_seed_builds_the_documented_world_as_the_api_shows_it(seeded_world):
    owner = seeded_world.owner
    assert owner.email == OWNER_EMAIL
    assert owner.subscription()["planCode"] == "basic"
    assert owner.subscription()["propertyCount"] == 2

    properties = {p["name"]: p for p in owner.properties()}
    assert sorted(properties) == sorted([MELATI, ANGGREK])
    assert properties[MELATI]["roomCount"] == 3
    assert properties[MELATI]["occupiedRoomCount"] == 2
    assert properties[ANGGREK]["roomCount"] == 2
    assert properties[ANGGREK]["occupiedRoomCount"] == 1
    detail = {
        name: owner.read(f"/properties/{p['id']}") for name, p in properties.items()
    }
    assert detail[MELATI]["bankAccount"] == BANK_ACCOUNT
    assert detail[ANGGREK]["bankAccount"] is None

    assert [r["number"] for r in owner.rooms(seeded_world.melati)] == ["A1", "A2", "A3"]
    assert [r["number"] for r in owner.rooms(seeded_world.anggrek)] == ["B1", "B2"]


def test_the_seed_has_two_activated_tenants_and_one_invited_only(seeded_world, world):
    owner = seeded_world.owner

    melati = {t["name"]: t for t in owner.tenants(seeded_world.melati)}
    anggrek = {t["name"]: t for t in owner.tenants(seeded_world.anggrek)}

    assert sorted(melati) == ["Budi Tenant", "Sari Tenant"]
    assert {t["accountStatus"] for t in melati.values()} == {"active"}
    assert melati["Budi Tenant"]["room"]["number"] == "A1"
    assert melati["Sari Tenant"]["room"]["number"] == "A2"
    assert list(anggrek) == ["Dewi Tenant"]
    assert anggrek["Dewi Tenant"]["accountStatus"] == "notActivated"
    assert seeded_world.budi.email == BUDI_EMAIL
    preview = world.client.post(
        "/invitations/previews", json={"token": seeded_world.dewi_token}
    )
    assert preview.json()["status"] == "valid"


def test_the_seed_has_one_manager_assigned_to_one_property(seeded_world):
    owner, manager = seeded_world.owner, seeded_world.manager

    listed = owner.managers()

    assert [m["name"] for m in listed] == ["Mira Manager"]
    assert [p["name"] for p in listed[0]["properties"]] == [MELATI]
    assert [p["name"] for p in manager.properties()] == [MELATI]


def test_the_seed_has_one_classified_complaint(seeded_world):
    owner = seeded_world.owner

    complaints = owner.complaints()

    assert len(complaints) == 1
    complaint = complaints[0]
    assert complaint["id"] == seeded_world.complaint["id"]
    assert complaint["tenantName"] == "Budi Tenant"
    assert complaint["room"]["number"] == "A1"
    assert complaint["status"] == "new"
    assert complaint["classification"]["category"] == "Listrik"
    assert len(seeded_world.manager.complaints()) == 1


def test_the_seed_has_one_unpaid_bill_per_lease_from_the_daily_job(seeded_world):
    owner = seeded_world.owner

    bills = {b["tenant"]["name"]: b for b in owner.rent_bills()}

    assert sorted(bills) == ["Budi Tenant", "Dewi Tenant", "Sari Tenant"]
    assert {b["payment"]["status"] for b in bills.values()} == {"unpaid"}
    assert {b["isCurrent"] for b in bills.values()} == {True}
    assert bills["Budi Tenant"]["periodStart"] == "2026-10-01"
    assert bills["Budi Tenant"]["amount"] == 1_200_000
    assert bills["Sari Tenant"]["periodStart"] == "2026-10-10"
    assert bills["Sari Tenant"]["dueDate"] == "2026-10-15"
    assert bills["Dewi Tenant"]["periodStart"] == "2026-10-15"
    assert bills["Dewi Tenant"]["canUploadReceipt"] is False
    assert [b["tenant"]["name"] for b in seeded_world.budi.rent_bills()] == [
        "Budi Tenant"
    ]


def test_the_seed_is_built_on_the_frozen_date(seeded_world, world):
    assert seeded_world.date == date(2026, 10, 23)
    assert world.clock.today == seeded_world.date


# Isolation


@pytest.mark.parametrize("attempt", ["first", "second"])
def test_tests_in_one_module_do_not_see_each_others_data(world, attempt):
    owner = world.owner_signs_up(email="same@example.com")

    assert owner.properties() == []
    owner.add_property(f"Kos {attempt}")

    assert [p["name"] for p in owner.properties()] == [f"Kos {attempt}"]


@pytest.mark.parametrize("attempt", ["first", "second"])
def test_seeded_worlds_of_different_tests_are_identical_and_separate(
    seeded_world, attempt
):
    owner = seeded_world.owner

    assert len(owner.properties()) == 2
    assert len(owner.rent_bills()) == 3
    owner.add_property(f"Kos Extra {attempt}")
    assert len(owner.properties()) == 3


# The AI stubs, through the complaint endpoints


def test_a_complaint_is_classified_when_the_classifier_works(seeded_world, world):
    budi = seeded_world.budi
    world.stubs.classifier_works(category="Air", urgency="medium")

    created = budi.submit_complaint(seeded_world.rooms["A1"])

    assert created["classificationState"] == "classifying"
    shown = budi.complaint(created)
    assert shown["classificationState"] is None
    assert shown["classification"]["category"] == "Air"
    assert shown["classification"]["urgency"] == "medium"
    assert len(world.stubs.classifier.calls) == 2


def test_an_unavailable_classifier_leaves_the_complaint_awaiting_classification(
    seeded_world, world
):
    world.stubs.classifier_unavailable()

    created = seeded_world.budi.submit_complaint(seeded_world.rooms["A1"])

    shown = seeded_world.owner.complaint(created)
    assert shown["classification"] is None
    assert shown["classificationState"] == "awaitingClassification"
    assert shown["status"] == "new"


def test_a_classifier_that_times_out_leaves_the_complaint_awaiting_classification(
    seeded_world, world
):
    world.stubs.classifier_times_out()

    created = seeded_world.budi.submit_complaint(seeded_world.rooms["A1"])

    shown = seeded_world.owner.complaint(created)
    assert shown["classification"] is None
    assert shown["classificationState"] == "awaitingClassification"


def test_the_classifier_can_recover_after_it_was_unavailable(seeded_world, world):
    world.stubs.classifier_unavailable()
    world.stubs.classifier_works()

    created = seeded_world.budi.submit_complaint(seeded_world.rooms["A1"])

    assert seeded_world.owner.complaint(created)["classification"] is not None


def test_a_complaint_to_an_owner_without_a_plan_is_not_classified(world):
    owner = world.owner_signs_up()
    room = owner.add_room(owner.add_property("Kos Melati"), "A1")
    tenant = world.tenant_activates(
        owner.add_tenant(room, "Budi Tenant", "081211111111")
    )

    created = tenant.submit_complaint(room)

    assert created["classificationState"] == "notClassified"
    world.stubs.assert_classifier_called(0)


def test_releasing_the_stubs_ends_the_thread_a_timed_out_classifier_left(
    seeded_world, world
):
    world.stubs.classifier_times_out()

    seeded_world.budi.submit_complaint(seeded_world.rooms["A1"])

    [thread] = world.stubs.stalled_threads
    assert thread.is_alive()
    world.stubs.release_stalled()
    assert not thread.is_alive()


def test_releasing_the_stubs_ends_the_thread_a_timed_out_summarizer_left(
    seeded_world, world
):
    owner, budi = seeded_world.owner, seeded_world.budi
    world.stubs.summarizer_times_out()
    bill = budi.rent_bills()[0]

    owner.post(
        f"/rent-bills/{bill['id']}/cash-payment",
        json={"receivedOn": "2026-10-01"},
        expect=200,
    )

    [thread] = world.stubs.stalled_threads
    assert thread.is_alive()
    world.stubs.release_stalled()
    assert not thread.is_alive()
    assert len(world.stubs.summarizer.calls) == 1


def test_a_stalled_classifier_answers_again_once_it_is_told_to_work(
    seeded_world, world
):
    world.stubs.classifier_times_out()
    stalled = seeded_world.budi.submit_complaint(seeded_world.rooms["A1"])
    world.stubs.classifier_works(category="Air", urgency="low")

    worked = seeded_world.budi.submit_complaint(seeded_world.rooms["A1"])

    assert seeded_world.owner.complaint(stalled)["classification"] is None
    assert seeded_world.owner.complaint(worked)["classification"]["category"] == "Air"
    assert len(world.stubs.stalled_threads) == 1


LEFT_BEHIND = []


def test_a_timeout_scenario_leaves_its_stalled_thread_to_the_teardown(
    seeded_world, world
):
    world.stubs.classifier_times_out()

    seeded_world.budi.submit_complaint(seeded_world.rooms["A1"])

    LEFT_BEHIND.extend(world.stubs.stalled_threads)
    assert LEFT_BEHIND
    assert all(thread.is_alive() for thread in LEFT_BEHIND)


def test_the_test_after_a_timeout_scenario_starts_clean(seeded_world, world):
    from app.services import complaints

    assert not any(thread.is_alive() for thread in LEFT_BEHIND)
    assert world.stubs.stalled_threads == []
    assert complaints.CLASSIFICATION_TIMEOUT_SECONDS == 10.0

    created = seeded_world.budi.submit_complaint(seeded_world.rooms["A1"])

    assert seeded_world.owner.complaint(created)["classification"] is not None


# Push, mail and the clock


def test_the_clock_moves_the_date_and_the_daily_job_creates_the_next_bill(
    seeded_world, world
):
    owner = seeded_world.owner
    assert len(owner.rent_bills()) == 3

    world.clock.set(date(2026, 11, 1))
    world.clock.run_daily_jobs()

    bills = owner.rent_bills()
    assert len(bills) == 4
    newest = [b for b in bills if b["periodStart"] == "2026-11-01"]
    assert [b["tenant"]["name"] for b in newest] == ["Budi Tenant"]
    assert newest[0]["isCurrent"] is True
    older = [
        b for b in bills if b["tenant"]["name"] == "Budi Tenant" and b is not newest[0]
    ]
    assert [b["isCurrent"] for b in older] == [False]

    world.clock.run_daily_jobs()
    assert len(owner.rent_bills()) == 4


def test_the_clock_advances_by_days(world):
    start = world.clock.today

    world.clock.advance(3)
    world.clock.advance()

    assert (world.clock.today - start).days == 4


def test_the_daily_job_without_a_secret_match_fails_the_step(world):
    wrong = Clock(world.client, "not-the-secret", world.clock.today)

    with pytest.raises(AssertionError, match="run_daily_jobs.*expected 204.*401"):
        wrong.run_daily_jobs()


def test_pushes_reach_the_devices_registered_for_a_session(seeded_world, world):
    budi = seeded_world.budi
    budi.enable_push("device-budi")
    world.stubs.assert_not_pushed("device-budi")

    world.clock.set(date(2026, 11, 1))
    world.clock.run_daily_jobs()

    world.stubs.assert_pushed("device-budi", "billIssued")
    assert "billIssued" in [n["type"] for n in budi.notifications()]
    world.stubs.assert_not_pushed("device-sari")


def test_push_assertions_fail_when_nothing_was_pushed(world):
    with pytest.raises(AssertionError, match="nothing was pushed to device-x"):
        world.stubs.assert_pushed("device-x")


def test_the_mailbox_stub_keeps_each_verification_code(world):
    owner = world.owner_signs_up(email="rina@example.com", verified=False)

    code = world.stubs.verification_code("rina@example.com")

    assert len(code) == 6
    owner.post("/auth/email-verification/confirmation", json={"code": code}, expect=200)
    with pytest.raises(
        AssertionError, match="no verification code was emailed to x@y.z"
    ):
        world.stubs.verification_code("x@y.z")
