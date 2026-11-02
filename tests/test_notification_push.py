"""Pushing a notification to the devices of its recipients."""

from datetime import UTC, datetime, timedelta
from itertools import count
from types import SimpleNamespace

import pytest
from notification_support import (
    ACTIVATION,
    CATEGORIES_BY_ROLE,
    awaiting_bill,
    change_complaint,
    dump,
    edit_session,
    items,
    mark_read,
    of_type,
    pay_cash,
    read_all,
    register_token,
    revoke_session,
    save_settings,
    stored_for,
    stored_rows,
    submit_complaint,
    unassign,
    upload_receipt,
    verify,
)
from rent_bill_support import days_ago

DEVICE = {"name": "Pixel 8", "platform": "Android 14"}
PASSWORD = "T7#vq9-lorem-ipsum"
STORED_CONTACTS = [
    ("Siti", "Ibu", "081234567890"),
    ("Agus", "Kakak", "08571234567"),
]
ROLE_OF = {"tenant_in": "tenant", "owner_in": "owner", "manager_in": "manager"}
TOKEN_OF = {
    "tenant_in": "tenant-device",
    "owner_in": "owner-device",
    "manager_in": "manager-device",
}

# event -> who is pushed: (account, category, notification type)
RECIPIENTS = {
    "paymentStatusChanged": [
        ("tenant_in", "paymentStatus", "paymentStatusChanged"),
    ],
    "complaintStatusChanged": [
        ("tenant_in", "complaintProgress", "complaintStatusChanged"),
    ],
    "complaintSubmitted": [
        ("owner_in", "newComplaint", "complaintSubmitted"),
        ("manager_in", "newComplaint", "complaintSubmitted"),
    ],
    "receiptUploaded": [
        ("owner_in", "receiptUpload", "receiptUploaded"),
        ("manager_in", "receiptUpload", "receiptUploaded"),
    ],
    "cashPaymentRecorded": [
        ("owner_in", "accountActivity", "cashPaymentRecorded"),
        ("tenant_in", "paymentStatus", "paymentStatusChanged"),
    ],
    "tenantActivated": [
        ("owner_in", "accountActivity", "tenantActivated"),
        ("manager_in", "accountActivity", "tenantActivated"),
    ],
    "managerActivated": [
        ("owner_in", "accountActivity", "managerActivated"),
    ],
}
EVENT_NAMES = list(RECIPIENTS)
RECIPIENT_CASES = [
    pytest.param(event, index, id=f"{event}-{who}")
    for event, recipients in RECIPIENTS.items()
    for index, (who, _, _) in enumerate(recipients)
]


@pytest.fixture
def tokens(client, scene):
    """Register a device token for the tenant, the owner and the manager."""
    for who, token in TOKEN_OF.items():
        register_token(client, getattr(scene, who), token)
    return TOKEN_OF


@pytest.fixture
def run_event(
    client,
    scene,
    make_rent_bill,
    make_complaint,
    make_tenant,
    make_manager,
    make_room,
    sent_emails,
):
    """Return a function that causes one of the notifying events."""

    def activate(token: str, name: str):
        return client.post(
            ACTIVATION,
            json={
                "token": token,
                "name": name,
                "email": f"{name.split()[0].lower()}@example.com",
                "password": PASSWORD,
                "device": DEVICE,
            },
        )

    runs = count()

    def period() -> dict:
        """Each run bills a period of its own, as a lease has one bill per period."""
        number = next(runs)
        return {} if number == 0 else {"period_start": days_ago(45 + 40 * number)}

    def run(name: str) -> None:
        lease = scene.tenant.lease
        if name == "paymentStatusChanged":
            bill = awaiting_bill(make_rent_bill, lease, **period())
            response = verify(client, scene.owner_in.headers, bill)
        elif name == "complaintStatusChanged":
            complaint = make_complaint(scene.tenant, scene.room)
            response = change_complaint(client, scene.owner_in.headers, complaint.id)
        elif name == "complaintSubmitted":
            response = submit_complaint(client, scene.tenant_in.headers)
        elif name == "receiptUploaded":
            response = upload_receipt(
                client, scene.tenant_in.headers, make_rent_bill(lease, **period())
            )
        elif name == "cashPaymentRecorded":
            response = pay_cash(
                client, scene.manager_in.headers, make_rent_bill(lease, **period())
            )
        elif name == "tenantActivated":
            newcomer = make_tenant(
                make_room(scene.prop, number="A2"),
                name="Nina New",
                contacts=STORED_CONTACTS,
            )
            response = activate(newcomer.token, "Nina New")
        else:
            invited = make_manager(scene.owner, [scene.prop], name="Dewi Manager")
            response = activate(invited.token, "Dewi Manager")
        assert response.status_code in (200, 201), response.text

    return run


def seen_by(client, scene, who: str, notification) -> dict:
    """The notification as the recipient's list shows it."""
    (found,) = [
        item
        for item in items(client, getattr(scene, who))
        if item["id"] == str(notification.id)
    ]
    return found


# Which notifications are pushed, and to whom


@pytest.mark.parametrize("event", EVENT_NAMES)
def test_an_event_pushes_to_every_recipient_with_the_category_on(
    client, database, scene, tokens, pushes, run_event, event
):
    run_event(event)
    expected = [tokens[who] for who, _, _ in RECIPIENTS[event]]
    assert sorted(pushes.tokens()) == sorted(expected)


@pytest.mark.parametrize("event", EVENT_NAMES)
def test_the_push_carries_the_notification_as_the_recipient_sees_it(
    client, database, scene, tokens, pushes, run_event, event
):
    run_event(event)
    for who, _, type_ in RECIPIENTS[event]:
        (sent,) = pushes.to(tokens[who])
        assert dump(sent) == seen_by(client, scene, who, sent)
        assert dump(sent)["type"] == type_
        assert dump(sent)["read"] is False


