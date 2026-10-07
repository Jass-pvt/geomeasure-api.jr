"""Quality scoring engine for processed geospatial datasets."""

from typing import Any

from app.models.schemas import (
    QualityCrsSummary,
    QualityGeometrySummary,
    QualityGrade,
    QualityMeasurementSummary,
    QualityReportResponse,
    QualityScore,
)


def compute_quality_report(record: Any, result: Any) -> QualityReportResponse:
    total_features = record.feature_count
    items = result.features if hasattr(result, "features") else []

    valid_cnt = sum(
        1
        for f in items
        if getattr(f, "geometry_valid", True) and not getattr(f, "geometry_repaired", False)
    )
    repaired_cnt = sum(1 for f in items if getattr(f, "geometry_repaired", False))
    invalid_cnt = max(0, total_features - (valid_cnt + repaired_cnt))

    measured_cnt = sum(1 for f in items if getattr(f, "measurement", None) is not None)
    unsupported_cnt = sum(1 for f in items if getattr(f, "geometry_type", "") == "Point")
    failed_cnt = sum(
        1
        for f in items
        if getattr(f, "measurement", None) is None
        and getattr(f, "geometry_type", "") != "Point"
        and getattr(f, "status", "") != "SUCCESS"
    )

    transformed = record.source_crs != record.measurement_crs

    # Deduct penalty points for quality issues
    penalty = 0
    if total_features > 0:
        penalty += int((invalid_cnt / total_features) * 50)
        penalty += int((repaired_cnt / total_features) * 15)
        penalty += int((failed_cnt / total_features) * 25)

    if record.warnings:
        penalty += min(10, len(record.warnings) * 2)

    score_val = max(0, 100 - penalty)

    if score_val >= 90:
        grade = QualityGrade.EXCELLENT
    elif score_val >= 75:
        grade = QualityGrade.GOOD
    elif score_val >= 50:
        grade = QualityGrade.FAIR
    else:
        grade = QualityGrade.POOR

    all_warnings = list(record.warnings)
    for f in items:
        if hasattr(f, "warnings") and f.warnings:
            all_warnings.extend(f.warnings)

    return QualityReportResponse(
        file_id=record.id,
        quality=QualityScore(overall=grade, score=score_val),
        geometry=QualityGeometrySummary(
            total=total_features,
            valid=valid_cnt,
            repaired=repaired_cnt,
            invalid=invalid_cnt,
        ),
        crs=QualityCrsSummary(
            source=record.source_crs,
            measurement=record.measurement_crs or "NONE",
            transformed=transformed,
        ),
        measurements=QualityMeasurementSummary(
            measured=measured_cnt,
            unsupported=unsupported_cnt,
            failed=failed_cnt,
        ),
        warnings=sorted(list(set(all_warnings))),
    )
