from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from app.models.enums import GeometryType
from app.models.schemas import (
    ErrorResponse,
    FileInfoResponse,
    MeasurementResponse,
    QualityReportResponse,
    SummaryResponse,
    UploadResponse,
)
from app.services import reporting
from app.services.geometry import to_feature_collection
from app.services.processor import FileProcessor
from app.services.quality import compute_quality_report
from app.storage.memory import ResultRepository

router = APIRouter(prefix="/api/files", tags=["files"])

NOT_FOUND_RESPONSE = {404: {"model": ErrorResponse, "description": "Unknown file ID."}}
UPLOAD_ERROR_RESPONSES = {
    400: {"model": ErrorResponse, "description": "Malformed request or empty file."},
    413: {"model": ErrorResponse, "description": "File exceeds the configured size limit."},
    415: {"model": ErrorResponse, "description": "Unsupported file type."},
    422: {"model": ErrorResponse, "description": "Invalid archive, missing CRS or bad content."},
}


def get_processor(request: Request) -> FileProcessor:
    return request.app.state.processor


def get_repository(request: Request) -> ResultRepository:
    return request.app.state.repository


ProcessorDep = Annotated[FileProcessor, Depends(get_processor)]
RepositoryDep = Annotated[ResultRepository, Depends(get_repository)]


@router.post(
    "/",
    status_code=201,
    response_model=UploadResponse,
    responses={200: {"model": UploadResponse, "description": "Duplicate of an earlier upload."}}
    | UPLOAD_ERROR_RESPONSES,
    summary="Upload a KML file or a Shapefile ZIP and measure its features",
    description=(
        "Accepts `.kml` or a `.zip` containing one ESRI Shapefile (.shp, .shx, .dbf, .prj). "
        "Measurements are always calculated in a projected CRS. Re-uploading identical bytes "
        "returns the original result with `duplicate=true` and HTTP 200."
    ),
)
async def upload_file(
    processor: ProcessorDep,
    response: Response,
    file: Annotated[UploadFile, File(description="KML file or ZIP archive with a Shapefile.")],
) -> UploadResponse:
    outcome = await processor.process(file)
    record = outcome.record
    if outcome.duplicate:
        response.status_code = 200

    fps = (
        round((record.feature_count / (record.processing_time_ms / 1000.0)), 1)
        if record.processing_time_ms > 0 and record.feature_count > 0
        else None
    )

    return UploadResponse(
        id=record.id,
        filename=record.filename,
        status=record.status,
        feature_count=record.feature_count,
        source_crs=record.source_crs,
        measurement_crs=record.measurement_crs,
        processing_time_ms=record.processing_time_ms,
        features_per_second=fps,
        warnings=record.warnings,
        duplicate=outcome.duplicate,
    )


@router.get(
    "/{file_id}",
    response_model=FileInfoResponse,
    responses=NOT_FOUND_RESPONSE,
    summary="Get file-level metadata",
)
def get_file(file_id: str, repository: RepositoryDep) -> FileInfoResponse:
    return reporting.build_file_info(repository.get_record(file_id))


@router.get(
    "/{file_id}/measurements/",
    response_model=MeasurementResponse,
    responses=NOT_FOUND_RESPONSE,
    summary="List feature-level measurements",
    description="Paginated feature results, optionally filtered by geometry type.",
)
def get_measurements(
    file_id: str,
    repository: RepositoryDep,
    page: Annotated[int, Query(ge=1, description="1-based page number.")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Items per page (max 100).")] = 20,
    geometry_type: Annotated[
        GeometryType | None, Query(description="Only return features of this geometry type.")
    ] = None,
) -> MeasurementResponse:
    record = repository.get_record(file_id)
    result = repository.get_result(file_id)
    return reporting.build_measurements_page(record, result, page, page_size, geometry_type)


@router.get(
    "/{file_id}/summary/",
    response_model=SummaryResponse,
    responses=NOT_FOUND_RESPONSE,
    summary="Aggregate summary for a processed file",
    description="Total area and total length are reported separately; they are never combined.",
)
def get_summary(file_id: str, repository: RepositoryDep) -> SummaryResponse:
    return reporting.build_summary(repository.get_record(file_id))


@router.get(
    "/{file_id}/quality/",
    response_model=QualityReportResponse,
    responses=NOT_FOUND_RESPONSE,
    summary="Get dataset geospatial quality report",
    description=(
        "Evaluates geometry health, CRS transformations, "
        "and measurement coverage to score dataset quality (0-100)."
    ),
)
def get_quality(file_id: str, repository: RepositoryDep) -> QualityReportResponse:
    record = repository.get_record(file_id)
    result = repository.get_result(file_id)
    return compute_quality_report(record, result)


@router.get(
    "/{file_id}/geojson",
    responses=NOT_FOUND_RESPONSE,
    summary="Normalized features as GeoJSON (WGS84)",
    description="Repaired geometries re-projected to EPSG:4326 per RFC 7946.",
)
def get_geojson(file_id: str, repository: RepositoryDep) -> JSONResponse:
    repository.get_record(file_id)
    result = repository.get_result(file_id)
    collection = to_feature_collection(result.geometries, result.source_crs, result.features)
    return JSONResponse(collection, media_type="application/geo+json")