@pytest.mark.parametrize(("event", "index"), RECIPIENT_CASES)
def test_a_category_switched_off_stops_the_push_but_not_the_notification(
    client, database, scene, tokens, pushes, run_event, event, index
):
    who, category, type_ = RECIPIENTS[event][index]
    save_settings(client, getattr(scene, who), ROLE_OF[who], off=(category,))
    run_event(event)
    others = [tokens[w] for i, (w, _, _) in enumerate(RECIPIENTS[event]) if i != index]
    assert sorted(pushes.tokens()) == sorted(others)
    shown = of_type(client, getattr(scene, who), type_)
    assert len(shown) == 1
    assert shown[0]["read"] is False


@pytest.mark.parametrize(("event", "index"), RECIPIENT_CASES)
def test_only_the_matching_category_decides_the_push(
    client, database, scene, tokens, pushes, run_event, event, index
):
    who, category, _ = RECIPIENTS[event][index]
    others = tuple(c for c in CATEGORIES_BY_ROLE[ROLE_OF[who]] if c != category)
    save_settings(client, getattr(scene, who), ROLE_OF[who], off=others)
    run_event(event)
    assert tokens[who] in pushes.tokens()


@pytest.mark.parametrize(("event", "index"), RECIPIENT_CASES)
def test_the_settings_of_one_recipient_do_not_affect_another(
    client, database, scene, tokens, pushes, run_event, event, index
):
    who, category, _ = RECIPIENTS[event][index]
    save_settings(client, getattr(scene, who), ROLE_OF[who], off=(category,))
    run_event(event)
    for other, _, _ in RECIPIENTS[event]:
        if other != who:
            assert tokens[other] in pushes.tokens()


def test_switching_every_category_off_still_lists_the_notification(
    client, database, scene, tokens, pushes, run_event
):
    save_settings(
        client, scene.owner_in, "owner", off=tuple(CATEGORIES_BY_ROLE["owner"])
    )
    run_event("receiptUploaded")
    assert pushes.tokens() == [tokens["manager_in"]]
    assert len(of_type(client, scene.owner_in, "receiptUploaded")) == 1


def test_a_user_who_never_saved_settings_is_pushed(
    client, database, scene, tokens, pushes, run_event
):
    run_event("paymentStatusChanged")
    assert pushes.tokens() == [tokens["tenant_in"]]


def test_the_settings_of_another_user_with_the_same_role_do_not_apply(
    client, database, scene, tokens, pushes, run_event, make_user, sign_in
):
    stranger = sign_in(make_user(name="Other Owner"))
    save_settings(client, stranger, "owner", off=("receiptUpload",))
    run_event("receiptUploaded")
    assert tokens["owner_in"] in pushes.tokens()


def test_the_settings_apply_to_every_session_of_the_user(
    client, database, scene, tokens, pushes, run_event, sign_in
):
    tablet = sign_in(scene.owner, device_name="Galaxy Tab")
    register_token(client, tablet, "owner-tablet")
    save_settings(client, tablet, "owner", off=("receiptUpload",))
    run_event("receiptUploaded")
    assert pushes.tokens() == [tokens["manager_in"]]


# Which devices are pushed


def test_nobody_is_pushed_when_no_token_is_registered(
    client, database, scene, pushes, run_event
):
    run_event("receiptUploaded")
    assert pushes.attempts == []
    assert len(stored_rows(database)) == 2


def test_only_users_with_a_token_are_pushed(client, database, scene, pushes, run_event):
    register_token(client, scene.owner_in, "owner-device")
    run_event("receiptUploaded")
    assert pushes.tokens() == ["owner-device"]
    assert len(of_type(client, scene.manager_in, "receiptUploaded")) == 1


def test_every_live_session_with_a_token_is_pushed(
    client, database, scene, pushes, sign_in, run_event
):
    tablet = sign_in(scene.owner, device_name="Galaxy Tab")
    register_token(client, scene.owner_in, "owner-phone")
    register_token(client, tablet, "owner-tablet")
    run_event("receiptUploaded")
    assert sorted(pushes.tokens()) == ["owner-phone", "owner-tablet"]
    (on_phone,) = pushes.to("owner-phone")
    (on_tablet,) = pushes.to("owner-tablet")
    assert dump(on_phone) == dump(on_tablet)


def test_a_session_without_a_token_is_skipped(
    client, database, scene, pushes, sign_in, run_event
):
    sign_in(scene.owner, device_name="Galaxy Tab")
    register_token(client, scene.owner_in, "owner-phone")
    run_event("receiptUploaded")
    assert pushes.tokens() == ["owner-phone"]


def test_a_session_ended_in_the_database_is_skipped(
    client, database, scene, pushes, sign_in, run_event
):
    tablet = sign_in(scene.owner, device_name="Galaxy Tab")
    register_token(client, scene.owner_in, "owner-phone")
    register_token(client, tablet, "owner-tablet")
    revoke_session(database, tablet.session_id)
    run_event("receiptUploaded")
    assert pushes.tokens() == ["owner-phone"]


def test_a_session_ended_by_the_user_is_skipped(
    client, database, scene, pushes, sign_in, run_event
):
    tablet = sign_in(scene.owner, device_name="Galaxy Tab")
    register_token(client, scene.owner_in, "owner-phone")
    register_token(client, tablet, "owner-tablet")
    ended = client.delete(
        f"/me/sessions/{tablet.session_id}", headers=scene.owner_in.headers
    )
    assert ended.status_code == 204
    run_event("receiptUploaded")
    assert pushes.tokens() == ["owner-phone"]


