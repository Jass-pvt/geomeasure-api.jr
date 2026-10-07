import threading
from dataclasses import dataclass
from typing import Protocol

from pyproj import CRS
from shapely.geometry.base import BaseGeometry

from app.core.exceptions import FileRecordNotFoundError
from app.models.schemas import FeatureMeasurement, FileRecord


@dataclass(frozen=True)
class MeasurementResult:
    """Feature-level output plus the (repaired) source-CRS geometries for GeoJSON export."""

    features: list[FeatureMeasurement]
    geometries: list[BaseGeometry | None]
    source_crs: CRS


class ResultRepository(Protocol):
    """Storage contract; swap the in-memory implementation for PostGIS/S3 later."""

    def add(self, record: FileRecord, result: MeasurementResult) -> None: ...

    def get_record(self, file_id: str) -> FileRecord: ...

    def get_result(self, file_id: str) -> MeasurementResult: ...

    def find_by_hash(self, file_hash: str) -> FileRecord | None: ...


class InMemoryRepository:
    """Process-local storage. Everything is lost on restart (intentional for this assignment)."""

    def __init__(self) -> None:
        self._records: dict[str, FileRecord] = {}
        self._results: dict[str, MeasurementResult] = {}
        self._ids_by_hash: dict[str, str] = {}
        self._lock = threading.Lock()

    def add(self, record: FileRecord, result: MeasurementResult) -> None:
        with self._lock:
            self._records[record.id] = record
            self._results[record.id] = result
            self._ids_by_hash.setdefault(record.file_hash, record.id)

    def get_record(self, file_id: str) -> FileRecord:
        record = self._records.get(file_id)
        if record is None:
            raise FileRecordNotFoundError()
        return record

    def get_result(self, file_id: str) -> MeasurementResult:
        result = self._results.get(file_id)
        if result is None:
            raise FileRecordNotFoundError()
        return result

    def find_by_hash(self, file_hash: str) -> FileRecord | None:
        file_id = self._ids_by_hash.get(file_hash)
        return self._records.get(file_id) if file_id else None
