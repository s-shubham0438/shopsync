from fastapi import APIRouter, status

from app.api.v1 import health
from app.schemas.common import ErrorResponse

# Documented on every v1 operation so the OpenAPI schema matches the real
# error envelope (overrides FastAPI's default HTTPValidationError for 422).
api_router = APIRouter(
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "Validation error",
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponse,
            "description": "Unexpected server error",
        },
    }
)
api_router.include_router(health.router)
