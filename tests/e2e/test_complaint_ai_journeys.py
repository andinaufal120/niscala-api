"""End-to-end journeys of complaint classification by the AI and by hand."""

CATEGORIES = [
    "Listrik",
    "Air",
    "Bangunan",
    "Perabot",
    "Kebersihan",
    "Keamanan",
    "Internet",
    "Lainnya",
]


def assert_error(response, status, code, field=None):
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code, body
    assert body["field"] == field, body


def ids(items):
    return [item["id"] for item in items]


def of_type(notifications, type_):
    return [n for n in notifications if n["type"] == type_]


def file_classified(world, tenant, room, text, category, urgency):
    """Submit a complaint that the working classifier answers as given."""
    world.stubs.classifier_works(
        category=category,
        urgency=urgency,
        suggested_action=f"Look into the {category}.",
    )
    return tenant.submit_complaint(room, text)


def file_unclassified(world, tenant, room, text):
    """Submit a complaint while the classifier is down."""
    world.stubs.classifier_unavailable()
    return tenant.submit_complaint(room, text)


def classify(person, complaint, category, urgency, **kwargs):
    return person.put(
        f"/complaints/{complaint['id']}/classification",
        json={"category": category, "urgency": urgency},
        **kwargs,
    )


def move_to(person, complaint, status, note=None):
    body = (
        {"status": status} if note is None else {"status": status, "handlingNote": note}
    )
    return person.post(
        f"/complaints/{complaint['id']}/status-changes", json=body, expect=201
    ).json()


def set_scope(person, scope, *, categories):
    """Save the push settings with the given urgency scope for new complaints."""
    items = [
        {
            "category": category,
            "pushEnabled": True,
            "urgencyScope": scope if category == "newComplaint" else None,
        }
        for category in categories
    ]
    person.put("/me/notification-settings", json={"items": items}, expect=200)


STAFF_CATEGORIES = ["newComplaint", "receiptUpload", "overdueBill", "accountActivity"]


def watch_pushes(world, *devices):
    """Record the pushes each device has had when every classification starts."""
    seen = []
    original = world.stubs.classifier.classify

    def classify_and_record(description, categories):
        seen.append({d: list(world.stubs.pushes_to(d)) for d in devices})
        return original(description, categories)

    world.stubs.classifier.classify = classify_and_record
    return seen


def find(items, complaint):
    return next(item for item in items if item["id"] == complaint["id"])


# Classification by the AI


def test_complaints_are_classified_after_saving_and_listed_by_urgency_then_newest_first(
    seeded_world, world
):
    owner, manager, budi, sari = (
        seeded_world.owner,
        seeded_world.manager,
        seeded_world.budi,
        seeded_world.sari,
    )
    a1, a2 = seeded_world.rooms["A1"], seeded_world.rooms["A2"]
    seed = seeded_world.complaint
    medium_old = file_classified(
        world, budi, a1, "The tap in the kitchen leaks.", "Air", "medium"
    )
    low = file_classified(
        world, sari, a2, "The corridor needs sweeping.", "Kebersihan", "low"
    )
    waiting_old = file_unclassified(world, budi, a1, "The lamp in the hall is dim.")
    high_new = file_classified(
        world, sari, a2, "The gate lock does not close.", "Keamanan", "high"
    )
    medium_new = file_classified(
        world, budi, a1, "The wardrobe door fell off.", "Perabot", "medium"
    )
    waiting_new = file_unclassified(world, sari, a2, "The wifi keeps dropping.")

    assert medium_old["classificationState"] == "classifying"
    assert medium_old["classification"] is None
    expected = [
        high_new,
        seed,
        medium_new,
        medium_old,
        low,
        waiting_new,
        waiting_old,
    ]
    for staff in (owner, manager):
        listed = staff.complaints()
        assert ids(listed) == ids(expected)
        shown = find(listed, high_new)
        assert shown["classification"] == {
            "category": "Keamanan",
            "urgency": "high",
            "suggestedAction": "Look into the Keamanan.",
            "classifiedByName": None,
            "originalAiClassification": None,
        }
        assert shown["classificationState"] is None
        assert shown["classificationWithheld"] is False
        assert find(listed, low)["classification"]["urgency"] == "low"
        assert find(listed, seed)["classification"]["category"] == "Listrik"
        for waiting in (waiting_new, waiting_old):
            shown = find(listed, waiting)
            assert shown["classification"] is None
            assert shown["classificationState"] == "awaitingClassification"
            assert shown["classificationWithheld"] is False
            assert shown["status"] == "new"
    detail = owner.complaint(medium_new)
    assert detail["classification"]["category"] == "Perabot"
    assert detail["classification"]["urgency"] == "medium"
    assert detail["classificationState"] is None

    assert ids(budi.complaints()) == ids([medium_new, waiting_old, medium_old, seed])
    assert ids(sari.complaints()) == ids([waiting_new, high_new, low])


