"""A4: adapter failures must never leak URLs, query strings, keys, tags or credentials to logs."""

import logging

import pytest

from app.adapters.base import AdapterUnavailableError
from app.adapters.logsafe import redact, safe_frames, safe_str
from app.adapters.runner import AdapterRunner
from app.adapters.schemas import AdapterStatus, StoreSearchQuery
from app.core.logging import JsonFormatter
from tests.adapters.fakes import FakeAdapter

SECRETS = [
    "SECRETKEY123",
    "myaff-21",
    "hunter2",
    "eyJhbGciOiJIUzI1NiJ9abcdef",
    "q=iphone",
    "/v1/search",
    "AKIA0123456789ABCDEF0123456789XYZ",
    "sess-998877",
]
LEAKY = (
    "GET https://bob:hunter2@api.store.in/v1/search?q=iphone&api_key=SECRETKEY123&tag=myaff-21 "
    "failed; Authorization: Bearer eyJhbGciOiJIUzI1NiJ9abcdef; "
    "signature=AKIA0123456789ABCDEF0123456789XYZ session_id=sess-998877"
)


def everything_logged(caplog: pytest.LogCaptureFixture) -> str:
    """Every byte a handler could emit: message, extras, any traceback, and formatted JSON."""
    fmt = JsonFormatter()
    parts = []
    for record in caplog.records:
        parts.append(record.getMessage())
        parts.append(repr(vars(record)))
        parts.append(fmt.format(record))
    return "\n".join(parts)


@pytest.mark.parametrize(
    "error",
    [AdapterUnavailableError(LEAKY), RuntimeError(LEAKY), ValueError(LEAKY)],
    ids=["expected-adapter-error", "unexpected-crash", "value-error"],
)
async def test_failure_logs_contain_no_sensitive_values(
    caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    adapter = FakeAdapter("amazon", error=error)
    with caplog.at_level(logging.DEBUG, logger="app.adapters"):
        outcome = await AdapterRunner([adapter], default_timeout=1).search_all(
            StoreSearchQuery(text="iphone")
        )
    assert outcome.results[0].status is AdapterStatus.ERROR
    logged = everything_logged(caplog)
    for secret in SECRETS:
        assert secret not in logged, f"leaked {secret!r}"
    # Still useful for debugging: which store, what kind of error, which host.
    assert type(error).__name__ in logged
    assert "api.store.in" in logged
    # No raw tracebacks attached.
    assert all(r.exc_info is None and not r.exc_text for r in caplog.records)


async def test_crash_logs_code_location_without_message(caplog: pytest.LogCaptureFixture) -> None:
    adapter = FakeAdapter("amazon", error=RuntimeError(LEAKY))
    with caplog.at_level(logging.WARNING, logger="app.adapters"):
        await AdapterRunner([adapter], default_timeout=1).search_all(StoreSearchQuery(text="x"))
    crash = next(r for r in caplog.records if r.getMessage() == "adapter_crashed")
    frames = crash.frames  # type: ignore[attr-defined]
    assert frames and all(" in " in f and ":" in f for f in frames)
    assert any("fakes.py" in f for f in frames)


class TestRedact:
    @pytest.mark.parametrize(
        ("raw", "must_not_contain", "must_contain"),
        [
            (
                "https://api.x.in/p?key=abc123&tag=aff-21",
                ["key=abc123", "aff-21", "/p?"],
                ["api.x.in"],
            ),
            ("https://user:pw123@db.x.in:5432/shop", ["user", "pw123", "/shop"], ["db.x.in:5432"]),
            ("api_key=abc123 token: zz9 password='p w'", ["abc123", "zz9", "p w"], ["api_key="]),
            ("Authorization: Basic dXNlcjpwYXNz", ["dXNlcjpwYXNz"], ["Authorization"]),
            ("x-amz-signature=deadbeef; affiliate_id=me-21", ["deadbeef", "me-21"], []),
            (
                "opaque abcdefghijklmnopqrstuvwxyz0123456789 end",
                ["abcdefghijklmnop"],
                ["opaque", "end"],
            ),
        ],
    )
    def test_masks_sensitive_parts(
        self, raw: str, must_not_contain: list[str], must_contain: list[str]
    ) -> None:
        out = redact(raw)
        for bad in must_not_contain:
            assert bad not in out
        for good in must_contain:
            assert good in out

    def test_plain_messages_untouched_and_length_capped(self) -> None:
        assert redact("store returned 503 Service Unavailable") == (
            "store returned 503 Service Unavailable"
        )
        assert len(redact("x " * 1000)) <= 300

    def test_safe_frames_have_no_message(self) -> None:
        try:
            raise ValueError("secret=abc")
        except ValueError as exc:
            frames = safe_frames(exc)
        assert frames and "secret" not in " ".join(frames)


# --------------------------------------------------------------------------- #
# N1: a broken __str__ must never crash logging (and so never the whole search)
# --------------------------------------------------------------------------- #
class RaisingStrError(Exception):
    def __str__(self) -> str:
        raise RuntimeError("str() itself fails")


class RaisingStrAdapterError(AdapterUnavailableError):
    def __str__(self) -> str:
        raise RuntimeError("str() itself fails")


class NonStrError(Exception):
    def __str__(self) -> str:
        return 42  # type: ignore[return-value]


@pytest.mark.parametrize(
    "error",
    [RaisingStrError(), RaisingStrAdapterError(), NonStrError()],
    ids=["plain-exception", "adapter-error-subclass", "str-returns-non-str"],
)
async def test_unprintable_adapter_error_is_isolated(
    caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    # The independent reviewer's scenario: this used to fail the entire search (ExceptionGroup).
    broken = FakeAdapter("amazon", error=error)
    healthy = FakeAdapter("flipkart")
    with caplog.at_level(logging.WARNING, logger="app.adapters"):
        outcome = await AdapterRunner([broken, healthy], default_timeout=1).search_all(
            StoreSearchQuery(text="iphone")
        )
    by_store = {r.platform_slug: r for r in outcome.results}
    assert by_store["amazon"].status is AdapterStatus.ERROR
    assert by_store["amazon"].error_code == type(error).__name__
    assert by_store["flipkart"].status is AdapterStatus.OK
    assert [listing.external_id for listing in by_store["flipkart"].listings] == ["flipkart-1"]
    logged = everything_logged(caplog)
    assert f"<unprintable {type(error).__name__}>" in logged


class TestNeverRaises:
    def test_safe_str_falls_back(self) -> None:
        assert safe_str(RaisingStrError()) == "<unprintable RaisingStrError>"
        assert safe_str(NonStrError()) == "<unprintable NonStrError>"
        assert safe_str("plain text") == "plain text"

    def test_redact_falls_back_and_keeps_behaviour(self) -> None:
        assert redact(RaisingStrError()) == "<unprintable RaisingStrError>"
        assert redact(NonStrError()) == "<unprintable NonStrError>"
        # Existing redaction unchanged for normal input.
        assert redact("https://api.x.in/p?api_key=abc") == "https://api.x.in/[redacted]"

    def test_safe_frames_survives_a_broken_traceback(self) -> None:
        class BrokenTracebackError(Exception):
            @property
            def __traceback__(self) -> object:  # type: ignore[override]
                raise RuntimeError("no traceback for you")

        assert safe_frames(BrokenTracebackError()) == []
