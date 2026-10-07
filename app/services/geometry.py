"""Geometry validation, repair, and GeoJSON serialization routines."""

import math
from dataclasses import dataclass
from typing import Any

import geopandas as gpd
from pyproj import CRS
from shapely import make_valid, unary_union
from shapely.errors import ShapelyError
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from app.models.enums import GeometryType
from app.models.schemas import FeatureMeasurement

POLYGONAL_TYPES = frozenset({"Polygon", "MultiPolygon"})
GEOJSON_CRS = "EPSG:4326"


@dataclass(frozen=True)
class GeometryReport:
    valid: bool
    repaired: bool
    usable: bool
    error: str | None = None


def geometry_type_name(geometry: BaseGeometry | None) -> str:
    return GeometryType.UNKNOWN.value if geometry is None else geometry.geom_type


def validate_geometries(
    geometries: list[BaseGeometry | None],
) -> tuple[list[BaseGeometry | None], list[GeometryReport]]:
    """Validate each geometry independently; repair only the invalid ones.

    A feature that cannot be repaired is flagged as unusable; it never aborts the dataset.
    """
    checked = [_check_geometry(geometry) for geometry in geometries]
    return [geometry for geometry, _ in checked], [report for _, report in checked]


def _check_geometry(geometry: BaseGeometry | None) -> tuple[BaseGeometry | None, GeometryReport]:
    if geometry is None:
        return None, GeometryReport(False, False, False, "Feature has no geometry.")
    if geometry.is_empty:
        return geometry, GeometryReport(False, False, False, "Geometry is empty.")

    if geometry.is_valid:
        if _is_degenerate(geometry):
            return geometry, GeometryReport(
                False, False, False, "Geometry is degenerate (zero area or length)."
            )
        return geometry, GeometryReport(True, False, True)

    repaired = _repair(geometry)
    if repaired is None or repaired.is_empty:
        return geometry, GeometryReport(
            False, False, False, "Geometry is invalid and could not be repaired safely."
        )
    if _is_degenerate(repaired):
        return geometry, GeometryReport(
            False, False, False, "Geometry is degenerate (zero area or length)."
        )
    return repaired, GeometryReport(False, True, True)


def _is_degenerate(geometry: BaseGeometry) -> bool:
    return (
        geometry.geom_type in POLYGONAL_TYPES and math.isclose(geometry.area, 0.0, abs_tol=1e-12)
    ) or (
        geometry.geom_type in ("LineString", "MultiLineString")
        and math.isclose(geometry.length, 0.0, abs_tol=1e-9)
    )


def _repair(geometry: BaseGeometry) -> BaseGeometry | None:
    """Repair with make_valid, accepting the result only if it keeps the geometry's family."""
    try:
        fixed = make_valid(geometry)
    except (ShapelyError, ValueError):
        return None
    if fixed.is_empty or not fixed.is_valid:
        return None
    if geometry.geom_type in POLYGONAL_TYPES:
        return _polygonal_part(fixed)
    return fixed if fixed.geom_type == geometry.geom_type else None


def _polygonal_part(geometry: BaseGeometry) -> BaseGeometry | None:
    if geometry.geom_type in POLYGONAL_TYPES:
        return geometry
    if geometry.geom_type == "GeometryCollection":
        parts = [part for part in geometry.geoms if part.geom_type in POLYGONAL_TYPES]
        if parts:
            return unary_union(parts)
    return None


def to_feature_collection(
    geometries: list[BaseGeometry | None],
    crs: CRS,
    features: list[FeatureMeasurement],
) -> dict[str, Any]:
    """Build an RFC 7946 FeatureCollection (WGS84) from stored geometries."""
    series = gpd.GeoSeries(geometries, crs=crs).to_crs(GEOJSON_CRS)
    items = []
    for geometry, feature in zip(series, features, strict=True):
        items.append(
            {
                "type": "Feature",
                "id": feature.feature_id,
                "geometry": _geometry_mapping(geometry),
                "properties": {
                    **feature.properties,
                    "feature_index": feature.feature_index,
                    "geometry_type": feature.geometry_type,
                    "status": feature.status.value,
                },
            }
        )
    return {"type": "FeatureCollection", "features": items}


def _geometry_mapping(geometry: BaseGeometry | None) -> dict[str, Any] | None:
    if geometry is None or geometry.is_empty:
        return None
    if not all(math.isfinite(value) for value in geometry.bounds):
        return None
    return mapping(geometry)
