"""Cross-cutting behaviour: error envelope, request ids, CORS, OpenAPI."""

import httpx
import pytest
from fastapi import FastAPI, Query

from app.core.errors import NotFoundError


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    @app.get("/_test/not-found")
    async def not_found() -> None:
        raise NotFoundError("Product not found.")

    @app.get("/_test/validate")
    async def validate(page: int = Query(ge=1)) -> dict[str, int]:
        return {"page": page}

    @app.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("database password is hunter2")

    return app


async def test_app_error_renders_envelope(client: httpx.AsyncClient) -> None:
    resp = await client.get("/_test/not-found")
    assert resp.status_code == 404
    error = resp.json()["error"]
    assert error["code"] == "not_found"
    assert error["message"] == "Product not found."
    assert error["request_id"] == resp.headers["X-Request-ID"]


async def test_unknown_route_uses_envelope(client: httpx.AsyncClient) -> None:
    resp = await client.get("/nope")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


async def test_validation_error_envelope(client: httpx.AsyncClient) -> None:
    resp = await client.get("/_test/validate", params={"page": 0})
    assert resp.status_code == 422
    body = resp.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"][0]["loc"] == ["query", "page"]
    assert "input" not in body["details"][0]


async def test_unhandled_exception_is_generic_500(client: httpx.AsyncClient) -> None:
    resp = await client.get("/_test/boom")
    assert resp.status_code == 500
    body = resp.json()["error"]
    assert body["code"] == "internal_error"
    assert "hunter2" not in resp.text
    assert body["request_id"] == resp.headers["X-Request-ID"]


async def test_incoming_request_id_is_echoed(client: httpx.AsyncClient) -> None:
    resp = await client.get("/nope", headers={"X-Request-ID": "abc-123"})
    assert resp.headers["X-Request-ID"] == "abc-123"


async def test_malformed_request_id_is_replaced(client: httpx.AsyncClient) -> None:
    resp = await client.get("/nope", headers={"X-Request-ID": "bad id\twith spaces"})
    assert resp.headers["X-Request-ID"] != "bad id\twith spaces"


async def test_cors_allows_configured_origin(client: httpx.AsyncClient) -> None:
    resp = await client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert resp.headers["access-control-allow-credentials"] == "true"


async def test_cors_rejects_unknown_origin(client: httpx.AsyncClient) -> None:
    resp = await client.options(
        "/api/v1/health",
        headers={"Origin": "https://evil.test", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in resp.headers


async def test_openapi_documents_error_envelope(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/api/v1/openapi.json")).json()
    responses = schema["paths"]["/api/v1/health"]["get"]["responses"]
    assert set(responses) >= {"200", "503", "500"}
    assert "ErrorResponse" in schema["components"]["schemas"]
