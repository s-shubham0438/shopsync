import asyncio
import logging
import time

import pytest

from app.adapters.base import AdapterAuthError, AdapterUnavailableError, StoreAdapter
from app.adapters.runner import AdapterRunner
from app.adapters.schemas import AdapterStatus, StoreSearchQuery
from tests.adapters.fakes import FakeAdapter, make_listing

QUERY = StoreSearchQuery(text="iphone")


def runner(*adapters: FakeAdapter, timeout: float = 1.0, **kw: object) -> AdapterRunner:
    return AdapterRunner(list(adapters), default_timeout=timeout, **kw)  # type: ignore[arg-type]


def rejections(caplog: pytest.LogCaptureFixture) -> list[tuple[str, str | None]]:
    return [
        (r.reason, r.external_id)  # type: ignore[attr-defined]
        for r in caplog.records
        if r.getMessage() == "adapter_listing_rejected"
    ]


async def test_stores_run_in_parallel() -> None:
    stores = [FakeAdapter(s, delay=0.2) for s in ("amazon", "flipkart", "myntra")]
    started = time.perf_counter()
    outcome = await runner(*stores).search_all(QUERY)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.45, f"looks sequential: {elapsed:.2f}s"
    assert [r.status for r in outcome.results] == [AdapterStatus.OK] * 3
    assert len(outcome.listings) == 3
    assert not outcome.is_partial


async def test_slow_store_times_out_alone() -> None:
    fast = FakeAdapter("amazon")
    slow = FakeAdapter("flipkart", delay=5)
    started = time.perf_counter()
    outcome = await runner(fast, slow, timeout=0.1).search_all(QUERY)
    assert time.perf_counter() - started < 1
    by_store = {r.platform_slug: r for r in outcome.results}
    assert by_store["amazon"].status is AdapterStatus.OK
    assert by_store["flipkart"].status is AdapterStatus.TIMEOUT
    assert by_store["flipkart"].error_code == "timeout"
    assert slow.cancelled  # the slow call was actually stopped, not left running
    assert outcome.is_partial and outcome.failed_stores == ("flipkart",)


async def test_failing_store_is_isolated_and_message_not_exposed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ok = FakeAdapter("amazon")
    expected = FakeAdapter("flipkart", error=AdapterAuthError("bad key"))
    crashed = FakeAdapter("myntra", error=RuntimeError("secret=abc123"))
    with caplog.at_level(logging.WARNING, logger="app.adapters"):
        outcome = await runner(ok, expected, crashed).search_all(QUERY)
    codes = {r.platform_slug: (r.status, r.error_code) for r in outcome.results}
    assert codes == {
        "amazon": (AdapterStatus.OK, None),
        "flipkart": (AdapterStatus.ERROR, "AdapterAuthError"),
        "myntra": (AdapterStatus.ERROR, "RuntimeError"),
    }
    # Results only ever carry the class name; the raw message stays out of the result.
    assert all("abc123" not in repr(r) for r in outcome.results)


async def test_store_specific_timeouts() -> None:
    a = FakeAdapter("amazon", delay=0.3)
    f = FakeAdapter("flipkart", delay=0.3, timeout_seconds=1.0)  # adapter's own default
    m = FakeAdapter("myntra", delay=0.3)
    outcome = await runner(a, f, m, timeout=0.1, timeouts={"myntra": 1.0}).search_all(QUERY)
    status = {r.platform_slug: r.status for r in outcome.results}
    assert status == {
        "amazon": AdapterStatus.TIMEOUT,  # global 0.1s
        "flipkart": AdapterStatus.OK,  # adapter override 1s
        "myntra": AdapterStatus.OK,  # settings override 1s
    }


def test_timeout_precedence() -> None:
    a = FakeAdapter("amazon", timeout_seconds=2.0)
    r = runner(a, timeout=4.0, timeouts={"amazon": 6.0})
    assert r.timeout_for(a) == 6.0
    assert runner(a, timeout=4.0).timeout_for(a) == 2.0
    assert runner(FakeAdapter("myntra"), timeout=4.0).timeout_for(FakeAdapter("myntra")) == 4.0


