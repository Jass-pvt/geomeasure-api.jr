"""Format parsers. Every parser returns the same normalized GeoDataFrame layout."""

import io
import math
import tempfile
import zipfile
import zlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import geopandas as gpd
from pyproj import CRS
from shapely.errors import ShapelyError
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from shapely.geometry.base import BaseGeometry

from app.config import Settings
from app.core.exceptions import (
    GeospatialParseError,
    InvalidArchiveError,
    MissingCRSError,
    MissingShapefileComponentError,
)
from app.core.security import (
    extract_archive,
    is_archive_metadata_entry,
    validate_archive_entries,
)
from app.models.enums import FileKind
from app.services.ingestion import IngestedFile

FEATURE_ID_COLUMN = "feature_id"
PROPERTIES_COLUMN = "properties"
PARSE_ERROR_COLUMN = "parse_error"

KML_CRS = CRS.from_epsg(4326)
KML_GEOMETRY_TAGS = frozenset({"Point", "LineString", "LinearRing", "Polygon", "MultiGeometry"})
KML_TEXT_PROPERTIES = frozenset({"name", "description"})
SHAPEFILE_REQUIRED_COMPANIONS = (".shx", ".dbf")
ARCHIVE_READ_ERRORS = (zipfile.BadZipFile, NotImplementedError, zlib.error, EOFError)


@dataclass
class ParsedDataset:
    """Normalized parser output.

    ``dataset`` has columns: geometry, feature_id, properties (dict) and parse_error.
    """

    dataset: gpd.GeoDataFrame
    crs_assumed: bool = False
    warnings: list[str] = field(default_factory=list)


class GeospatialParser(ABC):
    @abstractmethod
    def parse(self, ingested: IngestedFile) -> ParsedDataset:
        """Parse an ingested file or raise a GeoMeasureError subclass."""


def build_dataset(
    geometries: list[BaseGeometry | None],
    feature_ids: list[str],
    properties: list[dict[str, Any]],
    parse_errors: list[str | None],
    crs: CRS,
) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            FEATURE_ID_COLUMN: feature_ids,
            PROPERTIES_COLUMN: properties,
            PARSE_ERROR_COLUMN: parse_errors,
        },
        geometry=geometries,
        crs=crs,
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class KMLParser(GeospatialParser):
    """Parses KML with the standard library.

    KML mandates WGS84 longitude/latitude, so EPSG:4326 is assumed explicitly. Altitude values
    are discarded because all measurements are planar (2D).
    """

    def parse(self, ingested: IngestedFile) -> ParsedDataset:
        try:
            root = ElementTree.fromstring(ingested.content)
        except ElementTree.ParseError as exc:
            raise GeospatialParseError("The KML file is not well-formed XML.") from exc
        if _local_name(root.tag) != "kml":
            raise GeospatialParseError("The XML document is not a KML file.")

        placemarks = [el for el in root.iter() if _local_name(el.tag) == "Placemark"]
        if not placemarks:
            raise GeospatialParseError("The KML file does not contain any Placemarks.")

        geometries: list[BaseGeometry | None] = []
        feature_ids: list[str] = []
        properties: list[dict[str, Any]] = []
        parse_errors: list[str | None] = []
        for index, placemark in enumerate(placemarks):
            geometry, error = self._read_geometry(placemark)
            geometries.append(geometry)
            parse_errors.append(error)
            feature_ids.append(placemark.get("id") or str(index))
            properties.append(self._read_properties(placemark))

        if all(geometry is None for geometry in geometries):
            raise GeospatialParseError("The KML file does not contain any readable geometry.")

        dataset = build_dataset(geometries, feature_ids, properties, parse_errors, KML_CRS)
        return ParsedDataset(dataset=dataset, crs_assumed=True)

    def _read_geometry(
        self, placemark: ElementTree.Element
    ) -> tuple[BaseGeometry | None, str | None]:
        element = next(
            (child for child in placemark if _local_name(child.tag) in KML_GEOMETRY_TAGS), None
        )
        if element is None:
            return None, "Placemark has no geometry."
        try:
            return self._build_geometry(element), None
        except (ValueError, ShapelyError) as exc:
            return None, f"Geometry could not be parsed: {exc}"

    def _build_geometry(self, element: ElementTree.Element) -> BaseGeometry:
        tag = _local_name(element.tag)
        if tag == "Point":
            return Point(self._coordinates(element)[0])
        if tag in {"LineString", "LinearRing"}:
            return LineString(self._coordinates(element))
        if tag == "Polygon":
            return self._build_polygon(element)
        return self._build_multi_geometry(element)

    def _build_polygon(self, element: ElementTree.Element) -> Polygon:
        shell: list[tuple[float, float]] | None = None
        holes: list[list[tuple[float, float]]] = []
        for child in element:
            boundary = _local_name(child.tag)
            if boundary == "outerBoundaryIs":
                shell = self._coordinates(child)
            elif boundary == "innerBoundaryIs":
                holes.append(self._coordinates(child))
        if shell is None:
            raise ValueError("Polygon has no outer boundary.")
        return Polygon(shell, holes)

    def _build_multi_geometry(self, element: ElementTree.Element) -> BaseGeometry:
        parts = [
            self._build_geometry(child)
            for child in element
            if _local_name(child.tag) in KML_GEOMETRY_TAGS
        ]
        if not parts:
            raise ValueError("MultiGeometry has no members.")
        if len(parts) == 1:
            return parts[0]
        member_types = {part.geom_type for part in parts}
        if member_types == {"Point"}:
            return MultiPoint(parts)
        if member_types == {"LineString"}:
            return MultiLineString(parts)
        if member_types == {"Polygon"}:
            return MultiPolygon(parts)
        return GeometryCollection(parts)

    @staticmethod
    def _coordinates(element: ElementTree.Element) -> list[tuple[float, float]]:
        node = next((el for el in element.iter() if _local_name(el.tag) == "coordinates"), None)
        if node is None or not (node.text or "").strip():
            raise ValueError("Missing coordinates.")
        points: list[tuple[float, float]] = []
        for token in node.text.split():
            parts = token.split(",")
            if len(parts) < 2:
                raise ValueError("Malformed coordinate tuple.")
            lon, lat = float(parts[0]), float(parts[1])
            if not (math.isfinite(lon) and math.isfinite(lat)):
                raise ValueError("Non-finite coordinate.")
            if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
                raise ValueError("Coordinate outside valid longitude/latitude range.")
            points.append((lon, lat))
        return points

    @staticmethod
    def _read_properties(placemark: ElementTree.Element) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        for child in placemark:
            tag = _local_name(child.tag)
            text = (child.text or "").strip()
            if tag in KML_TEXT_PROPERTIES and text:
                properties[tag] = text
            elif tag == "ExtendedData":
                for item in child.iter():
                    key = item.get("name")
                    if not key:
                        continue
                    item_tag = _local_name(item.tag)
                    if item_tag == "SimpleData":
                        properties[key] = (item.text or "").strip()
                    elif item_tag == "Data":
                        value = next((v for v in item if _local_name(v.tag) == "value"), None)
                        properties[key] = (value.text or "").strip() if value is not None else ""
        return properties


