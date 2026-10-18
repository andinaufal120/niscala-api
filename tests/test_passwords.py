"""Password hashing and verification."""

import pytest


def test_hash_is_an_argon2id_string():
    from app.services.passwords import hash_password

    assert hash_password("correct horse battery").startswith("$argon2id$")


def test_hash_does_not_contain_the_password():
    from app.services.passwords import hash_password

    assert "correct horse battery" not in hash_password("correct horse battery")


def test_hashing_the_same_password_twice_gives_different_hashes():
    from app.services.passwords import hash_password

    assert hash_password("same password") != hash_password("same password")


def test_correct_password_verifies():
    from app.services.passwords import hash_password, verify_password

    assert verify_password(
        "correct horse battery", hash_password("correct horse battery")
    )


def test_wrong_password_does_not_verify_and_does_not_raise():
    from app.services.passwords import hash_password, verify_password

    assert (
        verify_password("wrong password", hash_password("correct horse battery"))
        is False
    )


@pytest.mark.parametrize(
    "attempt", ["Correct horse battery", " correct horse battery", ""]
)
def test_verification_is_exact_and_case_sensitive(attempt):
    from app.services.passwords import hash_password, verify_password

    assert verify_password(attempt, hash_password("correct horse battery")) is False


@pytest.mark.parametrize(
    "password", ["x", "pässwörd with spaces ✓", "a" * 128, " padded "]
)
def test_any_password_round_trips(password):
    from app.services.passwords import hash_password, verify_password

    password_hash = hash_password(password)
    assert verify_password(password, password_hash) is True
    assert verify_password(password + "x", password_hash) is False


def test_each_hash_verifies_only_its_own_password():
    from app.services.passwords import hash_password, verify_password

    first, second = hash_password("first password"), hash_password("second password")
    assert verify_password("first password", first)
    assert not verify_password("first password", second)
