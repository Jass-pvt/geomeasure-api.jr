import pytest

from app.core.exceptions import GeospatialParseError
from app.models.enums import FileKind
from app.services.ingestion import IngestedFile
from app.services.parser import KMLParser
from tests.conftest import (
    COLLINEAR_COORDS,
    kml_document,
    line_placemark,
    point_placemark,
    polygon_placemark,
)


def ingest(content: bytes) -> IngestedFile:
    return IngestedFile("t.kml", FileKind.KML, content, len(content), "0" * 64)


def test_kml_assumes_wgs84_explicitly():
    parsed = KMLParser().parse(ingest(kml_document(point_placemark("p"))))
    assert parsed.crs_assumed is True
    assert parsed.dataset.crs.to_epsg() == 4326


def test_kml_parses_all_geometry_kinds_and_properties(sample_kml):
    dataset = KMLParser().parse(ingest(sample_kml)).dataset
    assert dataset.geometry.geom_type.tolist() == ["Polygon", "Polygon", "LineString", "Point"]
    assert dataset["feature_id"].tolist() == ["block-a", "block-b", "access-road", "gate-1"]
    assert dataset["properties"].iat[0] == {"name": "Survey Block A", "category": "survey"}


def test_kml_polygon_hole_is_preserved(sample_kml):
    polygon = KMLParser().parse(ingest(sample_kml)).dataset.geometry.iat[1]
    assert len(polygon.interiors) == 1


def test_kml_multigeometry_becomes_multi_type():
    placemark = (
        "<Placemark><MultiGeometry><Point><coordinates>80,13</coordinates></Point>"
        "<Point><coordinates>81,13</coordinates></Point></MultiGeometry></Placemark>"
    )
    dataset = KMLParser().parse(ingest(kml_document(placemark))).dataset
    assert dataset.geometry.iat[0].geom_type == "MultiPoint"


@pytest.mark.parametrize(
    "content",
    [b"<kml><Document>", b"<html></html>", kml_document(), b"not xml at all"],
)
def test_kml_rejects_unusable_documents(content):
    with pytest.raises(GeospatialParseError):
        KMLParser().parse(ingest(content))


def test_kml_with_only_unreadable_geometry_is_rejected():
    bad = "<Placemark><Point><coordinates>abc,def</coordinates></Point></Placemark>"
    with pytest.raises(GeospatialParseError):
        KMLParser().parse(ingest(kml_document(bad)))


def test_kml_bad_placemark_does_not_discard_good_ones():
    bad = "<Placemark><Point><coordinates>999,13</coordinates></Point></Placemark>"
    dataset = KMLParser().parse(ingest(kml_document(point_placemark("ok"), bad))).dataset
    assert dataset.geometry.iat[0] is not None
    assert dataset.geometry.iat[1] is None
    assert "outside valid" in dataset["parse_error"].iat[1]


def test_kml_upload_isolates_bad_feature(client, upload):
    content = kml_document(
        polygon_placemark("valid polygon"),
        polygon_placemark("degenerate polygon", COLLINEAR_COORDS),
        line_placemark("valid line"),
        point_placemark("a point"),
    )
    response = upload(client, "mixed.kml", content)
    assert response.status_code == 201
    assert response.json()["status"] == "COMPLETED_WITH_WARNINGS"

    summary = client.get(f"/api/files/{response.json()['id']}/summary/").json()
    assert summary["processing_summary"] == {"successful": 3, "failed": 1, "unsupported": 0}

    items = client.get(f"/api/files/{response.json()['id']}/measurements/").json()["items"]
    failed = items[1]
    assert failed["status"] == "FAILED"
    assert failed["errors"]
    assert failed["measurement"] is None
    assert [items[0]["status"], items[2]["status"], items[3]["status"]] == ["SUCCESS"] * 3


def test_kml_mixed_multigeometry_is_unsupported(client, upload):
    mixed = (
        "<Placemark><MultiGeometry><Point><coordinates>80,13</coordinates></Point>"
        "<LineString><coordinates>80,13 80.01,13.01</coordinates></LineString>"
        "</MultiGeometry></Placemark>"
    )
    response = upload(client, "mixed.kml", kml_document(polygon_placemark("ok"), mixed))
    file_id = response.json()["id"]
    unsupported = client.get(f"/api/files/{file_id}/measurements/").json()["items"][1]
    assert unsupported["status"] == "UNSUPPORTED_GEOMETRY"
    assert unsupported["measurement"] is None
    assert client.get(f"/api/files/{file_id}/summary/").json()["processing_summary"] == {
        "successful": 1,
        "failed": 0,
        "unsupported": 1,
    }


def test_malformed_kml_upload_returns_422(client, upload):
    response = upload(client, "broken.kml", b"<kml><Placemark>")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "GEOSPATIAL_PARSE_ERROR"