async def test_cancellation_propagates_and_stops_all_stores() -> None:
    stores = [FakeAdapter(s, delay=5) for s in ("amazon", "flipkart")]
    task = asyncio.create_task(runner(*stores, timeout=10).search_all(QUERY))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert all(s.cancelled for s in stores)


async def test_rejected_records_are_dropped_deterministically_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter = FakeAdapter(
        "amazon",
        results=[
            make_listing("amazon", "A1", title="first A1"),
            make_listing("flipkart", "F1"),  # wrong store
            make_listing("amazon", "A2", url="https://amazon.in.evil.com/p"),  # deceptive host
            make_listing("amazon", "A1", title="second A1"),  # duplicate id
            "not a listing",
            # Built without validation, as a buggy adapter might: the runner must still catch it.
            make_listing("amazon", "A3").model_copy(
                update={"url": "https://www.amazon.in/r?u=https://evil.com"}
            ),
            make_listing("amazon", "A4"),
        ],
    )
    with caplog.at_level(logging.WARNING, logger="app.adapters"):
        outcome = await runner(adapter).search_all(QUERY)
    result = outcome.results[0]
    assert [(listing.external_id, listing.title) for listing in result.listings] == [
        ("A1", "first A1"),
        ("A4", "Product A4"),
    ]
    assert result.rejected == 5
    assert rejections(caplog) == [
        ("platform_mismatch", "F1"),
        ("url_host_not_allowed", "A2"),
        ("duplicate_external_id", "A1"),
        ("not_a_listing", None),
        ("url_embedded_redirect", "A3"),
    ]
    # Logs never include the URL itself (it may carry affiliate tags/tokens).
    assert not any("evil.com" in str(vars(r)) for r in caplog.records)


async def test_first_valid_duplicate_wins() -> None:
    adapter = FakeAdapter(
        "amazon",
        results=[
            make_listing("amazon", "A1", url="https://evil-amazon.in/p", title="bad"),
            make_listing("amazon", "A1", title="good"),
        ],
    )
    result = (await runner(adapter).search_all(QUERY)).results[0]
    assert [listing.title for listing in result.listings] == ["good"]


async def test_results_capped_at_query_limit_in_order() -> None:
    adapter = FakeAdapter("amazon", results=[make_listing("amazon", f"A{i}") for i in range(10)])
    result = (await runner(adapter).search_all(StoreSearchQuery(text="x", limit=3))).results[0]
    assert [listing.external_id for listing in result.listings] == ["A0", "A1", "A2"]


async def test_non_list_response_is_rejected() -> None:
    adapter = FakeAdapter("amazon", results=None)
    adapter.results = {"oops": 1}  # type: ignore[assignment]
    result = (await runner(adapter).search_all(QUERY)).results[0]
    assert result.status is AdapterStatus.OK
    assert result.listings == () and result.rejected == 1


async def test_no_adapters_returns_empty_outcome() -> None:
    outcome = await AdapterRunner([], default_timeout=1).search_all(QUERY)
    assert outcome.results == () and not outcome.is_partial


async def test_fetch_product_uses_same_isolation() -> None:
    ok = FakeAdapter("amazon", results=[make_listing("amazon", "A9")])
    down = FakeAdapter("flipkart", error=AdapterUnavailableError("503"))
    r = runner(ok, down)
    found = await r.fetch_product("amazon", "A9")
    assert found.status is AdapterStatus.OK and found.listings[0].external_id == "A9"
    missing = await r.fetch_product("amazon", "nope")
    assert missing.status is AdapterStatus.OK and missing.listings == ()
    assert (await r.fetch_product("flipkart", "x")).status is AdapterStatus.ERROR
    with pytest.raises(KeyError):
        await r.fetch_product("croma", "x")


