"""The pages a browser gets at the invitation, password-reset and email-change links."""

import html
import re
from urllib.parse import quote, urlsplit

import pytest

PACKAGE = "id.niscala.app"
PLAY_PREFIX = "https://play.google.com/store/apps/details?id="
PLAY_LINK = PLAY_PREFIX + PACKAGE
BASE_URL = "https://niscala.example.com"

PAGE_HEADERS = {
    "cache-control": "no-store",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
}

# Every address that serves the page, as (name, path) pairs.
PAGES = {
    "invitation": "/invitations/some-token",
    "password_reset_with_token": "/password-reset?token=some-token",
    "password_reset_without_token": "/password-reset",
    "email_change_with_token": "/email-change?token=some-token",
    "email_change_without_token": "/email-change",
}

TOKEN_MARKER = "tk9f3a7c"

# Tokens that are safe to send as one path segment.
HOSTILE_PATH_TOKENS = {
    "tag": f"{TOKEN_MARKER}<b>x<i>",
    "attribute_break": f'{TOKEN_MARKER}"><img src=x onerror=alert(1)>',
    "single_quote": f"{TOKEN_MARKER}'-alert(1)-'",
    "double_quote": f'{TOKEN_MARKER}"quoted"',
    "entity": f"{TOKEN_MARKER}&amp;&lt;",
    "template": f"{TOKEN_MARKER}{{{{7*7}}}}",
    "percent_format": f"{TOKEN_MARKER}%s%d",
    "lookup": f"{TOKEN_MARKER}${{jndi:ldap:x}}",
    "plain": f"{TOKEN_MARKER}-AbC_123",
}

HOSTILE_QUERY_TOKENS = {
    **HOSTILE_PATH_TOKENS,
    "script": f"{TOKEN_MARKER}<script>alert(1)</script>",
    "closing_script": f"</script><script>alert('{TOKEN_MARKER}')</script>",
    "javascript_url": f"javascript:alert('{TOKEN_MARKER}')",
}


@pytest.fixture
def play_package(monkeypatch):
    """Control `GOOGLE_PLAY_PACKAGE_NAME`; call with no argument to leave it unset."""
    from app.config import get_settings

    monkeypatch.delenv("GOOGLE_PLAY_PACKAGE_NAME", raising=False)
    get_settings.cache_clear()

    def configure(value: str | None = PACKAGE) -> None:
        if value is None:
            monkeypatch.delenv("GOOGLE_PLAY_PACKAGE_NAME", raising=False)
        else:
            monkeypatch.setenv("GOOGLE_PLAY_PACKAGE_NAME", value)
        get_settings.cache_clear()

    configure(PACKAGE)
    yield configure
    get_settings.cache_clear()


