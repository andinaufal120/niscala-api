"""The database engine, the per-request session and the naming convention."""

from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def build_client(engine) -> TestClient:
    from app.db import get_session

    from app.errors import ApiError, register_error_handlers

    session_dep = Annotated[Session, Depends(get_session)]

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE scratch_items (id int PRIMARY KEY)"))

    private = FastAPI()
    register_error_handlers(private)

    def insert(session: Session, item_id: int) -> None:
        session.execute(text("INSERT INTO scratch_items VALUES (:id)"), {"id": item_id})

    @private.get("/ping")
    def ping(session: session_dep):
        return {"value": session.execute(text("SELECT 1")).scalar_one()}

    @private.get("/commit")
    def commit(session: session_dep):
        insert(session, 1)
        return {"ok": True}

    @private.get("/api-error")
    def api_error(session: session_dep):
        insert(session, 2)
        raise ApiError(409, "SCRATCH_CONFLICT")

    @private.get("/crash")
    def crash(session: session_dep):
        insert(session, 3)
        raise RuntimeError("crash")

    return TestClient(private, raise_server_exceptions=False)


def stored_ids(engine) -> list[int]:
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id FROM scratch_items ORDER BY id"))
        return [row[0] for row in rows]


def test_get_engine_is_cached_and_points_at_the_configured_database(
    database, postgres_url
):
    from app.db import get_engine

    engine = get_engine()
    assert get_engine() is engine
    expected = make_url(postgres_url)
    assert engine.url.host == expected.host
    assert engine.url.port == expected.port
    assert engine.url.database == expected.database


def test_get_session_yields_a_working_session(database):
    from app.db import get_session

    generator = get_session()
    session = next(generator)
    try:
        assert isinstance(session, Session)
        assert session.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        generator.close()


def test_session_dependency_serves_queries_in_a_request(database):
    response = build_client(database).get("/ping")
    assert response.status_code == 200
    assert response.json() == {"value": 1}


def test_session_commits_when_the_handler_returns_normally(database):
    client = build_client(database)
    assert client.get("/commit").status_code == 200
    assert stored_ids(database) == [1]


def test_session_rolls_back_when_the_handler_raises_api_error(database):
    client = build_client(database)
    response = client.get("/api-error")
    assert response.status_code == 409
    assert response.json() == {
        "code": "SCRATCH_CONFLICT",
        "field": None,
        "message": response.json()["message"],
    }
    assert response.json()["message"]
    assert stored_ids(database) == []


def test_session_rolls_back_when_the_handler_raises_unexpected_error(database):
    client = build_client(database)
    response = client.get("/crash")
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert stored_ids(database) == []


def test_session_is_closed_after_a_successful_request(database):
    client = build_client(database)
    client.get("/commit")
    assert database.pool.checkedout() == 0


def test_session_is_closed_after_a_failed_request(database):
    client = build_client(database)
    client.get("/api-error")
    client.get("/crash")
    assert database.pool.checkedout() == 0


def test_get_session_rolls_back_and_reraises_when_thrown_into(database):
    from app.db import get_session

    generator = get_session()
    session = next(generator)
    session.execute(text("SELECT 1"))
    try:
        generator.throw(ValueError("failure"))
    except ValueError:
        pass
    else:
        raise AssertionError("the original exception must propagate")
    assert database.pool.checkedout() == 0


def test_naming_convention_defines_all_constraint_kinds():
    from app.models import Base

    assert {"pk", "fk", "uq", "ix", "ck"} <= set(Base.metadata.naming_convention)
