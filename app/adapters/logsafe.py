"""Make adapter error details safe to log.

Store API errors often embed the full request URL (httpx exceptions do), which can carry query
strings, API keys, signatures, affiliate tags or user:password credentials. Everything adapters
log about a failure goes through `redact()` first, and tracebacks are reduced to
"file:line in function" frames, never exception text or local variables.
"""

import re
import traceback
from pathlib import Path

MAX_LOGGED_ERROR_CHARS = 300
MAX_LOGGED_FRAMES = 6
REDACTED = "[redacted]"

# scheme://[user:pass@]host[:port]/path?query#fragment  ->  scheme://host[:port]/[redacted]
_URL = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*)://([^\s/?#'\"<>]+)[^\s'\"<>]*")
# "Bearer abc...", "Basic abc...", "Token abc..."
_AUTH_SCHEME = re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{6,}")
# key=value / key: value pairs whose value is sensitive.
_SECRET_PAIR = re.compile(
    r"(?i)\b("
    r"api[_-]?key|apikey|access[_-]?key(?:[_-]?id)?|secret(?:[_-]?key)?|client[_-]?secret|"
    r"(?:access|refresh|id)[_-]?token|token|password|passwd|pwd|"
    r"x-amz-signature|signature|sig|"
    r"tag|aff(?:iliate)?[_-]?(?:id|tag)|affid|subid|"
    r"authorization|auth|cookie|set-cookie|session(?:[_-]?id)?"
    r")(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s&,;]+)"
)
# Long opaque strings (keys, signatures, session ids) even when unlabelled.
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")


def _strip_url(match: re.Match[str]) -> str:
    scheme, authority = match.group(1), match.group(2)
    host = authority.rsplit("@", 1)[-1]  # drop user:password@
    return f"{scheme}://{host}/{REDACTED}"


def _type_name(obj: object) -> str:
    try:
        return type(obj).__name__
    except Exception:
        return "object"


def safe_str(obj: object) -> str:
    """`str(obj)` that never raises. A broken `__str__` (raising, or returning a non-str) gives
    `<unprintable TypeName>` instead, so logging about a failure can't itself fail."""
    try:
        text = str(obj)
        if isinstance(text, str):
            return text
    except Exception:  # noqa: S110  (deliberate: fall through to the safe placeholder)
        pass
    return f"<unprintable {_type_name(obj)}>"


def redact(text: object) -> str:
    """Return `text` with URLs reduced to their host and secrets masked; length-capped.

    Never raises (formatting/conversion problems yield a placeholder), because it runs inside
    error handlers whose job is to isolate a failing store.
    """
    try:
        value = safe_str(text)
        value = _URL.sub(_strip_url, value)
        value = _AUTH_SCHEME.sub(lambda m: f"{m.group(1)} {REDACTED}", value)
        value = _SECRET_PAIR.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", value)
        value = _LONG_TOKEN.sub(REDACTED, value)
        value = " ".join(value.split())
        if len(value) > MAX_LOGGED_ERROR_CHARS:
            value = value[: MAX_LOGGED_ERROR_CHARS - 3] + "..."
        return value
    except Exception:
        return f"<unprintable {_type_name(text)}>"


def safe_frames(exc: BaseException) -> list[str]:
    """Where the error happened, without any message text or variable values. Never raises."""
    try:
        frames = traceback.extract_tb(exc.__traceback__)[-MAX_LOGGED_FRAMES:]
        return [f"{Path(f.filename).name}:{f.lineno} in {f.name}" for f in frames]
    except Exception:
        return []
