"""Database engine and the per-request session dependency."""

from collections.abc import Iterator
from functools import cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.config import get_settings


@cache
def get_engine() -> Engine:
    """Return the process-wide engine for the configured database."""
    return create_engine(get_settings().database_url)


def get_session() -> Iterator[Session]:
    """Yield a session for one request.

    Commits when the handler returns normally. On any exception the session is
    rolled back and the exception propagates. The session is always closed.
    """
    session = Session(get_engine())
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
