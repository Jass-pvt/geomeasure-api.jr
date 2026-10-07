"""Pipeline orchestration: ingest -> parse -> validate -> select CRS -> transform -> measure."""

import logging
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import geopandas as gpd
from fastapi import UploadFile
from fastapi.concurrency import run_in_threadpool
from pyproj import CRS
from shapely.geometry.base import BaseGeometry

from app.config import Settings
from app.core.exceptions import GeoMeasureError, MeasurementError
from app.models.enums import FeatureStatus, ProcessingStatus
from app.models.schemas import (
    CRSInfo,
    FeatureMeasurement,
    FileRecord,
    MeasurementMethod,
    MeasurementTotals,
    ProcessingSummary,
)
from app.services.crs import (
    MeasurementCRS,
    crs_label,
    estimate_measurement_crs,
    transform_to_measurement_crs,
)
from app.services.geometry import GeometryReport, geometry_type_name, validate_geometries
from app.services.ingestion import IngestedFile, ingest_upload
from app.services.measurement import (
    SUPPORTED_GEOMETRIES,
    RawMeasurement,
    measure_geometry,
)
from app.services.parser import (
    FEATURE_ID_COLUMN,
    PARSE_ERROR_COLUMN,
    PROPERTIES_COLUMN,
    ParsedDataset,
    get_parser,
)
from app.services.serialization import sanitize_properties
from app.storage.memory import MeasurementResult, ResultRepository

logger = logging.getLogger("geomeasure.processor")

KML_CRS_NOTE = "Source CRS assumed to be EPSG:4326, as mandated by the KML specification."
REPAIR_WARNING = "Geometry was invalid and has been repaired with make_valid()."


@dataclass(frozen=True)
class ProcessingOutcome:
    record: FileRecord
    duplicate: bool


class FileProcessor:
    """Central orchestration layer. Stateless apart from its repository, so it can move to a
    background worker later without changes to the stages it calls."""

    def __init__(self, settings: Settings, repository: ResultRepository) -> None:
        self._settings = settings
        self._repository = repository

    async def process(self, upload: UploadFile) -> ProcessingOutcome:
        ingested = await ingest_upload(upload, self._settings)
        existing = self._repository.find_by_hash(ingested.sha256)
        if existing is not None:
            logger.info("file_id=%s duplicate_upload filename=%s", existing.id, ingested.filename)
            return ProcessingOutcome(record=existing, duplicate=True)
        record = await run_in_threadpool(self.process_ingested, ingested)
        return ProcessingOutcome(record=record, duplicate=False)

    def process_ingested(self, ingested: IngestedFile) -> FileRecord:
        file_id = str(uuid4())
        started = time.perf_counter()
        logger.info("file_id=%s processing_started filename=%s", file_id, ingested.filename)
        try:
            record, result = self._run_pipeline(file_id, ingested, started)
        except GeoMeasureError as exc:
            logger.warning("file_id=%s processing_rejected code=%s", file_id, exc.code)
            raise
        self._repository.add(record, result)
        logger.info(
            "file_id=%s processing_completed features=%d status=%s duration_ms=%d warnings=%d",
            file_id,
            record.feature_count,
            record.status.value,
            record.processing_time_ms,
            len(record.warnings),
        )
        return record

    def _run_pipeline(
        self, file_id: str, ingested: IngestedFile, started: float
    ) -> tuple[FileRecord, MeasurementResult]:
        created_at = datetime.now(UTC)
        parsed = get_parser(ingested.kind, self._settings).parse(ingested)
        dataset = parsed.dataset

        geometries, reports = validate_geometries(dataset.geometry.tolist())
        measurement_crs, planar = _transform_usable(dataset.crs, geometries, reports)

        source_label = crs_label(dataset.crs)
        crs_info = CRSInfo(
            source=source_label,
            measurement=measurement_crs.label if measurement_crs else None,
        )
        features: list[FeatureMeasurement] = []
        totals = {"area": 0.0, "length": 0.0}
        for index in range(len(dataset)):
            feature, raw = _measure_feature(
                index=index,
                dataset=dataset,
                parsed=parsed,
                geometry=geometries[index],
                report=reports[index],
                planar_geometry=planar.get(index),
                measurement_crs=measurement_crs,
                crs_info=crs_info,
            )
            features.append(feature)
            if raw is not None:
                totals[raw.type.value] += raw.value

        summary = _summarize(features)
        warnings = _file_warnings(parsed, features, reports, measurement_crs, summary)
        record = FileRecord(
            id=file_id,
            filename=ingested.filename,
            file_size_bytes=ingested.size_bytes,
            file_hash=ingested.sha256,
            feature_count=len(features),
            geometry_types=dict(sorted(Counter(f.geometry_type for f in features).items())),
            source_crs=source_label,
            measurement_crs=measurement_crs.label if measurement_crs else None,
            measurement_crs_name=measurement_crs.name if measurement_crs else None,
            status=_overall_status(summary, warnings),
            created_at=created_at,
            processed_at=datetime.now(UTC),
            processing_time_ms=round((time.perf_counter() - started) * 1000),
            warnings=warnings,
            processing_summary=summary,
            totals=MeasurementTotals(
                total_area_m2=round(totals["area"], 2), total_length_m=round(totals["length"], 2)
            ),
        )
        result = MeasurementResult(features=features, geometries=geometries, source_crs=dataset.crs)
        return record, result


