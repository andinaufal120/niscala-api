"""Local rules that block weak or guessable passwords."""

from pathlib import Path

import pytest

COMMON_PASSWORDS_FILE = (
    Path(__file__).resolve().parent.parent / "data" / "common-passwords.txt"
)
NAME = "Rina Owner"
EMAIL = "rina@example.com"
STRONG_PASSWORDS = ["T7#vq9-lorem-ipsum", "mUk3!xqz-Plover", "correct horse battery"]


def file_entries() -> list[str]:
    return [
        line.strip()
        for line in COMMON_PASSWORDS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def listed_passwords(count: int = 8) -> list[str]:
    return [entry for entry in file_entries() if len(entry) >= 8][:count]


def check(password: str, name: str = NAME, email: str = EMAIL, **extra):
    from app.services.passwords import check_password_allowed

    return check_password_allowed(password, name=name, email=email, **extra)


def assert_blocked(password: str, name: str = NAME, email: str = EMAIL, **extra):
    from app.errors import ApiError

    with pytest.raises(ApiError) as caught:
        check(password, name, email, **extra)
    assert caught.value.status_code == 422
    assert caught.value.code == "PASSWORD_TOO_COMMON"
    return caught.value


def test_list_file_holds_about_a_hundred_thousand_entries():
    lines = COMMON_PASSWORDS_FILE.read_text(encoding="utf-8").splitlines()
    assert sum(1 for line in lines if line.strip()) >= 99_000


def test_common_passwords_are_loaded_lower_cased_into_a_frozenset():
    from app.services.passwords import common_passwords

    loaded = common_passwords()
    assert isinstance(loaded, frozenset)
    assert len(loaded) >= 96_000
    assert all(entry == entry.lower() for entry in loaded)
    assert "password123" in loaded
    assert "qwertyuiop" in loaded


def test_common_passwords_are_loaded_once():
    from app.services.passwords import common_passwords

    assert common_passwords() is common_passwords()


@pytest.mark.parametrize("password", STRONG_PASSWORDS[:2])
def test_strong_examples_are_not_in_the_list(password):
    from app.services.passwords import common_passwords

    assert password.lower() not in common_passwords()


@pytest.mark.parametrize("password", ["password123", "qwertyuiop"])
def test_known_common_passwords_are_blocked(password):
    assert_blocked(password)


@pytest.mark.parametrize("password", listed_passwords())
def test_entries_of_the_list_are_blocked(password):
    assert_blocked(password)


@pytest.mark.parametrize("password", listed_passwords())
def test_list_entries_are_blocked_in_any_case(password):
    assert_blocked(password.upper())
    assert_blocked(password.lower())
    assert_blocked(password.swapcase())


def test_list_entries_are_blocked_whatever_the_user():
    assert_blocked("password123", name="Budi Santoso", email="budi.s@example.org")


@pytest.mark.parametrize(
    "password",
    [
        "aaaaaaaa",
        "11111111",
        "AAAAAAAA",
        "Aaaaaaaa",
        "zzzzzzzzzzzz",
        "a" * 128,
        "é" * 128,
    ],
)
def test_single_repeated_character_is_blocked(password):
    assert_blocked(password)


@pytest.mark.parametrize(
    "password",
    [
        "12345678",
        "23456789",
        "abcdefgh",
        "ABCDEFGH",
        "AbCdEfGh",
        "87654321",
        "hgfedcba",
        "HGFEDCBA",
        "abcdefghijklmnop",
        "9876543210",
    ],
)
def test_ascending_or_descending_run_is_blocked(password):
    assert_blocked(password)


@pytest.mark.parametrize("password", ["xk12345678", "12345678xk", "abcdefgh1"])
def test_partial_run_is_allowed(password):
    from app.services.passwords import common_passwords

    assert password.lower() not in common_passwords()
    check(password)


@pytest.mark.parametrize(
    "password",
    [
        "niscala!",
        "NISCALA!!",
        "NiScAlA123",
        "xx-niscala-xx",
        "T7#vq9-niscala",
        "niscala-T7#vq9",
        "T7#vq9-NISCALA-lorem",
    ],
)
def test_password_containing_the_app_name_is_blocked(password):
    assert_blocked(password)


@pytest.mark.parametrize(
    "password",
    [
        "T7#vq9-rina-ipsum",
        "T7#vq9-RINA-ipsum",
        "Rina-T7#vq9-lorem",
        "T7#vq9-lorem-rina",
        "rinaT7#vq9lorem",
    ],
)
def test_password_containing_the_email_local_part_is_blocked(password):
    assert_blocked(password)


def test_email_local_part_is_compared_lower_cased():
    assert_blocked("T7#vq9-budi.s-ipsum", email="Budi.S@Example.com")
    assert_blocked("T7#vq9-BUDI.S-ipsum", email="budi.s@example.com")


def test_email_domain_is_not_part_of_the_local_part():
    check("T7#vq9-example-ipsum", email="rina@example.com")


def test_email_local_part_of_exactly_four_characters_is_checked():
    assert_blocked("T7#vq9-abcd-ipsum", email="abcd@example.com")


@pytest.mark.parametrize("email", ["abc@example.com", "ab@example.com", "a@b.co"])
def test_email_local_part_shorter_than_four_characters_is_ignored(email):
    local = email.split("@")[0]
    check(f"T7#vq9-{local}-ipsum", email=email)


@pytest.mark.parametrize(
    "password",
    [
        "T7#vq9-rina owner-ipsum",
        "T7#vq9-RINA OWNER-ipsum",
        "Rina Owner T7#vq9",
        "T7#vq9 rina owner",
    ],
)
def test_password_containing_the_name_is_blocked(password):
    assert_blocked(password, email="unrelated@example.com")


def test_name_is_trimmed_before_comparison():
    assert_blocked("T7#vq9-rina owner-ipsum", name="  Rina Owner  ", email="u@e.com")


def test_name_of_exactly_four_characters_is_checked():
    assert_blocked("T7#vq9-budi-ipsum", name="Budi", email="unrelated@example.com")
    assert_blocked("T7#vq9-budi-ipsum", name=" BUDI ", email="unrelated@example.com")


@pytest.mark.parametrize("name", ["Ann", "Al", "A", "  Ann  "])
def test_name_shorter_than_four_characters_is_ignored(name):
    check(
        f"T7#vq9-{name.strip().lower()}-ipsum", name=name, email="unrelated@example.com"
    )


def test_name_of_three_characters_after_trimming_is_ignored_even_with_padding():
    check("T7#vq9-ann-ipsum", name="    Ann    ", email="unrelated@example.com")


@pytest.mark.parametrize("password", STRONG_PASSWORDS)
def test_strong_passwords_are_allowed(password):
    assert check(password) is None


def test_a_128_character_password_is_allowed():
    password = ("T7#vq9-lorem-ipsum-" * 10)[:128]
    assert len(password) == 128
    assert check(password) is None


def test_the_error_names_the_password_field_by_default():
    assert assert_blocked("password123").field == "password"


def test_the_error_uses_the_given_field():
    assert assert_blocked("password123", field="newPassword").field == "newPassword"


def test_the_error_has_a_message():
    assert assert_blocked("password123").message