def test_a_push_for_a_new_complaint_follows_the_urgency_scope_of_each_recipient(
    seeded_world, world, expire_subscription
):
    owner, manager, budi = seeded_world.owner, seeded_world.manager, seeded_world.budi
    room = seeded_world.rooms["A1"]
    owner.enable_push("device-rina")
    manager.enable_push("device-mira")
    seen = watch_pushes(world, "device-rina", "device-mira")
    rina, mira = "device-rina", "device-mira"
    pushed = ["complaintSubmitted"]
    assert [
        (i["category"], i["urgencyScope"])
        for i in owner.read("/me/notification-settings")["items"]
        if i["category"] == "newComplaint"
    ] == [("newComplaint", "allUrgencies")]
    set_scope(owner, "highOnly", categories=STAFF_CATEGORIES)

    medium = file_classified(
        world, budi, room, "The ceiling stain grows.", "Air", "medium"
    )

    assert seen[-1] == {rina: [], mira: pushed}
    assert world.stubs.pushes_to(rina) == []
    assert world.stubs.pushes_to(mira) == pushed
    [announced] = [
        n
        for n in of_type(owner.notifications(), "complaintSubmitted")
        if n["complaint"]["complaintId"] == medium["id"]
    ]
    assert announced["complaint"]["urgency"] is None
    assert owner.complaint(medium)["classification"]["urgency"] == "medium"

    high = file_classified(
        world, budi, room, "Sparks come from the socket.", "Listrik", "high"
    )

    assert seen[-1] == {rina: [], mira: pushed * 2}
    assert world.stubs.pushes_to(rina) == pushed
    assert world.stubs.pushes_to(mira) == pushed * 2
    [announced] = [
        n
        for n in of_type(owner.notifications(), "complaintSubmitted")
        if n["complaint"]["complaintId"] == high["id"]
    ]
    assert announced["complaint"]["category"] is None
    assert announced["complaint"]["urgency"] is None

    unclassified = file_unclassified(world, budi, room, "The mirror is cracked.")

    assert world.stubs.pushes_to(rina) == pushed
    assert world.stubs.pushes_to(mira) == pushed * 3
    assert find(owner.complaints(), unclassified)["classificationState"] == (
        "awaitingClassification"
    )
    assert any(
        n["complaint"]["complaintId"] == unclassified["id"]
        for n in of_type(owner.notifications(), "complaintSubmitted")
    )

    set_scope(owner, "allUrgencies", categories=STAFF_CATEGORIES)
    file_classified(world, budi, room, "The shelf is loose.", "Perabot", "low")

    assert seen[-1] == {rina: pushed * 2, mira: pushed * 4}
    assert world.stubs.pushes_to(rina) == pushed * 2
    assert world.stubs.pushes_to(mira) == pushed * 4

    set_scope(owner, "highOnly", categories=STAFF_CATEGORIES)
    expire_subscription(owner.namespace)
    calls = len(seen)

    skipped = budi.submit_complaint(room, "The door handle came off.")

    assert skipped["classificationState"] == "notClassified"
    assert len(seen) == calls
    assert world.stubs.pushes_to(rina) == pushed * 2
    assert world.stubs.pushes_to(mira) == pushed * 5
    assert any(
        n["complaint"]["complaintId"] == skipped["id"]
        for n in of_type(owner.notifications(), "complaintSubmitted")
    )


# Classification by hand


