"""Attaching, replacing and reading the photo of a complaint."""

from uuid import uuid4

import pytest
from rent_bill_support import GIF_BYTES, MEGABYTE, jpeg, png
from sqlalchemy import select
from sqlalchemy.orm import Session

COMPLAINTS = "/complaints"
DETAIL_FIELDS = {
    "id",
    "description",
    "status",
    "property",
    "room",
    "tenantName",
    "createdAt",
    "hasPhoto",
    "classification",
    "classificationState",
    "classificationWithheld",
    "statusChanges",
}


def role(name: str):
    from app.schemas.auth import UserRole

    return UserRole(name)


def assert_error(response, status: int, code: str, field: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["field"] == field
    assert body["message"]


def photo_url(complaint) -> str:
    return f"{COMPLAINTS}/{complaint.id}/photo"


def upload(
    client,
    headers,
    complaint,
    content: bytes | None = None,
    content_type: str = "image/png",
    filename: str = "photo.png",
):
    return client.put(
        photo_url(complaint),
        files={"file": (filename, png() if content is None else content, content_type)},
        headers=headers,
    )


def download(client, headers, complaint):
    return client.get(photo_url(complaint), headers=headers)


def media_type(response) -> str:
    return response.headers["content-type"].split(";")[0]


def stored_photos(database) -> list:
    from app.models.complaints import ComplaintPhoto

    with Session(database, expire_on_commit=False) as db:
        return list(db.scalars(select(ComplaintPhoto)))


def stored_complaint(database, complaint):
    from app.models import Complaint

    with Session(database, expire_on_commit=False) as db:
        return db.get(Complaint, complaint.id)


def stored_changes(database, complaint) -> list:
    from app.models import ComplaintStatusChange

    with Session(database, expire_on_commit=False) as db:
        return list(
            db.scalars(
                select(ComplaintStatusChange).where(
                    ComplaintStatusChange.complaint_id == complaint.id
                )
            )
        )


def stored_notifications(database) -> list:
    from app.models import Notification

    with Session(database, expire_on_commit=False) as db:
        return list(db.scalars(select(Notification)))


def snapshot(database, complaint) -> tuple:
    """Everything stored about a complaint and its photo."""
    row = stored_complaint(database, complaint)
    return (
        row.description,
        row.status,
        row.classification_state,
        row.ai_category,
        row.ai_urgency,
        row.ai_suggested_action,
        row.manual_category,
        row.manual_urgency,
        [
            (c.id, c.status, c.handling_note)
            for c in stored_changes(database, complaint)
        ],
        [(p.content, p.content_type, p.uploaded_at) for p in stored_photos(database)],
    )


def detail(client, headers, complaint):
    response = client.get(f"{COMPLAINTS}/{complaint.id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def listed(client, headers) -> list[dict]:
    response = client.get(COMPLAINTS, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def unassign(database, manager, property_) -> None:
    from app.models import ManagerAssignment

    with Session(database) as db:
        db.delete(db.get(ManagerAssignment, (manager.id, property_.id)))
        db.commit()


@pytest.fixture
def owner(make_user, subscribe_owner):
    user = make_user(name="Rina Owner")
    subscribe_owner(user, "pro")
    return user


@pytest.fixture
def owner_in(owner, sign_in):
    return sign_in(owner)


@pytest.fixture
def prop(owner, make_property):
    return make_property(owner, name="Kos Melati")


@pytest.fixture
def room(prop, make_room):
    return make_room(prop, number="A1")


@pytest.fixture
def tenant(room, make_verified_tenant):
    return make_verified_tenant(room, name="Budi Tenant")


@pytest.fixture
def tenant_in(tenant, sign_in):
    return sign_in(tenant.user)


@pytest.fixture
def manager(make_user, prop, assign_manager):
    user = make_user(name="Mira Manager", role=role("manager"))
    assign_manager(user, prop)
    return user


@pytest.fixture
def manager_in(manager, sign_in):
    return sign_in(manager)


@pytest.fixture
def complaint(tenant, room, make_complaint):
    return make_complaint(tenant, room)


@pytest.fixture
def neighbour_in(prop, make_room, make_verified_tenant, sign_in):
    """Another tenant of the same property."""
    other_room = make_room(prop, number="A2")
    other = make_verified_tenant(other_room, name="Siti Tenant")
    return sign_in(other.user)


@pytest.fixture
def other_owner_in(make_user, make_property, sign_in):
    """An owner of another property."""
    other = make_user(name="Other Owner")
    make_property(other, name="Kos Lain")
    return sign_in(other)


@pytest.fixture
def stranger_in(make_user, sign_in):
    """A manager assigned to no property."""
    return sign_in(make_user(name="Stranger", role=role("manager")))


# Authentication and roles


def test_an_upload_without_a_token_is_rejected(client, database, complaint):
    response = client.put(
        photo_url(complaint), files={"file": ("a.png", png(), "image/png")}
    )
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


def test_an_upload_with_a_garbage_token_is_rejected(client, database, complaint):
    response = upload(client, {"Authorization": "Bearer garbage"}, complaint)
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


def test_a_read_without_a_token_is_rejected(client, database, complaint):
    assert_error(client.get(photo_url(complaint)), 401, "ACCESS_TOKEN_INVALID")


def test_a_read_with_a_garbage_token_is_rejected(client, database, complaint):
    response = download(client, {"Authorization": "Bearer garbage"}, complaint)
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


def test_an_upload_from_an_unverified_tenant_is_rejected(
    client, database, complaint, make_user, sign_in
):
    session = sign_in(make_user(role=role("tenant"), email_verified=False))
    assert_error(upload(client, session.headers, complaint), 403, "EMAIL_NOT_VERIFIED")


@pytest.mark.parametrize("name", ["tenant", "owner", "manager"])
def test_a_read_from_an_unverified_account_is_rejected(
    client, database, complaint, make_user, sign_in, name
):
    session = sign_in(make_user(role=role(name), email_verified=False))
    assert_error(
        download(client, session.headers, complaint), 403, "EMAIL_NOT_VERIFIED"
    )


@pytest.mark.parametrize("who", ["owner_in", "manager_in"])
def test_management_cannot_upload_a_photo(client, database, complaint, request, who):
    headers = request.getfixturevalue(who).headers
    assert_error(upload(client, headers, complaint), 403, "FORBIDDEN")


def test_admins_cannot_upload_a_photo(client, database, complaint, make_user, sign_in):
    session = sign_in(make_user(role=role("admin")))
    assert_error(upload(client, session.headers, complaint), 403, "FORBIDDEN")


def test_admins_cannot_read_a_photo(client, database, complaint, make_user, sign_in):
    session = sign_in(make_user(role=role("admin")))
    assert_error(download(client, session.headers, complaint), 403, "FORBIDDEN")


def test_a_forbidden_upload_saves_nothing(
    client, database, complaint, owner_in, manager_in
):
    before = snapshot(database, complaint)
    upload(client, owner_in.headers, complaint)
    upload(client, manager_in.headers, complaint)
    assert snapshot(database, complaint) == before
    assert stored_photos(database) == []


# Upload access


def test_a_tenant_cannot_upload_a_photo_for_the_complaint_of_another_tenant(
    client, database, complaint, neighbour_in
):
    before = snapshot(database, complaint)
    response = upload(client, neighbour_in.headers, complaint)
    assert_error(response, 404, "COMPLAINT_NOT_FOUND")
    assert snapshot(database, complaint) == before
    assert stored_photos(database) == []


def test_a_tenant_of_another_owner_cannot_upload_for_the_complaint(
    client,
    database,
    complaint,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
    sign_in,
):
    other_prop = make_property(make_user(name="Other Owner"), name="Kos Lain")
    other = make_verified_tenant(make_room(other_prop, number="Z9"), name="Other")
    response = upload(client, sign_in(other.user).headers, complaint)
    assert_error(response, 404, "COMPLAINT_NOT_FOUND")
    assert stored_photos(database) == []


def test_an_upload_for_an_unknown_complaint_is_not_found(client, database, tenant_in):
    response = client.put(
        f"{COMPLAINTS}/{uuid4()}/photo",
        files={"file": ("a.png", png(), "image/png")},
        headers=tenant_in.headers,
    )
    assert_error(response, 404, "COMPLAINT_NOT_FOUND")


def test_an_upload_with_a_malformed_complaint_id_is_a_validation_error(
    client, database, tenant_in
):
    response = client.put(
        f"{COMPLAINTS}/not-a-uuid/photo",
        files={"file": ("a.png", png(), "image/png")},
        headers=tenant_in.headers,
    )
    assert_error(response, 422, "VALIDATION_FAILED", "complaintId")


def test_a_tenant_whose_lease_ended_can_still_attach_a_photo(
    client, database, room, make_verified_tenant, sign_in, make_complaint
):
    stored = make_verified_tenant(room, lease_ended=True)
    own = make_complaint(stored, room)
    response = upload(client, sign_in(stored.user).headers, own)
    assert response.status_code == 200, response.text


# Upload success


def test_uploading_answers_with_the_complaint_detail_and_a_photo(
    client, database, complaint, tenant_in, prop, room
):
    response = upload(client, tenant_in.headers, complaint)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert body["id"] == str(complaint.id)
    assert body["description"] == complaint.description
    assert body["status"] == "new"
    assert body["property"] == {"id": str(prop.id), "name": "Kos Melati"}
    assert body["room"] == {"id": str(room.id), "number": "A1"}
    assert body["tenantName"] == "Budi Tenant"
    assert body["hasPhoto"] is True


def test_the_response_equals_the_detail_read_afterwards(
    client, database, complaint, tenant_in
):
    uploaded = upload(client, tenant_in.headers, complaint).json()
    assert uploaded == detail(client, tenant_in.headers, complaint)


def test_the_response_carries_the_status_history(
    client, database, complaint, tenant_in
):
    body = upload(client, tenant_in.headers, complaint).json()
    assert [c["status"] for c in body["statusChanges"]] == ["new"]


def test_the_photo_is_stored_with_its_bytes_and_type(
    client, database, complaint, tenant_in
):
    content = png(4096)
    upload(client, tenant_in.headers, complaint, content)
    (photo,) = stored_photos(database)
    assert photo.complaint_id == complaint.id
    assert bytes(photo.content) == content
    assert photo.content_type == "image/png"
    assert photo.uploaded_at.tzinfo is not None


def test_a_jpeg_photo_is_accepted_and_keeps_its_type(
    client, database, complaint, tenant_in
):
    content = jpeg(4096)
    response = upload(
        client, tenant_in.headers, complaint, content, "image/jpeg", "photo.jpg"
    )
    assert response.status_code == 200, response.text
    (photo,) = stored_photos(database)
    assert bytes(photo.content) == content
    assert photo.content_type == "image/jpeg"


def test_the_uploaded_photo_can_be_downloaded_by_everyone_with_access(
    client, database, complaint, tenant_in, owner_in, manager_in
):
    content = png(1500)
    upload(client, tenant_in.headers, complaint, content)
    for session in (tenant_in, owner_in, manager_in):
        response = download(client, session.headers, complaint)
        assert response.status_code == 200
        assert media_type(response) == "image/png"
        assert response.content == content


def test_a_downloaded_jpeg_keeps_its_bytes_and_type(
    client, database, complaint, tenant_in, owner_in
):
    content = jpeg(2500)
    upload(client, tenant_in.headers, complaint, content, "image/jpeg", "photo.jpg")
    response = download(client, owner_in.headers, complaint)
    assert media_type(response) == "image/jpeg"
    assert response.content == content


def test_a_photo_belongs_only_to_its_own_complaint(
    client, database, tenant, room, make_complaint, tenant_in
):
    first = make_complaint(tenant, room)
    second = make_complaint(tenant, room)
    upload(client, tenant_in.headers, first)
    assert detail(client, tenant_in.headers, first)["hasPhoto"] is True
    assert detail(client, tenant_in.headers, second)["hasPhoto"] is False
    assert_error(download(client, tenant_in.headers, second), 404, "PHOTO_NOT_FOUND")


def test_a_photo_can_be_attached_to_a_freshly_submitted_complaint(
    client, database, tenant_in
):
    created = client.post(
        COMPLAINTS,
        json={"description": "The air conditioner does not cool."},
        headers=tenant_in.headers,
    ).json()
    response = client.put(
        f"{COMPLAINTS}/{created['id']}/photo",
        files={"file": ("a.png", png(), "image/png")},
        headers=tenant_in.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["hasPhoto"] is True


# Replacing


def test_a_second_upload_replaces_the_first(client, database, complaint, tenant_in):
    upload(client, tenant_in.headers, complaint, png(1000))
    new_content = jpeg(2000)
    response = upload(
        client, tenant_in.headers, complaint, new_content, "image/jpeg", "new.jpg"
    )
    assert response.status_code == 200, response.text
    assert response.json()["hasPhoto"] is True
    (photo,) = stored_photos(database)
    assert bytes(photo.content) == new_content
    assert photo.content_type == "image/jpeg"
    fetched = download(client, tenant_in.headers, complaint)
    assert fetched.content == new_content
    assert media_type(fetched) == "image/jpeg"


def test_a_replacement_of_the_same_type_swaps_the_bytes(
    client, database, complaint, tenant_in, owner_in
):
    upload(client, tenant_in.headers, complaint, png(1000))
    new_content = png(3000)
    upload(client, tenant_in.headers, complaint, new_content)
    assert len(stored_photos(database)) == 1
    assert download(client, owner_in.headers, complaint).content == new_content


def test_many_uploads_leave_one_photo(client, database, complaint, tenant_in):
    for size in (100, 200, 300):
        assert (
            upload(client, tenant_in.headers, complaint, png(size)).status_code == 200
        )
    (photo,) = stored_photos(database)
    assert len(bytes(photo.content)) == 300


def test_a_replacement_does_not_touch_the_photo_of_another_complaint(
    client, database, tenant, room, make_complaint, tenant_in
):
    first = make_complaint(tenant, room)
    second = make_complaint(tenant, room)
    upload(client, tenant_in.headers, first, png(500))
    upload(client, tenant_in.headers, second, jpeg(600), "image/jpeg")
    upload(client, tenant_in.headers, first, png(700))
    assert len(stored_photos(database)) == 2
    assert download(client, tenant_in.headers, second).content == jpeg(600)
    assert download(client, tenant_in.headers, first).content == png(700)


# Complaint status


def seeded_complaint(make_complaint, tenant, room, status):
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    history = [("new", None, now - timedelta(minutes=10))]
    if status in ("inProgress", "done"):
        history.append(("inProgress", "On it.", now - timedelta(minutes=5)))
    if status == "done":
        history.append(("done", "Fixed.", now - timedelta(minutes=1)))
    return make_complaint(tenant, room, status=status, changes=history)


@pytest.mark.parametrize("status", ["inProgress", "done"])
def test_a_complaint_that_is_no_longer_new_refuses_a_photo(
    client, database, tenant, room, make_complaint, tenant_in, status
):
    started = seeded_complaint(make_complaint, tenant, room, status)
    before = snapshot(database, started)
    response = upload(client, tenant_in.headers, started)
    assert_error(response, 409, "COMPLAINT_NOT_NEW")
    assert snapshot(database, started) == before
    assert stored_photos(database) == []


@pytest.mark.parametrize("status", ["inProgress", "done"])
def test_a_complaint_that_is_no_longer_new_keeps_its_existing_photo(
    client, database, tenant, room, make_complaint, tenant_in, owner_in, status
):
    started = make_complaint(tenant, room)
    original = png(900)
    upload(client, tenant_in.headers, started, original)
    for step in ("inProgress", "done")[: ("inProgress", "done").index(status) + 1]:
        moved = client.post(
            f"{COMPLAINTS}/{started.id}/status-changes",
            json={"status": step},
            headers=owner_in.headers,
        )
        assert moved.status_code == 201, moved.text
    before = snapshot(database, started)
    response = upload(client, tenant_in.headers, started, jpeg(), "image/jpeg")
    assert_error(response, 409, "COMPLAINT_NOT_NEW")
    assert snapshot(database, started) == before
    assert download(client, tenant_in.headers, started).content == original


def test_a_photo_is_accepted_until_management_starts_the_complaint(
    client, database, complaint, tenant_in, owner_in
):
    assert upload(client, tenant_in.headers, complaint).status_code == 200
    moved = client.post(
        f"{COMPLAINTS}/{complaint.id}/status-changes",
        json={"status": "inProgress"},
        headers=owner_in.headers,
    )
    assert moved.status_code == 201, moved.text
    assert_error(upload(client, tenant_in.headers, complaint), 409, "COMPLAINT_NOT_NEW")


def test_the_photo_of_a_started_complaint_can_still_be_read(
    client, database, tenant, room, make_complaint, tenant_in, owner_in
):
    started = make_complaint(tenant, room)
    content = png(777)
    upload(client, tenant_in.headers, started, content)
    client.post(
        f"{COMPLAINTS}/{started.id}/status-changes",
        json={"status": "inProgress"},
        headers=owner_in.headers,
    )
    assert download(client, tenant_in.headers, started).content == content
    assert download(client, owner_in.headers, started).content == content


# Side effects


def test_uploading_changes_neither_status_nor_history_nor_classification(
    client, database, tenant, room, make_complaint, tenant_in
):
    classified = make_complaint(
        tenant, room, ai=("Listrik", "high", "Send an electrician today.")
    )
    before = stored_complaint(database, classified)
    history = [(c.id, c.status) for c in stored_changes(database, classified)]
    body = upload(client, tenant_in.headers, classified).json()
    after = stored_complaint(database, classified)
    assert after.status == before.status == "new"
    assert after.classification_state == before.classification_state
    assert (after.ai_category, after.ai_urgency, after.ai_suggested_action) == (
        "Listrik",
        "high",
        "Send an electrician today.",
    )
    assert [(c.id, c.status) for c in stored_changes(database, classified)] == history
    assert body["status"] == "new"
    assert body["classification"]["category"] == "Listrik"
    assert len(body["statusChanges"]) == 1


def test_uploading_leaves_a_pending_classification_state_alone(
    client, database, tenant, room, make_complaint, tenant_in
):
    pending = make_complaint(tenant, room, classification_state="classifying")
    body = upload(client, tenant_in.headers, pending).json()
    assert body["classificationState"] == "classifying"
    assert stored_complaint(database, pending).classification_state == "classifying"


def test_uploading_does_not_call_the_classifier(
    client, database, complaint, tenant_in, fake_classifier
):
    upload(client, tenant_in.headers, complaint)
    assert fake_classifier.calls == []


def test_uploading_creates_no_notification(
    client, database, complaint, tenant_in, pushes
):
    before = len(stored_notifications(database))
    upload(client, tenant_in.headers, complaint)
    upload(client, tenant_in.headers, complaint, jpeg(), "image/jpeg")
    assert len(stored_notifications(database)) == before
    assert pushes.attempts == []


def test_a_rejected_upload_creates_no_notification(
    client, database, complaint, tenant_in, pushes
):
    before = len(stored_notifications(database))
    upload(client, tenant_in.headers, complaint, GIF_BYTES, "image/gif")
    assert len(stored_notifications(database)) == before
    assert pushes.attempts == []


# File validation


@pytest.mark.parametrize(
    ("content", "content_type", "filename"),
    [
        (GIF_BYTES, "image/gif", "photo.gif"),
        (GIF_BYTES, "image/png", "photo.png"),
        (b"%PDF-1.7\n" + b"0" * 64, "application/pdf", "photo.pdf"),
        (b"%PDF-1.7\n" + b"0" * 64, "image/png", "photo.png"),
        (b"just some text", "text/plain", "photo.txt"),
        (b"just some text", "image/jpeg", "photo.jpg"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp", "photo.webp"),
        (b"\x89PNG", "image/png", "photo.png"),
        (b"\xff\xd8", "image/jpeg", "photo.jpg"),
        (b"", "image/png", "photo.png"),
        (b"", "image/jpeg", "photo.jpg"),
    ],
    ids=[
        "gif",
        "gif_labelled_png",
        "pdf",
        "pdf_labelled_png",
        "text",
        "text_labelled_jpeg",
        "webp",
        "truncated_png_signature",
        "truncated_jpeg_signature",
        "empty_png",
        "empty_jpeg",
    ],
)
def test_a_file_that_is_not_a_jpg_or_png_is_rejected_on_the_file_field(
    client, database, complaint, tenant_in, content, content_type, filename
):
    before = snapshot(database, complaint)
    response = upload(
        client, tenant_in.headers, complaint, content, content_type, filename
    )
    assert_error(response, 422, "PHOTO_TYPE_INVALID", "file")
    assert snapshot(database, complaint) == before
    assert stored_photos(database) == []


@pytest.mark.parametrize(
    ("make", "declared", "stored", "filename"),
    [
        (png, "image/jpeg", "image/png", "photo.jpg"),
        (jpeg, "image/png", "image/jpeg", "photo.png"),
        (png, "application/octet-stream", "image/png", "photo.bin"),
        (jpeg, "text/plain", "image/jpeg", "photo"),
    ],
    ids=["png_labelled_jpeg", "jpeg_labelled_png", "png_unlabelled", "jpeg_text"],
)
def test_the_image_type_is_decided_from_the_file_bytes(
    client, database, complaint, tenant_in, owner_in, make, declared, stored, filename
):
    response = upload(client, tenant_in.headers, complaint, make(), declared, filename)
    assert response.status_code == 200, response.text
    (photo,) = stored_photos(database)
    assert photo.content_type == stored
    fetched = download(client, owner_in.headers, complaint)
    assert media_type(fetched) == stored
    assert fetched.content == make()


@pytest.mark.parametrize(
    "header",
    [
        b"\xff\xd8\xff\xdb",
        b"\xff\xd8\xff\xe1",
        b"\xff\xd8\xff\xee",
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00",
    ],
    ids=["dqt", "exif", "adobe", "jfif"],
)
def test_any_jpeg_signature_is_accepted(client, database, complaint, tenant_in, header):
    content = header.ljust(64, b"\x00")
    response = upload(client, tenant_in.headers, complaint, content, "image/jpeg")
    assert response.status_code == 200, response.text
    (photo,) = stored_photos(database)
    assert photo.content_type == "image/jpeg"


def test_a_missing_file_is_rejected_on_the_file_field(
    client, database, complaint, tenant_in
):
    before = snapshot(database, complaint)
    response = client.put(photo_url(complaint), headers=tenant_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", "file")
    assert snapshot(database, complaint) == before


def test_a_part_with_another_name_is_rejected_on_the_file_field(
    client, database, complaint, tenant_in
):
    response = client.put(
        photo_url(complaint),
        files={"image": ("a.png", png(), "image/png")},
        headers=tenant_in.headers,
    )
    assert_error(response, 422, "VALIDATION_FAILED", "file")
    assert stored_photos(database) == []


@pytest.mark.parametrize(
    ("size", "make"),
    [
        (5 * MEGABYTE, png),
        (5 * MEGABYTE, jpeg),
        (5 * MEGABYTE - 1, png),
        (1024, jpeg),
    ],
    ids=["exactly_five_png", "exactly_five_jpeg", "just_under_png", "small_jpeg"],
)
def test_a_file_within_five_megabytes_is_accepted(
    client, database, complaint, tenant_in, size, make
):
    content = make(size)
    content_type = "image/png" if make is png else "image/jpeg"
    response = upload(client, tenant_in.headers, complaint, content, content_type)
    assert response.status_code == 200, response.text
    (photo,) = stored_photos(database)
    assert len(bytes(photo.content)) == size


@pytest.mark.parametrize("make", [png, jpeg], ids=["png", "jpeg"])
def test_a_file_over_five_megabytes_is_rejected_on_the_file_field(
    client, database, complaint, tenant_in, make
):
    before = snapshot(database, complaint)
    content_type = "image/png" if make is png else "image/jpeg"
    response = upload(
        client, tenant_in.headers, complaint, make(5 * MEGABYTE + 1), content_type
    )
    assert_error(response, 422, "PHOTO_TOO_LARGE", "file")
    assert snapshot(database, complaint) == before
    assert stored_photos(database) == []


def test_a_rejected_file_leaves_an_existing_photo_untouched(
    client, database, complaint, tenant_in, owner_in
):
    original = png(1000)
    upload(client, tenant_in.headers, complaint, original)
    before = snapshot(database, complaint)
    response = upload(client, tenant_in.headers, complaint, GIF_BYTES, "image/gif")
    assert_error(response, 422, "PHOTO_TYPE_INVALID", "file")
    assert snapshot(database, complaint) == before
    (photo,) = stored_photos(database)
    assert bytes(photo.content) == original
    assert download(client, owner_in.headers, complaint).content == original
    assert detail(client, tenant_in.headers, complaint)["hasPhoto"] is True


def test_an_oversized_file_leaves_an_existing_photo_untouched(
    client, database, complaint, tenant_in
):
    original = jpeg(1000)
    upload(client, tenant_in.headers, complaint, original, "image/jpeg")
    before = snapshot(database, complaint)
    response = upload(client, tenant_in.headers, complaint, png(5 * MEGABYTE + 1))
    assert_error(response, 422, "PHOTO_TOO_LARGE", "file")
    assert snapshot(database, complaint) == before
    (photo,) = stored_photos(database)
    assert bytes(photo.content) == original
    assert photo.content_type == "image/jpeg"


def test_a_failed_upload_leaves_the_complaint_saved_and_a_retry_works(
    client, database, complaint, tenant_in
):
    failed = upload(client, tenant_in.headers, complaint, GIF_BYTES, "image/gif")
    assert failed.status_code == 422
    body = detail(client, tenant_in.headers, complaint)
    assert body["id"] == str(complaint.id)
    assert body["hasPhoto"] is False
    assert upload(client, tenant_in.headers, complaint).status_code == 200
    assert detail(client, tenant_in.headers, complaint)["hasPhoto"] is True


# Reading the photo


def test_a_photo_is_not_found_for_a_complaint_without_one(
    client, database, complaint, tenant_in, owner_in, manager_in
):
    for session in (tenant_in, owner_in, manager_in):
        response = download(client, session.headers, complaint)
        assert_error(response, 404, "PHOTO_NOT_FOUND")


def test_a_photo_read_for_an_unknown_complaint_is_not_found(
    client, database, tenant_in
):
    response = client.get(f"{COMPLAINTS}/{uuid4()}/photo", headers=tenant_in.headers)
    assert_error(response, 404, "COMPLAINT_NOT_FOUND")


def test_a_photo_read_with_a_malformed_complaint_id_is_a_validation_error(
    client, database, tenant_in
):
    response = client.get(f"{COMPLAINTS}/not-a-uuid/photo", headers=tenant_in.headers)
    assert_error(response, 422, "VALIDATION_FAILED", "complaintId")


def test_a_seeded_photo_is_readable(client, database, complaint, tenant_in, add_photo):
    content = jpeg(333)
    add_photo(complaint, content, "image/jpeg")
    response = download(client, tenant_in.headers, complaint)
    assert response.status_code == 200
    assert media_type(response) == "image/jpeg"
    assert response.content == content


@pytest.fixture
def add_photo(database):
    from datetime import UTC, datetime

    from app.models.complaints import ComplaintPhoto

    def add(complaint, content: bytes, content_type: str) -> None:
        with Session(database) as db:
            db.add(
                ComplaintPhoto(
                    complaint_id=complaint.id,
                    content=content,
                    content_type=content_type,
                    uploaded_at=datetime.now(UTC),
                )
            )
            db.commit()

    return add


def test_another_tenant_cannot_read_the_photo(
    client, database, complaint, add_photo, neighbour_in
):
    add_photo(complaint, png(), "image/png")
    assert_error(
        download(client, neighbour_in.headers, complaint), 404, "COMPLAINT_NOT_FOUND"
    )


def test_another_tenant_gets_the_same_answer_with_and_without_a_photo(
    client, database, complaint, add_photo, neighbour_in
):
    without = download(client, neighbour_in.headers, complaint)
    add_photo(complaint, png(), "image/png")
    with_photo = download(client, neighbour_in.headers, complaint)
    assert without.status_code == with_photo.status_code == 404
    assert without.json() == with_photo.json()


def test_an_owner_of_another_property_cannot_read_the_photo(
    client, database, complaint, add_photo, other_owner_in
):
    add_photo(complaint, png(), "image/png")
    assert_error(
        download(client, other_owner_in.headers, complaint), 404, "COMPLAINT_NOT_FOUND"
    )


def test_an_unassigned_manager_cannot_read_the_photo(
    client, database, complaint, add_photo, stranger_in
):
    add_photo(complaint, png(), "image/png")
    assert_error(
        download(client, stranger_in.headers, complaint), 404, "COMPLAINT_NOT_FOUND"
    )


def test_an_unassigned_manager_gets_complaint_not_found_even_without_a_photo(
    client, database, complaint, stranger_in
):
    assert_error(
        download(client, stranger_in.headers, complaint), 404, "COMPLAINT_NOT_FOUND"
    )


def test_a_manager_loses_access_to_the_photo_when_unassigned(
    client, database, complaint, add_photo, manager, manager_in, prop
):
    add_photo(complaint, png(), "image/png")
    assert download(client, manager_in.headers, complaint).status_code == 200
    unassign(database, manager, prop)
    assert_error(
        download(client, manager_in.headers, complaint), 404, "COMPLAINT_NOT_FOUND"
    )


def test_an_owner_cannot_read_the_photo_of_a_deleted_property(
    client,
    database,
    owner,
    owner_in,
    make_property,
    make_room,
    make_verified_tenant,
    make_complaint,
    add_photo,
):
    gone = make_property(owner, name="Kos Lama", deleted=True)
    gone_room = make_room(gone, number="G1")
    gone_tenant = make_verified_tenant(gone_room)
    old = make_complaint(gone_tenant, gone_room)
    add_photo(old, png(), "image/png")
    assert_error(download(client, owner_in.headers, old), 404, "COMPLAINT_NOT_FOUND")


def test_a_manager_assigned_to_the_property_reads_a_photo_of_any_status(
    client, database, tenant, room, make_complaint, add_photo, manager_in
):
    done = seeded_complaint(make_complaint, tenant, room, "done")
    add_photo(done, png(64), "image/png")
    response = download(client, manager_in.headers, done)
    assert response.status_code == 200
    assert response.content == png(64)


# hasPhoto in the complaint views


@pytest.mark.parametrize("who", ["tenant_in", "owner_in", "manager_in"])
def test_has_photo_is_false_in_the_detail_before_an_upload(
    client, database, complaint, request, who
):
    headers = request.getfixturevalue(who).headers
    assert detail(client, headers, complaint)["hasPhoto"] is False


@pytest.mark.parametrize("who", ["tenant_in", "owner_in", "manager_in"])
def test_has_photo_is_false_in_the_list_before_an_upload(
    client, database, complaint, request, who
):
    headers = request.getfixturevalue(who).headers
    (item,) = listed(client, headers)
    assert item["hasPhoto"] is False


@pytest.mark.parametrize("who", ["tenant_in", "owner_in", "manager_in"])
def test_has_photo_is_true_in_the_detail_after_an_upload(
    client, database, complaint, tenant_in, request, who
):
    upload(client, tenant_in.headers, complaint)
    headers = request.getfixturevalue(who).headers
    assert detail(client, headers, complaint)["hasPhoto"] is True


@pytest.mark.parametrize("who", ["tenant_in", "owner_in", "manager_in"])
def test_has_photo_is_true_in_the_list_after_an_upload(
    client, database, complaint, tenant_in, request, who
):
    upload(client, tenant_in.headers, complaint)
    headers = request.getfixturevalue(who).headers
    (item,) = listed(client, headers)
    assert item["id"] == str(complaint.id)
    assert item["hasPhoto"] is True


def test_the_list_flags_only_the_complaints_that_have_a_photo(
    client, database, tenant, room, make_complaint, tenant_in, owner_in
):
    with_photo = make_complaint(tenant, room)
    without = make_complaint(tenant, room)
    upload(client, tenant_in.headers, with_photo)
    for headers in (tenant_in.headers, owner_in.headers):
        flags = {i["id"]: i["hasPhoto"] for i in listed(client, headers)}
        assert flags == {str(with_photo.id): True, str(without.id): False}


def test_the_status_change_response_reports_the_photo(
    client, database, complaint, tenant_in, owner_in
):
    upload(client, tenant_in.headers, complaint)
    moved = client.post(
        f"{COMPLAINTS}/{complaint.id}/status-changes",
        json={"status": "inProgress"},
        headers=owner_in.headers,
    )
    assert moved.status_code == 201, moved.text
    assert moved.json()["hasPhoto"] is True


def test_a_seeded_photo_shows_in_the_views_of_everyone_with_access(
    client, database, complaint, add_photo, tenant_in, owner_in, manager_in
):
    add_photo(complaint, png(), "image/png")
    for session in (tenant_in, owner_in, manager_in):
        assert detail(client, session.headers, complaint)["hasPhoto"] is True
        (item,) = listed(client, session.headers)
        assert item["hasPhoto"] is True


def test_the_photo_stays_after_the_subscription_ends(
    client, database, complaint, owner, tenant_in, owner_in, expire_subscription
):
    content = png(512)
    upload(client, tenant_in.headers, complaint, content)
    expire_subscription(owner)
    assert detail(client, owner_in.headers, complaint)["hasPhoto"] is True
    assert download(client, owner_in.headers, complaint).content == content


# An account with several records


@pytest.fixture
def second_complaint(prop, tenant, make_room, make_verified_tenant, make_complaint):
    """A complaint filed under a second record of the tenant's account."""
    other_room = make_room(prop, number="B2")
    record = make_verified_tenant(other_room, user=tenant.user)
    return make_complaint(record, other_room)


def test_a_tenant_attaches_a_photo_to_a_complaint_of_another_record(
    client, database, second_complaint, tenant_in
):
    response = upload(client, tenant_in.headers, second_complaint)
    assert response.status_code == 200, response.text
    assert response.json()["hasPhoto"] is True
    assert len(stored_photos(database)) == 1


def test_a_tenant_replaces_a_photo_of_a_complaint_of_another_record(
    client, database, second_complaint, tenant_in
):
    upload(client, tenant_in.headers, second_complaint, png(64))
    response = upload(
        client, tenant_in.headers, second_complaint, jpeg(), "image/jpeg", "photo.jpg"
    )
    assert response.status_code == 200, response.text
    (photo,) = stored_photos(database)
    assert photo.content_type == "image/jpeg"


def test_a_tenant_reads_the_photo_of_a_complaint_of_another_record(
    client, database, second_complaint, tenant_in
):
    content = png(128)
    upload(client, tenant_in.headers, second_complaint, content)
    response = download(client, tenant_in.headers, second_complaint)
    assert response.status_code == 200, response.text
    assert response.content == content
    assert detail(client, tenant_in.headers, second_complaint)["hasPhoto"] is True


def test_another_account_cannot_attach_a_photo_to_it(
    client, database, second_complaint, neighbour_in
):
    response = upload(client, neighbour_in.headers, second_complaint)
    assert_error(response, 404, "COMPLAINT_NOT_FOUND")
    assert stored_photos(database) == []


def test_the_photo_is_refused_once_the_complaint_of_another_record_moved_on(
    client, database, second_complaint, tenant_in, owner_in
):
    moved = client.post(
        f"{COMPLAINTS}/{second_complaint.id}/status-changes",
        json={"status": "inProgress"},
        headers=owner_in.headers,
    )
    assert moved.status_code == 201, moved.text
    response = upload(client, tenant_in.headers, second_complaint)
    assert_error(response, 409, "COMPLAINT_NOT_NEW")


# Contract
