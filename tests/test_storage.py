"""File stores, the store chosen from the settings, and `save_file`."""

import io
import logging
from uuid import uuid4

import pytest
from file_store_support import MemoryFileStore
from sqlalchemy import text
from sqlalchemy.orm import Session

ACCOUNT_ID = "abc123"
ACCESS_KEY_ID = "access-key"
SECRET_ACCESS_KEY = "secret-key"
BUCKET = "niscala-files"
R2_VARIABLES = {
    "R2_ACCOUNT_ID": ACCOUNT_ID,
    "R2_ACCESS_KEY_ID": ACCESS_KEY_ID,
    "R2_SECRET_ACCESS_KEY": SECRET_ACCESS_KEY,
    "R2_BUCKET": BUCKET,
}


def new_key(folder: str = "receipts") -> str:
    return f"{folder}/{uuid4()}/{uuid4()}"


# The protocol


def test_the_protocol_declares_put_get_and_delete():
    from app.storage import FileStore

    for name in ("put", "get", "delete"):
        assert callable(getattr(FileStore, name, None))


# The local store


@pytest.fixture
def local(tmp_path):
    from app.storage import LocalFileStore

    return LocalFileStore(tmp_path / "files")


def test_a_local_store_returns_what_was_put(local):
    key = new_key()
    local.put(key, b"image bytes", "image/png")
    assert local.get(key) == b"image bytes"


def test_a_local_store_keeps_the_file_below_its_root(local, tmp_path):
    key = new_key()
    local.put(key, b"image bytes", "image/png")
    files = [p for p in (tmp_path / "files").rglob("*") if p.is_file()]
    assert len(files) == 1
    assert files[0].relative_to(tmp_path / "files").parts[:-1] == tuple(
        key.split("/")[:-1]
    )
    assert files[0].read_bytes() == b"image bytes"


def test_a_local_store_creates_the_missing_directories(tmp_path):
    from app.storage import LocalFileStore

    root = tmp_path / "does" / "not" / "exist"
    store = LocalFileStore(root)
    store.put(new_key(), b"x", "image/png")
    assert root.is_dir()


def test_a_local_store_replaces_the_content_of_an_existing_key(local):
    key = new_key()
    local.put(key, b"first", "image/png")
    local.put(key, b"second", "image/jpeg")
    assert local.get(key) == b"second"


def test_a_local_store_keeps_keys_apart(local):
    first, second = new_key(), new_key()
    local.put(first, b"one", "image/png")
    local.put(second, b"two", "image/png")
    assert local.get(first) == b"one"
    assert local.get(second) == b"two"


def test_a_local_store_stores_empty_and_large_content(local):
    empty, large = new_key(), new_key()
    local.put(empty, b"", "image/png")
    local.put(large, b"\x00\xff" * 1_000_000, "image/png")
    assert local.get(empty) == b""
    assert local.get(large) == b"\x00\xff" * 1_000_000


def test_a_local_store_raises_file_not_found_for_a_missing_key(local):
    with pytest.raises(FileNotFoundError):
        local.get(new_key())


def test_a_local_store_deletes_a_key(local):
    key = new_key()
    local.put(key, b"x", "image/png")
    local.delete(key)
    with pytest.raises(FileNotFoundError):
        local.get(key)


def test_deleting_a_missing_key_is_not_an_error(local):
    local.delete(new_key())


def test_deleting_twice_is_not_an_error(local):
    key = new_key()
    local.put(key, b"x", "image/png")
    local.delete(key)
    local.delete(key)


def test_deleting_one_key_keeps_the_others(local):
    kept, removed = new_key(), new_key()
    local.put(kept, b"kept", "image/png")
    local.put(removed, b"removed", "image/png")
    local.delete(removed)
    assert local.get(kept) == b"kept"


ESCAPING_KEYS = ["../outside", "receipts/../../outside", "/etc/outside", "a/../../b"]


@pytest.mark.parametrize("key", ESCAPING_KEYS)
def test_a_local_store_refuses_a_key_that_escapes_its_root(local, tmp_path, key):
    with pytest.raises(ValueError):
        local.put(key, b"x", "image/png")
    with pytest.raises(ValueError):
        local.get(key)
    with pytest.raises(ValueError):
        local.delete(key)
    assert not (tmp_path / "outside").exists()


def test_a_refused_key_does_not_touch_a_file_outside_the_root(local, tmp_path):
    outside = tmp_path / "outside"
    outside.write_bytes(b"keep me")
    with pytest.raises(ValueError):
        local.delete("../outside")
    assert outside.read_bytes() == b"keep me"


# The R2 store


@pytest.fixture
def r2():
    from app.storage import R2FileStore

    return R2FileStore(ACCOUNT_ID, ACCESS_KEY_ID, SECRET_ACCESS_KEY, BUCKET)


