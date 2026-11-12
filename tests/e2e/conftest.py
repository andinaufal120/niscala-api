"""Fixtures of the end-to-end scenarios, built on the shared test setup."""

import sys

import pytest

from e2e.e2e_world import Cast, Clock, Stubs, build_seed

JOBS_SECRET = "e2e-jobs-secret"
FAKE_FIREBASE_CREDENTIALS = '{"type": "service_account", "project_id": "e2e"}'


@pytest.fixture
def jobs_secret(database):
    """Configure the secret that lets a caller run the daily jobs."""
    from app.config import get_settings

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("JOBS_SECRET", JOBS_SECRET)
        get_settings.cache_clear()
        yield JOBS_SECRET
    get_settings.cache_clear()


@pytest.fixture
def clock(app, client, frozen_today, jobs_secret, monkeypatch) -> Clock:
    """Control the Asia/Jakarta date every date rule reads, starting at the frozen date."""
    moving = Clock(client, jobs_secret, frozen_today)
    for name, module in list(sys.modules.items()):
        if name.startswith("app.") and getattr(module, "today_jakarta", None):
            monkeypatch.setattr(module, "today_jakarta", lambda: moving.today)
    monkeypatch.setattr("app.services.tenants._today", lambda: moving.today)
    return moving


@pytest.fixture
def stubs(
    database,
    mailbox,
    fake_classifier,
    fake_summarizer,
    play,
    google,
    file_store,
    fake_firebase,
    firebase_credentials,
    fcm,
    monkeypatch,
) -> Stubs:
    """Every external service stubbed, with push delivery going to the FCM outbox."""
    firebase_credentials(FAKE_FIREBASE_CREDENTIALS)
    return Stubs(
        classifier=fake_classifier,
        summarizer=fake_summarizer,
        play=play,
        google=google,
        mailbox=mailbox,
        fcm=fcm,
        files=file_store,
        monkeypatch=monkeypatch,
    )


@pytest.fixture
def world(client, stubs, clock, make_user) -> Cast:
    """The steps of a scenario, with fresh stubs and a fresh clock for each test."""
    return Cast(client=client, stubs=stubs, clock=clock, make_user=make_user)


@pytest.fixture
def seeded_world(world):
    """The documented world, built through the steps of `world`."""
    return build_seed(world)
