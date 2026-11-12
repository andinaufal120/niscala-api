"""The `android_cert_sha256` setting that feeds the Digital Asset Links file."""

import pytest
from pydantic import ValidationError

VARIABLE = "ANDROID_CERT_SHA256"


def fingerprint(seed: int = 0, *, upper: bool = True) -> str:
    """A well-formed fingerprint: 32 bytes as hex pairs separated by colons."""
    text = ":".join(f"{(seed + 7 * n) % 256:02X}" for n in range(32))
    return text if upper else text.lower()


FIRST = fingerprint(1)
SECOND = fingerprint(100)


@pytest.fixture
def configure(monkeypatch):
    """Control `ANDROID_CERT_SHA256`; call with no argument to leave it unset."""
    from app.config import get_settings

    monkeypatch.delenv(VARIABLE, raising=False)
    get_settings.cache_clear()

    def apply(value: str | None = None) -> None:
        if value is None:
            monkeypatch.delenv(VARIABLE, raising=False)
        else:
            monkeypatch.setenv(VARIABLE, value)
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


def read_setting() -> list[str]:
    from app.config import Settings

    return Settings().android_cert_sha256


def test_the_fingerprint_helper_builds_95_characters() -> None:
    assert len(FIRST) == 95
    assert FIRST != SECOND


# Parsing


def test_the_default_is_an_empty_list(configure) -> None:
    configure(None)
    assert read_setting() == []


def test_an_empty_value_is_an_empty_list(configure) -> None:
    configure("")
    assert read_setting() == []


def test_a_value_of_only_blanks_and_commas_is_an_empty_list(configure) -> None:
    configure(" , ,,  ,")
    assert read_setting() == []


def test_one_fingerprint_is_a_list_of_one(configure) -> None:
    configure(FIRST)
    assert read_setting() == [FIRST]


def test_several_fingerprints_keep_their_configured_order(configure) -> None:
    configure(f"{SECOND},{FIRST}")
    assert read_setting() == [SECOND, FIRST]


def test_spaces_around_each_entry_are_trimmed(configure) -> None:
    configure(f"  {FIRST}  ,\t{SECOND} ")
    assert read_setting() == [FIRST, SECOND]


def test_blank_entries_are_dropped(configure) -> None:
    configure(f",{FIRST},, ,{SECOND},")
    assert read_setting() == [FIRST, SECOND]


def test_lower_case_entries_are_stored_upper_case(configure) -> None:
    configure(fingerprint(1, upper=False))
    assert read_setting() == [FIRST]


def test_mixed_case_entries_are_stored_upper_case(configure) -> None:
    mixed = "".join(
        char.lower() if index % 2 else char for index, char in enumerate(FIRST)
    )
    assert mixed != FIRST
    configure(mixed)
    assert read_setting() == [FIRST]


def test_every_entry_of_a_list_is_normalized(configure) -> None:
    configure(f"{fingerprint(1, upper=False)}, {fingerprint(100, upper=False)}")
    assert read_setting() == [FIRST, SECOND]


def test_the_setting_is_read_through_get_settings(configure) -> None:
    from app.config import get_settings

    configure(fingerprint(1, upper=False))
    assert get_settings().android_cert_sha256 == [FIRST]


def test_a_changed_environment_is_seen_after_the_cache_is_cleared(configure) -> None:
    from app.config import get_settings

    configure(FIRST)
    assert get_settings().android_cert_sha256 == [FIRST]
    configure(SECOND)
    assert get_settings().android_cert_sha256 == [SECOND]


def test_the_all_zero_and_all_f_fingerprints_are_valid(configure) -> None:
    zeros = ":".join(["00"] * 32)
    ones = ":".join(["FF"] * 32)
    configure(f"{zeros},{ones}")
    assert read_setting() == [zeros, ones]


# Invalid shapes

VALID_BYTES = FIRST.split(":")


def with_bytes(count: int) -> str:
    return ":".join((VALID_BYTES * 2)[:count])


def replace_first_colon(separator: str) -> str:
    return FIRST.replace(":", separator, 1)


INVALID = {
    "one_byte": "AB",
    "31_bytes": with_bytes(31),
    "33_bytes": with_bytes(33),
    "64_bytes": ":".join(["AB"] * 64),
    "94_characters": FIRST[:-1],
    "96_characters": FIRST + "A",
    "trailing_colon": FIRST + ":",
    "leading_colon": ":" + FIRST,
    "no_separators": FIRST.replace(":", ""),
    "dash_separators": FIRST.replace(":", "-"),
    "space_separators": FIRST.replace(":", " "),
    "dot_separators": FIRST.replace(":", "."),
    "underscore_separators": FIRST.replace(":", "_"),
    "one_dash_among_colons": replace_first_colon("-"),
    "one_space_among_colons": replace_first_colon(" "),
    "two_colons_in_a_row": FIRST.replace(":", "::", 1)[:-1],
    "empty_segment": "::".join([FIRST[:2], FIRST[6:]]),
    "non_hex_letter": "G" + FIRST[1:],
    "non_hex_letter_in_the_middle": FIRST[:40] + "Z" + FIRST[41:],
    "non_hex_last_character": FIRST[:-1] + "X",
    "non_ascii_digit": "١" + FIRST[1:],
    "hex_prefix": "0x" + FIRST[2:],
    "segments_of_uneven_length": "A:BCD:" + FIRST[6:],
    "segments_of_three_digits": ":".join(["ABC"] * 24)[:95],
    "single_digit_segments": ":".join(["A"] * 32),
    "unrelated_text": "not-a-fingerprint",
    "sha1_length": ":".join(VALID_BYTES[:20]),
    "uuid": "123e4567-e89b-12d3-a456-426614174000",
}


@pytest.mark.parametrize("value", INVALID.values(), ids=INVALID.keys())
def test_an_invalid_fingerprint_stops_settings_from_loading(configure, value) -> None:
    configure(value)
    with pytest.raises(ValidationError):
        read_setting()


@pytest.mark.parametrize("value", INVALID.values(), ids=INVALID.keys())
def test_an_invalid_fingerprint_stops_the_cached_settings_from_loading(
    configure, value
) -> None:
    from app.config import get_settings

    configure(value)
    with pytest.raises(ValidationError):
        get_settings()


def test_one_invalid_entry_among_valid_ones_fails_the_whole_value(configure) -> None:
    configure(f"{FIRST},{FIRST[:-1]},{SECOND}")
    with pytest.raises(ValidationError):
        read_setting()


def test_an_invalid_first_entry_fails_even_when_the_rest_is_valid(configure) -> None:
    configure(f"{FIRST.replace(':', '-')},{SECOND}")
    with pytest.raises(ValidationError):
        read_setting()


def test_the_error_names_the_setting(configure) -> None:
    configure("nonsense")
    with pytest.raises(ValidationError) as caught:
        read_setting()
    locations = [error["loc"] for error in caught.value.errors()]
    assert any("android_cert_sha256" in location for location in locations)
