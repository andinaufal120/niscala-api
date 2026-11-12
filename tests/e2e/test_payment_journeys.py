"""Scenarios of paying rent: receipts, cash, manual changes, overview and push."""

from datetime import date, timedelta

from e2e.e2e_auth import assert_error
from e2e.e2e_people import JPG_BYTES, PNG_BYTES, jpg_receipt
from e2e.e2e_rent import (
    MIB,
    assert_field_error,
    bill_of,
    build_site,
    join,
    notifications_of,
    real_today,
    types_of,
)

TODAY = date(2026, 10, 23)
LEASE = {"startDate": TODAY, "gracePeriodDays": 5}
GIF_BYTES = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00;"
PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def upload(person, bill, content: bytes, name="receipt.png", kind="image/png"):
    """Send a receipt as written and return the raw answer."""
    return person.put(
        f"/rent-bills/{bill['id']}/receipt", files={"file": (name, content, kind)}
    )


def padded(content: bytes, size: int) -> bytes:
    """The image bytes followed by zeros up to `size` bytes in total."""
    return content + b"\x00" * (size - len(content))


def issued(world, site, name="Budi Tenant", room="A1", **lease):
    """Add an active tenant billed today and return the tenant and the bill."""
    tenant = join(world, site.owner, site.rooms[room], name, lease={**LEASE, **lease})
    world.clock.run_daily_jobs()
    return tenant, bill_of(tenant, name)


def verify(person, bill, **kwargs):
    return person.post(f"/rent-bills/{bill['id']}/verification", **kwargs)


def reject(person, bill, reason="Receipt is blurry", **kwargs):
    return person.post(
        f"/rent-bills/{bill['id']}/rejection", json={"reason": reason}, **kwargs
    )


def cash(person, bill, received_on, **kwargs):
    return person.post(
        f"/rent-bills/{bill['id']}/cash-payment",
        json={"receivedOn": received_on.isoformat()},
        **kwargs,
    )


def change(person, bill, **body):
    return person.post(f"/rent-bills/{bill['id']}/status-changes", json=body)


def test_tenant_pays_by_transfer_is_rejected_uploads_again_and_is_verified(world):
    world.clock.set(TODAY)
    site = build_site(world)
    owner, manager = site.owner, site.manager
    budi, bill = issued(world, site)
    assert bill["canUploadReceipt"] is True
    assert_error(
        owner.get(f"/rent-bills/{bill['id']}/receipt"), 404, "RECEIPT_NOT_FOUND"
    )

    uploaded = budi.upload_receipt(bill)

    assert uploaded["payment"]["status"] == "awaitingVerification"
    assert uploaded["payment"]["hasReceipt"] is True
    assert uploaded["canUploadReceipt"] is False
    assert uploaded["daysOverdue"] == 0
    assert uploaded["bankAccount"]["accountNumber"] == "1234567890"
    for person in (owner, manager):
        (note,) = notifications_of(person, "receiptUploaded")
        assert note["rentBill"]["rentBillId"] == bill["id"]
        assert note["tenant"]["name"] == "Budi Tenant"
        assert note["room"]["number"] == "A1"
        assert note["property"]["name"] == "Kos Melati"
        waiting = person.rent_bills(paymentStatus="awaitingVerification")
        assert [b["id"] for b in waiting] == [bill["id"]]
        assert person.rent_bills(paymentStatus="unpaid") == []
        image = person.get(f"/rent-bills/{bill['id']}/receipt")
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        assert image.content == PNG_BYTES
    assert types_of(budi) == ["billIssued"]

    blank = reject(owner, bill, reason="   ")
    assert_field_error(blank, 422, "REASON_REQUIRED", "reason")
    assert owner.rent_bill(bill)["payment"]["status"] == "awaitingVerification"

    rejected = reject(owner, bill, expect=200).json()

    assert rejected["payment"]["status"] == "rejected"
    assert rejected["payment"]["rejectionReason"] == "Receipt is blurry"
    seen = budi.rent_bill(bill)
    assert seen["payment"]["status"] == "rejected"
    assert seen["payment"]["rejectionReason"] == "Receipt is blurry"
    assert seen["canUploadReceipt"] is True
    (changed,) = notifications_of(budi, "paymentStatusChanged")
    assert changed["rentBill"]["paymentStatus"] == "rejected"
    assert changed["rentBill"]["reason"] == "Receipt is blurry"
    assert owner.rent_bills(paymentStatus="awaitingVerification") == []

    again = budi.upload_receipt(bill, jpg_receipt())

    assert again["payment"]["status"] == "awaitingVerification"
    assert again["payment"]["rejectionReason"] is None
    assert len(notifications_of(owner, "receiptUploaded")) == 2
    assert len(notifications_of(manager, "receiptUploaded")) == 2
    swapped = manager.get(f"/rent-bills/{bill['id']}/receipt")
    assert swapped.headers["content-type"] == "image/jpeg"
    assert swapped.content == JPG_BYTES
    world.stubs.assert_files_stored(1)

    world.clock.advance(2)
    paid = verify(manager, bill, expect=200).json()

    assert paid["payment"]["status"] == "paid"
    assert paid["payment"]["method"] == "transfer"
    assert paid["payment"]["paidOn"] == real_today().isoformat()
    assert paid["canUploadReceipt"] is False
    seen = budi.rent_bill(bill)
    assert seen["payment"]["status"] == "paid"
    assert seen["payment"]["method"] == "transfer"
    announced = [
        n["rentBill"]["paymentStatus"]
        for n in notifications_of(budi, "paymentStatusChanged")
    ]
    assert announced == ["paid", "rejected"]
    assert (
        notifications_of(budi, "paymentStatusChanged")[0]["rentBill"]["paymentMethod"]
        == "transfer"
    )
    history = seen["statusChanges"]
    assert [h["status"] for h in history] == [
        "unpaid",
        "awaitingVerification",
        "rejected",
        "awaitingVerification",
        "paid",
    ]
    assert history[0]["actorName"] is None
    assert history[2]["reason"] == "Receipt is blurry"
    assert history[2]["actorName"] == "Rina Owner"
    assert history[4]["method"] == "transfer"
    assert history[4]["actorName"] == "Mira Manager"
    assert [h["manual"] for h in history] == [False] * 5

    assert_error(verify(owner, bill), 409, "RENT_BILL_NOT_AWAITING_VERIFICATION")
    assert_error(reject(owner, bill), 409, "RENT_BILL_NOT_AWAITING_VERIFICATION")
    assert_error(upload(budi, bill, PNG_BYTES), 409, "RENT_BILL_NOT_UPLOADABLE")