class ShapefileZipParser(GeospatialParser):
    """Safely extracts one Shapefile from a ZIP archive and reads it with GeoPandas.

    A missing .prj is rejected: inventing a CRS would make every measurement untrustworthy.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def parse(self, ingested: IngestedFile) -> ParsedDataset:
        self._settings.storage_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self._settings.storage_dir) as workdir:
            shp_path = self._extract(ingested.content, Path(workdir))
            frame = self._read(shp_path)
        return ParsedDataset(dataset=self._normalize(frame))

    def _extract(self, content: bytes, workdir: Path) -> Path:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                infos = [
                    info
                    for info in validate_archive_entries(archive, self._settings)
                    if not is_archive_metadata_entry(info)
                ]
                shp_name = self._select_shapefile([i.filename for i in infos if not i.is_dir()])
                extract_archive(archive, infos, workdir, self._settings.max_zip_uncompressed_bytes)
        except ARCHIVE_READ_ERRORS as exc:
            raise InvalidArchiveError("The ZIP archive is corrupted or unreadable.") from exc
        return workdir / shp_name

    @staticmethod
    def _select_shapefile(names: list[str]) -> str:
        normalized = [name.replace("\\", "/") for name in names]
        shapefiles = sorted(name for name in normalized if name.lower().endswith(".shp"))
        if not shapefiles:
            raise MissingShapefileComponentError("The archive does not contain a .shp file.")
        if len(shapefiles) > 1:
            raise InvalidArchiveError(
                "The archive contains more than one Shapefile; upload exactly one per ZIP."
            )
        stem = shapefiles[0][: -len(".shp")].lower()
        available = {name.lower() for name in normalized}
        missing = [ext for ext in SHAPEFILE_REQUIRED_COMPANIONS if stem + ext not in available]
        if missing:
            raise MissingShapefileComponentError(
                f"The archive is missing required Shapefile component(s): {', '.join(missing)}."
            )
        if stem + ".prj" not in available:
            raise MissingCRSError()
        return shapefiles[0]

    @staticmethod
    def _read(shp_path: Path) -> gpd.GeoDataFrame:
        try:
            frame = gpd.read_file(shp_path)
        except Exception as exc:  # GDAL/pyogrio raise many unrelated exception types
            raise GeospatialParseError(
                "The Shapefile could not be read; it may be corrupted."
            ) from exc
        if frame.crs is None:
            raise MissingCRSError(
                "The Shapefile's .prj file is missing or unreadable. "
                "A CRS is required for reliable measurements."
            )
        if frame.empty:
            raise GeospatialParseError("The Shapefile does not contain any features.")
        return frame

    @staticmethod
    def _normalize(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        geometry_column = frame.geometry.name
        properties = frame.drop(columns=geometry_column).to_dict("records")
        count = len(frame)
        return build_dataset(
            geometries=frame.geometry.tolist(),
            feature_ids=[str(i) for i in range(count)],
            properties=properties,
            parse_errors=[None] * count,
            crs=frame.crs,
        )


def get_parser(kind: FileKind, settings: Settings) -> GeospatialParser:
    if kind is FileKind.KML:
        return KMLParser()
    return ShapefileZipParser(settings)
