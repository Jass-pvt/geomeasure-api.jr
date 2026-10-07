from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import FeatureStatus, MeasurementType, ProcessingStatus


class ErrorDetail(BaseModel):
    code: str = Field(examples=["MISSING_CRS"])
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str
    version: str


class CRSInfo(BaseModel):
    source: str = Field(description="CRS declared by (or assumed for) the uploaded file.")
    measurement: str | None = Field(
        description="CRS in which measurements were calculated; null if nothing was measurable."
    )


class Measurement(BaseModel):
    type: MeasurementType
    value: float = Field(description="Rounded to 2 decimals for presentation only.")
    unit: str = Field(examples=["m²", "m"])


class MeasurementMethod(BaseModel):
    method: str = Field(
        description="'projected_crs' (geometry transformed to a chosen UTM zone) or "
        "'source_projected_crs' (the file's own projected CRS was suitable).",
        examples=["projected_crs"],
    )
    measurement_crs: str
    projection: str
    unit_conversion_factor: float = Field(description="Metres per CRS unit; 1.0 for metric CRSs.")
    notes: list[str] = Field(default_factory=list)


class FeatureMeasurement(BaseModel):
    feature_index: int
    feature_id: str
    geometry_type: str
    properties: dict[str, Any]
    geometry_valid: bool
    geometry_repaired: bool
    crs: CRSInfo
    measurement: Measurement | None
    measurement_method: MeasurementMethod | None
    status: FeatureStatus
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ProcessingSummary(BaseModel):
    successful: int
    failed: int
    unsupported: int


class MeasurementTotals(BaseModel):
    total_area_m2: float
    total_length_m: float


class UploadResponse(BaseModel):
    id: str
    filename: str
    status: ProcessingStatus
    feature_count: int
    source_crs: str
    measurement_crs: str | None
    processing_time_ms: int
    features_per_second: float | None = Field(
        default=None, description="Calculated processing throughput in features/sec."
    )
    warnings: list[str]
    duplicate: bool = Field(
        default=False,
        description="True when an identical file (same SHA-256) was already processed.",
    )


class FileInfoResponse(BaseModel):
    id: str
    filename: str
    file_size_bytes: int
    file_hash: str = Field(description="SHA-256 of the uploaded bytes.")
    feature_count: int
    geometry_types: dict[str, int]
    source_crs: str
    measurement_crs: str | None
    measurement_crs_name: str | None
    status: ProcessingStatus
    created_at: datetime
    processed_at: datetime
    processing_time_ms: int
    features_per_second: float | None = Field(
        default=None, description="Calculated processing throughput in features/sec."
    )
    warnings: list[str]


class FileRecord(FileInfoResponse):
    """Internal metadata stored per processed file."""

    processing_summary: ProcessingSummary
    totals: MeasurementTotals


class MeasurementResponse(BaseModel):
    file_id: str
    page: int
    page_size: int
    total: int
    items: list[FeatureMeasurement]


class SummaryResponse(BaseModel):
    file_id: str
    feature_count: int
    geometry_summary: dict[str, int]
    processing_summary: ProcessingSummary
    measurements: MeasurementTotals
    crs: CRSInfo


class QualityGrade(StrEnum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class QualityScore(BaseModel):
    overall: QualityGrade
    score: int = Field(ge=0, le=100)


class QualityGeometrySummary(BaseModel):
    total: int
    valid: int
    repaired: int
    invalid: int


class QualityCrsSummary(BaseModel):
    source: str
    measurement: str
    transformed: bool


class QualityMeasurementSummary(BaseModel):
    measured: int
    unsupported: int
    failed: int


class QualityReportResponse(BaseModel):
    file_id: str
    quality: QualityScore
    geometry: QualityGeometrySummary
    crs: QualityCrsSummary
    measurements: QualityMeasurementSummary
    warnings: list[str]