def test_the_payment_date_of_a_verified_receipt_is_the_day_it_was_uploaded(world):
    world.clock.set(TODAY)
    site = build_site(world)
    budi, bill = issued(world, site)
    budi.upload_receipt(bill)

    world.clock.advance(3)
    paid = verify(site.owner, bill, expect=200).json()

    assert paid["payment"]["paidOn"] == real_today().isoformat()
    assert world.clock.today != real_today()


def test_a_receipt_must_be_a_jpg_or_png_image_by_content_and_at_most_five_mib(world):
    world.clock.set(TODAY)
    site = build_site(world)
    budi, bill = issued(world, site)

    for content, name, kind in (
        (GIF_BYTES, "receipt.gif", "image/gif"),
        (PDF_BYTES, "receipt.pdf", "application/pdf"),
        (PDF_BYTES, "receipt.png", "image/png"),
        (b"", "receipt.png", "image/png"),
    ):
        response = upload(budi, bill, content, name, kind)
        assert_field_error(response, 422, "RECEIPT_TYPE_INVALID", "file")
    too_big = upload(budi, bill, padded(PNG_BYTES, 5 * MIB + 1))
    assert_field_error(too_big, 422, "RECEIPT_TOO_LARGE", "file")
    assert budi.rent_bill(bill)["payment"]["status"] == "unpaid"
    assert budi.rent_bill(bill)["payment"]["hasReceipt"] is False
    world.stubs.assert_files_stored(0)
    assert notifications_of(site.owner, "receiptUploaded") == []

    exact = upload(budi, bill, padded(PNG_BYTES, 5 * MIB), "x.txt", "text/plain")

    assert exact.status_code == 200, exact.text
    assert exact.json()["payment"]["status"] == "awaitingVerification"
    world.stubs.assert_files_stored(1)


def test_a_jpeg_is_accepted_whatever_type_the_upload_declares(world):
    world.clock.set(TODAY)
    site = build_site(world)
    budi, bill = issued(world, site)

    response = upload(budi, bill, JPG_BYTES, "scan.bin", "application/octet-stream")

    assert response.status_code == 200, response.text
    image = site.owner.get(f"/rent-bills/{bill['id']}/receipt")
    assert image.headers["content-type"] == "image/jpeg"


