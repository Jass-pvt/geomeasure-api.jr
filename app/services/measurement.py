import math
from dataclasses import dataclass

from shapely.geometry.base import BaseGeometry

from app.core.exceptions import MeasurementError
from app.models.enums import MeasurementType
from app.models.schemas import Measurement
from app.services.crs import MeasurementCRS

AREA_GEOMETRIES = frozenset({"Polygon", "MultiPolygon"})
LENGTH_GEOMETRIES = frozenset({"LineString", "MultiLineString"})
POINT_GEOMETRIES = frozenset({"Point", "MultiPoint"})
SUPPORTED_GEOMETRIES = AREA_GEOMETRIES | LENGTH_GEOMETRIES | POINT_GEOMETRIES

AREA_UNIT = "m²"
LENGTH_UNIT = "m"
PRESENTATION_DECIMALS = 2


@dataclass(frozen=True)
class RawMeasurement:
    """Full-precision value in metres / square metres."""

    type: MeasurementType
    value: float

    def to_schema(self) -> Measurement:
        unit = AREA_UNIT if self.type is MeasurementType.AREA else LENGTH_UNIT
        return Measurement(
            type=self.type, value=round(self.value, PRESENTATION_DECIMALS), unit=unit
        )


def measure_geometry(
    geometry: BaseGeometry, measurement_crs: MeasurementCRS
) -> RawMeasurement | None:
    """Measure a geometry that is already expressed in ``measurement_crs``.

    Returns None for points (nothing to measure) and raises MeasurementError otherwise on failure.
    """
    if measurement_crs.crs.is_geographic:
        raise MeasurementError("Refusing to measure in a geographic CRS (degrees).")

    geometry_type = geometry.geom_type
    if geometry_type in POINT_GEOMETRIES:
        return None
    if geometry_type in AREA_GEOMETRIES:
        kind, value = MeasurementType.AREA, geometry.area * measurement_crs.unit_factor**2
    elif geometry_type in LENGTH_GEOMETRIES:
        kind, value = MeasurementType.LENGTH, geometry.length * measurement_crs.unit_factor
    else:
        raise MeasurementError(f"Geometry type {geometry_type} cannot be measured.")

    if not math.isfinite(value):
        raise MeasurementError("The measurement is not finite after CRS transformation.")
    return RawMeasurement(type=kind, value=value)
