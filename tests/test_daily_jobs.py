"""The daily jobs runner and the endpoint that triggers it."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

JOBS_URL = "/internal/jobs/daily"
SECRET = "jobs-secret-0123456789abcdef"


def days_ago(days: float) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


@pytest.fixture
def jobs_secret(monkeypatch):
    """Control `JOBS_SECRET` for one test; call with no argument to leave it unset."""
    from app.config import get_settings

    monkeypatch.delenv("JOBS_SECRET", raising=False)
    get_settings.cache_clear()

    def configure(value: str | None = SECRET) -> None:
        if value is None:
            monkeypatch.delenv("JOBS_SECRET", raising=False)
        else:
            monkeypatch.setenv("JOBS_SECRET", value)
        get_settings.cache_clear()

    yield configure
    get_settings.cache_clear()


def bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def emails(database) -> set[str]:
    from app.models import UserAccount

    with Session(database) as db:
        return set(db.scalars(select(UserAccount.email)))


def adder(email: str):
    """A job that stores one user account."""
    from app.models import UserAccount
    from app.schemas.auth import UserRole

    def job(db):
        db.add(UserAccount(name="Job", email=email, role=UserRole.OWNER))

    job.__name__ = f"add_{email.split('@')[0]}"
    return job


def failing(name: str = "broken_job"):
    def job(db):
        raise RuntimeError("boom")

    job.__name__ = name
    return job


def failing_after_write(email: str, name: str = "half_done_job"):
    from app.models import UserAccount
    from app.schemas.auth import UserRole

    def job(db):
        db.add(UserAccount(name="Job", email=email, role=UserRole.OWNER))
        db.flush()
        raise RuntimeError("boom")

    job.__name__ = name
    return job


def test_jobs_secret_defaults_to_unset(monkeypatch):
    from app.config import Settings

    monkeypatch.delenv("JOBS_SECRET", raising=False)
    assert Settings().jobs_secret is None


def test_jobs_secret_is_read_from_the_environment(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("JOBS_SECRET", SECRET)
    assert Settings().jobs_secret == SECRET


def test_the_session_cleanup_is_the_first_daily_job():
    from app.services.jobs import DAILY_JOBS
    from app.services.sessions import end_expired_sessions

    assert len(DAILY_JOBS) >= 1
    assert all(callable(job) for job in DAILY_JOBS)
    first = DAILY_JOBS[0]
    assert first is end_expired_sessions or first.__name__ == "end_expired_sessions"


def test_daily_jobs_have_distinct_names():
    from app.services.jobs import DAILY_JOBS

    names = [job.__name__ for job in DAILY_JOBS]
    assert len(names) == len(set(names))


def test_run_daily_jobs_runs_every_job_in_order(database):
    from app.services.jobs import run_daily_jobs

    order: list[str] = []

    def first(db):
        order.append("first")

    def second(db):
        order.append("second")

    def third(db):
        order.append("third")

    assert run_daily_jobs([first, second, third]) == []
    assert order == ["first", "second", "third"]


def test_run_daily_jobs_gives_each_job_its_own_session(database):
    from app.services.jobs import run_daily_jobs

    seen: list[Session] = []

    def first(db):
        seen.append(db)

    def second(db):
        seen.append(db)

    run_daily_jobs([first, second])
    assert len(seen) == 2
    assert all(isinstance(db, Session) for db in seen)
    assert seen[0] is not seen[1]


def test_run_daily_jobs_commits_a_successful_job(database):
    from app.services.jobs import run_daily_jobs

    assert run_daily_jobs([adder("one@example.com")]) == []
    assert emails(database) == {"one@example.com"}


def test_run_daily_jobs_with_no_jobs_returns_nothing(database):
    from app.services.jobs import run_daily_jobs

    assert run_daily_jobs([]) == []


def test_run_daily_jobs_rolls_back_a_failed_job(database):
    from app.services.jobs import run_daily_jobs

    failed = run_daily_jobs([failing_after_write("lost@example.com")])
    assert failed == ["half_done_job"]
    assert emails(database) == set()


def test_run_daily_jobs_continues_after_a_failure(database):
    from app.services.jobs import run_daily_jobs

    failed = run_daily_jobs(
        [
            adder("before@example.com"),
            failing_after_write("lost@example.com"),
            adder("after@example.com"),
        ]
    )
    assert failed == ["half_done_job"]
    assert emails(database) == {"before@example.com", "after@example.com"}


def test_run_daily_jobs_names_every_failed_job_in_order(database):
    from app.services.jobs import run_daily_jobs

    failed = run_daily_jobs(
        [failing("alpha"), adder("ok@example.com"), failing("omega")]
    )
    assert failed == ["alpha", "omega"]
    assert emails(database) == {"ok@example.com"}


def test_run_daily_jobs_logs_a_failed_job(database, caplog):
    from app.services.jobs import run_daily_jobs

    with caplog.at_level(logging.ERROR):
        run_daily_jobs([failing("noisy_job")])
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors
    assert any("noisy_job" in r.getMessage() for r in errors)


def test_run_daily_jobs_is_silent_when_every_job_succeeds(database, caplog):
    from app.services.jobs import run_daily_jobs

    with caplog.at_level(logging.WARNING):
        run_daily_jobs([adder("fine@example.com")])
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_run_daily_jobs_without_arguments_runs_the_default_jobs(
    database, make_user, db_session
):
    from app.models import UserSession
    from app.schemas.sessions import LoginMethod
    from app.services.jobs import run_daily_jobs

    user = make_user()
    row = UserSession(
        user_id=user.id,
        refresh_token_hash=uuid4().hex,
        device_name="Pixel 8",
        platform="Android 14",
        login_method=LoginMethod.PASSWORD,
        created_at=days_ago(200),
        last_active_at=days_ago(150),
    )
    db_session.add(row)
    db_session.commit()
    assert run_daily_jobs() == []
    db_session.expire_all()
    assert db_session.get(UserSession, row.id).revoked_at is not None


def test_the_endpoint_is_not_in_the_openapi_document(app):
    assert JOBS_URL not in app.openapi()["paths"]


def test_the_endpoint_is_absent_when_no_secret_is_configured(
    client, jobs_secret, monkeypatch
):
    calls: list[str] = []

    def spy(db):
        calls.append("ran")

    monkeypatch.setattr("app.services.jobs.DAILY_JOBS", [spy])
    jobs_secret(None)
    response = client.post(JOBS_URL, headers=bearer(SECRET))
    assert response.status_code == 404
    assert calls == []


@pytest.mark.parametrize("blank", ["", "   "])
def test_the_endpoint_is_absent_when_the_secret_is_blank(
    client, jobs_secret, monkeypatch, blank
):
    calls: list[str] = []

    def spy(db):
        calls.append("ran")

    monkeypatch.setattr("app.services.jobs.DAILY_JOBS", [spy])
    jobs_secret(blank)
    response = client.post(JOBS_URL, headers=bearer(blank))
    assert response.status_code == 404
    assert calls == []


def test_a_blank_secret_does_not_open_the_endpoint_without_a_header(
    client, jobs_secret
):
    jobs_secret("")
    assert client.post(JOBS_URL).status_code == 404


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-secret"},
        {"Authorization": f"Bearer {SECRET}x"},
        {"Authorization": f"Bearer {SECRET[:-1]}"},
        {"Authorization": f"bearer-{SECRET}"},
        {"Authorization": SECRET},
        {"Authorization": f"Basic {SECRET}"},
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer"},
    ],
    ids=[
        "missing",
        "wrong",
        "longer",
        "shorter",
        "malformed-scheme",
        "no-scheme",
        "basic-scheme",
        "empty-token",
        "no-token",
    ],
)
def test_a_wrong_or_missing_secret_is_unauthorized_and_runs_nothing(
    client, jobs_secret, monkeypatch, headers
):
    calls: list[str] = []

    def spy(db):
        calls.append("ran")

    monkeypatch.setattr("app.services.jobs.DAILY_JOBS", [spy])
    jobs_secret()
    response = client.post(JOBS_URL, headers=headers)
    assert response.status_code == 401
    body = response.json()
    assert set(body) == {"code", "field", "message"}
    assert body["code"]
    assert calls == []


def test_a_user_access_token_is_not_accepted_as_the_secret(
    client, jobs_secret, monkeypatch, make_user, sign_in
):
    calls: list[str] = []

    def spy(db):
        calls.append("ran")

    monkeypatch.setattr("app.services.jobs.DAILY_JOBS", [spy])
    jobs_secret()
    signed_in = sign_in(make_user())
    response = client.post(JOBS_URL, headers=signed_in.headers)
    assert response.status_code == 401
    assert calls == []


def test_the_correct_secret_runs_the_jobs_and_answers_no_content(
    client, database, jobs_secret, monkeypatch
):
    order: list[str] = []

    def first(db):
        order.append("first")

    def second(db):
        order.append("second")

    monkeypatch.setattr("app.services.jobs.DAILY_JOBS", [first, second])
    jobs_secret()
    response = client.post(JOBS_URL, headers=bearer(SECRET))
    assert response.status_code == 204
    assert response.content == b""
    assert order == ["first", "second"]


def test_the_endpoint_needs_no_user_login(client, database, jobs_secret, monkeypatch):
    monkeypatch.setattr("app.services.jobs.DAILY_JOBS", [])
    jobs_secret()
    response = client.post(JOBS_URL, headers=bearer(SECRET))
    assert response.status_code == 204


@pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
def test_only_post_is_allowed(client, database, jobs_secret, method):
    jobs_secret()
    response = getattr(client, method)(JOBS_URL, headers=bearer(SECRET))
    assert response.status_code in (404, 405)


def test_a_failing_job_makes_the_endpoint_answer_500_after_running_the_rest(
    client, database, jobs_secret, monkeypatch
):
    monkeypatch.setattr(
        "app.services.jobs.DAILY_JOBS",
        [
            adder("before@example.com"),
            failing_after_write("lost@example.com"),
            adder("after@example.com"),
        ],
    )
    jobs_secret()
    response = client.post(JOBS_URL, headers=bearer(SECRET))
    assert response.status_code == 500
    assert emails(database) == {"before@example.com", "after@example.com"}


def test_the_failure_response_has_the_standard_error_shape(
    client, database, jobs_secret, monkeypatch
):
    monkeypatch.setattr("app.services.jobs.DAILY_JOBS", [failing("broken_job")])
    jobs_secret()
    response = client.post(JOBS_URL, headers=bearer(SECRET))
    assert response.status_code == 500
    body = response.json()
    assert set(body) == {"code", "field", "message"}
    assert body["code"]


def test_the_endpoint_ends_expired_sessions_and_keeps_live_ones(
    client, database, db_session, jobs_secret, make_user
):
    from app.models import UserSession
    from app.schemas.sessions import LoginMethod

    user = make_user()

    def add(idle: float, age: float) -> UserSession:
        row = UserSession(
            user_id=user.id,
            refresh_token_hash=uuid4().hex,
            device_name="Pixel 8",
            platform="Android 14",
            login_method=LoginMethod.PASSWORD,
            created_at=days_ago(age),
            last_active_at=days_ago(idle),
        )
        db_session.add(row)
        return row

    idle_one = add(idle=120, age=130)
    old_one = add(idle=1, age=400)
    live_one = add(idle=1, age=10)
    db_session.commit()
    jobs_secret()
    response = client.post(JOBS_URL, headers=bearer(SECRET))
    assert response.status_code == 204
    with Session(database) as fresh:
        assert fresh.get(UserSession, idle_one.id).revoked_at is not None
        assert fresh.get(UserSession, old_one.id).revoked_at is not None
        assert fresh.get(UserSession, live_one.id).revoked_at is None


def test_calling_the_endpoint_twice_is_harmless(
    client, database, jobs_secret, make_user
):
    jobs_secret()
    assert client.post(JOBS_URL, headers=bearer(SECRET)).status_code == 204
    assert client.post(JOBS_URL, headers=bearer(SECRET)).status_code == 204