def test_a_property_without_a_bank_account_takes_no_receipt(world):
    world.clock.set(TODAY)
    site = build_site(world)
    dewi, bill = issued(world, site, "Dewi Tenant", "B1")

    assert bill["canUploadReceipt"] is False
    assert bill["property"]["name"] == "Kos Anggrek"
    assert dewi.rent_bill(bill)["bankAccount"] is None
    assert_error(upload(dewi, bill, PNG_BYTES), 409, "PROPERTY_BANK_ACCOUNT_MISSING")
    assert dewi.rent_bill(bill)["payment"]["status"] == "unpaid"
    world.stubs.assert_files_stored(0)
    recorded = cash(site.owner, bill, TODAY, expect=200).json()
    assert recorded["payment"]["status"] == "paid"


def test_an_overdue_bill_of_an_earlier_period_can_still_be_paid(world):
    world.clock.set(TODAY)
    site = build_site(world)
    budi, old = issued(world, site)
    world.clock.set(date(2026, 12, 5))
    world.clock.run_daily_jobs()

    bills = budi.rent_bills()
    assert [b["periodStart"] for b in bills] == ["2026-11-23", "2026-10-23"]
    assert [b["isCurrent"] for b in bills] == [True, False]
    assert bills[1]["daysOverdue"] == 38
    assert bills[1]["canUploadReceipt"] is True

    uploaded = budi.upload_receipt(old)
    assert uploaded["payment"]["status"] == "awaitingVerification"
    assert uploaded["daysOverdue"] == 0
    paid = verify(site.owner, old, expect=200).json()

    assert paid["payment"]["status"] == "paid"
    assert paid["periodStart"] == "2026-10-23"
    assert paid["payment"]["paidOn"] == real_today().isoformat()
    current = budi.rent_bills()[0]
    assert current["payment"]["status"] == "unpaid"


def test_a_manager_records_cash_and_the_owner_is_told_but_not_when_the_owner_does(
    world,
):
    world.clock.set(TODAY)
    site = build_site(world)
    owner, manager = site.owner, site.manager
    budi, first = issued(world, site, "Budi Tenant", "A1")
    sari, second = issued(world, site, "Sari Tenant", "A2")
    yesterday = TODAY - timedelta(days=1)
    tomorrow = TODAY + timedelta(days=1)

    future = cash(manager, first, tomorrow)
    assert_field_error(future, 422, "RECEIVED_ON_IN_FUTURE", "receivedOn")
    assert owner.rent_bill(first)["payment"]["status"] == "unpaid"
    assert notifications_of(owner, "cashPaymentRecorded") == []

    paid = cash(manager, first, yesterday, expect=200).json()

    assert paid["payment"]["status"] == "paid"
    assert paid["payment"]["method"] == "cash"
    assert paid["payment"]["paidOn"] == yesterday.isoformat()
    (note,) = notifications_of(owner, "cashPaymentRecorded")
    assert note["actorName"] == "Mira Manager"
    assert note["tenant"]["name"] == "Budi Tenant"
    assert note["rentBill"]["rentBillId"] == first["id"]
    (told,) = notifications_of(budi, "paymentStatusChanged")
    assert told["rentBill"]["paymentStatus"] == "paid"
    assert told["rentBill"]["paymentMethod"] == "cash"
    assert notifications_of(manager, "cashPaymentRecorded") == []
    assert_error(cash(manager, first, TODAY), 409, "RENT_BILL_NOT_PAYABLE")
    assert_error(cash(owner, first, TODAY), 409, "RENT_BILL_NOT_PAYABLE")

    cash(owner, second, TODAY, expect=200)

    assert len(notifications_of(owner, "cashPaymentRecorded")) == 1
    assert notifications_of(manager, "cashPaymentRecorded") == []
    assert len(notifications_of(sari, "paymentStatusChanged")) == 1
    detail = budi.rent_bill(first)
    assert [h["status"] for h in detail["statusChanges"]] == ["unpaid", "paid"]
    assert detail["statusChanges"][1]["method"] == "cash"
    assert detail["statusChanges"][1]["actorName"] == "Mira Manager"


