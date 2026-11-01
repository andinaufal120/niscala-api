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