def _transform_usable(
    source_crs: CRS,
    geometries: list[BaseGeometry | None],
    reports: list[GeometryReport],
) -> tuple[MeasurementCRS | None, dict[int, BaseGeometry]]:
    """Pick one measurement CRS for the dataset and transform all usable geometries once."""
    positions = [i for i, report in enumerate(reports) if report.usable]
    if not positions:
        return None, {}
    usable = gpd.GeoDataFrame(geometry=[geometries[i] for i in positions], crs=source_crs)
    measurement_crs = estimate_measurement_crs(usable)
    planar = transform_to_measurement_crs(usable, measurement_crs)
    return measurement_crs, dict(zip(positions, planar.geometry, strict=True))


def _measure_feature(
    *,
    index: int,
    dataset: gpd.GeoDataFrame,
    parsed: ParsedDataset,
    geometry: BaseGeometry | None,
    report: GeometryReport,
    planar_geometry: BaseGeometry | None,
    measurement_crs: MeasurementCRS | None,
    crs_info: CRSInfo,
) -> tuple[FeatureMeasurement, RawMeasurement | None]:
    properties, warnings = sanitize_properties(dataset[PROPERTIES_COLUMN].iat[index])
    errors: list[str] = []
    geometry_type = geometry_type_name(geometry)
    parse_error = dataset[PARSE_ERROR_COLUMN].iat[index]
    if not isinstance(parse_error, str):  # missing values may come back as NaN
        parse_error = None
    raw: RawMeasurement | None = None
    method: MeasurementMethod | None = None
    status = FeatureStatus.SUCCESS

    if parse_error:
        status, errors = FeatureStatus.FAILED, [parse_error]
    elif not report.usable:
        status, errors = FeatureStatus.FAILED, [report.error or "Geometry is unusable."]
    elif geometry_type not in SUPPORTED_GEOMETRIES:
        status = FeatureStatus.UNSUPPORTED_GEOMETRY
        warnings.append(f"Geometry type {geometry_type} is not supported for measurement.")
    else:
        if report.repaired:
            warnings.append(REPAIR_WARNING)
        try:
            raw = measure_geometry(planar_geometry, measurement_crs)
        except MeasurementError as exc:
            status, errors = FeatureStatus.FAILED, [exc.message]
        else:
            if raw is not None:
                method = _method_for(measurement_crs, parsed)

    feature = FeatureMeasurement(
        feature_index=index,
        feature_id=str(dataset[FEATURE_ID_COLUMN].iat[index]),
        geometry_type=geometry_type,
        properties=properties,
        geometry_valid=report.valid,
        geometry_repaired=report.repaired,
        crs=crs_info,
        measurement=raw.to_schema() if raw else None,
        measurement_method=method,
        status=status,
        warnings=warnings,
        errors=errors,
    )
    return feature, raw


def _method_for(measurement_crs: MeasurementCRS, parsed: ParsedDataset) -> MeasurementMethod:
    notes = list(measurement_crs.notes)
    if parsed.crs_assumed:
        notes.append(KML_CRS_NOTE)
    return MeasurementMethod(
        method=measurement_crs.method,
        measurement_crs=measurement_crs.label,
        projection=measurement_crs.name,
        unit_conversion_factor=measurement_crs.unit_factor,
        notes=notes,
    )


def _summarize(features: list[FeatureMeasurement]) -> ProcessingSummary:
    counts = Counter(feature.status for feature in features)
    return ProcessingSummary(
        successful=counts[FeatureStatus.SUCCESS],
        failed=counts[FeatureStatus.FAILED],
        unsupported=counts[FeatureStatus.UNSUPPORTED_GEOMETRY],
    )


def _file_warnings(
    parsed: ParsedDataset,
    features: list[FeatureMeasurement],
    reports: list[GeometryReport],
    measurement_crs: MeasurementCRS | None,
    summary: ProcessingSummary,
) -> list[str]:
    warnings = list(parsed.warnings)
    if summary.failed:
        warnings.append(f"{summary.failed} feature(s) failed and were excluded from measurements.")
    if summary.unsupported:
        warnings.append(f"{summary.unsupported} feature(s) have an unsupported geometry type.")
    repaired = sum(report.repaired for report in reports)
    if repaired:
        warnings.append(f"{repaired} invalid geometry(ies) were repaired before measurement.")
    if measurement_crs and measurement_crs.notes:
        warnings.extend(measurement_crs.notes)
    if not features:
        warnings.append("The file contains no features.")

    for feature in features:
        for w in feature.warnings:
            if w not in warnings:
                warnings.append(w)

    return warnings


def _overall_status(summary: ProcessingSummary, warnings: list[str]) -> ProcessingStatus:
    if summary.successful == 0:
        return ProcessingStatus.FAILED
    if warnings or summary.failed or summary.unsupported:
        return ProcessingStatus.COMPLETED_WITH_WARNINGS
    return ProcessingStatus.COMPLETED