def test_rejects_duplicate_adapters_and_bad_timeout() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        runner(FakeAdapter("amazon"), FakeAdapter("amazon"))
    with pytest.raises(ValueError, match="positive"):
        runner(FakeAdapter("amazon"), timeout=0)


# --------------------------------------------------------------------------- #
# A1: one malformed record never breaks the search
# --------------------------------------------------------------------------- #
async def test_malformed_records_rejected_without_breaking_search(
    caplog: pytest.LogCaptureFixture,
) -> None:
    good = make_listing("amazon", "A-OK")
    no_url = make_listing("amazon", "A-NOURL").model_copy(update={"url": None})
    list_id = make_listing("amazon", "A-LIST").model_copy(update={"external_id": ["x"]})
    int_slug = make_listing("amazon", "A-SLUG").model_copy(update={"platform_slug": 7})
    amazon = FakeAdapter("amazon", results=[no_url, list_id, int_slug, good])
    flipkart = FakeAdapter("flipkart")  # an unrelated, healthy store
    with caplog.at_level(logging.WARNING, logger="app.adapters"):
        outcome = await runner(amazon, flipkart).search_all(QUERY)

    by_store = {r.platform_slug: r for r in outcome.results}
    assert by_store["amazon"].status is AdapterStatus.OK
    assert [listing.external_id for listing in by_store["amazon"].listings] == ["A-OK"]
    assert by_store["amazon"].rejected == 3
    # Valid records from other stores survive.
    assert by_store["flipkart"].status is AdapterStatus.OK
    assert [listing.external_id for listing in by_store["flipkart"].listings] == ["flipkart-1"]
    # Each bad record is reported as invalid_record (a non-string id is never logged).
    assert rejections(caplog) == [
        ("invalid_record", "A-NOURL"),
        ("invalid_record", None),
        ("invalid_record", "A-SLUG"),
    ]


async def test_validation_bug_fails_only_that_store(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(adapter: StoreAdapter, raw: object) -> tuple[list[object], int]:
        if adapter.platform_slug == "amazon":
            raise RuntimeError("unexpected")
        return list(raw), 0  # type: ignore[call-overload]

    monkeypatch.setattr(AdapterRunner, "_validate", staticmethod(boom))
    outcome = await runner(FakeAdapter("amazon"), FakeAdapter("flipkart")).search_all(QUERY)
    by_store = {r.platform_slug: (r.status, r.error_code) for r in outcome.results}
    assert by_store == {
        "amazon": (AdapterStatus.ERROR, "invalid_response"),
        "flipkart": (AdapterStatus.OK, None),
    }


# --------------------------------------------------------------------------- #
# A3: fetch_product must return the product that was asked for
# --------------------------------------------------------------------------- #
class WrongProductAdapter(FakeAdapter):
    async def get_product(self, external_id: str) -> object:  # type: ignore[override]
        return self.results[0]


async def test_fetch_product_rejects_external_id_mismatch() -> None:
    adapter = WrongProductAdapter("amazon", results=[make_listing("amazon", "OTHER")])
    result = await runner(adapter).fetch_product("amazon", "REQUESTED")
    assert result.status is AdapterStatus.ERROR
    assert result.error_code == "external_id_mismatch"
    assert result.listings == ()


async def test_fetch_product_mismatch_with_malformed_listing_is_isolated() -> None:
    broken = make_listing("amazon", "X").model_copy(update={"external_id": None})
    result = await runner(WrongProductAdapter("amazon", results=[broken])).fetch_product(
        "amazon", "X"
    )
    assert result.status is AdapterStatus.ERROR
    assert result.error_code == "external_id_mismatch"


async def test_fetch_product_matching_id_still_succeeds() -> None:
    adapter = WrongProductAdapter("amazon", results=[make_listing("amazon", "SAME")])
    result = await runner(adapter).fetch_product("amazon", "SAME")
    assert result.status is AdapterStatus.OK
    assert [listing.external_id for listing in result.listings] == ["SAME"]