def test_a_session_ended_by_logout_is_skipped(
    client, database, scene, pushes, run_event
):
    register_token(client, scene.owner_in, "owner-device")
    register_token(client, scene.manager_in, "manager-device")
    assert (
        client.post("/auth/logout", headers=scene.owner_in.headers).status_code == 204
    )
    run_event("receiptUploaded")
    assert pushes.tokens() == ["manager-device"]
    assert len(stored_for(database, scene.owner)) == 1


def test_a_session_idle_for_more_than_90_days_is_skipped(
    client, database, scene, pushes, sign_in, run_event
):
    tablet = sign_in(scene.owner, device_name="Galaxy Tab")
    register_token(client, scene.owner_in, "owner-phone")
    register_token(client, tablet, "owner-tablet")
    edit_session(
        database,
        tablet.session_id,
        last_active_at=datetime.now(UTC) - timedelta(days=91),
    )
    run_event("receiptUploaded")
    assert pushes.tokens() == ["owner-phone"]


def test_a_user_whose_only_session_ended_gets_no_push_but_keeps_the_notification(
    client, database, scene, pushes, run_event
):
    register_token(client, scene.owner_in, "owner-device")
    revoke_session(database, scene.owner_in.session_id)
    run_event("receiptUploaded")
    assert pushes.attempts == []
    assert len(stored_for(database, scene.owner)) == 1


def test_a_replaced_token_receives_the_push_instead_of_the_old_one(
    client, database, scene, pushes, run_event
):
    register_token(client, scene.owner_in, "owner-old")
    register_token(client, scene.owner_in, "owner-new")
    run_event("receiptUploaded")
    assert pushes.tokens() == ["owner-new"]


def test_a_token_registered_later_applies_to_later_events_only(
    client, database, scene, pushes, run_event
):
    run_event("receiptUploaded")
    register_token(client, scene.owner_in, "owner-device")
    assert pushes.attempts == []
    run_event("receiptUploaded")
    assert pushes.tokens() == ["owner-device"]
    (sent,) = pushes.to("owner-device")
    newest = items(client, scene.owner_in)[0]
    assert str(sent.id) == newest["id"]


def test_each_push_is_sent_once_per_device(
    client, database, scene, tokens, pushes, run_event
):
    run_event("receiptUploaded")
    assert len(pushes.attempts) == 2
    assert sorted(t for t, _ in pushes.attempts) == sorted(
        [tokens["owner_in"], tokens["manager_in"]]
    )


def test_reading_notifications_pushes_nothing(
    client, database, scene, tokens, pushes, run_event
):
    run_event("receiptUploaded")
    before = len(pushes.attempts)
    first = items(client, scene.owner_in)[0]
    mark_read(client, scene.owner_in, first["id"])
    read_all(client, scene.manager_in)
    items(client, scene.owner_in)
    assert len(pushes.attempts) == before


def test_a_manager_unassigned_before_the_event_is_not_pushed(
    client, database, scene, tokens, pushes, run_event
):
    unassign(database, scene.manager, scene.prop)
    run_event("receiptUploaded")
    assert pushes.tokens() == [tokens["owner_in"]]


# A failing push never fails the event


@pytest.mark.parametrize("event", EVENT_NAMES)
def test_a_sender_that_always_fails_does_not_fail_the_event(
    client, database, scene, tokens, pushes, run_event, event
):
    pushes.fail_all = True
    run_event(event)
    assert pushes.sent == []
    assert len(pushes.attempts) == len(RECIPIENTS[event])
    for who, _, type_ in RECIPIENTS[event]:
        assert len(of_type(client, getattr(scene, who), type_)) == 1


def test_a_failing_token_does_not_stop_the_pushes_to_the_others(
    client, database, scene, tokens, pushes, run_event
):
    pushes.fail_tokens = {tokens["owner_in"]}
    run_event("receiptUploaded")
    assert pushes.tokens() == [tokens["manager_in"]]
    assert sorted(t for t, _ in pushes.attempts) == sorted(
        [tokens["owner_in"], tokens["manager_in"]]
    )
    assert len(of_type(client, scene.owner_in, "receiptUploaded")) == 1


def test_a_failing_token_does_not_stop_the_other_devices_of_the_same_user(
    client, database, scene, pushes, sign_in, run_event
):
    tablet = sign_in(scene.owner, device_name="Galaxy Tab")
    register_token(client, scene.owner_in, "owner-phone")
    register_token(client, tablet, "owner-tablet")
    pushes.fail_tokens = {"owner-phone"}
    run_event("receiptUploaded")
    assert pushes.tokens() == ["owner-tablet"]
    assert len(pushes.attempts) == 2


def test_a_failing_push_leaves_the_notification_unread_and_listed(
    client, database, scene, tokens, pushes, run_event
):
    pushes.fail_all = True
    run_event("paymentStatusChanged")
    (item,) = items(client, scene.tenant_in)
    assert item["read"] is False


# Complaints under the urgency scope


def classifier_says(fake_classifier, urgency: str) -> None:
    from app.schemas.complaints import AiComplaintClassification

    fake_classifier.result = AiComplaintClassification(
        category="Listrik", urgency=urgency, suggested_action="Send an electrician."
    )


@pytest.fixture
def staff(client, scene, subscribe_owner, fake_classifier, pushes):
    """A subscribed owner and a manager with devices; records pushes at classification."""
    subscribe_owner(scene.owner, "basic")
    register_token(client, scene.owner_in, "owner-device")
    register_token(client, scene.manager_in, "manager-device")
    register_token(client, scene.tenant_in, "tenant-device")
    seen: list[list[str]] = []
    original = fake_classifier.classify

    def classify(description, categories):
        seen.append(sorted(pushes.tokens()))
        return original(description, categories)

    fake_classifier.classify = classify
    return SimpleNamespace(before_classification=seen)


