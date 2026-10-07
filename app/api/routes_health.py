from fastapi import APIRouter, Request

from app.models.schemas import HealthResponse

router = APIRouter(tags=["health"])
SERVICE_NAME = "geomasure-api"


@router.get("/health", response_model=HealthResponse, summary="Service health check")
def health(request: Request) -> HealthResponse:
    return HealthResponse(service=SERVICE_NAME, version=request.app.state.settings.app_version)
