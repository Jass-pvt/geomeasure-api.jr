import io
import zipfile

import pytest

from app.config import Settings
from app.core.exceptions import InvalidArchiveError
from app.core.security import (
    detect_file_kind,
    is_safe_archive_path,
    sanitize_filename,
    validate_archive_entries,
)
from app.models.enums import FileKind
from tests.conftest import zip_bytes


@pytest.mark.parametrize(
    "name",
    ["../../file.shp", "/etc/passwd", "..\\evil.shp", "a/../../b.shp", "C:/windows/x.shp", ""],
)
def test_unsafe_archive_paths_are_detected(name):
    assert not is_safe_archive_path(name)


@pytest.mark.parametrize("name", ["layer.shp", "folder/layer.shp", "dir\\layer.dbf", "a..b.shp"])
def test_safe_archive_paths_are_allowed(name):
    assert is_safe_archive_path(name)


def test_file_kind_detection_is_case_insensitive():
    assert detect_file_kind("A.KML") is FileKind.KML
    assert detect_file_kind("x.Zip") is FileKind.SHAPEFILE_ZIP


def test_filename_sanitisation_strips_paths_and_control_characters():
    assert sanitize_filename("..\\..\\evil\nname.kml") == "evilname.kml"
    assert sanitize_filename(None) == ""


def test_path_traversal_zip_is_rejected_and_nothing_is_written(client, upload, tmp_path):
    payload = zip_bytes({"../../evil.shp": b"x", "../../evil.shx": b"x", "../../evil.dbf": b"x"})
    response = upload(client, "evil.zip", payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_ARCHIVE"
    assert not list(tmp_path.glob("evil*"))
    assert not list(tmp_path.parent.glob("evil*"))


def test_absolute_path_zip_is_rejected(client, upload):
    response = upload(client, "abs.zip", zip_bytes({"/etc/passwd": b"x"}))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_ARCHIVE"


def test_malformed_zip_is_rejected(client, upload):
    response = upload(client, "bad.zip", b"this is not a zip archive")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_ARCHIVE"


def test_zip_without_shapefile_is_rejected(client, upload):
    response = upload(client, "docs.zip", zip_bytes({"readme.txt": b"hello"}))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MISSING_SHAPEFILE_COMPONENT"


def test_too_many_archive_entries_are_rejected(client_factory, upload):
    client = client_factory(max_zip_files=3)
    payload = zip_bytes({f"f{i}.txt": b"x" for i in range(5)})
    response = upload(client, "many.zip", payload)
    assert response.status_code == 422
    assert "entries" in response.json()["error"]["message"]


def test_zip_bomb_is_rejected_by_uncompressed_limit(client_factory, upload):
    client = client_factory(max_zip_uncompressed_mb=1)
    payload = zip_bytes({"layer.shp": b"\0" * (2 * 1024 * 1024)})
    assert len(payload) < 100_000
    response = upload(client, "bomb.zip", payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_ARCHIVE"


def test_symlink_entries_are_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("link.shp")
        info.external_attr = 0o120777 << 16
        archive.writestr(info, "/etc/passwd")
    with (
        zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as archive,
        pytest.raises(InvalidArchiveError),
    ):
        validate_archive_entries(archive, Settings(_env_file=None))


def test_temporary_files_are_cleaned_up_on_success_and_failure(
    client, upload, storage_dir, sample_shapefile
):
    upload(client, "ok.zip", sample_shapefile)
    upload(client, "bad.zip", zip_bytes({"../x.shp": b"x"}))
    upload(client, "noprj.zip", zip_bytes({"a.shp": b"x", "a.shx": b"x", "a.dbf": b"x"}))
    assert list(storage_dir.iterdir()) == []
