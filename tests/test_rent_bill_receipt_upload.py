"""Uploading a transfer receipt for a rent bill."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from conftest import BANK_ACCOUNT
from rent_bill_support import (
    DETAIL_FIELDS,
    GIF_BYTES,
    MEGABYTE,
    assert_error,
    assert_field_error,
    assert_not_found,
    assert_refused,
    bill_url,
    clear_bank_account,
    days_ago,
    days_ahead,
    jpeg,
    make_property_view_only,
    parse_time,
    png,
    snapshot,
    stored_bill,
    stored_changes,
    stored_receipts,
)


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


def upload(
    client,
    headers,
    bill,
    content: bytes | None = None,
    content_type: str = "image/png",
    filename: str = "receipt.png",
):
    return client.put(
        bill_url(bill, "/receipt"),
        files={"file": (filename, png() if content is None else content, content_type)},
        headers=headers,
    )


@pytest.fixture
def lease(scene):
    return scene.tenant.lease


@pytest.fixture
def bill(make_rent_bill, lease):
    return make_rent_bill(lease)


# Authentication and roles


def test_an_upload_without_a_token_is_rejected(client, database, bill):
    response = client.put(
        bill_url(bill, "/receipt"), files={"file": ("a.png", png(), "image/png")}
    )
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


def test_an_upload_from_an_unverified_tenant_is_rejected(
    client, database, bill, make_user, sign_in
):
    session = sign_in(make_user(role=role("tenant"), email_verified=False))
    assert_error(upload(client, session.headers, bill), 403, "EMAIL_NOT_VERIFIED")


@pytest.mark.parametrize("who", ["owner_in", "manager_in"])
def test_management_cannot_upload_a_receipt(client, database, scene, bill, who):
    response = upload(client, getattr(scene, who).headers, bill)
    assert_error(response, 403, "FORBIDDEN")


def test_admins_cannot_upload_a_receipt(client, database, make_user, sign_in, bill):
    session = sign_in(make_user(role=role("admin")))
    assert_error(upload(client, session.headers, bill), 403, "FORBIDDEN")


def test_a_forbidden_upload_saves_nothing(client, database, scene, bill):
    before = snapshot(database, bill)
    upload(client, scene.owner_in.headers, bill)
    assert snapshot(database, bill) == before


def test_a_tenant_cannot_upload_for_the_bill_of_another_tenant(
    client, database, scene, make_room, make_verified_tenant, make_rent_bill
):
    neighbour = make_verified_tenant(make_room(scene.prop, number="A2"))
    other = make_rent_bill(neighbour.lease)
    before = snapshot(database, other)
    response = upload(client, scene.tenant_in.headers, other)
    assert_not_found(response)
    assert snapshot(database, other) == before


def test_an_upload_for_an_unknown_bill_is_not_found(client, database, scene):
    response = client.put(
        f"/rent-bills/{uuid4()}/receipt",
        files={"file": ("a.png", png(), "image/png")},
        headers=scene.tenant_in.headers,
    )
    assert_not_found(response)


# Success


def test_uploading_moves_the_bill_to_awaiting_verification(
    client, database, scene, bill
):
    response = upload(client, scene.tenant_in.headers, bill)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert body["id"] == str(bill.id)
    assert body["payment"]["status"] == "awaitingVerification"
    assert body["payment"]["hasReceipt"] is True
    assert body["payment"]["method"] is None
    assert body["payment"]["paidOn"] is None
    assert body["payment"]["rejectionReason"] is None
    assert body["daysOverdue"] == 0
    assert body["isCurrent"] is True
    assert body["canUploadReceipt"] is False


def test_the_response_carries_the_bank_account_and_the_amount_to_transfer(
    client, database, scene, make_rent_bill, lease
):
    bill = make_rent_bill(lease, amount=1350000)
    body = upload(client, scene.tenant_in.headers, bill).json()
    assert body["bankAccount"] == BANK_ACCOUNT
    assert body["amount"] == 1350000


def test_the_response_equals_the_detail_read_afterwards(client, database, scene, bill):
    uploaded = upload(client, scene.tenant_in.headers, bill).json()
    read = client.get(bill_url(bill), headers=scene.tenant_in.headers).json()
    assert uploaded == read


def test_the_bill_is_stored_as_awaiting_verification(client, database, scene, bill):
    upload(client, scene.tenant_in.headers, bill)
    row = stored_bill(database, bill)
    assert row.payment_status == "awaitingVerification"
    assert row.payment_method is None
    assert row.paid_on is None


def test_the_receipt_is_stored_with_its_bytes_and_type(client, database, scene, bill):
    content = png(4096)
    upload(client, scene.tenant_in.headers, bill, content)
    (receipt,) = stored_receipts(database)
    assert receipt.rent_bill_id == bill.id
    assert bytes(receipt.content) == content
    assert receipt.content_type == "image/png"
    before = datetime.now(UTC)
    assert abs((before - receipt.uploaded_at).total_seconds()) < 60


def test_a_jpeg_receipt_is_accepted_and_keeps_its_type(client, database, scene, bill):
    content = jpeg(4096)
    response = upload(
        client, scene.tenant_in.headers, bill, content, "image/jpeg", "receipt.jpg"
    )
    assert response.status_code == 200, response.text
    (receipt,) = stored_receipts(database)
    assert bytes(receipt.content) == content
    assert receipt.content_type == "image/jpeg"


def test_the_uploaded_receipt_can_be_downloaded(client, database, scene, bill):
    content = png(1500)
    upload(client, scene.tenant_in.headers, bill, content)
    for who in ("tenant_in", "owner_in", "manager_in"):
        response = client.get(
            bill_url(bill, "/receipt"), headers=getattr(scene, who).headers
        )
        assert response.status_code == 200
        assert response.headers["content-type"].split(";")[0] == "image/png"
        assert response.content == content


def test_the_upload_appends_one_history_entry_by_the_tenant(
    client, database, scene, bill
):
    before = datetime.now(UTC)
    upload(client, scene.tenant_in.headers, bill)
    created, change = stored_changes(database, bill)
    assert created.status == "unpaid"
    assert change.status == "awaitingVerification"
    assert change.method is None
    assert change.reason is None
    assert change.manual is False
    assert change.actor_id == scene.tenant.id
    assert abs((change.changed_at - before).total_seconds()) < 60


def test_the_history_in_the_response_ends_with_the_upload(
    client, database, scene, bill
):
    body = upload(client, scene.tenant_in.headers, bill).json()
    unpaid, awaiting = body["statusChanges"]
    assert unpaid["status"] == "unpaid"
    assert awaiting["status"] == "awaitingVerification"
    assert awaiting["actorName"] == "Budi Tenant"
    assert awaiting["manual"] is False
    assert parse_time(unpaid["changedAt"]) <= parse_time(awaiting["changedAt"])


def test_an_overdue_bill_can_still_be_paid_by_receipt(
    client, database, scene, make_rent_bill, lease
):
    bill = make_rent_bill(lease, due_date=days_ago(6))
    body = upload(client, scene.tenant_in.headers, bill).json()
    assert body["payment"]["status"] == "awaitingVerification"
    assert body["daysOverdue"] == 0


def test_a_view_only_property_still_accepts_receipts(client, database, scene, bill):
    make_property_view_only(database, scene.prop)
    response = upload(client, scene.tenant_in.headers, bill)
    assert response.status_code == 200, response.text


# Re-upload after rejection


def reject(client, scene, bill, reason: str = "The amount is wrong."):
    response = client.post(
        bill_url(bill, "/rejection"),
        json={"reason": reason},
        headers=scene.owner_in.headers,
    )
    assert response.status_code == 200, response.text


def test_a_rejected_bill_accepts_a_new_receipt(client, database, scene, bill):
    upload(client, scene.tenant_in.headers, bill, png(1000))
    reject(client, scene, bill)
    response = upload(client, scene.tenant_in.headers, bill, jpeg(2000), "image/jpeg")
    assert response.status_code == 200, response.text
    payment = response.json()["payment"]
    assert payment["status"] == "awaitingVerification"
    assert payment["rejectionReason"] is None
    assert payment["hasReceipt"] is True


def test_a_new_receipt_replaces_the_old_one(client, database, scene, bill):
    upload(client, scene.tenant_in.headers, bill, png(1000))
    reject(client, scene, bill)
    new_content = jpeg(2000)
    upload(client, scene.tenant_in.headers, bill, new_content, "image/jpeg")
    (receipt,) = stored_receipts(database)
    assert bytes(receipt.content) == new_content
    assert receipt.content_type == "image/jpeg"
    downloaded = client.get(bill_url(bill, "/receipt"), headers=scene.owner_in.headers)
    assert downloaded.content == new_content


def test_the_history_keeps_every_step_across_a_re_upload(client, database, scene, bill):
    upload(client, scene.tenant_in.headers, bill)
    reject(client, scene, bill, "The amount is wrong.")
    body = upload(client, scene.tenant_in.headers, bill).json()
    assert [c["status"] for c in body["statusChanges"]] == [
        "unpaid",
        "awaitingVerification",
        "rejected",
        "awaitingVerification",
    ]
    assert body["statusChanges"][2]["reason"] == "The amount is wrong."


def test_a_rejected_bill_seeded_directly_accepts_a_receipt(
    client, database, scene, make_rent_bill, lease
):
    bill = make_rent_bill(lease, status="rejected", rejection_reason="Blurry photo.")
    response = upload(client, scene.tenant_in.headers, bill)
    assert response.status_code == 200, response.text
    assert response.json()["payment"]["status"] == "awaitingVerification"
    assert response.json()["payment"]["rejectionReason"] is None


# Bill state


@pytest.mark.parametrize("status", ["awaitingVerification", "paid"])
def test_a_bill_that_is_not_unpaid_or_rejected_refuses_a_receipt(
    client, database, scene, make_rent_bill, lease, status
):
    method = "cash" if status == "paid" else None
    paid_on = days_ago(1) if status == "paid" else None
    bill = make_rent_bill(lease, status=status, method=method, paid_on=paid_on)
    before = snapshot(database, bill)
    response = upload(client, scene.tenant_in.headers, bill)
    assert_refused(response, "RENT_BILL_NOT_UPLOADABLE")
    assert snapshot(database, bill) == before


# Period


PERIODS = [
    (days_ago(60), days_ago(31)),
    (days_ago(30), days_ago(1)),
    (days_ahead(1), days_ahead(30)),
    (days_ahead(31), days_ahead(60)),
]
PERIOD_IDS = ["old", "ended_yesterday", "starts_tomorrow", "future"]


@pytest.mark.parametrize(("start", "end"), PERIODS, ids=PERIOD_IDS)
def test_an_unpaid_bill_of_any_period_accepts_a_receipt(
    client, database, scene, make_rent_bill, lease, start, end
):
    bill = make_rent_bill(lease, period_start=start, period_end=end)
    response = upload(client, scene.tenant_in.headers, bill)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["payment"]["status"] == "awaitingVerification"
    assert body["payment"]["hasReceipt"] is True
    assert body["canUploadReceipt"] is False
    assert stored_bill(database, bill).payment_status == "awaitingVerification"


@pytest.mark.parametrize(("start", "end"), PERIODS[:2], ids=PERIOD_IDS[:2])
def test_a_rejected_bill_of_a_past_period_accepts_a_receipt(
    client, database, scene, make_rent_bill, lease, start, end
):
    bill = make_rent_bill(
        lease,
        period_start=start,
        period_end=end,
        status="rejected",
        rejection_reason="Blurry photo.",
    )
    response = upload(client, scene.tenant_in.headers, bill)
    assert response.status_code == 200, response.text
    payment = response.json()["payment"]
    assert payment["status"] == "awaitingVerification"
    assert payment["rejectionReason"] is None
    assert payment["hasReceipt"] is True


def test_an_overdue_bill_of_a_past_period_stores_the_receipt_and_history(
    client, database, scene, make_rent_bill, lease
):
    bill = make_rent_bill(
        lease, period_start=days_ago(60), period_end=days_ago(31), due_date=days_ago(55)
    )
    content = png(2048)
    upload(client, scene.tenant_in.headers, bill, content)
    (receipt,) = stored_receipts(database)
    assert receipt.rent_bill_id == bill.id
    assert bytes(receipt.content) == content
    created, change = stored_changes(database, bill)
    assert created.status == "unpaid"
    assert change.status == "awaitingVerification"
    assert change.manual is False
    assert change.actor_id == scene.tenant.id


def test_a_past_bill_that_is_paid_or_awaiting_verification_refuses_a_receipt(
    client, database, scene, make_rent_bill, lease
):
    paid = make_rent_bill(
        lease,
        period_start=days_ago(90),
        period_end=days_ago(61),
        status="paid",
        method="cash",
        paid_on=days_ago(70),
    )
    waiting = make_rent_bill(
        lease,
        period_start=days_ago(60),
        period_end=days_ago(31),
        status="awaitingVerification",
    )
    for bill in (paid, waiting):
        before = snapshot(database, bill)
        response = upload(client, scene.tenant_in.headers, bill)
        assert_refused(response, "RENT_BILL_NOT_UPLOADABLE")
        assert snapshot(database, bill) == before


def test_a_past_bill_without_a_bank_account_refuses_a_receipt(
    client, database, scene, make_rent_bill, lease
):
    bill = make_rent_bill(lease, period_start=days_ago(60), period_end=days_ago(31))
    clear_bank_account(database, scene.prop)
    before = snapshot(database, bill)
    response = upload(client, scene.tenant_in.headers, bill)
    assert_refused(response, "PROPERTY_BANK_ACCOUNT_MISSING")
    assert snapshot(database, bill) == before


def test_the_current_bill_is_accepted_when_an_older_bill_is_still_unpaid(
    client, database, scene, make_rent_bill, lease
):
    old = make_rent_bill(
        lease, period_start=days_ago(60), period_end=days_ago(31), due_date=days_ago(55)
    )
    current = make_rent_bill(lease)
    assert upload(client, scene.tenant_in.headers, current).status_code == 200
    assert stored_bill(database, old).payment_status == "unpaid"


# Bank account


def test_a_property_without_a_bank_account_refuses_receipts(
    client, database, scene, bill
):
    clear_bank_account(database, scene.prop)
    before = snapshot(database, bill)
    response = upload(client, scene.tenant_in.headers, bill)
    assert_refused(response, "PROPERTY_BANK_ACCOUNT_MISSING")
    assert snapshot(database, bill) == before


# File validation


def assert_rejected_file(response, database, bill, before, code) -> None:
    assert_field_error(response, code, "file")
    assert snapshot(database, bill) == before


@pytest.mark.parametrize(
    ("content", "content_type", "filename"),
    [
        (GIF_BYTES, "image/gif", "receipt.gif"),
        (GIF_BYTES, "image/png", "receipt.png"),
        (b"%PDF-1.7\n" + b"0" * 64, "application/pdf", "receipt.pdf"),
        (b"%PDF-1.7\n" + b"0" * 64, "image/png", "receipt.png"),
        (b"just some text", "text/plain", "receipt.txt"),
        (b"just some text", "image/jpeg", "receipt.jpg"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp", "receipt.webp"),
        (b"", "image/png", "receipt.png"),
    ],
    ids=[
        "gif",
        "gif_labelled_png",
        "pdf",
        "pdf_labelled_png",
        "text",
        "text_labelled_jpeg",
        "webp",
        "empty",
    ],
)
def test_a_file_that_is_not_a_jpg_or_png_is_rejected_on_the_file_field(
    client, database, scene, bill, content, content_type, filename
):
    before = snapshot(database, bill)
    response = upload(
        client, scene.tenant_in.headers, bill, content, content_type, filename
    )
    assert_rejected_file(response, database, bill, before, "RECEIPT_TYPE_INVALID")


@pytest.mark.parametrize(
    ("make", "declared", "stored", "filename"),
    [
        (png, "image/jpeg", "image/png", "receipt.jpg"),
        (jpeg, "image/png", "image/jpeg", "receipt.png"),
        (png, "application/octet-stream", "image/png", "receipt.bin"),
        (jpeg, "text/plain", "image/jpeg", "receipt"),
    ],
    ids=["png_labelled_jpeg", "jpeg_labelled_png", "png_unlabelled", "jpeg_text"],
)
def test_the_image_type_is_decided_from_the_file_bytes(
    client, database, scene, bill, make, declared, stored, filename
):
    response = upload(client, scene.tenant_in.headers, bill, make(), declared, filename)
    assert response.status_code == 200, response.text
    (receipt,) = stored_receipts(database)
    assert receipt.content_type == stored
    download = client.get(bill_url(bill, "/receipt"), headers=scene.owner_in.headers)
    assert download.headers["content-type"].split(";")[0] == stored


def test_a_missing_file_is_rejected_on_the_file_field(client, database, scene, bill):
    before = snapshot(database, bill)
    response = client.put(bill_url(bill, "/receipt"), headers=scene.tenant_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", "file")
    assert snapshot(database, bill) == before


def test_a_part_with_another_name_is_rejected_on_the_file_field(
    client, database, scene, bill
):
    response = client.put(
        bill_url(bill, "/receipt"),
        files={"image": ("a.png", png(), "image/png")},
        headers=scene.tenant_in.headers,
    )
    assert_error(response, 422, "VALIDATION_FAILED", "file")


@pytest.mark.parametrize(
    ("size", "make"),
    [
        (5 * MEGABYTE, png),
        (5 * MEGABYTE, jpeg),
        (1, png),
    ],
    ids=["exactly_five_png", "exactly_five_jpeg", "tiny"],
)
def test_a_file_within_five_megabytes_is_accepted(
    client, database, scene, bill, size, make
):
    content = make(size) if size > 1 else make()
    content_type = "image/png" if make is png else "image/jpeg"
    response = upload(client, scene.tenant_in.headers, bill, content, content_type)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("make", [png, jpeg], ids=["png", "jpeg"])
def test_a_file_over_five_megabytes_is_rejected_on_the_file_field(
    client, database, scene, bill, make
):
    before = snapshot(database, bill)
    content_type = "image/png" if make is png else "image/jpeg"
    response = upload(
        client,
        scene.tenant_in.headers,
        bill,
        make(5 * MEGABYTE + 1),
        content_type,
    )
    assert_rejected_file(response, database, bill, before, "RECEIPT_TOO_LARGE")


def test_a_rejected_file_leaves_an_existing_receipt_untouched(
    client, database, scene, bill
):
    original = png(1000)
    upload(client, scene.tenant_in.headers, bill, original)
    reject(client, scene, bill)
    before = snapshot(database, bill)
    response = upload(client, scene.tenant_in.headers, bill, GIF_BYTES, "image/gif")
    assert_rejected_file(response, database, bill, before, "RECEIPT_TYPE_INVALID")
    (receipt,) = stored_receipts(database)
    assert bytes(receipt.content) == original
