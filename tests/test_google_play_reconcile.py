"""The daily job that fetches again the subscriptions whose paid period is about to end or just ended."""

import logging
from datetime import timedelta

import pytest
from google_play_support import (
    current_plan_of,
    everything,
    now,
    set_token,
    subscription_state,
)
from sqlalchemy.orm import Session
from subscription_support import set_subscription, view_only_properties


def at(days: float):
    return now() + timedelta(days=days)


def reconcile(database) -> None:
    from app.services.subscriptions import reconcile_google_play_subscriptions

    with Session(database) as db:
        reconcile_google_play_subscriptions(db)
        db.commit()


def subscribe(database, owner, token: str | None, ends_in_days: float, **options):
    set_subscription(database, owner, plan="basic", ends_at=at(ends_in_days), **options)
    if token is not None:
        set_token(database, owner, token)


@pytest.fixture
def owner(make_user):
    return make_user(name="Rina Owner")


# Registration among the daily jobs


def test_the_job_is_one_of_the_daily_jobs():
    from app.services.jobs import DAILY_JOBS
    from app.services.subscriptions import reconcile_google_play_subscriptions

    assert reconcile_google_play_subscriptions in DAILY_JOBS
    assert (
        reconcile_google_play_subscriptions.__name__
        == "reconcile_google_play_subscriptions"
    )


def test_the_job_runs_before_the_plan_limits_are_applied():
    from app.services.jobs import DAILY_JOBS
    from app.services.subscriptions import (
        apply_plan_limits,
        reconcile_google_play_subscriptions,
    )

    assert DAILY_JOBS.index(reconcile_google_play_subscriptions) < DAILY_JOBS.index(
        apply_plan_limits
    )


def test_the_session_cleanup_is_still_the_first_job():
    from app.services.jobs import DAILY_JOBS

    assert DAILY_JOBS[0].__name__ == "end_expired_sessions"


def test_every_daily_job_still_has_a_distinct_name():
    from app.services.jobs import DAILY_JOBS

    names = [job.__name__ for job in DAILY_JOBS]
    assert len(names) == len(set(names))


# Which subscriptions are fetched


@pytest.mark.parametrize("days", [-2.9, -2, -1, 0, 0.5, 0.9])
def test_a_subscription_ending_within_the_window_is_fetched(
    database, play, owner, days
):
    subscribe(database, owner, "token-a", days)
    play.add("token-a", owner=owner, expiry_time=at(days))
    reconcile(database)
    assert play.fetched == ["token-a"]


@pytest.mark.parametrize("days", [-3.1, -10, 1.1, 2, 30])
def test_a_subscription_ending_outside_the_window_is_not_fetched(
    database, play, owner, days
):
    subscribe(database, owner, "token-a", days)
    play.add("token-a", owner=owner)
    reconcile(database)
    assert play.fetched == []


def test_a_subscription_without_a_token_is_not_fetched(database, play, owner):
    subscribe(database, owner, None, 0.5)
    reconcile(database)
    assert play.fetched == []


def test_every_subscription_in_the_window_is_fetched_once(database, play, make_user):
    owners = [make_user(name=f"Owner {n}") for n in range(3)]
    for number, one in enumerate(owners):
        subscribe(database, one, f"token-{number}", 0.5)
        play.add(f"token-{number}", owner=one, expiry_time=at(0.5))
    reconcile(database)
    assert sorted(play.fetched) == ["token-0", "token-1", "token-2"]


def test_only_the_subscriptions_in_the_window_are_fetched(database, play, make_user):
    inside, before, after, untokened = (make_user(name=n) for n in "ABCD")
    subscribe(database, inside, "inside", 0.5)
    subscribe(database, before, "before", -5)
    subscribe(database, after, "after", 5)
    subscribe(database, untokened, None, 0.5)
    for token, one in (("inside", inside), ("before", before), ("after", after)):
        play.add(token, owner=one)
    reconcile(database)
    assert play.fetched == ["inside"]


# What the fetch changes


def test_a_missed_renewal_is_recovered(database, play, owner):
    subscribe(database, owner, "token-a", 0.5, auto_renew=True)
    renewed = at(30)
    play.add("token-a", owner=owner, expiry_time=renewed)
    reconcile(database)
    assert subscription_state(database, owner)[2] == renewed


def test_a_missed_cancellation_is_recovered(database, play, owner):
    subscribe(database, owner, "token-a", 0.5, auto_renew=True)
    play.add(
        "token-a",
        owner=owner,
        state="CANCELED",
        auto_renewing=False,
        expiry_time=at(0.5),
    )
    reconcile(database)
    assert subscription_state(database, owner)[3] is False


def test_a_missed_expiry_is_recorded(database, play, owner):
    subscribe(database, owner, "token-a", -1)
    expiry = at(-1)
    play.add("token-a", owner=owner, state="EXPIRED", expiry_time=expiry)
    reconcile(database)
    assert current_plan_of(database, owner) == "free"


def test_a_missed_refund_ends_the_plan_before_its_old_end(database, play, owner):
    subscribe(database, owner, "token-a", 0.5)
    play.add(
        "token-a", owner=owner, state="EXPIRED", expiry_time=now() - timedelta(hours=1)
    )
    reconcile(database)
    assert current_plan_of(database, owner) == "free"


