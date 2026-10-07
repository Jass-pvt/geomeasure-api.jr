from app.models.enums import GeometryType
from app.models.schemas import (
    CRSInfo,
    FileInfoResponse,
    FileRecord,
    MeasurementResponse,
    SummaryResponse,
)
from app.storage.memory import MeasurementResult


def build_file_info(record: FileRecord) -> FileInfoResponse:
    return FileInfoResponse.model_validate(record.model_dump())


def build_measurements_page(
    record: FileRecord,
    result: MeasurementResult,
    page: int,
    page_size: int,
    geometry_type: GeometryType | None,
) -> MeasurementResponse:
    features = result.features
    if geometry_type is not None:
        features = [f for f in features if f.geometry_type == geometry_type.value]
    start = (page - 1) * page_size
    return MeasurementResponse(
        file_id=record.id,
        page=page,
        page_size=page_size,
        total=len(features),
        items=features[start : start + page_size],
    )


def build_summary(record: FileRecord) -> SummaryResponse:
    return SummaryResponse(
        file_id=record.id,
        feature_count=record.feature_count,
        geometry_summary=record.geometry_types,
        processing_summary=record.processing_summary,
        measurements=record.totals,
        crs=CRSInfo(source=record.source_crs, measurement=record.measurement_crs),
    )
