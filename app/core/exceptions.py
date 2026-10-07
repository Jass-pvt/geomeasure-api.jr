class GeoMeasureError(Exception):
    """Base class for errors that are safe to show to API consumers."""

    code = "INTERNAL_ERROR"
    status_code = 500
    default_message = "An unexpected error occurred."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class InvalidRequestError(GeoMeasureError):
    code = "INVALID_REQUEST"
    status_code = 400
    default_message = "The request is malformed."


class EmptyFileError(GeoMeasureError):
    code = "EMPTY_FILE"
    status_code = 400
    default_message = "The uploaded file is empty."


class FileTooLargeError(GeoMeasureError):
    code = "FILE_TOO_LARGE"
    status_code = 413
    default_message = "The uploaded file exceeds the maximum allowed size."


class UnsupportedFileTypeError(GeoMeasureError):
    code = "UNSUPPORTED_FILE_TYPE"
    status_code = 415
    default_message = "Only KML files and ZIP archives containing Shapefiles are supported."


class InvalidArchiveError(GeoMeasureError):
    code = "INVALID_ARCHIVE"
    status_code = 422
    default_message = "The ZIP archive is invalid."


class MissingShapefileComponentError(InvalidArchiveError):
    code = "MISSING_SHAPEFILE_COMPONENT"
    default_message = "The ZIP archive does not contain a complete Shapefile."


class GeospatialParseError(GeoMeasureError):
    code = "GEOSPATIAL_PARSE_ERROR"
    status_code = 422
    default_message = "The file does not contain readable geospatial content."


class MissingCRSError(GeoMeasureError):
    code = "MISSING_CRS"
    status_code = 422
    default_message = (
        "The uploaded Shapefile does not contain CRS information. "
        "A CRS is required for reliable measurements."
    )


class UnsupportedCRSError(GeoMeasureError):
    code = "UNSUPPORTED_CRS"
    status_code = 422
    default_message = "The coordinate reference system cannot be used for measurement."


class InvalidGeometryError(GeoMeasureError):
    code = "INVALID_GEOMETRY"
    status_code = 422
    default_message = "The geometry is invalid and could not be repaired."


class MeasurementError(GeoMeasureError):
    code = "MEASUREMENT_FAILED"
    status_code = 422
    default_message = "The measurement could not be calculated."


class FileRecordNotFoundError(GeoMeasureError):
    """Raised for unknown file IDs (named to avoid shadowing the builtin FileNotFoundError)."""

    code = "FILE_NOT_FOUND"
    status_code = 404
    default_message = "No processed file exists with the requested ID."
