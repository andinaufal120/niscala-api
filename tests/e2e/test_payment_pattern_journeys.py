"""End-to-end journeys of payment patterns: facts, the risk flag and the AI summary."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from e2e.e2e_people import BANK_ACCOUNT
from e2e.e2e_world import MELATI

WEEKLY_RENT = 250_000


def assert_error(response, status, code, field=None):
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code, body
    assert body["field"] == field, body


def real_today():
    """Today in Asia/Jakarta by the real clock.

    A verified transfer receipt is dated by the real time of its upload, so a
    scenario that pays by transfer ends on this date.
    """
    return datetime.now(ZoneInfo("Asia/Jakarta")).date()


def pattern_page(owner, prop):
    return owner.read(f"/properties/{prop['id']}/payment-patterns")["items"]


def by_name(items):
    return {item["tenant"]["name"]: item for item in items}


def facts(item):
    """The facts of a tenant: on time, counted, average days late, arrears, at risk."""
    return (
        item["onTimeCount"],
        item["countedBillCount"],
        item["averageDaysLate"],
        item["arrears"],
        item["atRisk"],
    )


def bill_of(owner, name, period_start):
    return next(
        b
        for b in owner.rent_bills()
        if b["tenant"]["name"] == name and b["periodStart"] == period_start.isoformat()
    )


def pay_cash(owner, bill, day):
    return owner.post(
        f"/rent-bills/{bill['id']}/cash-payment",
        json={"receivedOn": day.isoformat()},
        expect=200,
    ).json()


def change_status(owner, bill, status, reason="Corrected after counting the cash."):
    body = {"status": status, "reason": reason}
    if status == "paid":
        body |= {"method": "cash", "receivedOn": bill["dueDate"]}
    return owner.post(
        f"/rent-bills/{bill['id']}/status-changes", json=body, expect=201
    ).json()


def test_payment_facts_and_the_risk_flag_follow_how_each_tenant_pays(world):
    today = real_today()
    start = today - timedelta(days=49)
    world.clock.set(start)
    world.stubs.summarizer.result = "Pola pembayaran terpantau."
    owner = world.owner_signs_up()
    owner.subscribe("basic")
    melati = owner.add_property(MELATI, bank_account=BANK_ACCOUNT)
    rooms = {
        number: owner.add_room(melati, number) for number in ("A10", "A3", "A2", "A4")
    }

    def lease(first, grace=0):
        return {
            "startDate": first,
            "billingCycle": "weekly",
            "rent": WEEKLY_RENT,
            "gracePeriodDays": grace,
        }

    ayu_token = owner.add_tenant(
        rooms["A2"], "Ayu Tenant", "081211111111", lease=lease(start)
    )
    owner.add_tenant(rooms["A3"], "Bima Tenant", "081222222222", lease=lease(start, 2))
    owner.add_tenant(
        rooms["A4"], "Dedi Tenant", "081233333333", lease=lease(today - timedelta(14))
    )
    owner.add_tenant(rooms["A10"], "Citra Tenant", "081244444444", lease=lease(start))
    ayu = world.tenant_activates(ayu_token, email="ayu@example.com")

    # How many days after the due date each period was paid; None is never paid.
    paid_after = {
        "Ayu Tenant": (start, 0, [0] * 7),
        "Bima Tenant": (start, 2, [0, 4, 0, 3, 0, 6, None]),
        "Dedi Tenant": (today - timedelta(14), 0, [0, None, 0]),
        "Citra Tenant": (start, 0, []),
    }
    period_starts = [start + timedelta(days=7 * week) for week in range(8)]
    payments = {}
    for name, (first, grace, lateness) in paid_after.items():
        for number, late in enumerate(lateness):
            if late is not None:
                period = first + timedelta(days=7 * number)
                day = period + timedelta(days=grace + late)
                payments.setdefault(day, []).append((name, period))

    for day in sorted({*period_starts, *payments}):
        world.clock.set(day)
        if day in period_starts:
            world.clock.run_daily_jobs()
        for name, period in payments.get(day, []):
            pay_cash(owner, bill_of(owner, name, period), day)

    assert world.clock.today == today
    assert len(owner.rent_bills()) == 8 * 3 + 3
    current = bill_of(owner, "Ayu Tenant", today)
    assert current["payment"]["status"] == "unpaid"
    ayu.upload_receipt(current)
    paid = owner.post(f"/rent-bills/{current['id']}/verification", expect=200).json()
    assert paid["payment"]["method"] == "transfer"
    assert paid["payment"]["paidOn"] == today.isoformat()

    items = pattern_page(owner, melati)

    assert [i["tenant"]["name"] for i in items] == [
        "Ayu Tenant",
        "Bima Tenant",
        "Dedi Tenant",
        "Citra Tenant",
    ]
    assert [i["room"]["number"] for i in items] == ["A2", "A3", "A4", "A10"]
    rows = by_name(items)
    assert facts(rows["Ayu Tenant"]) == (6, 6, 0, 0, False)
    assert facts(rows["Bima Tenant"]) == (2, 6, 5, WEEKLY_RENT, True)
    assert facts(rows["Dedi Tenant"]) == (2, 3, 7, WEEKLY_RENT, False)
    assert facts(rows["Citra Tenant"]) == (0, 6, 25, 7 * WEEKLY_RENT, True)
    for name in ("Ayu Tenant", "Bima Tenant", "Dedi Tenant"):
        assert rows[name]["summary"] == "Pola pembayaran terpantau."
        assert rows[name]["summaryWithheld"] is False
    assert rows["Citra Tenant"]["summary"] is None
    assert rows["Citra Tenant"]["summaryWithheld"] is False

    world.clock.advance()

    rows = by_name(pattern_page(owner, melati))
    assert facts(rows["Ayu Tenant"]) == (6, 6, 0, 0, False)
    assert facts(rows["Bima Tenant"]) == (2, 6, 5, WEEKLY_RENT, True)
    assert facts(rows["Dedi Tenant"]) == (2, 3, 8, WEEKLY_RENT, True)
    assert facts(rows["Citra Tenant"]) == (0, 6, 19, 8 * WEEKLY_RENT, True)
    overview = owner.read(f"/properties/{melati['id']}/payment-overview")["items"]
    assert [i["tenant"]["name"] for i in overview] == [
        i["tenant"]["name"] for i in pattern_page(owner, melati)
    ]
    assert [i["bill"]["payment"]["status"] for i in overview] == [
        "paid",
        "unpaid",
        "paid",
        "unpaid",
    ]

    anggrek = owner.add_property("Kos Anggrek")
    mira = world.manager_activates(
        owner.add_manager([anggrek], name="Mira Manager"), email="mira@example.com"
    )
    assert mira.read(f"/properties/{anggrek['id']}/payment-patterns")["items"] == []
    assert_error(
        mira.get(f"/properties/{melati['id']}/payment-patterns"),
        404,
        "PROPERTY_NOT_FOUND",
    )
    assert_error(
        ayu.get(f"/properties/{melati['id']}/payment-patterns"), 403, "FORBIDDEN"
    )


def test_a_summary_is_made_after_a_payment_change_and_replaced_or_removed_by_the_next(
    seeded_world, world, expire_subscription
):
    owner, budi = seeded_world.owner, seeded_world.budi
    melati = seeded_world.melati
    summarizer = world.stubs.summarizer
    bill = budi.rent_bills()[0]
    paid_on_time = seeded_world.date.replace(day=1)

    def rows():
        return by_name(pattern_page(owner, melati))

    overdue = (0, 1, 22, 1_200_000, True)
    settled = (1, 1, 0, 0, False)

    assert facts(rows()["Budi Tenant"]) == overdue
    for row in rows().values():
        assert row["summary"] is None
        assert row["summaryWithheld"] is False
    assert summarizer.calls == []

    summarizer.result = "Summary one."
    pay_cash(owner, bill, paid_on_time)

    row = rows()["Budi Tenant"]
    assert row["summary"] == "Summary one."
    assert row["summaryWithheld"] is False
    assert facts(row) == settled
    assert rows()["Sari Tenant"]["summary"] is None
    assert len(summarizer.calls) == 1
    sent_facts, sent_bills = summarizer.calls[0]
    assert (sent_facts.on_time_count, sent_facts.counted_bill_count) == (1, 1)
    assert [(b.status, b.days_late) for b in sent_bills] == [("paid", 0)]
    assert rows()["Budi Tenant"]["summary"] == "Summary one."
    assert len(summarizer.calls) == 1

    summarizer.result = "Summary two."
    change_status(owner, bill, "unpaid")

    row = rows()["Budi Tenant"]
    assert row["summary"] == "Summary two."
    assert facts(row) == overdue
    assert len(summarizer.calls) == 2

    world.stubs.summarizer_unavailable()
    pay_cash(owner, bill, paid_on_time)

    row = rows()["Budi Tenant"]
    assert row["summary"] is None
    assert row["summaryWithheld"] is False
    assert facts(row) == settled
    assert len(summarizer.calls) == 3

    world.stubs.summarizer_works("Summary three.")
    assert rows()["Budi Tenant"]["summary"] is None
    assert rows()["Budi Tenant"]["summary"] is None
    assert len(summarizer.calls) == 3

    world.stubs.summarizer_times_out()
    change_status(owner, bill, "unpaid")

    row = rows()["Budi Tenant"]
    assert row["summary"] is None
    assert row["summaryWithheld"] is False
    assert facts(row) == overdue
    assert len(summarizer.calls) == 4

    world.stubs.summarizer_works("   ")
    pay_cash(owner, bill, paid_on_time)
    assert rows()["Budi Tenant"]["summary"] is None
    summarizer.result = "x" * 501
    change_status(owner, bill, "unpaid")
    assert rows()["Budi Tenant"]["summary"] is None
    assert len(summarizer.calls) == 6

    summarizer.result = "Summary four."
    budi.upload_receipt(bill)

    row = rows()["Budi Tenant"]
    assert row["summary"] == "Summary four."
    assert facts(row) == (0, 0, 0, 0, False)
    assert len(summarizer.calls) == 7

    expire_subscription(owner.namespace)

    row = rows()["Budi Tenant"]
    assert row["summary"] is None
    assert row["summaryWithheld"] is True
    assert facts(row) == (0, 0, 0, 0, False)
    assert rows()["Sari Tenant"]["summaryWithheld"] is False
    assert facts(rows()["Sari Tenant"]) == (0, 1, 8, 1_000_000, True)

    owner.subscribe("basic")

    row = rows()["Budi Tenant"]
    assert row["summary"] == "Summary four."
    assert row["summaryWithheld"] is False
    assert len(summarizer.calls) == 7

    expire_subscription(owner.namespace)
    summarizer.result = "Summary five."
    owner.post(
        f"/rent-bills/{bill['id']}/rejection",
        json={"reason": "The receipt is blurry."},
        expect=200,
    )

    row = rows()["Budi Tenant"]
    assert row["summary"] is None
    assert row["summaryWithheld"] is False
    assert len(summarizer.calls) == 7

    owner.subscribe("basic")

    assert rows()["Budi Tenant"]["summary"] is None
    assert rows()["Budi Tenant"]["summaryWithheld"] is False
    assert len(summarizer.calls) == 7

    budi.upload_receipt(bill)

    assert rows()["Budi Tenant"]["summary"] == "Summary five."
    assert len(summarizer.calls) == 8
