from enum import StrEnum


class FileKind(StrEnum):
    KML = "kml"
    SHAPEFILE_ZIP = "shapefile_zip"


class ProcessingStatus(StrEnum):
    """RECEIVED and PROCESSING are reserved for asynchronous processing (future scope)."""

    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    FAILED = "FAILED"


class MeasurementType(StrEnum):
    AREA = "area"
    LENGTH = "length"


class FeatureStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    UNSUPPORTED_GEOMETRY = "UNSUPPORTED_GEOMETRY"


class GeometryType(StrEnum):
    POINT = "Point"
    MULTI_POINT = "MultiPoint"
    LINE_STRING = "LineString"
    MULTI_LINE_STRING = "MultiLineString"
    POLYGON = "Polygon"
    MULTI_POLYGON = "MultiPolygon"
    GEOMETRY_COLLECTION = "GeometryCollection"
    UNKNOWN = "Unknown"
