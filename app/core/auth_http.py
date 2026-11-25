"""HTTP plumbing for authentication: cookies, client IP and the CSRF origin check.

Deployment assumption (Phase 5 decision): the browser reaches the API same-origin (frontend
proxy) or same-site (subdomain). Cookies are therefore HttpOnly + Secure + SameSite=Lax.

- `ss_access` (path /api/v1): the short-lived access JWT.
- `ss_refresh` (path /api/v1/auth): the refresh token, only ever sent to auth endpoints.

CSRF: SameSite=Lax already stops cross-site POSTs from carrying the cookies in modern browsers.
As a second layer, every state-changing request that carries an auth cookie must come from an
allowed Origin (`CORS_ORIGINS`, or the API's own origin); otherwise 403 `csrf_failed`.
Requests without auth cookies (e.g. login itself) are not affected.
"""

import ipaddress
from datetime import datetime
from urllib.parse import urlsplit

from fastapi import Request, Response

from app.core.config import API_V1_PREFIX, Settings
from app.core.errors import ForbiddenError

ACCESS_COOKIE = "ss_access"
REFRESH_COOKIE = "ss_refresh"
ACCESS_COOKIE_PATH = API_V1_PREFIX
REFRESH_COOKIE_PATH = f"{API_V1_PREFIX}/auth"

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class CsrfError(ForbiddenError):
    code = "csrf_failed"
    message = "This request was blocked because it did not come from the ShopSync website."


# --------------------------------------------------------------------------- #
# Cookies
# --------------------------------------------------------------------------- #
def _set(
    response: Response, settings: Settings, name: str, value: str, path: str, expires: datetime
) -> None:
    response.set_cookie(
        key=name,
        value=value,
        expires=expires,
        path=path,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )


def set_auth_cookies(
    response: Response,
    settings: Settings,
    *,
    access_token: str,
    access_expires: datetime,
    refresh_token: str,
    refresh_expires: datetime,
) -> None:
    _set(response, settings, ACCESS_COOKIE, access_token, ACCESS_COOKIE_PATH, access_expires)
    _set(response, settings, REFRESH_COOKIE, refresh_token, REFRESH_COOKIE_PATH, refresh_expires)


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    for name, path in ((ACCESS_COOKIE, ACCESS_COOKIE_PATH), (REFRESH_COOKIE, REFRESH_COOKIE_PATH)):
        response.delete_cookie(
            key=name,
            path=path,
            domain=settings.cookie_domain,
            secure=settings.cookie_secure,
            httponly=True,
            samesite=settings.cookie_samesite,
        )


# --------------------------------------------------------------------------- #
# Client IP
# --------------------------------------------------------------------------- #
def client_ip(request: Request, settings: Settings) -> str | None:
    """The caller's IP. X-Forwarded-For is used only for `TRUSTED_PROXY_COUNT` proxies we run:
    the address that many hops from the right (anything further left is client-controlled)."""
    candidate: str | None = request.client.host if request.client else None
    if settings.trusted_proxy_count:
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",")]
        hops = [h for h in hops if h]
        if len(hops) >= settings.trusted_proxy_count:
            candidate = hops[-settings.trusted_proxy_count]
    if candidate is None:
        return None
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# CSRF origin check (router-level dependency)
# --------------------------------------------------------------------------- #
def _origin_of(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


def verify_origin(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return
    if ACCESS_COOKIE not in request.cookies and REFRESH_COOKIE not in request.cookies:
        return  # not cookie-authenticated: nothing a forged request could ride on
    settings: Settings = request.app.state.settings
    header = request.headers.get("origin") or request.headers.get("referer")
    origin = _origin_of(header) if header and header != "null" else None
    allowed = {o.lower() for o in settings.cors_origins}
    allowed.add(f"{request.url.scheme}://{request.url.netloc}".lower())  # same-origin
    if origin is None or origin not in allowed:
        raise CsrfError()
