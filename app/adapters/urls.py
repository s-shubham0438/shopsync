"""URL safety checks for links that come from store feeds.

Store URLs later back the public `/go/{listing_id}` redirect, so a malformed or malicious feed
must never be able to point users at another site. Rules (all must pass):

* `https` only, at most 2048 characters, no whitespace, control characters or backslashes
  (browsers treat `\\` like `/`, which parsers disagree on);
* no credentials (`https://amazon.in@evil.com`), no non-standard port;
* ASCII hostname without a trailing dot (blocks homographs and `amazon.in.` tricks);
* hostname is an **exact** member of the store's allowlist (no suffix matching, so
  `amazon.in.evil.com` / `evil-amazon.in` / `x.amazon.in` are rejected);
* no redirect payload anywhere in the path, query or fragment, which is how open-redirect
  endpoints on otherwise-trusted hosts are abused. Each component is checked as-is and after
  up to MAX_DECODE_PASSES percent-decodings (so `https%253A%252F%252F` is caught), and values
  starting with `//`, `/\\`, `\\/`, `\\\\` (browsers normalise `\\` to `/`) or a scheme count too.
"""

from collections.abc import Set
from urllib.parse import parse_qsl, unquote, urlsplit

MAX_URL_LENGTH = 2048
# Redirect payloads are often percent-encoded more than once so they survive one decode.
MAX_DECODE_PASSES = 3
# Prefixes a browser (or a careless redirect endpoint) treats as "another site/scheme".
# Browsers normalise "\" to "/", so "/\evil.com" and "\/evil.com" behave like "//evil.com".
_REDIRECT_PREFIXES = (
    "http:",
    "https:",
    "//",
    "\\\\",
    "/\\",
    "\\/",
    "javascript:",
    "data:",
    "vbscript:",
)


def _decodings(text: str) -> list[str]:
    """`text` plus each successive percent-decoding of it (stops when decoding is stable)."""
    forms = [text]
    for _ in range(MAX_DECODE_PASSES):
        decoded = unquote(forms[-1])
        if decoded == forms[-1]:
            break
        forms.append(decoded)
    return forms


def _looks_like_redirect(value: str) -> bool:
    return any(
        form.strip().lower().startswith(_REDIRECT_PREFIXES) or "://" in form
        for form in _decodings(value)
    )


def _query_has_redirect(component: str) -> bool:
    if not component:
        return False
    for form in _decodings(component):
        if "://" in form:
            return True
        if any(_looks_like_redirect(v) for _, v in parse_qsl(form, keep_blank_values=True)):
            return True
    return False


def _path_has_redirect(path: str) -> bool:
    # A real product path never needs an absolute URL, "//" or a backslash in it; those are
    # how path-style redirect endpoints (/redirect/https://x, /r//x) are abused.
    return any("://" in form or "//" in form or "\\" in form for form in _decodings(path))


def url_problem(url: str, allowed_hosts: Set[str] | None = None) -> str | None:
    """Return a short machine-readable reason the URL is unsafe, or None if it's acceptable.

    With `allowed_hosts=None` only the structural rules are applied (used for image URLs and
    schema-level checks); pass the store's allowlist to also enforce the hostname.
    """
    if len(url) > MAX_URL_LENGTH:
        return "url_too_long"
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 or ch == "\\" for ch in url):
        return "url_bad_characters"
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "url_unparseable"
    if parts.scheme != "https":
        return "url_not_https"
    if "@" in parts.netloc:
        return "url_has_credentials"
    if port not in (None, 443):
        return "url_bad_port"
    host = parts.hostname
    if not host:
        return "url_no_host"
    if not host.isascii():
        return "url_non_ascii_host"
    if host.endswith("."):
        return "url_trailing_dot"
    if allowed_hosts is not None and host not in allowed_hosts:
        return "url_host_not_allowed"
    if (
        _path_has_redirect(parts.path)
        or _query_has_redirect(parts.query)
        or _query_has_redirect(parts.fragment)
    ):
        return "url_embedded_redirect"
    return None