def manager_listens_to(client, scene, scope: str, enabled: bool = True) -> None:
    off = () if enabled else ("newComplaint",)
    save_settings(client, scene.manager_in, "manager", off=off, scope=scope)


def test_a_high_urgency_complaint_is_pushed_to_high_only_recipients_after_classification(
    client, database, scene, staff, fake_classifier, pushes
):
    manager_listens_to(client, scene, "highOnly")
    classifier_says(fake_classifier, "high")
    assert submit_complaint(client, scene.tenant_in.headers).status_code == 201
    assert staff.before_classification == [["owner-device"]]
    assert sorted(pushes.tokens()) == ["manager-device", "owner-device"]


def test_the_late_push_is_the_notification_already_listed(
    client, database, scene, staff, fake_classifier, pushes
):
    manager_listens_to(client, scene, "highOnly")
    classifier_says(fake_classifier, "high")
    submit_complaint(client, scene.tenant_in.headers)
    (sent,) = pushes.to("manager-device")
    (listed,) = items(client, scene.manager_in)
    assert dump(sent)["id"] == listed["id"]
    assert dump(sent)["type"] == "complaintSubmitted"
    assert dump(sent)["read"] is False
    assert len(stored_for(database, scene.manager)) == 1


def test_recipients_of_all_urgencies_are_not_pushed_twice(
    client, database, scene, staff, fake_classifier, pushes
):
    manager_listens_to(client, scene, "highOnly")
    classifier_says(fake_classifier, "high")
    submit_complaint(client, scene.tenant_in.headers)
    assert len(pushes.to("owner-device")) == 1
    assert len(pushes.to("manager-device")) == 1
    assert len(stored_for(database, scene.owner)) == 1


@pytest.mark.parametrize("urgency", ["low", "medium"])
def test_a_complaint_of_lower_urgency_is_never_pushed_to_high_only_recipients(
    client, database, scene, staff, fake_classifier, pushes, urgency
):
    manager_listens_to(client, scene, "highOnly")
    classifier_says(fake_classifier, urgency)
    submit_complaint(client, scene.tenant_in.headers)
    assert pushes.tokens() == ["owner-device"]
    assert len(of_type(client, scene.manager_in, "complaintSubmitted")) == 1


@pytest.mark.parametrize("failure", ["error", "invalid_category"])
def test_a_failed_classification_is_never_pushed_to_high_only_recipients(
    client, database, scene, staff, fake_classifier, pushes, failure
):
    manager_listens_to(client, scene, "highOnly")
    if failure == "error":
        fake_classifier.error = RuntimeError("model down")
    else:
        from app.schemas.complaints import AiComplaintClassification

        fake_classifier.result = AiComplaintClassification(
            category="Astrologi", urgency="high", suggested_action="Look at the stars."
        )
    created = submit_complaint(client, scene.tenant_in.headers)
    assert created.status_code == 201
    assert pushes.tokens() == ["owner-device"]
    assert len(of_type(client, scene.manager_in, "complaintSubmitted")) == 1


def test_a_complaint_without_a_subscription_is_pushed_to_all_urgency_recipients_only(
    client, database, scene, pushes
):
    register_token(client, scene.owner_in, "owner-device")
    register_token(client, scene.manager_in, "manager-device")
    manager_listens_to(client, scene, "highOnly")
    created = submit_complaint(client, scene.tenant_in.headers).json()
    assert created["classificationState"] == "notClassified"
    assert pushes.tokens() == ["owner-device"]
    assert len(of_type(client, scene.manager_in, "complaintSubmitted")) == 1


def test_recipients_of_all_urgencies_are_pushed_at_submission_whatever_the_urgency(
    client, database, scene, staff, fake_classifier, pushes
):
    classifier_says(fake_classifier, "low")
    submit_complaint(client, scene.tenant_in.headers)
    assert staff.before_classification == [["manager-device", "owner-device"]]
    assert sorted(pushes.tokens()) == ["manager-device", "owner-device"]


def test_a_failed_classification_still_pushes_to_all_urgency_recipients(
    client, database, scene, staff, fake_classifier, pushes
):
    fake_classifier.error = RuntimeError("model down")
    submit_complaint(client, scene.tenant_in.headers)
    assert sorted(pushes.tokens()) == ["manager-device", "owner-device"]


def test_every_high_only_recipient_is_pushed_after_a_high_urgency_classification(
    client, database, scene, staff, fake_classifier, pushes
):
    save_settings(client, scene.owner_in, "owner", scope="highOnly")
    manager_listens_to(client, scene, "highOnly")
    classifier_says(fake_classifier, "high")
    submit_complaint(client, scene.tenant_in.headers)
    assert staff.before_classification == [[]]
    assert sorted(pushes.tokens()) == ["manager-device", "owner-device"]


def test_high_only_recipients_get_nothing_from_a_low_urgency_complaint(
    client, database, scene, staff, fake_classifier, pushes
):
    save_settings(client, scene.owner_in, "owner", scope="highOnly")
    manager_listens_to(client, scene, "highOnly")
    classifier_says(fake_classifier, "low")
    submit_complaint(client, scene.tenant_in.headers)
    assert pushes.attempts == []
    assert len(of_type(client, scene.owner_in, "complaintSubmitted")) == 1
    assert len(of_type(client, scene.manager_in, "complaintSubmitted")) == 1


