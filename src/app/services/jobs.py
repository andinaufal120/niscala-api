"""Jobs that run once a day, each in its own transaction."""

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.db import get_engine
from app.services.notifications import send_due_date_reminders, send_overdue_notices
from app.services.sessions import end_expired_sessions
from app.services.subscriptions import (
    apply_plan_limits,
    reconcile_google_play_subscriptions,
)

logger = logging.getLogger(__name__)

type Job = Callable[[Session], object]

DAILY_JOBS: list[Job] = [
    end_expired_sessions,
    send_due_date_reminders,
    send_overdue_notices,
    reconcile_google_play_subscriptions,
    apply_plan_limits,
]


def run_daily_jobs(jobs: list[Job] | None = None) -> list[str]:
    """Run each job in its own session and return the names of the jobs that failed.

    A job's changes are committed when it returns and rolled back when it raises.
    A failure is logged and the remaining jobs still run.
    """
    failed: list[str] = []
    for job in DAILY_JOBS if jobs is None else jobs:
        with Session(get_engine()) as db:
            try:
                job(db)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Daily job %s failed", job.__name__)
                failed.append(job.__name__)
    return failed
