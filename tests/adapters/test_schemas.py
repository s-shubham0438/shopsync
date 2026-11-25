from pathlib import Path

import pytest
from pydantic import ValidationError

from app.adapters.schemas import (
    AdapterResult,
    AdapterStatus,
    Offer,
    StoreSearchOutcome,
    StoreSearchQuery,
)
from tests.adapters.fakes import make_listing


class TestStoreSearchQuery:
    def test_trims_and_defaults(self) -> None:
        q = StoreSearchQuery(text="  iphone 15  ")
        assert q.text == "iphone 15"
        assert q.limit == 20

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"text": "   "},
            {"text": "x" * 201},
            {"text": "a", "limit": 0},
            {"text": "a", "limit": 51},
            {"text": "a", "min_price": -1},
            {"text": "a", "min_price": 10.5},  # paise must be integers
            {"text": "a", "min_price": 500, "max_price": 100},
            {"text": "a", "category_slug": "Mobiles!"},
            {"text": "a", "unexpected": True},
        ],
    )
    def test_rejects_invalid(self, kwargs: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            StoreSearchQuery(**kwargs)  # type: ignore[arg-type]

    def test_is_immutable(self) -> None:
        q = StoreSearchQuery(text="a")
        with pytest.raises(ValidationError):
            q.text = "b"  # type: ignore[misc]


class TestStoreListing:
    def test_valid_listing(self) -> None:
        listing = make_listing(mrp=129_900, rating=4.56, ean="0-195949-035470")
        assert listing.price == 99_900
        assert listing.mrp == 129_900
        assert listing.rating == 4.6
        assert listing.ean == "0195949035470"
        assert listing.fetched_at.tzinfo is not None

    def test_mrp_below_price_is_dropped(self) -> None:
        assert make_listing(mrp=50_000).mrp is None

    @pytest.mark.parametrize("ean", ["ABC123", "123", "1" * 15])
    def test_invalid_ean_is_dropped(self, ean: str) -> None:
        assert make_listing(ean=ean).ean is None

    def test_unsafe_image_is_dropped_not_fatal(self) -> None:
        assert make_listing(image_url="http://cdn.example.com/a.jpg").image_url is None
        assert make_listing(image_url="https://cdn.example.com/a.jpg").image_url is not None

    @pytest.mark.parametrize(
        "overrides",
        [
            {"price": -1},
            {"price": 999.0},  # floats never allowed for money
            {"price": 10**12},  # absurd: likely a unit error
            {"rating": 5.5},
            {"review_count": -3},
            {"url": "http://www.amazon.in/p/1"},
            {"url": "https://www.amazon.in@evil.com/"},
            {"platform_slug": "Amazon"},
            {"title": ""},
        ],
    )
    def test_rejects_invalid(self, overrides: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            make_listing(**overrides)

    def test_offers_validated(self) -> None:
        listing = make_listing(offers=[{"type": "bank", "title": "10% off"}])
        assert listing.offers == (Offer(type="bank", title="10% off"),)  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            make_listing(offers=[{"type": "lottery", "title": "?"}])

    @pytest.mark.parametrize("module", ["schemas.py", "base.py", "urls.py", "runner.py"])
    def test_independent_of_database_models(self, module: str) -> None:
        # Adapter contracts must not depend on SQLAlchemy or the ORM models.
        source = (Path(__file__).parents[2] / "app" / "adapters" / module).read_text("utf-8")
        assert "sqlalchemy" not in source
        assert "app.models" not in source


def test_outcome_flags_partial_results() -> None:
    q = StoreSearchQuery(text="a")
    ok = AdapterResult("amazon", AdapterStatus.OK, listings=(make_listing(),))
    slow = AdapterResult("flipkart", AdapterStatus.TIMEOUT, error_code="timeout")
    outcome = StoreSearchOutcome(query=q, results=(ok, slow))
    assert outcome.is_partial
    assert outcome.failed_stores == ("flipkart",)
    assert len(outcome.listings) == 1
    assert not StoreSearchOutcome(query=q, results=(ok,)).is_partial
