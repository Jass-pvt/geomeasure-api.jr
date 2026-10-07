import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import routes_files, routes_health
from app.config import Settings, get_settings
from app.core.exceptions import GeoMeasureError
from app.core.logging import ROOT_LOGGER_NAME, configure_logging
from app.middleware.correlation import CorrelationIdMiddleware
from app.services.processor import FileProcessor
from app.storage.memory import InMemoryRepository

logger = logging.getLogger(f"{ROOT_LOGGER_NAME}.api")

HTTP_ERROR_CODES = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
INTERNAL_ERROR_MESSAGE = "An unexpected internal error occurred."

DESCRIPTION = (
    "Upload a KML file or a zipped ESRI Shapefile and receive per-feature area/length "
    "measurements. Geographic coordinates are never measured in degrees: geometries are "
    "projected to a suitable UTM zone first, and every result states how it was measured."
)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    return JSONResponse(status_code=status_code, content=body)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title=settings.app_name, version=settings.app_version, description=DESCRIPTION)
    app.add_middleware(CorrelationIdMiddleware)

    app.state.settings = settings
    app.state.repository = InMemoryRepository()
    app.state.processor = FileProcessor(settings, app.state.repository)

    app.include_router(routes_health.router)
    app.include_router(routes_files.router)

    @app.exception_handler(GeoMeasureError)
    async def handle_domain_error(_: Request, exc: GeoMeasureError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"] if part != "body")
        return _error_response(400, "INVALID_REQUEST", f"Invalid '{location}': {first['msg']}.")

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = HTTP_ERROR_CODES.get(exc.status_code, "HTTP_ERROR")
        return _error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_exception", exc_info=exc)
        return _error_response(500, "INTERNAL_ERROR", INTERNAL_ERROR_MESSAGE)

    return app


app = create_app()