def test_an_r2_store_can_be_constructed_without_network(r2):
    assert r2 is not None


def test_an_r2_store_talks_to_the_account_endpoint_in_the_auto_region(r2):
    assert (
        r2.client.meta.endpoint_url == f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com"
    )
    assert r2.client.meta.region_name == "auto"


def test_an_r2_put_sends_the_object_with_its_content_type(r2):
    from botocore.stub import Stubber

    key = new_key()
    with Stubber(r2.client) as stubber:
        stubber.add_response(
            "put_object",
            {},
            {
                "Bucket": BUCKET,
                "Key": key,
                "Body": b"image bytes",
                "ContentType": "image/jpeg",
            },
        )
        r2.put(key, b"image bytes", "image/jpeg")
        stubber.assert_no_pending_responses()


def test_an_r2_get_returns_the_body(r2):
    from botocore.response import StreamingBody
    from botocore.stub import Stubber

    key = new_key()
    body = b"image bytes"
    with Stubber(r2.client) as stubber:
        stubber.add_response(
            "get_object",
            {"Body": StreamingBody(io.BytesIO(body), len(body))},
            {"Bucket": BUCKET, "Key": key},
        )
        assert r2.get(key) == body
        stubber.assert_no_pending_responses()


@pytest.mark.parametrize("code", ["NoSuchKey", "404"])
def test_an_r2_get_of_a_missing_key_raises_file_not_found(r2, code):
    from botocore.stub import Stubber

    with Stubber(r2.client) as stubber:
        stubber.add_client_error(
            "get_object", service_error_code=code, http_status_code=404
        )
        with pytest.raises(FileNotFoundError):
            r2.get(new_key())


def test_an_r2_get_passes_other_errors_on(r2):
    from botocore.exceptions import ClientError
    from botocore.stub import Stubber

    with Stubber(r2.client) as stubber:
        stubber.add_client_error(
            "get_object", service_error_code="AccessDenied", http_status_code=403
        )
        with pytest.raises(ClientError):
            r2.get(new_key())


def test_an_r2_delete_removes_the_object(r2):
    from botocore.stub import Stubber

    key = new_key()
    with Stubber(r2.client) as stubber:
        stubber.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": key})
        r2.delete(key)
        stubber.assert_no_pending_responses()


def test_an_r2_delete_of_a_missing_key_does_not_raise(r2):
    from botocore.stub import Stubber

    with Stubber(r2.client) as stubber:
        stubber.add_client_error(
            "delete_object", service_error_code="NoSuchKey", http_status_code=404
        )
        r2.delete(new_key())


# The store chosen from the settings


@pytest.fixture
def configure(monkeypatch, tmp_path):
    """Set the storage settings for one test, ignoring any `.env` file."""
    from app import storage
    from app.config import Settings, get_settings

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    names = [*R2_VARIABLES, "FILE_STORAGE_DIR"]

    def forget() -> None:
        get_settings.cache_clear()
        for value in vars(storage).values():
            clear = getattr(value, "cache_clear", None)
            if callable(clear):
                clear()

    def apply(**variables: str | None) -> None:
        for name in names:
            monkeypatch.delenv(name, raising=False)
        for name, value in variables.items():
            if value is not None:
                monkeypatch.setenv(name, value)
        forget()

    apply()
    yield apply
    forget()


def test_all_four_r2_settings_select_the_r2_store(configure, tmp_path):
    from app.storage import R2FileStore, get_file_store

    configure(**R2_VARIABLES, FILE_STORAGE_DIR=str(tmp_path))
    assert isinstance(get_file_store(), R2FileStore)


def test_the_r2_store_uses_the_configured_account(configure):
    from app.storage import get_file_store

    configure(**R2_VARIABLES)
    store = get_file_store()
    assert (
        store.client.meta.endpoint_url
        == f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com"
    )


def test_no_r2_settings_select_the_local_store(configure, tmp_path):
    from app.storage import LocalFileStore, get_file_store

    configure(FILE_STORAGE_DIR=str(tmp_path / "files"))
    store = get_file_store()
    assert isinstance(store, LocalFileStore)
    key = new_key()
    store.put(key, b"x", "image/png")
    assert (tmp_path / "files").is_dir()
    assert [p for p in (tmp_path / "files").rglob("*") if p.is_file()]


@pytest.mark.parametrize("missing", list(R2_VARIABLES))
def test_one_missing_r2_setting_selects_the_local_store(configure, tmp_path, missing):
    from app.storage import LocalFileStore, get_file_store

    variables = {k: v for k, v in R2_VARIABLES.items() if k != missing}
    configure(**variables, FILE_STORAGE_DIR=str(tmp_path))
    assert isinstance(get_file_store(), LocalFileStore)


