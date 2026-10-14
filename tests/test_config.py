import pytest
from pydantic import ValidationError

from app.core.config import Settings


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
