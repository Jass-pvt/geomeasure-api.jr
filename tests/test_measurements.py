import pytest
from pyproj import CRS, Geod
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    box,
)

from app.core.exceptions import MeasurementError
from app.services.crs import MeasurementCRS
from app.services.measurement import measure_geometry
from tests.conftest import kml_document, polygon_placemark


def metric(epsg: int = 32644, factor: float = 1.0) -> MeasurementCRS:
    crs = CRS.from_epsg(epsg)
    return MeasurementCRS(crs, f"EPSG:{epsg}", crs.name, "source_projected_crs", factor, False)


def test_polygon_area():
    raw = measure_geometry(box(0, 0, 100, 200), metric())
    assert raw.type.value == "area"
    assert raw.value == 20000.0
    assert raw.to_schema().unit == "m²"


def test_multipolygon_area_is_summed():
    geometry = MultiPolygon([box(0, 0, 10, 10), box(20, 20, 25, 25)])
    assert measure_geometry(geometry, metric()).value == 125.0


def test_linestring_length_uses_pythagoras():
    raw = measure_geometry(LineString([(0, 0), (3, 4)]), metric())
    assert raw.type.value == "length"
    assert raw.value == 5.0
    assert raw.to_schema().unit == "m"


def test_multilinestring_length_is_summed():
    geometry = MultiLineString([[(0, 0), (3, 4)], [(0, 0), (0, 10)]])
    assert measure_geometry(geometry, metric()).value == 15.0


@pytest.mark.parametrize("geometry", [Point(1, 1), MultiPoint([(0, 0), (1, 1)])])
def test_points_have_no_measurement(geometry):
    assert measure_geometry(geometry, metric()) is None


def test_unsupported_geometry_raises_measurement_error():
    with pytest.raises(MeasurementError):
        measure_geometry(GeometryCollection([Point(0, 0)]), metric())


def test_non_metric_units_are_converted_to_metres():
    feet = metric(epsg=2263, factor=0.3048006096)
    assert measure_geometry(LineString([(0, 0), (100, 0)]), feet).value == pytest.approx(30.48006)
    assert measure_geometry(box(0, 0, 100, 100), feet).value == pytest.approx(929.0341, rel=1e-6)


def test_measuring_in_degrees_is_refused():
    geographic = MeasurementCRS(
        CRS.from_epsg(4326), "EPSG:4326", "WGS 84", "projected_crs", 1.0, False
    )
    with pytest.raises(MeasurementError):
        measure_geometry(box(0, 0, 1, 1), geographic)


def test_presentation_rounding_does_not_alter_raw_value():
    raw = measure_geometry(box(0, 0, 1.00123, 1.00123), metric())
    assert raw.value != round(raw.value, 2)
    assert raw.to_schema().value == round(raw.value, 2)


def test_geographic_polygon_area_matches_geodesic_area(client, upload):
    """Area from the API (UTM) must be close to the true ellipsoidal area, not degrees²."""
    response = upload(client, "square.kml", kml_document(polygon_placemark("sq")))
    file_id = response.json()["id"]
    item = client.get(f"/api/files/{file_id}/measurements/").json()["items"][0]

    lon0, lat0, lon1, lat1 = 80.0, 13.0, 80.01, 13.01
    geodesic, _ = Geod(ellps="WGS84").polygon_area_perimeter(
        [lon0, lon1, lon1, lon0], [lat0, lat0, lat1, lat1]
    )
    assert item["measurement"]["value"] == pytest.approx(abs(geodesic), rel=2e-3)
    assert item["measurement"]["value"] > 1_000_000
    assert box(lon0, lat0, lon1, lat1).area == pytest.approx(1e-4)  # raw degrees², meaningless


def test_api_proves_measurement_crs_is_projected_not_geographic(client, upload, sample_kml):
    body = upload(client, "sample.kml", sample_kml).json()
    assert body["source_crs"] != body["measurement_crs"]
    assert CRS.from_user_input(body["source_crs"]).is_geographic
    measurement_crs = CRS.from_user_input(body["measurement_crs"])
    assert measurement_crs.is_projected
    assert not measurement_crs.is_geographic