@pytest.mark.parametrize("blank", list(R2_VARIABLES))
@pytest.mark.parametrize("value", ["", "   "], ids=["empty", "spaces"])
def test_one_blank_r2_setting_selects_the_local_store(
    configure, tmp_path, blank, value
):
    from app.storage import LocalFileStore, get_file_store

    configure(**{**R2_VARIABLES, blank: value}, FILE_STORAGE_DIR=str(tmp_path))
    assert isinstance(get_file_store(), LocalFileStore)


def test_the_settings_expose_the_storage_values(configure, tmp_path):
    from pathlib import Path

    from app.config import get_settings

    configure(**R2_VARIABLES, FILE_STORAGE_DIR=str(tmp_path))
    settings = get_settings()
    assert settings.r2_account_id == ACCOUNT_ID
    assert settings.r2_access_key_id == ACCESS_KEY_ID
    assert settings.r2_secret_access_key == SECRET_ACCESS_KEY
    assert settings.r2_bucket == BUCKET
    assert Path(settings.file_storage_dir) == tmp_path


def test_the_r2_settings_are_unset_by_default(configure):
    from app.config import get_settings

    settings = get_settings()
    assert settings.r2_account_id is None
    assert settings.r2_access_key_id is None
    assert settings.r2_secret_access_key is None
    assert settings.r2_bucket is None


# Saving a file with a transaction


@pytest.fixture
def store():
    return MemoryFileStore()


def begin(db: Session) -> None:
    """Start the transaction, as the first statement of a request does."""
    db.execute(text("SELECT 1"))


def seed(store: MemoryFileStore, key: str, content: bytes = b"old") -> str:
    store.put(key, content, "image/png")
    store.calls.clear()
    return key


def test_save_file_puts_the_object_at_once(db_session, store):
    from app.storage import save_file

    begin(db_session)
    key = new_key()
    save_file(db_session, store, key, b"new", "image/jpeg")
    assert store.objects[key] == (b"new", "image/jpeg")


def test_a_commit_keeps_the_new_object(db_session, store):
    from app.storage import save_file

    begin(db_session)
    key = new_key()
    save_file(db_session, store, key, b"new", "image/png")
    db_session.commit()
    assert store.objects[key] == (b"new", "image/png")
    assert store.deleted() == []


def test_a_commit_deletes_the_replaced_object(db_session, store):
    from app.storage import save_file

    old = seed(store, new_key())
    begin(db_session)
    key = new_key()
    save_file(db_session, store, key, b"new", "image/png", replaces=old)
    db_session.commit()
    assert store.keys == {key}


def test_the_replaced_object_stays_until_the_commit(db_session, store):
    from app.storage import save_file

    old = seed(store, new_key())
    begin(db_session)
    key = new_key()
    save_file(db_session, store, key, b"new", "image/png", replaces=old)
    assert store.keys == {old, key}
    assert store.deleted() == []


def test_a_rollback_deletes_the_new_object_and_keeps_the_replaced_one(
    db_session, store
):
    from app.storage import save_file

    old = seed(store, new_key())
    begin(db_session)
    key = new_key()
    save_file(db_session, store, key, b"new", "image/png", replaces=old)
    db_session.rollback()
    assert store.keys == {old}


def test_a_rollback_without_a_replaced_object_deletes_the_new_one(db_session, store):
    from app.storage import save_file

    begin(db_session)
    key = new_key()
    save_file(db_session, store, key, b"new", "image/png")
    db_session.rollback()
    assert store.objects == {}


def test_a_released_savepoint_deletes_nothing_until_the_outer_commit(db_session, store):
    from app.storage import save_file

    old = seed(store, new_key())
    begin(db_session)
    key = new_key()
    with db_session.begin_nested():
        save_file(db_session, store, key, b"new", "image/png", replaces=old)
    assert store.keys == {old, key}
    assert store.deleted() == []
    db_session.commit()
    assert store.keys == {key}


def test_a_released_savepoint_followed_by_an_outer_rollback_deletes_the_new_object(
    db_session, store
):
    from app.storage import save_file

    old = seed(store, new_key())
    begin(db_session)
    key = new_key()
    with db_session.begin_nested():
        save_file(db_session, store, key, b"new", "image/png", replaces=old)
    db_session.rollback()
    assert store.keys == {old}


def test_every_file_saved_in_a_transaction_follows_its_commit(db_session, store):
    from app.storage import save_file

    old_a, old_b = seed(store, new_key()), seed(store, new_key())
    begin(db_session)
    new_a, new_b = new_key(), new_key()
    save_file(db_session, store, new_a, b"a", "image/png", replaces=old_a)
    save_file(db_session, store, new_b, b"b", "image/png", replaces=old_b)
    db_session.commit()
    assert store.keys == {new_a, new_b}