def test_every_device_of_a_high_only_recipient_is_pushed_after_classification(
    client, database, scene, staff, fake_classifier, pushes, sign_in
):
    tablet = sign_in(scene.manager, device_name="Galaxy Tab")
    register_token(client, tablet, "manager-tablet")
    manager_listens_to(client, scene, "highOnly")
    classifier_says(fake_classifier, "high")
    submit_complaint(client, scene.tenant_in.headers)
    assert sorted(pushes.tokens()) == [
        "manager-device",
        "manager-tablet",
        "owner-device",
    ]


@pytest.mark.parametrize("scope", ["allUrgencies", "highOnly"])
@pytest.mark.parametrize("urgency", ["low", "high"])
def test_a_recipient_with_the_category_off_is_never_pushed(
    client, database, scene, staff, fake_classifier, pushes, scope, urgency
):
    manager_listens_to(client, scene, scope, enabled=False)
    classifier_says(fake_classifier, urgency)
    submit_complaint(client, scene.tenant_in.headers)
    assert "manager-device" not in pushes.tokens()
    assert len(of_type(client, scene.manager_in, "complaintSubmitted")) == 1


def test_the_tenant_is_never_pushed_about_their_own_complaint(
    client, database, scene, staff, fake_classifier, pushes
):
    classifier_says(fake_classifier, "high")
    submit_complaint(client, scene.tenant_in.headers)
    assert "tenant-device" not in pushes.tokens()


def test_a_failing_sender_does_not_fail_the_submission_or_the_classification(
    client, database, scene, staff, fake_classifier, pushes
):
    pushes.fail_all = True
    manager_listens_to(client, scene, "highOnly")
    classifier_says(fake_classifier, "high")
    created = submit_complaint(client, scene.tenant_in.headers)
    assert created.status_code == 201
    detail = client.get(
        f"/complaints/{created.json()['id']}", headers=scene.owner_in.headers
    )
    assert detail.json()["classification"]["urgency"] == "high"
    assert len(pushes.attempts) == 2


# Pushes go out only after the event is committed


def recording_stored_ids(database, pushes) -> list[set[str]]:
    """Make each send note which notifications were committed at that moment."""
    seen: list[set[str]] = []

    def note(token, notification):
        seen.append({str(row["id"]) for row in stored_rows(database)})

    pushes.before_send = note
    return seen


def notify_owner(db, scene, type_: str = "receiptUploaded") -> None:
    from app.schemas.notifications import NotificationType
    from app.services import notifications

    notifications.notify(db, [scene.owner.id], NotificationType(type_), scene.prop.id)


@pytest.mark.parametrize("event", EVENT_NAMES)
def test_every_push_is_sent_once_its_notification_is_committed(
    client, database, scene, tokens, pushes, run_event, event
):
    seen = recording_stored_ids(database, pushes)
    run_event(event)
    assert len(seen) == len(RECIPIENTS[event])
    for committed, (_, notification) in zip(seen, pushes.attempts, strict=True):
        assert str(notification.id) in committed


def test_a_push_is_not_sent_before_the_commit_and_is_sent_after_it(
    client, database, scene, pushes, db_session
):
    register_token(client, scene.owner_in, "owner-device")
    notify_owner(db_session, scene)
    assert pushes.attempts == []
    db_session.flush()
    assert pushes.attempts == []
    db_session.commit()
    assert pushes.tokens() == ["owner-device"]


def test_the_pushed_notification_is_the_one_that_was_stored(
    client, database, scene, pushes, db_session
):
    register_token(client, scene.owner_in, "owner-device")
    notify_owner(db_session, scene)
    db_session.commit()
    (sent,) = pushes.to("owner-device")
    (stored,) = stored_for(database, scene.owner)
    assert sent.id == stored["id"]
    assert dump(sent) == items(client, scene.owner_in)[0]


def test_a_rolled_back_session_sends_nothing(
    client, database, scene, pushes, db_session
):
    register_token(client, scene.owner_in, "owner-device")
    notify_owner(db_session, scene)
    db_session.rollback()
    db_session.commit()
    assert pushes.attempts == []
    assert stored_rows(database) == []


def test_a_rollback_drops_the_queued_pushes_but_not_the_later_ones(
    client, database, scene, pushes, db_session
):
    register_token(client, scene.owner_in, "owner-device")
    notify_owner(db_session, scene, "receiptUploaded")
    db_session.rollback()
    notify_owner(db_session, scene, "tenantActivated")
    db_session.commit()
    (sent,) = pushes.to("owner-device")
    assert dump(sent)["type"] == "tenantActivated"
    assert len(stored_for(database, scene.owner)) == 1


def test_several_notifications_in_one_transaction_are_all_sent_after_the_commit(
    client, database, scene, pushes, db_session
):
    register_token(client, scene.owner_in, "owner-device")
    notify_owner(db_session, scene, "receiptUploaded")
    notify_owner(db_session, scene, "tenantActivated")
    assert pushes.attempts == []
    db_session.commit()
    assert sorted(dump(n)["type"] for n in pushes.to("owner-device")) == [
        "receiptUploaded",
        "tenantActivated",
    ]


def test_a_later_commit_does_not_send_the_same_push_again(
    client, database, scene, pushes, db_session
):
    register_token(client, scene.owner_in, "owner-device")
    notify_owner(db_session, scene)
    db_session.commit()
    db_session.commit()
    notify_owner(db_session, scene, "tenantActivated")
    db_session.commit()
    assert [dump(n)["type"] for n in pushes.to("owner-device")] == [
        "receiptUploaded",
        "tenantActivated",
    ]


def test_a_released_savepoint_does_not_send_the_push(
    client, database, scene, pushes, db_session
):
    register_token(client, scene.owner_in, "owner-device")
    with db_session.begin_nested():
        notify_owner(db_session, scene)
    assert pushes.attempts == []
    db_session.commit()
    assert pushes.tokens() == ["owner-device"]