def test_cash_is_refused_for_a_bill_awaiting_verification_and_accepted_after_a_rejection(
    world,
):
    world.clock.set(TODAY)
    site = build_site(world)
    owner = site.owner
    budi, bill = issued(world, site)
    budi.upload_receipt(bill)

    assert_error(cash(owner, bill, TODAY), 409, "RENT_BILL_NOT_PAYABLE")
    reject(owner, bill, expect=200)
    paid = cash(owner, bill, TODAY, expect=200).json()

    assert paid["payment"]["status"] == "paid"
    assert paid["payment"]["method"] == "cash"


def test_management_changes_a_status_by_hand_with_a_reason_and_it_shows_in_the_history(
    world,
):
    world.clock.set(TODAY)
    site = build_site(world)
    owner, manager = site.owner, site.manager
    budi, bill = issued(world, site)
    base = {"reason": "Paid in person"}

    assert_field_error(
        change(owner, bill, status="unpaid", reason="No change"),
        422,
        "STATUS_UNCHANGED",
        "status",
    )
    assert_field_error(
        change(owner, bill, status="rejected", reason="  "),
        422,
        "REASON_REQUIRED",
        "reason",
    )
    for body in (
        {"status": "paid", **base},
        {"status": "paid", **base, "method": "cash"},
        {"status": "paid", **base, "receivedOn": "2026-10-23"},
    ):
        assert change(owner, bill, **body).status_code == 422
    assert_field_error(
        change(
            owner, bill, status="paid", **base, method="cash", receivedOn="2026-10-24"
        ),
        422,
        "RECEIVED_ON_IN_FUTURE",
        "receivedOn",
    )
    extra = change(owner, bill, status="rejected", reason="Nope", method="cash")
    assert extra.status_code == 422
    assert owner.rent_bill(bill)["payment"]["status"] == "unpaid"
    assert notifications_of(budi, "paymentStatusChanged") == []

    paid = change(
        owner, bill, status="paid", **base, method="cash", receivedOn="2026-10-22"
    )
    assert paid.status_code == 201, paid.text
    assert paid.json()["payment"]["status"] == "paid"
    assert paid.json()["payment"]["method"] == "cash"
    assert paid.json()["payment"]["paidOn"] == "2026-10-22"
    assert paid.json()["canUploadReceipt"] is False
    assert_error(upload(budi, bill, PNG_BYTES), 409, "RENT_BILL_NOT_UPLOADABLE")

    unpaid = change(manager, bill, status="unpaid", reason="Cash was a mistake")
    assert unpaid.status_code == 201, unpaid.text
    body = unpaid.json()
    assert body["payment"]["status"] == "unpaid"
    assert body["payment"]["method"] is None
    assert body["payment"]["paidOn"] is None
    assert body["canUploadReceipt"] is True
    assert cash(owner, bill, TODAY, expect=200).json()["payment"]["status"] == "paid"
    change(owner, bill, status="unpaid", reason="Reverted again")
    again = budi.upload_receipt(bill)
    assert again["payment"]["status"] == "awaitingVerification"

    rejected = change(owner, bill, status="rejected", reason="Wrong amount")
    assert rejected.status_code == 201, rejected.text
    assert rejected.json()["payment"]["rejectionReason"] == "Wrong amount"
    assert budi.rent_bill(bill)["payment"]["rejectionReason"] == "Wrong amount"

    history = budi.rent_bill(bill)["statusChanges"]
    assert [h["status"] for h in history] == [
        "unpaid",
        "paid",
        "unpaid",
        "paid",
        "unpaid",
        "awaitingVerification",
        "rejected",
    ]
    assert [h["manual"] for h in history] == [
        False,
        True,
        True,
        False,
        True,
        False,
        True,
    ]
    assert [h["reason"] for h in history] == [
        None,
        "Paid in person",
        "Cash was a mistake",
        None,
        "Reverted again",
        None,
        "Wrong amount",
    ]
    assert history[1]["method"] == "cash"
    assert history[1]["actorName"] == "Rina Owner"
    assert history[2]["actorName"] == "Mira Manager"
    assert history[2]["method"] is None
    announced = notifications_of(budi, "paymentStatusChanged")
    assert [n["rentBill"]["paymentStatus"] for n in announced] == [
        "rejected",
        "unpaid",
        "paid",
        "unpaid",
        "paid",
    ]
    assert announced[0]["rentBill"]["reason"] == "Wrong amount"
    assert announced[4]["rentBill"]["reason"] == "Paid in person"
    assert announced[4]["rentBill"]["paymentMethod"] == "cash"


