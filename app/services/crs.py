import math
from dataclasses import dataclass, field

import geopandas as gpd
from pyproj import CRS, Transformer

from app.core.exceptions import MeasurementError, MissingCRSError, UnsupportedCRSError

UTM_ZONE_WIDTH_DEGREES = 6
UTM_ZONE_COUNT = 60
UTM_MAX_LATITUDE = 84.0
UTM_MIN_LATITUDE = -80.0
WGS84_UTM_NORTH_BASE_EPSG = 32600
WGS84_UTM_SOUTH_BASE_EPSG = 32700
GEOGRAPHIC_EPSG = "EPSG:4326"

METHOD_UTM = "projected_crs"
METHOD_SOURCE = "source_projected_crs"


@dataclass(frozen=True)
class MeasurementCRS:
    crs: CRS
    label: str
    name: str
    method: str
    unit_factor: float
    requires_transform: bool
    notes: list[str] = field(default_factory=list)


def crs_label(crs: CRS) -> str:
    authority = crs.to_authority()
    return f"{authority[0]}:{authority[1]}" if authority else crs.name


def utm_epsg_for(longitude: float, latitude: float) -> int:
    """WGS84 UTM EPSG code: zone = floor((lon + 180) / 6) + 1; 326xx north, 327xx south."""
    if not (-180.0 <= longitude <= 180.0 and -90.0 <= latitude <= 90.0):
        raise UnsupportedCRSError("Dataset coordinates are outside valid longitude/latitude range.")
    if not UTM_MIN_LATITUDE <= latitude <= UTM_MAX_LATITUDE:
        raise MeasurementError(
            "The dataset lies outside the latitude range covered by UTM (80°S to 84°N)."
        )
    zone = min(math.floor((longitude + 180.0) / UTM_ZONE_WIDTH_DEGREES) + 1, UTM_ZONE_COUNT)
    base = WGS84_UTM_NORTH_BASE_EPSG if latitude >= 0 else WGS84_UTM_SOUTH_BASE_EPSG
    return base + zone


def metres_per_unit(crs: CRS) -> float:
    if not crs.axis_info:
        raise UnsupportedCRSError("The CRS does not declare axis units.")
    factor = crs.axis_info[0].unit_conversion_factor
    if not factor or not math.isfinite(factor) or factor <= 0:
        raise UnsupportedCRSError("The CRS declares invalid axis units.")
    return float(factor)


def _is_pseudo_mercator(crs: CRS) -> bool:
    operation = crs.coordinate_operation
    return operation is not None and "pseudo mercator" in operation.method_name.lower()


def _extent_lonlat(dataset: gpd.GeoDataFrame) -> tuple[float, float, float, float]:
    """Return (west, south, east, north) in degrees, transforming only the bounding box."""
    minx, miny, maxx, maxy = dataset.total_bounds
    if not all(math.isfinite(v) for v in (minx, miny, maxx, maxy)):
        raise UnsupportedCRSError("The dataset extent could not be determined.")
    if dataset.crs.is_geographic:
        return minx, miny, maxx, maxy
    transformer = Transformer.from_crs(dataset.crs, GEOGRAPHIC_EPSG, always_xy=True)
    xs, ys = transformer.transform([minx, maxx, minx, maxx], [miny, miny, maxy, maxy])
    if not all(math.isfinite(v) for v in (*xs, *ys)):
        raise UnsupportedCRSError("The dataset extent cannot be converted to longitude/latitude.")
    return min(xs), min(ys), max(xs), max(ys)


def estimate_measurement_crs(dataset: gpd.GeoDataFrame) -> MeasurementCRS:
    """Choose one CRS in which every feature of the dataset will be measured.

    - Projected source CRS: used as-is, unless it is (Pseudo-)Mercator, which distorts area badly.
    - Geographic source CRS (or Web Mercator): local WGS84 UTM zone from the extent centre.
    """
    source = dataset.crs
    if source is None:
        raise MissingCRSError()
    if source.is_projected and not _is_pseudo_mercator(source):
        return MeasurementCRS(
            crs=source,
            label=crs_label(source),
            name=source.name,
            method=METHOD_SOURCE,
            unit_factor=metres_per_unit(source),
            requires_transform=False,
        )
    if not (source.is_geographic or source.is_projected):
        raise UnsupportedCRSError(
            "Only geographic and projected coordinate reference systems are supported."
        )

    west, south, east, north = _extent_lonlat(dataset)
    centre_lon, centre_lat = (west + east) / 2.0, (south + north) / 2.0
    utm = CRS.from_epsg(utm_epsg_for(centre_lon, centre_lat))
    notes: list[str] = []
    if east - west > UTM_ZONE_WIDTH_DEGREES:
        notes.append(
            "The dataset spans more than one UTM zone; a single local UTM projection "
            "reduces accuracy toward the edges of the extent."
        )
    return MeasurementCRS(
        crs=utm,
        label=crs_label(utm),
        name=utm.name,
        method=METHOD_UTM,
        unit_factor=1.0,
        requires_transform=True,
        notes=notes,
    )


def transform_to_measurement_crs(
    dataset: gpd.GeoDataFrame, measurement_crs: MeasurementCRS
) -> gpd.GeoDataFrame:
    """Transform the whole dataset once; returns the input unchanged if no transform is needed."""
    if not measurement_crs.requires_transform:
        return dataset
    return dataset.to_crs(measurement_crs.crs)