def test_another_sessions_commit_does_not_send_the_pushes_queued_here(
    client, database, scene, pushes, db_session
):
    from sqlalchemy.orm import Session

    register_token(client, scene.owner_in, "owner-device")
    notify_owner(db_session, scene)
    with Session(database) as other:
        other.commit()
    assert pushes.attempts == []
    db_session.commit()
    assert pushes.tokens() == ["owner-device"]


def test_a_failing_sender_does_not_make_the_commit_fail(
    client, database, scene, pushes, db_session
):
    register_token(client, scene.owner_in, "owner-device")
    pushes.fail_all = True
    notify_owner(db_session, scene)
    db_session.commit()
    assert len(pushes.attempts) == 1
    assert len(stored_for(database, scene.owner)) == 1


def test_a_commit_tries_every_device_even_when_all_of_them_fail(
    client, database, scene, pushes, db_session, sign_in
):
    tablet = sign_in(scene.owner, device_name="Galaxy Tab")
    register_token(client, scene.owner_in, "owner-phone")
    register_token(client, tablet, "owner-tablet")
    pushes.fail_tokens = {"owner-phone", "owner-tablet"}
    notify_owner(db_session, scene)
    db_session.commit()
    assert sorted(t for t, _ in pushes.attempts) == ["owner-phone", "owner-tablet"]


def failing_after_the_event(monkeypatch, error: Exception) -> None:
    """Make the complaint status change fail once its notification was queued."""

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr("app.services.complaints._detail", fail)


def test_a_request_that_fails_with_a_client_error_after_notifying_sends_no_push(
    client, database, scene, tokens, pushes, make_complaint, monkeypatch
):
    from app.errors import ApiError

    complaint = make_complaint(scene.tenant, scene.room)
    failing_after_the_event(monkeypatch, ApiError(409, "COMPLAINT_STATUS_NOT_NEXT"))
    response = change_complaint(client, scene.owner_in.headers, complaint.id)
    assert response.status_code == 409
    assert pushes.attempts == []
    assert stored_rows(database) == []


def test_a_request_that_fails_with_a_server_error_after_notifying_sends_no_push(
    app, database, scene, tokens, pushes, make_complaint, monkeypatch
):
    from fastapi.testclient import TestClient

    complaint = make_complaint(scene.tenant, scene.room)
    failing_after_the_event(monkeypatch, RuntimeError("boom"))
    response = change_complaint(
        TestClient(app, raise_server_exceptions=False),
        scene.owner_in.headers,
        complaint.id,
    )
    assert response.status_code == 500
    assert pushes.attempts == []
    assert stored_rows(database) == []


def test_the_same_event_pushes_once_the_request_succeeds(
    client, database, scene, tokens, pushes, make_complaint
):
    complaint = make_complaint(scene.tenant, scene.room)
    response = change_complaint(client, scene.owner_in.headers, complaint.id)
    assert response.status_code == 201
    assert pushes.tokens() == [tokens["tenant_in"]]


def test_a_rejected_request_sends_no_push(
    client, database, scene, tokens, pushes, make_complaint
):
    complaint = make_complaint(scene.tenant, scene.room)
    response = change_complaint(
        client, scene.owner_in.headers, complaint.id, status="done"
    )
    assert response.status_code == 409
    assert pushes.attempts == []


# A dead device token is removed from its session


def token_of(read_session, signed_in) -> str | None:
    return read_session(signed_in.session_id).push_token


@pytest.mark.parametrize("event", EVENT_NAMES)
def test_a_dead_token_is_removed_from_its_session_after_any_event(
    client, database, scene, tokens, pushes, run_event, read_session, event
):
    dead_who, _, _ = RECIPIENTS[event][0]
    pushes.invalid_tokens = {tokens[dead_who]}
    run_event(event)
    assert token_of(read_session, getattr(scene, dead_who)) is None


def test_only_the_session_with_the_dead_token_loses_its_token(
    client, database, scene, tokens, pushes, run_event, read_session
):
    pushes.invalid_tokens = {tokens["owner_in"]}
    run_event("receiptUploaded")
    assert token_of(read_session, scene.owner_in) is None
    assert token_of(read_session, scene.manager_in) == tokens["manager_in"]
    assert token_of(read_session, scene.tenant_in) == tokens["tenant_in"]


def test_a_dead_token_does_not_stop_the_pushes_to_the_other_recipients(
    client, database, scene, tokens, pushes, run_event
):
    pushes.invalid_tokens = {tokens["owner_in"]}
    run_event("receiptUploaded")
    assert pushes.tokens() == [tokens["manager_in"]]
    assert sorted(t for t, _ in pushes.attempts) == sorted(
        [tokens["owner_in"], tokens["manager_in"]]
    )


def test_a_dead_token_leaves_the_other_sessions_of_the_same_user_untouched(
    client, database, scene, pushes, sign_in, run_event, read_session
):
    tablet = sign_in(scene.owner, device_name="Galaxy Tab")
    register_token(client, scene.owner_in, "owner-phone")
    register_token(client, tablet, "owner-tablet")
    pushes.invalid_tokens = {"owner-phone"}
    run_event("receiptUploaded")
    assert pushes.tokens() == ["owner-tablet"]
    assert token_of(read_session, scene.owner_in) is None
    assert token_of(read_session, tablet) == "owner-tablet"


def test_every_dead_token_of_one_event_is_removed(
    client, database, scene, tokens, pushes, run_event, read_session
):
    pushes.invalid_tokens = set(tokens.values())
    run_event("receiptUploaded")
    assert pushes.tokens() == []
    assert token_of(read_session, scene.owner_in) is None
    assert token_of(read_session, scene.manager_in) is None
    assert token_of(read_session, scene.tenant_in) == tokens["tenant_in"]