def test_a_failing_classifier_never_blocks_a_complaint_and_management_classifies_by_hand(
    seeded_world, world
):
    owner, manager, budi = seeded_world.owner, seeded_world.manager, seeded_world.budi
    room = seeded_world.rooms["A1"]

    first = file_unclassified(world, budi, room, "The fan makes a grinding noise.")
    world.stubs.classifier_times_out()
    second = budi.submit_complaint(room, "The curtain rail fell down.")

    assert first["classificationState"] == "classifying"
    assert second["classificationState"] == "classifying"
    for complaint in (first, second):
        for person in (budi, owner, manager):
            shown = person.complaint(complaint)
            assert shown["status"] == "new"
            assert shown["classification"] is None
            assert shown["classificationState"] == "awaitingClassification"
            assert shown["classificationWithheld"] is False
    assert len(owner.complaints()) == 3

    progress = move_to(owner, second, "inProgress", "Carpenter called.")
    assert progress["status"] == "inProgress"
    assert progress["classificationState"] == "awaitingClassification"

    assert owner.read("/complaint-categories")["items"] == CATEGORIES
    assert budi.read("/complaint-categories")["items"] == CATEGORIES
    for bad in ("Plumbing", "listrik"):
        assert_error(
            classify(owner, first, bad, "high"),
            422,
            "COMPLAINT_CATEGORY_INVALID",
            "category",
        )
    assert_error(classify(budi, first, "Air", "high"), 403, "FORBIDDEN")
    shown = owner.complaint(first)
    assert shown["classification"] is None
    assert shown["classificationState"] == "awaitingClassification"

    by_hand = classify(manager, first, "Perabot", "medium", expect=200).json()

    assert by_hand["classification"] == {
        "category": "Perabot",
        "urgency": "medium",
        "suggestedAction": None,
        "classifiedByName": "Mira Manager",
        "originalAiClassification": None,
    }
    assert by_hand["classificationState"] is None
    assert by_hand["classificationWithheld"] is False
    assert by_hand["status"] == "new"
    seen_by_owner = owner.complaint(first)
    assert seen_by_owner["classification"]["classifiedByName"] == "Mira Manager"
    tenant_view = budi.complaint(first)["classification"]
    assert (tenant_view["category"], tenant_view["urgency"]) == ("Perabot", "medium")
    assert ids(owner.complaints()) == ids([seeded_world.complaint, first, second])

    again = classify(owner, first, "Perabot", "medium", expect=200).json()
    assert again["classification"]["classifiedByName"] == "Mira Manager"
    changed = classify(owner, first, "Bangunan", "low", expect=200).json()
    assert changed["classification"]["category"] == "Bangunan"
    assert changed["classification"]["classifiedByName"] == "Rina Owner"

    move_to(manager, second, "done")
    finished = classify(owner, second, "Perabot", "high", expect=200).json()
    assert finished["status"] == "done"
    assert finished["classification"]["classifiedByName"] == "Rina Owner"
    assert ids(owner.complaints()) == ids([second, seeded_world.complaint, first])


def test_a_late_ai_result_never_overwrites_a_manual_classification(seeded_world, world):
    owner, budi = seeded_world.owner, seeded_world.budi
    room = seeded_world.rooms["A1"]
    world.stubs.classifier_works(
        category="Listrik",
        urgency="high",
        suggested_action="Send an electrician today.",
    )
    original = world.stubs.classifier.classify
    during = {}

    def classify_by_hand_first(description, categories):
        [pending] = [c for c in owner.complaints() if c["description"] == description]
        during["state"] = pending["classificationState"]
        during["answer"] = classify(owner, pending, "Air", "low", expect=200).json()
        return original(description, categories)

    world.stubs.classifier.classify = classify_by_hand_first

    created = budi.submit_complaint(room, "Water is dripping from the ceiling.")

    assert during["state"] == "classifying"
    assert during["answer"]["classification"]["category"] == "Air"
    shown = owner.complaint(created)
    assert shown["classification"] == {
        "category": "Air",
        "urgency": "low",
        "suggestedAction": None,
        "classifiedByName": "Rina Owner",
        "originalAiClassification": {
            "category": "Listrik",
            "urgency": "high",
            "suggestedAction": "Send an electrician today.",
        },
    }
    assert shown["classificationState"] is None
    assert ids(owner.complaints()) == ids([seeded_world.complaint, created])
    assert find(owner.complaints(), created)["classification"]["urgency"] == "low"


