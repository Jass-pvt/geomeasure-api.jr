from tests.conftest import kml_document, point_placemark


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "geomasure-api", "version": "1.0.0"}


def test_documentation_endpoints(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/files/" in paths
    assert "/api/files/{file_id}/measurements/" in paths


def test_full_kml_flow(client, upload, sample_kml):
    created = upload(client, "sample.kml", sample_kml)
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "COMPLETED"
    assert body["feature_count"] == 4
    assert body["source_crs"] == "EPSG:4326"
    assert body["measurement_crs"] == "EPSG:32644"
    assert body["duplicate"] is False

    info = client.get(f"/api/files/{body['id']}").json()
    assert info["geometry_types"] == {"LineString": 1, "Point": 1, "Polygon": 2}
    assert len(info["file_hash"]) == 64
    assert info["file_size_bytes"] == len(sample_kml)

    summary = client.get(f"/api/files/{body['id']}/summary/").json()
    assert summary["processing_summary"] == {"successful": 4, "failed": 0, "unsupported": 0}
    assert summary["measurements"]["total_area_m2"] > 0
    assert summary["measurements"]["total_length_m"] > 0
    assert summary["crs"] == {"source": "EPSG:4326", "measurement": "EPSG:32644"}


def test_measurement_items_expose_methodology(client, upload, sample_kml):
    file_id = upload(client, "sample.kml", sample_kml).json()["id"]
    page = client.get(f"/api/files/{file_id}/measurements/").json()
    polygon = next(item for item in page["items"] if item["feature_id"] == "block-a")
    assert polygon["measurement"]["type"] == "area"
    assert polygon["measurement"]["unit"] == "m²"
    assert polygon["measurement_method"]["method"] == "projected_crs"
    assert polygon["measurement_method"]["projection"] == "WGS 84 / UTM zone 44N"
    assert polygon["properties"]["name"] == "Survey Block A"
    assert polygon["status"] == "SUCCESS"
    point = next(item for item in page["items"] if item["feature_id"] == "gate-1")
    assert point["measurement"] is None
    assert point["measurement_method"] is None


def test_pagination_and_geometry_filter(client, upload, sample_kml):
    points = kml_document(*(point_placemark(f"p{i}", 80 + i / 1000) for i in range(25)))
    file_id = upload(client, "points.kml", points).json()["id"]

    page = client.get(f"/api/files/{file_id}/measurements/?page=3&page_size=10").json()
    assert (page["page"], page["page_size"], page["total"], len(page["items"])) == (3, 10, 25, 5)
    assert page["items"][0]["feature_index"] == 20

    sample_id = upload(client, "sample.kml", sample_kml).json()["id"]
    polygons = client.get(f"/api/files/{sample_id}/measurements/?geometry_type=Polygon").json()
    assert polygons["total"] == 2
    assert {item["geometry_type"] for item in polygons["items"]} == {"Polygon"}


def test_invalid_pagination_and_filter_are_rejected(client, upload, sample_kml):
    file_id = upload(client, "sample.kml", sample_kml).json()["id"]
    for query in ("page=0", "page_size=0", "page_size=101", "geometry_type=Hexagon"):
        response = client.get(f"/api/files/{file_id}/measurements/?{query}")
        assert response.status_code == 400, query
        assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_unknown_file_id_returns_structured_404(client):
    for path in ("", "/measurements/", "/summary/", "/geojson"):
        response = client.get(f"/api/files/does-not-exist{path}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "FILE_NOT_FOUND"


def test_geojson_export_is_wgs84(client, upload, sample_shapefile):
    file_id = upload(client, "parcels.zip", sample_shapefile).json()["id"]
    response = client.get(f"/api/files/{file_id}/geojson")
    assert response.status_code == 200
    first = response.json()["features"][0]
    lon, lat = first["geometry"]["coordinates"][0][0]
    assert 79.0 < lon < 81.0 and 12.0 < lat < 14.0