def test_a_dead_token_keeps_the_notification_unread_and_listed(
    client, database, scene, tokens, pushes, run_event
):
    pushes.invalid_tokens = set(tokens.values())
    run_event("receiptUploaded")
    for who in ("owner_in", "manager_in"):
        (item,) = of_type(client, getattr(scene, who), "receiptUploaded")
        assert item["read"] is False
    assert len(stored_rows(database)) == 2


def test_a_removed_token_receives_no_push_for_later_events(
    client, database, scene, tokens, pushes, run_event
):
    pushes.invalid_tokens = {tokens["owner_in"]}
    run_event("receiptUploaded")
    run_event("receiptUploaded")
    assert [t for t, _ in pushes.attempts].count(tokens["owner_in"]) == 1
    assert pushes.tokens() == [tokens["manager_in"]] * 2


def test_a_session_registers_a_new_token_after_its_old_one_was_removed(
    client, database, scene, tokens, pushes, run_event, read_session
):
    pushes.invalid_tokens = {tokens["owner_in"]}
    run_event("receiptUploaded")
    register_token(client, scene.owner_in, "owner-fresh")
    run_event("receiptUploaded")
    assert pushes.to("owner-fresh")
    assert token_of(read_session, scene.owner_in) == "owner-fresh"


def test_a_token_registered_meanwhile_survives_the_removal_of_the_old_one(
    client, database, scene, tokens, pushes, run_event, read_session
):
    def replace_while_sending(token, notification):
        if token == tokens["owner_in"]:
            edit_session(database, scene.owner_in.session_id, push_token="owner-new")

    pushes.before_send = replace_while_sending
    pushes.invalid_tokens = {tokens["owner_in"]}
    run_event("receiptUploaded")
    assert token_of(read_session, scene.owner_in) == "owner-new"


def test_a_token_that_became_null_meanwhile_stays_null(
    client, database, scene, tokens, pushes, run_event, read_session
):
    def clear_while_sending(token, notification):
        if token == tokens["owner_in"]:
            edit_session(database, scene.owner_in.session_id, push_token=None)

    pushes.before_send = clear_while_sending
    pushes.invalid_tokens = {tokens["owner_in"]}
    run_event("receiptUploaded")
    assert token_of(read_session, scene.owner_in) is None
    assert token_of(read_session, scene.manager_in) == tokens["manager_in"]


def test_removing_a_dead_token_does_not_touch_the_session_otherwise(
    client, database, scene, tokens, pushes, run_event, read_session
):
    before = read_session(scene.owner_in.session_id)
    pushes.invalid_tokens = {tokens["owner_in"]}
    run_event("receiptUploaded")
    after = read_session(scene.owner_in.session_id)
    assert after.revoked_at is None
    assert after.user_id == before.user_id
    assert after.last_active_at == before.last_active_at


def test_the_owner_still_uses_the_session_whose_token_was_removed(
    client, database, scene, tokens, pushes, run_event
):
    pushes.invalid_tokens = {tokens["owner_in"]}
    run_event("receiptUploaded")
    assert (
        client.get("/notifications", headers=scene.owner_in.headers).status_code == 200
    )


@pytest.mark.parametrize("event", EVENT_NAMES)
def test_other_send_errors_keep_the_token(
    client, database, scene, tokens, pushes, run_event, read_session, event
):
    pushes.fail_all = True
    run_event(event)
    for who, _, _ in RECIPIENTS[event]:
        assert token_of(read_session, getattr(scene, who)) == tokens[who]


def test_a_failing_token_is_tried_again_for_the_next_event(
    client, database, scene, tokens, pushes, run_event
):
    pushes.fail_tokens = {tokens["owner_in"]}
    run_event("receiptUploaded")
    run_event("receiptUploaded")
    assert [t for t, _ in pushes.attempts].count(tokens["owner_in"]) == 2


def test_a_dead_token_and_a_failing_token_are_told_apart(
    client, database, scene, tokens, pushes, run_event, read_session
):
    pushes.invalid_tokens = {tokens["owner_in"]}
    pushes.fail_tokens = {tokens["manager_in"]}
    run_event("receiptUploaded")
    assert token_of(read_session, scene.owner_in) is None
    assert token_of(read_session, scene.manager_in) == tokens["manager_in"]


def test_a_token_of_a_recipient_with_the_category_off_is_never_tried_or_removed(
    client, database, scene, tokens, pushes, run_event, read_session
):
    save_settings(client, scene.manager_in, "manager", off=("receiptUpload",))
    pushes.invalid_tokens = {tokens["manager_in"]}
    run_event("receiptUploaded")
    assert tokens["manager_in"] not in [t for t, _ in pushes.attempts]
    assert token_of(read_session, scene.manager_in) == tokens["manager_in"]


# Delivery through FCM end to end


@pytest.fixture
def fcm_configured(firebase_credentials, fake_firebase, fcm):
    firebase_credentials(
        '{"type": "service_account", "project_id": "niscala-test", "private_key_id": "1"}'
    )
    return fcm


@pytest.mark.parametrize("event", EVENT_NAMES)
def test_an_event_is_delivered_to_fcm_with_the_message_for_its_type(
    client, database, scene, tokens, fcm_configured, run_event, event
):
    run_event(event)
    expected = {tokens[who]: type_ for who, _, type_ in RECIPIENTS[event]}
    assert sorted(fcm_configured.tokens()) == sorted(expected)
    for message, _ in fcm_configured.sent:
        type_ = expected[message.token]
        assert message.data["type"] == type_
        assert message.android.notification.title_loc_key == (
            f"notification_{type_}_title"
        )
        assert message.android.notification.body_loc_key == f"notification_{type_}_body"
        assert message.android.priority == "high"


