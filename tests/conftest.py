import io
import zipfile
from collections.abc import Callable
from pathlib import Path

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
SHAPEFILE_PARTS = (".shp", ".shx", ".dbf", ".prj", ".cpg")

SQUARE_COORDS = "80.000,13.000 80.010,13.000 80.010,13.010 80.000,13.010 80.000,13.000"
COLLINEAR_COORDS = "80.000,13.000 80.001,13.001 80.002,13.002 80.000,13.000"
LINE_COORDS = "80.000,13.000 80.010,13.000 80.020,13.010"


def polygon_placemark(name: str, coords: str = SQUARE_COORDS) -> str:
    return (
        f"<Placemark><name>{name}</name><Polygon><outerBoundaryIs><LinearRing>"
        f"<coordinates>{coords}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>"
    )


def line_placemark(name: str, coords: str = LINE_COORDS) -> str:
    return (
        f"<Placemark><name>{name}</name><LineString><coordinates>{coords}</coordinates>"
        "</LineString></Placemark>"
    )


def point_placemark(name: str, lon: float = 80.0, lat: float = 13.0) -> str:
    return (
        f"<Placemark><name>{name}</name><Point><coordinates>{lon},{lat}</coordinates></Point>"
        "</Placemark>"
    )


def kml_document(*placemarks: str) -> bytes:
    body = "".join(placemarks)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<kml xmlns="http://www.opengis.net/kml/2.2"><Document>{body}</Document></kml>'
    ).encode()


def zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, storage_dir=tmp_path / "work")


@pytest.fixture
def client_factory(tmp_path: Path) -> Callable[..., TestClient]:
    def make(**overrides: object) -> TestClient:
        values = {"storage_dir": tmp_path / "work", **overrides}
        settings = Settings(_env_file=None, **values)
        return TestClient(create_app(settings), raise_server_exceptions=False)

    return make


@pytest.fixture
def client(client_factory: Callable[..., TestClient]) -> TestClient:
    return client_factory()


@pytest.fixture
def storage_dir(client: TestClient) -> Path:
    return client.app.state.settings.storage_dir


@pytest.fixture
def upload() -> Callable[..., object]:
    def send(client: TestClient, filename: str, content: bytes):
        return client.post(
            "/api/files/", files={"file": (filename, content, "application/octet-stream")}
        )

    return send


@pytest.fixture
def shapefile_zip(tmp_path: Path) -> Callable[..., bytes]:
    def build(frame: gpd.GeoDataFrame, drop: tuple[str, ...] = ()) -> bytes:
        folder = tmp_path / "shp_build"
        folder.mkdir(exist_ok=True)
        frame.to_file(folder / "layer.shp")
        entries = {
            f"layer{ext}": (folder / f"layer{ext}").read_bytes()
            for ext in SHAPEFILE_PARTS
            if ext not in drop and (folder / f"layer{ext}").exists()
        }
        return zip_bytes(entries)

    return build


@pytest.fixture
def sample_kml() -> bytes:
    return (EXAMPLES_DIR / "sample.kml").read_bytes()


@pytest.fixture
def sample_shapefile() -> bytes:
    return (EXAMPLES_DIR / "sample_shapefile.zip").read_bytes()
