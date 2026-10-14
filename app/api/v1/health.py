from fastapi import APIRouter, Response, status

from app.api.deps import HealthServiceDep
from app.schemas.health import HealthResponse, HealthStatus

router = APIRouter(tags=["system"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health",
    description="Probes PostgreSQL and Redis. Returns 200 when all dependencies are "
    "reachable, 503 (same body shape) when any is degraded.",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": HealthResponse,
            "description": "One or more dependencies are unavailable",
        }
    },
)
async def health(response: Response, service: HealthServiceDep) -> HealthResponse:
    report = await service.check()
    if report.status is not HealthStatus.OK:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report
