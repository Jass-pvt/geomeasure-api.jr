"""Time the full processing pipeline on synthetic KML datasets.

Usage: python scripts/benchmark.py
Prints a markdown table; paste your own measured numbers into the README.
"""

import hashlib
import statistics
import sys
import tempfile
import time
from pathlib import Path

# Add project root directory to sys.path so 'app' module can be imported directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.models.enums import FileKind
from app.services.ingestion import IngestedFile
from app.services.processor import FileProcessor
from app.storage.memory import InMemoryRepository

DATASET_SIZES = (10, 100, 1000)
REPEATS = 5
GRID_WIDTH = 50
CELL_DEGREES = 0.001


def synthetic_kml(feature_count: int) -> bytes:
    placemarks = []
    for i in range(feature_count):
        x0 = 80.0 + (i % GRID_WIDTH) * CELL_DEGREES * 2
        y0 = 13.0 + (i // GRID_WIDTH) * CELL_DEGREES * 2
        x1, y1 = x0 + CELL_DEGREES, y0 + CELL_DEGREES
        ring = f"{x0},{y0} {x1},{y0} {x1},{y1} {x0},{y1} {x0},{y0}"
        placemarks.append(
            f"<Placemark><name>f{i}</name><Polygon><outerBoundaryIs><LinearRing>"
            f"<coordinates>{ring}</coordinates></LinearRing></outerBoundaryIs>"
            "</Polygon></Placemark>"
        )
    body = "".join(placemarks)
    return (
        f'<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>{body}'
        "</Document></kml>"
    ).encode()


def main() -> None:
    print("| Dataset | Features | Size | Median time | Per feature |")
    print("|---------|----------|------|-------------|-------------|")
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(_env_file=None, storage_dir=Path(tmp))
        for count in DATASET_SIZES:
            content = synthetic_kml(count)
            digest = hashlib.sha256(content).hexdigest()
            ingested = IngestedFile("bench.kml", FileKind.KML, content, len(content), digest)
            timings = []
            for _ in range(REPEATS):
                processor = FileProcessor(settings, InMemoryRepository())
                started = time.perf_counter()
                processor.process_ingested(ingested)
                timings.append((time.perf_counter() - started) * 1000)
            median = statistics.median(timings)
            print(
                f"| synthetic | {count} | {len(content) / 1024:.1f} KB | "
                f"{median:.0f} ms | {median / count:.2f} ms |"
            )


if __name__ == "__main__":
    main()
