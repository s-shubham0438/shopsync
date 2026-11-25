from fastapi import APIRouter, Depends, status

from app.api.v1 import auth, catalog, health
from app.core.auth_http import verify_origin
from app.schemas.common import ErrorResponse

# Documented on every v1 operation so the OpenAPI schema matches the real
# error envelope (overrides FastAPI's default HTTPValidationError for 422).
api_router = APIRouter(
    # CSRF second layer: state-changing requests carrying auth cookies must come from an
    # allowed Origin (see app/core/auth_http.py).
    dependencies=[Depends(verify_origin)],
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "Validation error",
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponse,
            "description": "Unexpected server error",
        },
    },
)
api_router.include_router(health.router)
api_router.include_router(catalog.router)
api_router.include_router(auth.router)
