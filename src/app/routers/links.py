"""Public pages and files that let Android open Niscala links in the app."""

import html

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import get_settings
from app.errors import ApiError

router = APIRouter(include_in_schema=False)

PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def _package_name() -> str | None:
    """The configured Play package name, or None when unset or blank."""
    return (get_settings().google_play_package_name or "").strip() or None


def _link_page() -> HTMLResponse:
    """The same page for every link: open it in the app, or install the app first.

    It never depends on the request, so it cannot echo or reveal anything about a token.
    """
    package = _package_name()
    store = ""
    if package:
        url = "https://play.google.com/store/apps/details?id=" + html.escape(
            package, quote=True
        )
        store = f'\n<p><a href="{url}">Unduh Niscala di Google Play</a></p>'
    document = f"""<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Buka di aplikasi Niscala</title>
</head>
<body>
<h1>Buka tautan ini di aplikasi Niscala</h1>
<p>Buka tautan ini di ponsel yang sudah terpasang aplikasi Niscala.</p>
<p>Jika aplikasi belum terpasang, pasang dari Google Play, lalu buka tautan ini lagi.</p>{store}
</body>
</html>
"""
    return HTMLResponse(document, headers=PAGE_HEADERS)


@router.get("/.well-known/assetlinks.json")
def get_assetlinks():
    """Digital Asset Links statement for the app; 404 until package and certificate are set."""
    settings = get_settings()
    package = _package_name()
    if not package or not settings.android_cert_sha256:
        raise ApiError(404, "NOT_FOUND")
    return JSONResponse(
        [
            {
                "relation": ["delegate_permission/common.handle_all_urls"],
                "target": {
                    "namespace": "android_app",
                    "package_name": package,
                    "sha256_cert_fingerprints": settings.android_cert_sha256,
                },
            }
        ]
    )


@router.get("/invitations/{token}")
def get_invitation_page():
    """Fallback page for an invitation link opened outside the app."""
    return _link_page()


@router.get("/password-reset")
def get_password_reset_page():
    """Fallback page for a password-reset link opened outside the app."""
    return _link_page()


@router.get("/email-change")
def get_email_change_page():
    """Fallback page for an email-change link opened outside the app."""
    return _link_page()