def test_the_fcm_message_names_the_notification_the_recipient_can_fetch(
    client, database, scene, tokens, fcm_configured, run_event
):
    run_event("receiptUploaded")
    for message, _ in fcm_configured.sent:
        who = next(w for w, t in tokens.items() if t == message.token)
        assert (
            message.data["notificationId"]
            == items(client, getattr(scene, who))[0]["id"]
        )


def test_a_token_fcm_reports_unregistered_is_removed_through_the_real_sender(
    client, database, scene, tokens, fcm_configured, run_event, read_session
):
    from firebase_admin import messaging

    fcm_configured.errors[tokens["owner_in"]] = messaging.UnregisteredError("gone")
    run_event("receiptUploaded")
    assert token_of(read_session, scene.owner_in) is None
    assert token_of(read_session, scene.manager_in) == tokens["manager_in"]
    assert len(of_type(client, scene.owner_in, "receiptUploaded")) == 1


def test_a_token_fcm_reports_invalid_is_removed_through_the_real_sender(
    client, database, scene, tokens, fcm_configured, run_event, read_session
):
    from firebase_admin import exceptions

    fcm_configured.errors[tokens["owner_in"]] = exceptions.InvalidArgumentError("bad")
    run_event("receiptUploaded")
    assert token_of(read_session, scene.owner_in) is None


def test_an_fcm_outage_keeps_the_token_and_the_notification(
    client, database, scene, tokens, fcm_configured, run_event, read_session
):
    from firebase_admin import exceptions

    fcm_configured.error = exceptions.UnavailableError("down")
    run_event("receiptUploaded")
    assert len(fcm_configured.sent) == 2
    assert token_of(read_session, scene.owner_in) == tokens["owner_in"]
    assert token_of(read_session, scene.manager_in) == tokens["manager_in"]
    assert len(of_type(client, scene.owner_in, "receiptUploaded")) == 1


def test_one_device_failing_at_fcm_does_not_stop_the_others(
    client, database, scene, tokens, fcm_configured, run_event
):
    fcm_configured.errors[tokens["owner_in"]] = RuntimeError("socket closed")
    run_event("receiptUploaded")
    assert sorted(fcm_configured.tokens()) == sorted(
        [tokens["owner_in"], tokens["manager_in"]]
    )


def test_unusable_credentials_do_not_fail_the_event_or_lose_the_notification(
    client, database, scene, tokens, run_event, firebase_credentials, fake_firebase
):
    firebase_credentials("this is not json")
    run_event("receiptUploaded")
    assert len(of_type(client, scene.owner_in, "receiptUploaded")) == 1
    assert len(of_type(client, scene.manager_in, "receiptUploaded")) == 1


def test_without_credentials_an_event_is_only_logged(
    client,
    database,
    scene,
    tokens,
    run_event,
    firebase_credentials,
    fake_firebase,
    caplog,
):
    firebase_credentials()
    with caplog.at_level("INFO"):
        run_event("receiptUploaded")
    assert fake_firebase.initializations == []
    assert tokens["owner_in"] in caplog.text
    assert tokens["manager_in"] in caplog.text


# The late push for a high-urgency complaint uses the same path


def test_the_late_push_is_sent_after_the_classification_is_committed(
    client, database, scene, staff, fake_classifier, pushes
):
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    urgencies: list[str | None] = []

    def note(token, notification):
        if token != "manager-device":
            return
        with Session(database) as db:
            urgencies.append(
                db.execute(
                    text("SELECT ai_urgency FROM complaints WHERE id = :id"),
                    {"id": notification.complaint.complaint_id},
                ).scalar_one()
            )

    pushes.before_send = note
    manager_listens_to(client, scene, "highOnly")
    classifier_says(fake_classifier, "high")
    submit_complaint(client, scene.tenant_in.headers)
    assert urgencies == ["high"]


def test_a_dead_token_found_by_the_late_push_is_removed(
    client, database, scene, staff, fake_classifier, pushes, read_session
):
    manager_listens_to(client, scene, "highOnly")
    classifier_says(fake_classifier, "high")
    pushes.invalid_tokens = {"manager-device"}
    assert submit_complaint(client, scene.tenant_in.headers).status_code == 201
    assert token_of(read_session, scene.manager_in) is None
    assert token_of(read_session, scene.owner_in) == "owner-device"
    assert len(of_type(client, scene.manager_in, "complaintSubmitted")) == 1


def test_a_dead_token_found_at_submission_is_removed_before_the_late_push(
    client, database, scene, staff, fake_classifier, pushes, read_session
):
    pushes.invalid_tokens = {"owner-device"}
    classifier_says(fake_classifier, "high")
    submit_complaint(client, scene.tenant_in.headers)
    assert token_of(read_session, scene.owner_in) is None
    assert pushes.tokens() == ["manager-device"]


def test_a_failing_late_push_keeps_the_token_and_the_classification(
    client, database, scene, staff, fake_classifier, pushes, read_session
):
    manager_listens_to(client, scene, "highOnly")
    classifier_says(fake_classifier, "high")
    pushes.fail_tokens = {"manager-device"}
    created = submit_complaint(client, scene.tenant_in.headers)
    assert created.status_code == 201
    assert token_of(read_session, scene.manager_in) == "manager-device"
    detail = client.get(
        f"/complaints/{created.json()['id']}", headers=scene.owner_in.headers
    )
    assert detail.json()["classification"]["urgency"] == "high"