def test_moving_a_paid_bill_back_to_unpaid_makes_it_payable_by_receipt_again(world):
    world.clock.set(TODAY)
    site = build_site(world)
    owner = site.owner
    budi, bill = issued(world, site)
    cash(owner, bill, TODAY, expect=200)
    assert budi.rent_bills()[0]["canUploadReceipt"] is False

    change(owner, bill, status="unpaid", reason="Cash was never received")

    assert budi.rent_bills()[0]["canUploadReceipt"] is True
    budi.upload_receipt(bill)
    paid = verify(owner, bill, expect=200).json()
    assert paid["payment"]["status"] == "paid"
    assert paid["payment"]["method"] == "transfer"


def test_the_payment_overview_lists_each_active_tenant_with_the_bill_of_the_date(world):
    world.clock.set(TODAY)
    site = build_site(world, melati_rooms=("10", "2", "1", "7"), anggrek_rooms=("B1",))
    owner = site.owner
    ten, _ = issued(world, site, "Ten Tenant", "10")
    two, _ = issued(world, site, "Two Tenant", "2")
    sold = owner.add_tenant(site.rooms["7"], "Undated Tenant", "081211111119", lease={})
    gone = owner.add_tenant(site.rooms["1"], "Gone Tenant", "081211111118", lease=LEASE)
    owner.delete(f"/tenants/{gone.id}", expect=204)
    issued(world, site, "Elsewhere Tenant", "B1")
    two_bill = two.rent_bills()[0]
    cash(owner, two_bill, TODAY, expect=200)
    ten.upload_receipt(ten.rent_bills()[0])
    base = f"/properties/{site.melati['id']}/payment-overview"

    overview = owner.read(base)

    assert overview["date"] == "2026-10-23"
    assert [i["room"]["number"] for i in overview["items"]] == ["2", "7", "10"]
    assert [i["tenant"]["name"] for i in overview["items"]] == [
        "Two Tenant",
        "Undated Tenant",
        "Ten Tenant",
    ]
    statuses = [i["bill"] and i["bill"]["payment"]["status"] for i in overview["items"]]
    assert statuses == ["paid", None, "awaitingVerification"]
    assert overview["items"][0]["bill"]["id"] == two_bill["id"]
    assert overview["items"][0]["bill"]["amount"] == 1_000_000
    assert overview["items"][1]["tenant"]["id"] == sold.id
    assert site.manager.read(base) == overview

    before = owner.read(base, params={"date": "2026-10-22"})
    assert before["date"] == "2026-10-22"
    assert [i["bill"] for i in before["items"]] == [None, None, None]
    inside = owner.read(base, params={"date": "2026-11-22"})
    assert [i["bill"] and i["bill"]["periodStart"] for i in inside["items"]] == [
        "2026-10-23",
        None,
        "2026-10-23",
    ]
    after = owner.read(base, params={"date": "2026-11-23"})
    assert [i["bill"] for i in after["items"]] == [None, None, None]
    assert_error(
        site.manager.get(f"/properties/{site.anggrek['id']}/payment-overview"),
        404,
        "PROPERTY_NOT_FOUND",
    )
    stranger = world.owner_signs_up(email="other@example.com", name="Other Owner")
    assert_error(stranger.get(base), 404, "PROPERTY_NOT_FOUND")
    assert_error(ten.get(base), 403, "FORBIDDEN")


