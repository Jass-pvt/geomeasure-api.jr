from tests.conftest import kml_document, point_placemark


def test_valid_shapefile_zip_upload(client, upload, sample_shapefile):
    response = upload(client, "parcels.zip", sample_shapefile)
    assert response.status_code == 201
    assert response.json()["feature_count"] == 3


def test_empty_upload_is_rejected(client, upload):
    response = upload(client, "empty.kml", b"")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMPTY_FILE"


def test_missing_file_field_is_rejected(client):
    response = client.post("/api/files/")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_unsupported_extensions_are_rejected(client, upload):
    for name in ("malware.exe", "doc.pdf", "photo.jpg", "notes.txt", "data.tar.gz", "noextension"):
        response = upload(client, name, b"content")
        assert response.status_code == 415, name
        assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_oversized_upload_is_rejected(client_factory, upload):
    client = client_factory(max_upload_mb=1)
    response = upload(client, "big.kml", b"x" * (1024 * 1024 + 1))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_duplicate_upload_returns_original_result(client, upload, sample_kml):
    first = upload(client, "sample.kml", sample_kml)
    second = upload(client, "renamed.kml", sample_kml)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["id"] == first.json()["id"]


def test_different_content_is_not_a_duplicate(client, upload, sample_kml):
    first = upload(client, "a.kml", sample_kml)
    second = upload(client, "b.kml", kml_document(point_placemark("only")))
    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]


def test_filename_with_path_is_reduced_to_basename(client, upload, sample_kml):
    response = upload(client, "../../etc/survey.kml", sample_kml)
    assert response.status_code == 201
    assert response.json()["filename"] == "survey.kml"