@pytest.fixture
def base_url(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("INVITATION_BASE_URL", BASE_URL)
    get_settings.cache_clear()
    yield BASE_URL
    get_settings.cache_clear()


def page(client, path: str, **kwargs):
    response = client.get(path, **kwargs)
    assert response.status_code == 200, response.text
    return response


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["field"] is None
    assert body["message"]


def urls_in(body: str) -> list[str]:
    return re.findall(r"(?:https?:)?//[^\s\"'<>)]+", body)


all_pages = pytest.mark.parametrize("path", PAGES.values(), ids=PAGES.keys())


# Status and headers


@all_pages
def test_a_page_answers_200(client, play_package, path) -> None:
    assert page(client, path).status_code == 200


@all_pages
def test_a_page_is_utf8_html(client, play_package, path) -> None:
    content_type = page(client, path).headers["content-type"]
    assert content_type.lower().replace(" ", "") == "text/html;charset=utf-8"


@all_pages
@pytest.mark.parametrize("header", PAGE_HEADERS)
def test_a_page_carries_the_protective_headers(
    client, play_package, path, header
) -> None:
    assert page(client, path).headers[header] == PAGE_HEADERS[header]


@all_pages
def test_the_protective_headers_stay_when_the_package_is_unset(
    client, play_package, path
) -> None:
    play_package(None)
    response = page(client, path)
    assert response.status_code == 200
    for header, value in PAGE_HEADERS.items():
        assert response.headers[header] == value


@all_pages
def test_a_page_sets_no_cookie(client, play_package, path) -> None:
    assert "set-cookie" not in page(client, path).headers


@all_pages
def test_a_page_is_an_html_document(client, play_package, path) -> None:
    body = page(client, path).text.lower()
    assert "<html" in body
    assert "</html>" in body
    assert "<body" in body


# Wording


@all_pages
def test_a_page_names_the_app(client, play_package, path) -> None:
    assert "Niscala" in page(client, path).text


@all_pages
def test_a_page_tells_the_user_in_indonesian_to_open_the_link_in_the_app(
    client, play_package, path
) -> None:
    text = page(client, path).text.lower()
    assert "aplikasi" in text
    assert "buka" in text


@all_pages
def test_a_page_mentions_the_phone(client, play_package, path) -> None:
    text = page(client, path).text.lower()
    assert any(word in text for word in ("ponsel", "telepon", "hp", "handphone"))


@all_pages
def test_a_page_is_not_written_in_english(client, play_package, path) -> None:
    text = page(client, path).text.lower()
    assert "open this link" not in text
    assert "install the app" not in text


@all_pages
def test_a_page_says_to_open_the_link_again_after_installing(
    client, play_package, path
) -> None:
    text = page(client, path).text.lower()
    assert "lagi" in text or "ulang" in text


@all_pages
def test_a_page_declares_its_language_as_indonesian(client, play_package, path) -> None:
    assert re.search(r"<html[^>]*lang=[\"']id", page(client, path).text.lower())


@all_pages
def test_a_page_is_small(client, play_package, path) -> None:
    assert len(page(client, path).content) < 10_000


@all_pages
def test_a_page_says_nothing_about_validity(client, play_package, path) -> None:
    text = page(client, path).text.lower()
    for word in ("kedaluwarsa", "expired", "invalid", "tidak valid"):
        assert word not in text


# Google Play link


@all_pages
def test_the_play_link_points_at_the_configured_package(
    client, play_package, path
) -> None:
    assert PLAY_LINK in page(client, path).text


@all_pages
def test_the_play_link_is_an_anchor(client, play_package, path) -> None:
    assert re.search(
        r"<a\s[^>]*href=[\"']" + re.escape(PLAY_LINK) + r"[\"']",
        page(client, path).text,
    )


@all_pages
def test_there_is_no_play_link_when_the_package_is_unset(
    client, play_package, path
) -> None:
    play_package(None)
    text = page(client, path).text
    assert "play.google.com" not in text
    assert "<a " not in text.lower()


@all_pages
def test_there_is_no_play_link_when_the_package_is_blank(
    client, play_package, path
) -> None:
    play_package("   ")
    text = page(client, path).text
    assert "play.google.com" not in text


@all_pages
def test_the_wording_stays_when_there_is_no_play_link(
    client, play_package, path
) -> None:
    play_package(None)
    text = page(client, path).text
    assert "Niscala" in text
    assert "aplikasi" in text.lower()


@all_pages
def test_a_changed_package_shows_in_the_next_response(
    client, play_package, path
) -> None:
    assert PLAY_LINK in page(client, path).text
    play_package("id.niscala.beta")
    text = page(client, path).text
    assert PLAY_PREFIX + "id.niscala.beta" in text
    assert PLAY_LINK not in text


def test_the_package_is_html_escaped_in_the_link(client, play_package) -> None:
    play_package("com.x&y<z")
    text = page(client, "/password-reset").text
    assert "com.x&amp;y&lt;z" in text
    assert "y<z" not in text


def test_a_quote_in_the_package_cannot_break_out_of_the_attribute(
    client, play_package
) -> None:
    play_package('com.x" onmouseover="alert(1)')
    text = page(client, "/password-reset").text
    assert 'onmouseover="' not in text
    assert "alert(1)" not in text or "&quot;" in text or "&#" in text


def test_a_tag_in_the_package_is_not_markup(client, play_package) -> None:
    play_package("com.x</a><script>alert(1)</script>")
    text = page(client, "/password-reset").text
    assert "<script" not in text.lower()


# Token never appears


@pytest.mark.parametrize(
    "token", HOSTILE_PATH_TOKENS.values(), ids=HOSTILE_PATH_TOKENS.keys()
)
def test_the_invitation_page_never_repeats_the_token(
    client, play_package, token
) -> None:
    response = page(client, "/invitations/" + quote(token, safe=""))
    assert response.status_code == 200, response.text
    body = response.text
    assert TOKEN_MARKER not in body
    for form in (token, html.escape(token), quote(token, safe="")):
        assert form not in body


@pytest.mark.parametrize(
    "path", ["/password-reset", "/email-change"], ids=["password_reset", "email_change"]
)
@pytest.mark.parametrize(
    "token", HOSTILE_QUERY_TOKENS.values(), ids=HOSTILE_QUERY_TOKENS.keys()
)
def test_the_query_pages_never_repeat_the_token(
    client, play_package, path, token
) -> None:
    response = client.get(path, params={"token": token})
    assert response.status_code == 200, response.text
    body = response.text
    assert TOKEN_MARKER not in body
    for form in (token, html.escape(token), quote(token, safe="")):
        assert form not in body


@pytest.mark.parametrize("path", ["/password-reset", "/email-change"])
def test_a_page_never_runs_a_script_from_the_token(client, play_package, path) -> None:
    body = client.get(path, params={"token": "<script>alert(1)</script>"}).text
    assert "alert(1)" not in body


def test_a_hostile_token_leaves_no_script_in_the_page(client, play_package) -> None:
    body = page(client, "/invitations/" + quote("<script>alert(1)<", safe="")).text
    assert "alert(1)" not in body
    assert "<script" not in body.lower()


@pytest.mark.parametrize("path", ["/password-reset", "/email-change"])
def test_other_query_parameters_are_not_repeated_either(
    client, play_package, path
) -> None:
    body = client.get(path, params={"token": "a", "next": f"{TOKEN_MARKER}x"}).text
    assert TOKEN_MARKER not in body


@pytest.mark.parametrize("path", ["/password-reset", "/email-change"])
def test_a_very_long_token_does_not_change_the_page(client, play_package, path) -> None:
    plain = client.get(path)
    long = client.get(path, params={"token": "t" * 4000})
    assert long.status_code == 200
    assert long.content == plain.content


@pytest.mark.parametrize("path", ["/password-reset", "/email-change"])
@pytest.mark.parametrize("query", ["token=", "token=a&token=b", "other=1", "token"])
def test_odd_query_strings_get_the_same_page(client, play_package, path, query) -> None:
    plain = client.get(path)
    odd = client.get(f"{path}?{query}")
    assert odd.status_code == 200
    assert odd.content == plain.content


# Same page whatever the token is


@pytest.mark.parametrize("path", ["/password-reset", "/email-change"])
def test_the_query_pages_are_identical_for_any_token_and_for_none(
    client, play_package, path
) -> None:
    with_token = client.get(path, params={"token": "abc123"})
    other_token = client.get(path, params={"token": "zzz999-different"})
    without = client.get(path)
    assert with_token.content == other_token.content == without.content
    for header in PAGE_HEADERS:
        assert with_token.headers[header] == without.headers[header]


def test_the_invitation_pages_of_two_unknown_tokens_are_identical(
    client, play_package
) -> None:
    first = page(client, "/invitations/unknown-one")
    second = page(client, "/invitations/another-unknown-token-entirely")
    assert first.content == second.content
    assert first.status_code == second.status_code == 200


def test_the_three_kinds_of_page_say_the_same_thing(client, play_package) -> None:
    bodies = {
        client.get(path).content
        for path in ("/invitations/x", "/password-reset", "/email-change")
    }
    assert len(bodies) == 1


def test_the_invitation_page_is_identical_for_a_real_and_an_unknown_token(
    client, database, play_package, make_user, make_property, make_room, make_tenant
) -> None:
    owner = make_user()
    room = make_room(make_property(owner))
    stored = make_tenant(room)
    real = page(client, f"/invitations/{stored.token}")
    unknown = page(client, "/invitations/unknown-token")
    assert real.status_code == unknown.status_code == 200
    assert real.content == unknown.content
    assert stored.token not in real.text
    for header in PAGE_HEADERS:
        assert real.headers[header] == unknown.headers[header]


def test_the_invitation_page_is_identical_for_expired_and_valid_links(
    client, database, play_package, make_user, make_property, make_room, make_tenant
) -> None:
    owner = make_user()
    prop = make_property(owner)
    valid = make_tenant(make_room(prop, number="A1"))
    expired = make_tenant(make_room(prop, number="A2"), expired=True)
    first = page(client, f"/invitations/{valid.token}")
    second = page(client, f"/invitations/{expired.token}")
    assert first.status_code == second.status_code == 200
    assert first.content == second.content


def test_the_invitation_page_is_identical_for_a_used_link(
    client, database, play_package, make_user, make_property, make_room, make_tenant
) -> None:
    owner = make_user()
    prop = make_property(owner)
    valid = make_tenant(make_room(prop, number="A1"))
    used = make_tenant(make_room(prop, number="A2"), activated=True)
    first = page(client, f"/invitations/{valid.token}")
    second = page(client, f"/invitations/{used.token}")
    assert first.content == second.content


def test_the_invitation_page_is_identical_for_a_manager_link(
    client, database, play_package, make_user, make_manager
) -> None:
    owner = make_user()
    manager = make_manager(owner)
    real = page(client, f"/invitations/{manager.token}")
    unknown = page(client, "/invitations/unknown-token")
    assert real.status_code == 200
    assert real.content == unknown.content
    assert manager.token not in real.text


def test_viewing_the_page_does_not_use_up_the_invitation(
    client, database, play_package, make_user, make_property, make_room, make_tenant
) -> None:
    owner = make_user()
    stored = make_tenant(make_room(make_property(owner)))
    for _ in range(3):
        assert page(client, f"/invitations/{stored.token}").status_code == 200
    preview = client.post("/invitations/previews", json={"token": stored.token})
    assert preview.status_code == 200, preview.text
    assert preview.json()["status"] == "valid"


# No external resources


@all_pages
def test_a_page_loads_no_resources(client, play_package, path) -> None:
    body = page(client, path).text.lower()
    for fragment in (
        "src=",
        "<script",
        "<link",
        "<img",
        "<iframe",
        "<object",
        "<embed",
        "<form",
        "<video",
        "<audio",
        "<base",
        "@import",
        "url(",
        "http-equiv",
        "srcset",
    ):
        assert fragment not in body, fragment


@all_pages
def test_the_only_address_in_a_page_is_the_play_link(
    client, play_package, path
) -> None:
    addresses = urls_in(page(client, path).text)
    assert addresses
    for address in addresses:
        assert address.startswith(PLAY_PREFIX), address


@all_pages
def test_a_page_without_a_package_holds_no_address(client, play_package, path) -> None:
    play_package(None)
    assert urls_in(page(client, path).text) == []


@all_pages
def test_a_page_has_no_inline_event_handlers(client, play_package, path) -> None:
    body = page(client, path).text.lower()
    assert not re.search(r"\son[a-z]+\s*=", body)


# Authentication and methods


@all_pages
def test_a_page_needs_no_authentication(client, play_package, path) -> None:
    response = page(client, path)
    assert "authorization" not in response.request.headers
    assert response.status_code == 200


@all_pages
def test_a_bad_bearer_token_does_not_matter(client, play_package, path) -> None:
    response = page(client, path, headers={"Authorization": "Bearer nonsense"})
    assert response.status_code == 200


@all_pages
def test_a_page_needs_no_database(client, play_package, monkeypatch, path) -> None:
    from app.config import get_settings

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:x@127.0.0.1:1/none")
    get_settings.cache_clear()
    assert page(client, path).status_code == 200


@all_pages
def test_a_page_is_the_same_for_a_browser_and_for_the_app(
    client, play_package, path
) -> None:
    browser = page(client, path, headers={"User-Agent": "Mozilla/5.0 (X11; Linux)"})
    phone = page(
        client, path, headers={"User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8)"}
    )
    assert browser.content == phone.content


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
@pytest.mark.parametrize("path", ["/password-reset", "/email-change"])
def test_the_query_pages_are_only_for_reading(
    client, play_package, method, path
) -> None:
    assert_error(getattr(client, method)(path), 405, "METHOD_NOT_ALLOWED")


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_a_write_to_an_invitation_address_is_not_served_by_the_page(
    client, play_package, method
) -> None:
    response = getattr(client, method)("/invitations/some-token")
    assert response.status_code == 405, response.text
    assert response.json()["code"] == "METHOD_NOT_ALLOWED"


@pytest.mark.parametrize("path", ["/password-reset", "/email-change"])
def test_a_post_with_a_token_is_not_served_by_the_page(
    client, play_package, path
) -> None:
    response = client.post(path, json={"token": "abc"})
    assert_error(response, 405, "METHOD_NOT_ALLOWED")
    assert "text/html" not in response.headers["content-type"]


# The pages are not part of the contract


@pytest.mark.parametrize(
    "path", ["/invitations/{token}", "/password-reset", "/email-change"]
)
def test_the_page_paths_are_not_in_the_openapi_document(openapi, path) -> None:
    assert path not in openapi.document["paths"]


def test_the_page_methods_are_not_declared_on_neighbouring_paths(openapi) -> None:
    paths = openapi.document["paths"]
    for path, item in paths.items():
        if path.startswith("/invitations/"):
            assert set(item) == {"post"}, path
    assert not any(path.startswith("/password-reset") for path in paths)
    assert not any(path.startswith("/email-change") for path in paths)


def test_the_openapi_document_still_has_87_operations(openapi) -> None:
    operations = [
        (method, path)
        for path, item in openapi.document["paths"].items()
        for method in item
    ]
    assert len(operations) == 87


def test_the_route_errors_still_match_the_operations_of_the_document(app) -> None:
    from app import error_catalog

    operations = {
        (method.upper(), path)
        for path, item in app.openapi()["paths"].items()
        for method in item
    }
    assert set(error_catalog.ROUTE_ERRORS) == operations
    assert ("GET", "/password-reset") not in error_catalog.ROUTE_ERRORS
    assert ("GET", "/email-change") not in error_catalog.ROUTE_ERRORS
    assert ("GET", "/invitations/{token}") not in error_catalog.ROUTE_ERRORS


def test_the_page_responses_are_not_declared_as_html_in_the_document(openapi) -> None:
    assert "text/html" not in str(openapi.document)


# Existing endpoints on the same prefixes are unchanged


def test_previewing_an_unknown_invitation_still_answers_not_found(
    client, database, play_package
) -> None:
    response = client.post("/invitations/previews", json={"token": "unknown"})
    assert_error(response, 404, "INVITATION_NOT_FOUND")


def test_accepting_an_invitation_still_needs_a_session(client, play_package) -> None:
    response = client.post("/invitations/acceptances", json={"token": "unknown"})
    assert_error(response, 401, "ACCESS_TOKEN_INVALID")


def test_previewing_an_unknown_reset_link_still_answers_not_found(
    client, database, play_package
) -> None:
    response = client.post("/auth/password-reset-previews", json={"token": "unknown"})
    assert_error(response, 404, "PASSWORD_RESET_NOT_FOUND")


def test_completing_a_reset_with_an_unknown_link_still_answers_not_found(
    client, database, play_package
) -> None:
    response = client.post(
        "/auth/password-resets",
        json={"token": "unknown", "newPassword": "mUk3!xqz-Plover"},
    )
    assert_error(response, 404, "PASSWORD_RESET_NOT_FOUND")


def test_confirming_an_unknown_email_change_still_answers_not_found(
    client, database, play_package
) -> None:
    response = client.post("/auth/email-changes", json={"token": "unknown"})
    assert_error(response, 404, "EMAIL_CHANGE_NOT_FOUND")


def test_an_unknown_path_still_answers_the_uniform_not_found(
    client, play_package
) -> None:
    assert_error(client.get("/no-such-path"), 404, "NOT_FOUND")


def test_health_still_answers(client, database, play_package) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# The links the backend builds are served by the pages


def path_and_query(url: str) -> str:
    parts = urlsplit(url)
    return parts.path + (f"?{parts.query}" if parts.query else "")


def test_the_invitation_link_is_served_by_the_invitation_page(
    client, play_package, base_url
) -> None:
    from app.services.invitations import invitation_url

    url = invitation_url("abc-DEF_123")
    assert url.startswith(BASE_URL)
    response = client.get(path_and_query(url))
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Niscala" in response.text
    assert "abc-DEF_123" not in response.text


def test_the_password_reset_link_is_served_by_the_password_reset_page(
    client, play_package, base_url
) -> None:
    from app.services.invitations import password_reset_url

    url = password_reset_url("abc-DEF_123")
    assert url.startswith(BASE_URL)
    response = client.get(path_and_query(url))
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Niscala" in response.text
    assert "abc-DEF_123" not in response.text


def test_the_email_change_link_is_served_by_the_email_change_page(
    client, play_package, base_url
) -> None:
    from app.services.invitations import email_change_url

    url = email_change_url("abc-DEF_123")
    assert url.startswith(BASE_URL)
    response = client.get(path_and_query(url))
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Niscala" in response.text
    assert "abc-DEF_123" not in response.text


def test_the_built_links_carry_the_token_the_pages_ignore(
    client, play_package, base_url
) -> None:
    from app.services.invitations import (
        email_change_url,
        invitation_url,
        password_reset_url,
    )

    for build in (invitation_url, password_reset_url, email_change_url):
        response = client.get(path_and_query(build("x" * 43)))
        assert response.status_code == 200
        assert "x" * 43 not in response.text


def test_a_link_built_for_a_real_invitation_opens_the_page(
    client,
    database,
    play_package,
    base_url,
    make_user,
    make_property,
    make_room,
    make_tenant,
) -> None:
    from app.services.invitations import invitation_url

    stored = make_tenant(make_room(make_property(make_user())))
    response = client.get(path_and_query(invitation_url(stored.token)))
    assert response.status_code == 200
    assert stored.token not in response.text