def test_a_tenant_never_sees_another_tenants_bill_and_a_manager_only_assigned_ones(
    world,
):
    world.clock.set(TODAY)
    site = build_site(world)
    owner, manager = site.owner, site.manager
    budi, budi_bill = issued(world, site, "Budi Tenant", "A1")
    sari, sari_bill = issued(world, site, "Sari Tenant", "A2")
    dewi, dewi_bill = issued(world, site, "Dewi Tenant", "B1")
    sari.upload_receipt(sari_bill)

    assert [b["id"] for b in budi.rent_bills()] == [budi_bill["id"]]
    assert budi.rent_bills(tenantId=sari_bill["tenant"]["id"]) == []
    assert_error(budi.get(f"/rent-bills/{sari_bill['id']}"), 404, "RENT_BILL_NOT_FOUND")
    assert_error(
        budi.get(f"/rent-bills/{sari_bill['id']}/receipt"),
        404,
        "RENT_BILL_NOT_FOUND",
    )
    assert_error(upload(budi, sari_bill, PNG_BYTES), 404, "RENT_BILL_NOT_FOUND")
    assert_error(
        budi.get("/rent-bills/00000000-0000-4000-8000-000000000000"),
        404,
        "RENT_BILL_NOT_FOUND",
    )

    assert sorted(b["tenant"]["name"] for b in manager.rent_bills()) == [
        "Budi Tenant",
        "Sari Tenant",
    ]
    assert len(owner.rent_bills()) == 3
    assert len(owner.rent_bills(propertyId=site.anggrek["id"])) == 1
    assert_error(
        manager.get(f"/rent-bills/{dewi_bill['id']}"), 404, "RENT_BILL_NOT_FOUND"
    )
    assert_error(verify(manager, dewi_bill), 404, "RENT_BILL_NOT_FOUND")
    assert_error(cash(manager, dewi_bill, TODAY), 404, "RENT_BILL_NOT_FOUND")
    assert_error(
        change(
            manager,
            dewi_bill,
            status="paid",
            reason="x",
            method="cash",
            receivedOn="2026-10-23",
        ),
        404,
        "RENT_BILL_NOT_FOUND",
    )
    assert_error(verify(budi, sari_bill), 403, "FORBIDDEN")
    assert_error(reject(budi, budi_bill), 403, "FORBIDDEN")
    assert_error(cash(dewi, dewi_bill, TODAY), 403, "FORBIDDEN")
    assert_error(
        owner.put(
            f"/rent-bills/{sari_bill['id']}/receipt",
            files={"file": ("r.png", PNG_BYTES, "image/png")},
        ),
        403,
        "FORBIDDEN",
    )
    stranger = world.owner_signs_up(email="other@example.com", name="Other Owner")
    assert stranger.rent_bills() == []
    assert_error(
        stranger.get(f"/rent-bills/{budi_bill['id']}"), 404, "RENT_BILL_NOT_FOUND"
    )


def test_the_push_for_a_status_change_is_sent_unless_billing_push_is_switched_off(
    world,
):
    world.clock.set(TODAY)
    site = build_site(world)
    owner = site.owner
    token = owner.add_tenant(
        site.rooms["A1"], "Budi Tenant", "081211111111", lease=LEASE
    )
    budi = world.tenant_activates(token, email="budi@example.com")
    budi.enable_push("budi-device")
    owner.enable_push("owner-device")

    world.clock.run_daily_jobs()

    assert types_of(budi) == ["billIssued"]
    assert world.stubs.pushes_to("budi-device") == ["billIssued"]
    settings = budi.read("/me/notification-settings")["items"]
    assert [i["category"] for i in settings] == [
        "billing",
        "paymentStatus",
        "complaintProgress",
    ]
    assert all(i["pushEnabled"] for i in settings)
    switched = [{**i, "pushEnabled": i["category"] != "billing"} for i in settings]
    budi.put("/me/notification-settings", json={"items": switched}, expect=200)

    bill = budi.rent_bills()[0]
    budi.upload_receipt(bill)
    assert world.stubs.pushes_to("owner-device") == ["receiptUploaded"]
    verify(owner, bill, expect=200)

    assert world.stubs.pushes_to("budi-device") == [
        "billIssued",
        "paymentStatusChanged",
    ]
    world.clock.set(date(2026, 11, 23))
    world.clock.run_daily_jobs()
    assert len(notifications_of(budi, "billIssued")) == 2
    assert world.stubs.pushes_to("budi-device") == [
        "billIssued",
        "paymentStatusChanged",
    ]

    world.clock.set(date(2026, 12, 30))
    world.clock.run_daily_jobs()
    assert len(notifications_of(budi, "billOverdue")) >= 1
    assert "billOverdue" not in world.stubs.pushes_to("budi-device")
    assert "billOverdue" in world.stubs.pushes_to("owner-device")


def test_the_status_change_notification_is_listed_without_a_push_when_payment_push_is_off(
    world,
):
    world.clock.set(TODAY)
    site = build_site(world)
    owner = site.owner
    budi, bill = issued(world, site)
    budi.enable_push("budi-device")
    settings = budi.read("/me/notification-settings")["items"]
    off = [{**i, "pushEnabled": i["category"] != "paymentStatus"} for i in settings]
    budi.put("/me/notification-settings", json={"items": off}, expect=200)

    cash(owner, bill, TODAY, expect=200)

    assert len(notifications_of(budi, "paymentStatusChanged")) == 1
    world.stubs.assert_not_pushed("budi-device")
