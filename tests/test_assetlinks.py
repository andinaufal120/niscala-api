"""The Digital Asset Links file that lets Android open Niscala links in the app."""

import pytest

URL = "/.well-known/assetlinks.json"
PACKAGE = "id.niscala.app"
RELATION = "delegate_permission/common.handle_all_urls"


def fingerprint(seed: int) -> str:
    return ":".join(f"{(seed + 11 * n) % 256:02X}" for n in range(32))


FIRST = fingerprint(3)
SECOND = fingerprint(90)
THIRD = fingerprint(200)


@pytest.fixture
def links(monkeypatch):
    """Control the package and the fingerprints; unset by default."""
    from app.config import get_settings

    monkeypatch.delenv("GOOGLE_PLAY_PACKAGE_NAME", raising=False)
    monkeypatch.delenv("ANDROID_CERT_SHA256", raising=False)
    get_settings.cache_clear()

    def configure(package: str | None = PACKAGE, fingerprints: str | None = FIRST):
        for name, value in (
            ("GOOGLE_PLAY_PACKAGE_NAME", package),
            ("ANDROID_CERT_SHA256", fingerprints),
        ):
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        get_settings.cache_clear()

    yield configure
    get_settings.cache_clear()


def statement(package: str, fingerprints: list[str]) -> list[dict]:
    return [
        {
            "relation": [RELATION],
            "target": {
                "namespace": "android_app",
                "package_name": package,
                "sha256_cert_fingerprints": fingerprints,
            },
        }
    ]


def assert_not_found(response) -> None:
    assert response.status_code == 404, response.text
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert body["field"] is None
    assert body["message"]


# Configured


def test_the_file_lists_the_package_and_the_fingerprint(client, links) -> None:
    links()
    response = client.get(URL)
    assert response.status_code == 200, response.text
    assert response.json() == statement(PACKAGE, [FIRST])


def test_the_content_type_is_json(client, links) -> None:
    links()
    response = client.get(URL)
    assert response.headers["content-type"].split(";")[0].strip() == "application/json"


def test_the_file_holds_exactly_one_statement(client, links) -> None:
    links()
    assert len(client.get(URL).json()) == 1


def test_the_statement_has_only_the_handle_all_urls_relation(client, links) -> None:
    links()
    (entry,) = client.get(URL).json()
    assert entry["relation"] == [RELATION]


def test_the_target_has_exactly_the_documented_keys(client, links) -> None:
    links()
    (entry,) = client.get(URL).json()
    assert set(entry) == {"relation", "target"}
    assert set(entry["target"]) == {
        "namespace",
        "package_name",
        "sha256_cert_fingerprints",
    }
    assert entry["target"]["namespace"] == "android_app"


def test_several_fingerprints_stay_in_the_configured_order(client, links) -> None:
    links(fingerprints=f"{SECOND},{FIRST},{THIRD}")
    response = client.get(URL)
    assert response.status_code == 200, response.text
    assert response.json() == statement(PACKAGE, [SECOND, FIRST, THIRD])


def test_there_is_still_one_statement_for_several_fingerprints(client, links) -> None:
    links(fingerprints=f"{FIRST},{SECOND}")
    assert len(client.get(URL).json()) == 1


def test_lower_case_fingerprints_are_served_upper_case(client, links) -> None:
    links(fingerprints=f"{FIRST.lower()},{SECOND.lower()}")
    assert client.get(URL).json() == statement(PACKAGE, [FIRST, SECOND])


def test_blanks_in_the_setting_do_not_reach_the_file(client, links) -> None:
    links(fingerprints=f" {FIRST} , ,{SECOND},")
    assert client.get(URL).json() == statement(PACKAGE, [FIRST, SECOND])


def test_the_package_is_the_google_play_package(client, links) -> None:
    links(package="com.example.other")
    (entry,) = client.get(URL).json()
    assert entry["target"]["package_name"] == "com.example.other"


def test_a_changed_configuration_shows_in_the_next_response(client, links) -> None:
    links()
    assert client.get(URL).json() == statement(PACKAGE, [FIRST])
    links(package="id.niscala.beta", fingerprints=SECOND)
    assert client.get(URL).json() == statement("id.niscala.beta", [SECOND])


def test_the_file_is_the_same_on_every_request(client, links) -> None:
    links()
    assert client.get(URL).content == client.get(URL).content


# Not configured


def test_an_unset_package_answers_not_found(client, links) -> None:
    links(package=None)
    assert_not_found(client.get(URL))


def test_an_empty_package_answers_not_found(client, links) -> None:
    links(package="")
    assert_not_found(client.get(URL))


def test_a_blank_package_answers_not_found(client, links) -> None:
    links(package="   ")
    assert_not_found(client.get(URL))


def test_unset_fingerprints_answer_not_found(client, links) -> None:
    links(fingerprints=None)
    assert_not_found(client.get(URL))


def test_empty_fingerprints_answer_not_found(client, links) -> None:
    links(fingerprints="")
    assert_not_found(client.get(URL))


def test_blank_fingerprints_answer_not_found(client, links) -> None:
    links(fingerprints=" , ,")
    assert_not_found(client.get(URL))


def test_nothing_configured_answers_not_found(client, links) -> None:
    links(package=None, fingerprints=None)
    assert_not_found(client.get(URL))


def test_a_blank_package_with_empty_fingerprints_answers_not_found(
    client, links
) -> None:
    links(package=" ", fingerprints="")
    assert_not_found(client.get(URL))


def test_the_not_found_answer_is_json(client, links) -> None:
    links(package=None)
    content_type = client.get(URL).headers["content-type"]
    assert content_type.split(";")[0].strip() == "application/json"


def test_the_file_appears_once_both_values_are_configured(client, links) -> None:
    links(package=PACKAGE, fingerprints=None)
    assert client.get(URL).status_code == 404
    links(package=PACKAGE, fingerprints=FIRST)
    assert client.get(URL).status_code == 200
    links(package=None, fingerprints=FIRST)
    assert client.get(URL).status_code == 404


# Access


def test_the_file_needs_no_authentication(client, links) -> None:
    links()
    response = client.get(URL)
    assert "authorization" not in response.request.headers
    assert response.status_code == 200


def test_an_invalid_bearer_token_does_not_matter(client, links) -> None:
    links()
    response = client.get(URL, headers={"Authorization": "Bearer not-a-token"})
    assert response.status_code == 200
    assert response.json() == statement(PACKAGE, [FIRST])


def test_the_file_needs_no_database(client, links, monkeypatch) -> None:
    links()
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:x@127.0.0.1:1/none")
    from app.config import get_settings

    get_settings.cache_clear()
    assert client.get(URL).status_code == 200


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_only_reading_is_allowed(client, links, method) -> None:
    links()
    response = getattr(client, method)(URL)
    assert response.status_code == 405
    body = response.json()
    assert body["code"] == "METHOD_NOT_ALLOWED"
    assert body["field"] is None


# Contract


def test_the_file_is_not_in_the_openapi_document(openapi) -> None:
    for path in openapi.document["paths"]:
        assert "well-known" not in path
        assert "assetlinks" not in path


def test_the_document_has_no_schema_for_the_file(openapi) -> None:
    text = str(openapi.document)
    assert "assetlinks" not in text
    assert "sha256_cert_fingerprints" not in text