def test_correcting_an_ai_classification_keeps_the_original_for_management(
    seeded_world, world
):
    owner, manager, budi = seeded_world.owner, seeded_world.manager, seeded_world.budi
    seed = seeded_world.complaint
    ai = {
        "category": "Listrik",
        "urgency": "high",
        "suggestedAction": "Send an electrician today.",
    }

    unchanged = classify(owner, seed, "Listrik", "high", expect=200).json()

    assert unchanged["classification"] == {
        **ai,
        "classifiedByName": None,
        "originalAiClassification": None,
    }

    corrected = classify(owner, seed, "Air", "low", expect=200).json()

    assert corrected["classification"] == {
        "category": "Air",
        "urgency": "low",
        "suggestedAction": None,
        "classifiedByName": "Rina Owner",
        "originalAiClassification": ai,
    }
    for staff in (owner, manager):
        shown = find(staff.complaints(), seed)
        assert shown["classification"] == corrected["classification"]
        assert shown["classificationWithheld"] is False
    tenant_view = budi.complaint(seed)["classification"]
    assert (tenant_view["category"], tenant_view["urgency"]) == ("Air", "low")

    same = classify(manager, seed, "Air", "low", expect=200).json()
    assert same["classification"]["classifiedByName"] == "Rina Owner"

    again = classify(manager, seed, "Bangunan", "high", expect=200).json()
    assert again["classification"] == {
        "category": "Bangunan",
        "urgency": "high",
        "suggestedAction": None,
        "classifiedByName": "Mira Manager",
        "originalAiClassification": ai,
    }
    assert owner.complaint(seed)["classification"] == again["classification"]


# Subscription gating


def test_an_owner_whose_paid_period_ended_gets_ai_results_withheld_until_subscribing(
    seeded_world, world, expire_subscription
):
    owner, manager, budi = seeded_world.owner, seeded_world.manager, seeded_world.budi
    room = seeded_world.rooms["A1"]
    seed = seeded_world.complaint
    ai_high = file_classified(
        world, budi, room, "Sparks from the socket.", "Listrik", "high"
    )
    ai_low = file_classified(
        world, budi, room, "The floor is dusty.", "Kebersihan", "low"
    )
    by_hand = file_unclassified(world, budi, room, "The shower head is loose.")
    classify(owner, by_hand, "Air", "medium", expect=200)
    corrected = file_classified(
        world, budi, room, "The bed frame creaks.", "Perabot", "low"
    )
    classify(owner, corrected, "Bangunan", "high", expect=200)
    assert owner.subscription()["planCode"] == "basic"

    expire_subscription(owner.namespace)

    assert owner.subscription()["planCode"] == "free"
    withheld = [seed, ai_high, ai_low]
    for staff in (owner, manager):
        listed = staff.complaints()
        for complaint in withheld:
            shown = find(listed, complaint)
            assert shown["classification"] is None
            assert shown["classificationState"] is None
            assert shown["classificationWithheld"] is True
            detail = staff.complaint(complaint)
            assert detail["classification"] is None
            assert detail["classificationWithheld"] is True
        shown = find(listed, by_hand)
        assert shown["classification"]["category"] == "Air"
        assert shown["classification"]["classifiedByName"] == "Rina Owner"
        assert shown["classificationWithheld"] is False
        shown = find(listed, corrected)
        assert shown["classification"]["category"] == "Bangunan"
        assert shown["classification"]["originalAiClassification"] is None
        assert shown["classificationWithheld"] is False
        assert ids(listed) == ids([corrected, by_hand, ai_low, ai_high, seed])

    calls = len(world.stubs.classifier.calls)
    skipped = budi.submit_complaint(room, "The tiles in the bathroom are cracked.")
    assert skipped["classificationState"] == "notClassified"
    assert len(world.stubs.classifier.calls) == calls
    shown = owner.complaint(skipped)
    assert shown["classification"] is None
    assert shown["classificationState"] == "notClassified"
    assert shown["classificationWithheld"] is False
    by_hand_late = classify(owner, skipped, "Bangunan", "medium", expect=200).json()
    assert by_hand_late["classification"]["classifiedByName"] == "Rina Owner"
    assert by_hand_late["classification"]["originalAiClassification"] is None
    assert ids(owner.complaints()) == ids(
        [corrected, skipped, by_hand, ai_low, ai_high, seed]
    )

    overridden = classify(owner, ai_low, "Internet", "medium", expect=200).json()
    assert overridden["classification"]["category"] == "Internet"
    assert overridden["classification"]["originalAiClassification"] is None
    assert overridden["classificationWithheld"] is False

    owner.subscribe("basic")

    for staff in (owner, manager):
        listed = staff.complaints()
        for complaint, category in ((seed, "Listrik"), (ai_high, "Listrik")):
            shown = find(listed, complaint)
            assert shown["classification"]["category"] == category
            assert shown["classification"]["suggestedAction"] is not None
            assert shown["classificationWithheld"] is False
        shown = find(listed, ai_low)
        assert shown["classification"]["category"] == "Internet"
        assert shown["classification"]["originalAiClassification"] == {
            "category": "Kebersihan",
            "urgency": "low",
            "suggestedAction": "Look into the Kebersihan.",
        }
    assert find(owner.complaints(), skipped)["classificationState"] is None
    assert owner.complaint(skipped)["classification"]["category"] == "Bangunan"