def test_every_file_saved_in_a_transaction_follows_its_rollback(db_session, store):
    from app.storage import save_file

    old_a, old_b = seed(store, new_key()), seed(store, new_key())
    begin(db_session)
    save_file(db_session, store, new_key(), b"a", "image/png", replaces=old_a)
    save_file(db_session, store, new_key(), b"b", "image/png", replaces=old_b)
    db_session.rollback()
    assert store.keys == {old_a, old_b}


def test_the_work_of_a_finished_transaction_is_not_repeated(db_session, store):
    from app.storage import save_file

    old = seed(store, new_key())
    begin(db_session)
    save_file(db_session, store, new_key(), b"new", "image/png", replaces=old)
    db_session.commit()
    store.calls.clear()
    begin(db_session)
    db_session.commit()
    db_session.rollback()
    assert store.calls == []


def test_a_rolled_back_save_does_not_leak_into_the_next_transaction(db_session, store):
    from app.storage import save_file

    begin(db_session)
    save_file(db_session, store, new_key(), b"new", "image/png")
    db_session.rollback()
    survivor = seed(store, new_key())
    begin(db_session)
    db_session.commit()
    assert store.keys == {survivor}
    assert store.calls == []


def test_a_committed_save_followed_by_a_rollback_keeps_the_committed_object(
    db_session, store
):
    from app.storage import save_file

    begin(db_session)
    key = new_key()
    save_file(db_session, store, key, b"new", "image/png")
    db_session.commit()
    begin(db_session)
    db_session.rollback()
    assert store.keys == {key}


def test_pending_work_does_not_leak_between_sessions(database, store):
    from app.storage import save_file

    old = seed(store, new_key())
    with Session(database) as first, Session(database) as second:
        begin(first)
        begin(second)
        key = new_key()
        save_file(first, store, key, b"new", "image/png", replaces=old)
        second.commit()
        assert store.keys == {old, key}
        second.rollback()
        assert store.keys == {old, key}
        first.commit()
        assert store.keys == {key}


def test_a_rollback_in_another_session_keeps_the_pending_work(database, store):
    from app.storage import save_file

    old = seed(store, new_key())
    with Session(database) as first, Session(database) as second:
        begin(first)
        begin(second)
        key = new_key()
        save_file(first, store, key, b"new", "image/png", replaces=old)
        second.rollback()
        first.commit()
        assert store.keys == {key}


def test_a_failing_put_raises_and_leaves_nothing_pending(db_session, store):
    from app.storage import save_file

    old = seed(store, new_key())
    store.fail_on_put = True
    begin(db_session)
    with pytest.raises(RuntimeError):
        save_file(db_session, store, new_key(), b"new", "image/png", replaces=old)
    db_session.commit()
    assert store.keys == {old}
    assert store.deleted() == []


def test_a_failing_delete_does_not_make_the_commit_fail(db_session, store, caplog):
    from app.storage import save_file

    old = seed(store, new_key())
    begin(db_session)
    key = new_key()
    save_file(db_session, store, key, b"new", "image/png", replaces=old)
    store.fail_on_delete = True
    with caplog.at_level(logging.WARNING):
        db_session.commit()
    assert store.objects[key] == (b"new", "image/png")
    assert any(r.levelno >= logging.WARNING for r in caplog.records)
    assert store.deleted() == [old]


def test_a_failing_delete_does_not_make_the_rollback_fail(db_session, store, caplog):
    from app.storage import save_file

    begin(db_session)
    key = new_key()
    save_file(db_session, store, key, b"new", "image/png")
    store.fail_on_delete = True
    with caplog.at_level(logging.WARNING):
        db_session.rollback()
    assert any(r.levelno >= logging.WARNING for r in caplog.records)
    assert store.deleted() == [key]


def test_a_failing_delete_does_not_stop_the_other_deletes(db_session, store):
    from app.storage import save_file

    old_a, old_b = seed(store, new_key()), seed(store, new_key())
    begin(db_session)
    save_file(db_session, store, new_key(), b"a", "image/png", replaces=old_a)
    save_file(db_session, store, new_key(), b"b", "image/png", replaces=old_b)
    store.fail_on_delete = True
    db_session.commit()
    assert sorted(store.deleted()) == sorted([old_a, old_b])


def test_a_context_manager_session_commit_deletes_the_replaced_object(database, store):
    from app.storage import save_file

    old = seed(store, new_key())
    key = new_key()
    with Session(database) as db:
        begin(db)
        save_file(db, store, key, b"new", "image/png", replaces=old)
        db.commit()
    assert store.keys == {key}