def test_an_unchanged_purchase_changes_nothing(database, play, owner):
    expiry = at(0.5)
    subscribe(database, owner, "token-a", 0.5, auto_renew=True)
    set_subscription(database, owner, plan="basic", ends_at=expiry, auto_renew=True)
    play.add("token-a", owner=owner, expiry_time=expiry, auto_renewing=True)
    before = subscription_state(database, owner)
    reconcile(database)
    assert subscription_state(database, owner) == before


def test_running_the_job_twice_changes_nothing_more(database, play, owner):
    subscribe(database, owner, "token-a", 0.5)
    play.add("token-a", owner=owner, expiry_time=at(30))
    reconcile(database)
    once = everything(database)
    reconcile(database)
    assert everything(database) == once


# Failures


def test_an_unreachable_purchase_does_not_stop_the_others(
    database, play, make_user, caplog
):
    first, second, third = (make_user(name=n) for n in ("One", "Two", "Three"))
    for number, one in enumerate((first, second, third)):
        subscribe(database, one, f"token-{number}", 0.5)
        play.add(f"token-{number}", owner=one, expiry_time=at(30))
    play.unreachable_tokens = {"token-1"}
    stuck = subscription_state(database, second)
    with caplog.at_level(logging.INFO):
        reconcile(database)
    assert sorted(play.fetched) == ["token-0", "token-1", "token-2"]
    assert subscription_state(database, first)[2] > at(29)
    assert subscription_state(database, third)[2] > at(29)
    assert subscription_state(database, second) == stuck


def test_an_unreachable_purchase_is_logged(database, play, owner, caplog):
    subscribe(database, owner, "token-a", 0.5)
    play.add("token-a", owner=owner)
    play.unreachable = True
    with caplog.at_level(logging.INFO):
        reconcile(database)
    assert [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_the_job_does_not_raise_when_google_play_is_down(database, play, owner):
    subscribe(database, owner, "token-a", 0.5)
    play.add("token-a", owner=owner)
    play.unreachable = True
    before = everything(database)
    reconcile(database)
    assert everything(database) == before


def test_the_daily_run_does_not_report_the_job_as_failed_when_google_play_is_down(
    database, play, owner
):
    from app.services.jobs import run_daily_jobs
    from app.services.subscriptions import reconcile_google_play_subscriptions

    subscribe(database, owner, "token-a", 0.5)
    play.add("token-a", owner=owner)
    play.unreachable = True
    assert run_daily_jobs([reconcile_google_play_subscriptions]) == []


def test_an_unreachable_purchase_keeps_the_changes_of_the_others_after_the_commit(
    database, play, make_user
):
    from app.services.jobs import run_daily_jobs
    from app.services.subscriptions import reconcile_google_play_subscriptions

    first, second = make_user(name="One"), make_user(name="Two")
    for number, one in enumerate((first, second)):
        subscribe(database, one, f"token-{number}", 0.5)
        play.add(f"token-{number}", owner=one, expiry_time=at(30))
    play.unreachable_tokens = {"token-0"}
    assert run_daily_jobs([reconcile_google_play_subscriptions]) == []
    assert subscription_state(database, second)[2] > at(29)


# Google Play is not configured


def test_without_google_play_configured_the_job_does_nothing(
    database, owner, monkeypatch
):
    from app import google_play

    subscribe(database, owner, "token-a", 0.5)
    monkeypatch.setattr(
        google_play, "get_google_play", google_play.UnavailableGooglePlay
    )
    monkeypatch.setattr(
        "app.services.subscriptions.get_google_play",
        google_play.UnavailableGooglePlay,
        raising=False,
    )
    before = everything(database)
    reconcile(database)
    assert everything(database) == before


def test_the_real_getter_without_settings_makes_the_job_do_nothing(database, owner):
    subscribe(database, owner, "token-a", 0.5)
    before = everything(database)
    state = subscription_state(database, owner)
    reconcile(database)
    assert everything(database) == before
    assert subscription_state(database, owner) == state


def test_the_daily_run_without_google_play_configured_reports_no_failure(
    database, owner
):
    from app.services.jobs import run_daily_jobs

    subscribe(database, owner, "token-a", 0.5)
    assert run_daily_jobs() == []


# Together with the plan limits


def test_an_ended_plan_is_limited_in_the_same_daily_run(
    database, play, owner, make_property
):
    from app.services.jobs import run_daily_jobs

    set_subscription(database, owner, plan="pro", ends_at=at(0.5))
    set_token(database, owner, "token-a")
    properties = [make_property(owner, name=f"Kos {n}") for n in range(3)]
    play.add(
        "token-a", owner=owner, state="EXPIRED", expiry_time=now() - timedelta(hours=1)
    )
    assert run_daily_jobs() == []
    limited = view_only_properties(database, owner)
    assert len(limited) == 2
    assert properties[0].id not in limited


def test_a_renewed_plan_is_not_limited_in_the_daily_run(
    database, play, owner, make_property
):
    from app.services.jobs import run_daily_jobs

    set_subscription(database, owner, plan="pro", ends_at=at(0.5))
    set_token(database, owner, "token-a")
    for number in range(3):
        make_property(owner, name=f"Kos {number}")
    play.add("token-a", owner=owner, product_id="niscala_pro", expiry_time=at(30))
    assert run_daily_jobs() == []
    assert view_only_properties(database, owner) == set()