def test_a_tenant_sees_ai_results_withheld_like_management_while_the_owner_has_no_plan(
    seeded_world, world, expire_subscription
):
    owner, budi = seeded_world.owner, seeded_world.budi
    seed = seeded_world.complaint
    by_hand = file_unclassified(
        world, budi, seeded_world.rooms["A1"], "The shower head is loose."
    )
    classify(owner, by_hand, "Air", "medium", expect=200)
    assert budi.complaint(seed)["classification"]["category"] == "Listrik"

    expire_subscription(owner.namespace)

    listed = budi.complaints()
    for shown in (find(listed, seed), budi.complaint(seed)):
        assert shown["classification"] is None
        assert shown["classificationState"] is None
        assert shown["classificationWithheld"] is True
    for shown in (find(listed, by_hand), budi.complaint(by_hand)):
        assert shown["classification"]["category"] == "Air"
        assert shown["classification"]["urgency"] == "medium"
        assert shown["classificationWithheld"] is False

    owner.subscribe("basic")

    for shown in (find(budi.complaints(), seed), budi.complaint(seed)):
        assert shown["classification"]["category"] == "Listrik"
        assert shown["classification"]["urgency"] == "high"
        assert shown["classificationWithheld"] is False


def test_an_owner_on_the_free_plan_gets_no_classification_until_later_complaints(
    world,
):
    owner = world.owner_signs_up()
    prop = owner.add_property("Kos Melati")
    room = owner.add_room(prop, "A1")
    budi = world.tenant_activates(owner.add_tenant(room, "Budi Tenant", "081211111111"))
    world.stubs.classifier_works()

    first = budi.submit_complaint(room, "The tap in the bathroom leaks badly.")
    second = budi.submit_complaint(room, "The window in the room is stuck.")

    for created in (first, second):
        assert created["classificationState"] == "notClassified"
        assert created["classification"] is None
    world.stubs.assert_classifier_called(0)
    for complaint in (first, second):
        shown = owner.complaint(complaint)
        assert shown["classification"] is None
        assert shown["classificationState"] == "notClassified"
        assert shown["classificationWithheld"] is False
        assert budi.complaint(complaint)["classificationState"] == "notClassified"

    by_hand = classify(owner, first, "Air", "high", expect=200).json()
    assert by_hand["classification"]["category"] == "Air"
    assert by_hand["classification"]["classifiedByName"] == "Rina Owner"
    assert by_hand["classificationState"] is None
    assert ids(owner.complaints()) == ids([first, second])

    owner.subscribe("basic")
    third = budi.submit_complaint(room, "The light switch sparks when used.")

    assert third["classificationState"] == "classifying"
    world.stubs.assert_classifier_called(1)
    assert owner.complaint(third)["classification"]["category"] == "Listrik"
    assert owner.complaint(second)["classificationState"] == "notClassified"
    assert owner.complaint(second)["classification"] is None
    assert owner.complaint(first)["classification"]["category"] == "Air"
    assert owner.complaint(third)["property"]["name"] == "Kos Melati"
