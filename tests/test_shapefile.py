import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, Polygon

from tests.conftest import zip_bytes

UTM44 = "EPSG:32644"
SQUARE = Polygon([(420800, 1447000), (420900, 1447000), (420900, 1447200), (420800, 1447200)])


def utm_frame() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"name": ["parcel"]},
        geometry=[SQUARE],
        crs=UTM44,
    )


def test_sample_shapefile_known_areas(client, upload, sample_shapefile):
    file_id = upload(client, "parcels.zip", sample_shapefile).json()["id"]
    items = client.get(f"/api/files/{file_id}/measurements/").json()["items"]
    assert [item["measurement"]["value"] for item in items] == [20000.0, 4000.0, 36000.0]
    assert items[0]["measurement_method"]["method"] == "source_projected_crs"
    assert items[0]["properties"]["NAME"].strip() == "Plot 1"
    summary = client.get(f"/api/files/{file_id}/summary/").json()
    assert summary["measurements"]["total_area_m2"] == 60000.0


def test_generated_shapefile_projected_source_is_used_as_is(client, upload, shapefile_zip):
    response = upload(client, "layer.zip", shapefile_zip(utm_frame()))
    file_id = response.json()["id"]
    item = client.get(f"/api/files/{file_id}/measurements/").json()["items"][0]
    assert item["measurement"] == {"type": "area", "value": 20000.0, "unit": "m²"}


def test_geographic_shapefile_is_reprojected(client, upload, shapefile_zip):
    frame = utm_frame().to_crs("EPSG:4326")
    file_id = upload(client, "geo.zip", shapefile_zip(frame)).json()["id"]
    info = client.get(f"/api/files/{file_id}").json()
    assert info["source_crs"] == "EPSG:4326"
    assert info["measurement_crs"] == "EPSG:32644"
    item = client.get(f"/api/files/{file_id}/measurements/").json()["items"][0]
    assert item["measurement"]["value"] == pytest.approx(20000.0, rel=1e-3)


def test_line_shapefile_length(client, upload, shapefile_zip):
    frame = gpd.GeoDataFrame(
        {"id": [1]}, geometry=[LineString([(420800, 1447000), (420830, 1447040)])], crs=UTM44
    )
    file_id = upload(client, "lines.zip", shapefile_zip(frame)).json()["id"]
    item = client.get(f"/api/files/{file_id}/measurements/").json()["items"][0]
    assert item["measurement"] == {"type": "length", "value": 50.0, "unit": "m"}


def test_point_shapefile_has_no_measurement(client, upload, shapefile_zip):
    frame = gpd.GeoDataFrame({"id": [1]}, geometry=[Point(420800, 1447000)], crs=UTM44)
    file_id = upload(client, "points.zip", shapefile_zip(frame)).json()["id"]
    item = client.get(f"/api/files/{file_id}/measurements/").json()["items"][0]
    assert item["measurement"] is None
    assert item["status"] == "SUCCESS"


def test_missing_prj_is_rejected_with_missing_crs(client, upload, shapefile_zip):
    response = upload(client, "nocrs.zip", shapefile_zip(utm_frame(), drop=(".prj",)))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MISSING_CRS"


@pytest.mark.parametrize("missing", [".shp", ".shx", ".dbf"])
def test_missing_required_component_is_rejected(client, upload, shapefile_zip, missing):
    response = upload(client, "partial.zip", shapefile_zip(utm_frame(), drop=(missing,)))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MISSING_SHAPEFILE_COMPONENT"


def test_zip_with_two_shapefiles_is_rejected(client, upload):
    entries = {f"{stem}{ext}": b"x" for stem in ("a", "b") for ext in (".shp", ".shx", ".dbf")}
    response = upload(client, "two.zip", zip_bytes(entries))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_ARCHIVE"


def test_corrupt_shapefile_content_is_a_parse_error(client, upload):
    entries = {"x.shp": b"junk", "x.shx": b"junk", "x.dbf": b"junk", "x.prj": b"junk"}
    response = upload(client, "corrupt.zip", zip_bytes(entries))
    assert response.status_code == 422
    assert response.json()["error"]["code"] in {"GEOSPATIAL_PARSE_ERROR", "MISSING_CRS"}
