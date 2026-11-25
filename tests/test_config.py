from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Environment, Settings
from app.core.stores import STORES


def make(**kwargs: object) -> Settings:
    return Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]


def test_cors_origins_comma_separated() -> None:
    s = make(cors_origins="http://a.test, https://b.test/")
    assert s.cors_origins == ["http://a.test", "https://b.test"]


def test_cors_origins_json_list() -> None:
    s = make(cors_origins='["http://a.test"]')
    assert s.cors_origins == ["http://a.test"]


def test_cors_origins_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test,http://b.test")
    assert make().cors_origins == ["http://a.test", "http://b.test"]


@pytest.mark.parametrize("origin", ["*", "localhost:5173"])
def test_cors_origins_rejects_invalid(origin: str) -> None:
    with pytest.raises(ValidationError):
        make(cors_origins=origin)


def test_database_url_upgraded_to_asyncpg() -> None:
    s = make(database_url="postgresql://u:p@db:5432/x")
    assert s.sqlalchemy_url == "postgresql+asyncpg://u:p@db:5432/x"


# --------------------------------------------------------------------------- #
# Store adapter settings
# --------------------------------------------------------------------------- #
def test_store_defaults() -> None:
    s = make()
    assert s.enabled_stores == [store.slug for store in STORES]  # all six
    assert s.store_adapter_mode == "mock"
    assert s.store_adapter_timeout_seconds == 4.0
    assert s.store_adapter_timeouts == {}
    assert s.mock_adapter_failure_rate == 0.0


def test_enabled_stores_parsing_and_normalising(monkeypatch: pytest.MonkeyPatch) -> None:
    assert make(enabled_stores=" Amazon , FLIPKART ").enabled_stores == ["amazon", "flipkart"]
    assert make(enabled_stores='["myntra"]').enabled_stores == ["myntra"]
    monkeypatch.setenv("ENABLED_STORES", "ajio,croma")
    assert make().enabled_stores == ["ajio", "croma"]


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("amazon,ebay", "unknown store 'ebay'"),
        ("amazon,amazon", "duplicate stores: amazon"),
        ("", "at least one store"),
    ],
)
def test_enabled_stores_rejects_invalid(value: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        make(enabled_stores=value)


def test_store_timeout_overrides() -> None:
    assert make(store_adapter_timeouts="amazon=6, croma=2.5").store_adapter_timeouts == {
        "amazon": 6.0,
        "croma": 2.5,
    }
    assert make(store_adapter_timeouts='{"myntra": 3}').store_adapter_timeouts == {"myntra": 3.0}
    assert make(store_adapter_timeouts="").store_adapter_timeouts == {}


@pytest.mark.parametrize(
    "value", ["ebay=3", "amazon=0", "amazon=-1", "amazon=31", "amazon", "amazon=fast"]
)
def test_store_timeout_overrides_reject_invalid(value: str) -> None:
    with pytest.raises(ValidationError):
        make(store_adapter_timeouts=value)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"store_adapter_timeout_seconds": 0},
        {"store_adapter_timeout_seconds": 31},
        {"store_adapter_mode": "scrape"},
        {"mock_adapter_failure_rate": 1.5},
        {"mock_adapter_latency_ms": -1},
    ],
)
def test_store_settings_reject_out_of_range(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make(**kwargs)


def test_mock_failures_forbidden_in_production() -> None:
    with pytest.raises(ValidationError, match="must be 0 in production"):
        make(environment=Environment.PRODUCTION, mock_adapter_failure_rate=0.1)
    # Allowed outside production (to demo failure isolation), and 0 is fine everywhere.
    assert make(mock_adapter_failure_rate=0.3).mock_adapter_failure_rate == 0.3
    assert make(**PRODUCTION_OK).mock_adapter_failure_rate == 0.0


# A production configuration that passes every production check (Phase 5 adds auth checks).
PRODUCTION_OK: dict[str, Any] = {
    "environment": Environment.PRODUCTION,
    "auth_secret_key": "p" * 16 + "r0dUct10n-s3cr3t-value-xyz",
    "cors_origins": "https://shopsync.example",
    "frontend_url": "https://shopsync.example",
}


# --------------------------------------------------------------------------- #
# A8: timeouts must be numbers, never booleans
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("value", [True, False])
def test_global_store_timeout_rejects_booleans(value: bool) -> None:
    with pytest.raises(ValidationError, match="number of seconds"):
        make(store_adapter_timeout_seconds=value)


@pytest.mark.parametrize(("value", "expected"), [(5, 5.0), (2.5, 2.5), ("3", 3.0), ("0.75", 0.75)])
def test_global_store_timeout_accepts_numbers(value: object, expected: float) -> None:
    assert make(store_adapter_timeout_seconds=value).store_adapter_timeout_seconds == expected


@pytest.mark.parametrize("value", ["fast", "", "nan", "inf", 0, -1, 30.5])
def test_global_store_timeout_rejects_invalid(value: object) -> None:
    with pytest.raises(ValidationError):
        make(store_adapter_timeout_seconds=value)


@pytest.mark.parametrize(
    "value",
    ['{"amazon": true}', '{"amazon": false}', {"amazon": True}, {"amazon": False}],
    ids=["json-true", "json-false", "python-true", "python-false"],
)
def test_store_timeout_overrides_reject_booleans(value: object) -> None:
    with pytest.raises(ValidationError, match="number of seconds"):
        make(store_adapter_timeouts=value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('{"amazon": 6}', {"amazon": 6.0}),
        ('{"amazon": 2.5}', {"amazon": 2.5}),
        ({"amazon": 4}, {"amazon": 4.0}),
        ("amazon=6,flipkart=1.5", {"amazon": 6.0, "flipkart": 1.5}),
    ],
)
def test_store_timeout_overrides_accept_numbers(value: object, expected: dict[str, float]) -> None:
    assert make(store_adapter_timeouts=value).store_adapter_timeouts == expected


@pytest.mark.parametrize(
    "value", ["amazon=true", "amazon=nan", "amazon=inf", '{"amazon": "soon"}', '{"amazon": null}']
)
def test_store_timeout_overrides_reject_non_numbers(value: str) -> None:
    with pytest.raises(ValidationError):
        make(store_adapter_timeouts=value)


def test_store_timeout_from_env_json_boolean_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_ADAPTER_TIMEOUTS", '{"croma": true}')
    with pytest.raises(ValidationError, match="number of seconds"):
        make()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"database_url": "mysql://admin:HuNt3r2-db-pass@db/x"},
        {"redis_url": "http://:HuNt3r2-db-pass@localhost:6379/0"},
        {"auth_secret_key": "HuNt3r2-db-pass"},
    ],
)
def test_settings_errors_never_echo_values(kwargs: dict[str, str]) -> None:
    # Phase 5.1 finding: pydantic echoed rejected inputs (including secrets) in errors.
    with pytest.raises(ValidationError) as exc_info:
        make(**kwargs)
    assert "HuNt3r2-db-pass" not in str(exc_info.value)
