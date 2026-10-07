"""Tests for dataset geospatial quality report endpoint."""

from fastapi.testclient import TestClient


def test_get_quality_not_found(client: TestClient) -> None:
    response = client.get("/api/files/nonexistent-id/quality/")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FILE_NOT_FOUND"


def test_get_quality_success(client: TestClient, sample_kml: bytes) -> None:
    upload_res = client.post(
        "/api/files/",
        files={
            "file": (
                "sample.kml",
                sample_kml,
                "application/vnd.google-earth.kml+xml",
            )
        },
    )
    assert upload_res.status_code == 201
    file_id = upload_res.json()["id"]

    quality_res = client.get(f"/api/files/{file_id}/quality/")
    assert quality_res.status_code == 200

    data = quality_res.json()
    assert data["file_id"] == file_id
    assert "quality" in data
    assert data["quality"]["overall"] == "EXCELLENT"
    assert data["quality"]["score"] == 100
    assert data["geometry"]["total"] > 0
    assert data["crs"]["transformed"] is True
