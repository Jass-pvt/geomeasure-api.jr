import geopandas as gpd
import pytest
from pyproj import CRS
from shapely.geometry import Point, box

from app.core.exceptions import MeasurementError, MissingCRSError, UnsupportedCRSError
from app.services.crs import (
    estimate_measurement_crs,
    metres_per_unit,
    transform_to_measurement_crs,
    utm_epsg_for,
)

CHENNAI = (80.27, 13.08)
SYDNEY = (151.21, -33.87)
LONDON = (-0.12, 51.50)


def frame_at(lon: float, lat: float, crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=[box(lon, lat, lon + 0.01, lat + 0.01)], crs=crs)


@pytest.mark.parametrize(
    ("lon", "lat", "expected"),
    [
        (*CHENNAI, 32644),
        (*SYDNEY, 32756),
        (*LONDON, 32630),
        (-179.9, 10, 32601),
        (180.0, 10, 32660),
    ],
)
def test_utm_epsg_selection(lon, lat, expected):
    assert utm_epsg_for(lon, lat) == expected


@pytest.mark.parametrize(("lon", "lat"), [CHENNAI, SYDNEY, LONDON])
def test_utm_selection_agrees_with_geopandas(lon, lat):
    frame = frame_at(lon, lat)
    ours = estimate_measurement_crs(frame).crs.to_epsg()
    assert ours == frame.estimate_utm_crs().to_epsg()


def test_geographic_source_gets_projected_measurement_crs():
    choice = estimate_measurement_crs(frame_at(*CHENNAI))
    assert choice.crs.is_projected and not choice.crs.is_geographic
    assert choice.label != "EPSG:4326"
    assert choice.requires_transform
    assert choice.label == "EPSG:32644"


def test_southern_hemisphere_uses_327xx():
    assert estimate_measurement_crs(frame_at(*SYDNEY)).label == "EPSG:32756"


def test_selection_is_driven_by_data_not_hardcoded():
    labels = {estimate_measurement_crs(frame_at(*p)).label for p in (CHENNAI, SYDNEY, LONDON)}
    assert len(labels) == 3


def test_metric_projected_source_is_kept():
    choice = estimate_measurement_crs(frame_at(420800, 1447000, "EPSG:32644"))
    assert choice.label == "EPSG:32644"
    assert not choice.requires_transform
    assert choice.unit_factor == 1.0


def test_web_mercator_is_not_used_for_measurement():
    frame = frame_at(80.27, 13.08).to_crs("EPSG:3857")
    choice = estimate_measurement_crs(frame)
    assert choice.label == "EPSG:32644"
    assert choice.requires_transform


def test_feet_based_crs_reports_conversion_factor():
    assert metres_per_unit(CRS.from_epsg(2263)) == pytest.approx(0.3048006096)
    frame = gpd.GeoDataFrame(geometry=[Point(1_000_000, 200_000)], crs="EPSG:2263")
    choice = estimate_measurement_crs(frame)
    assert choice.unit_factor == pytest.approx(0.3048006096)
    assert not choice.requires_transform


def test_missing_crs_is_an_error():
    frame = gpd.GeoDataFrame(geometry=[Point(0, 0)])
    with pytest.raises(MissingCRSError):
        estimate_measurement_crs(frame)


def test_polar_data_is_rejected_clearly():
    with pytest.raises(MeasurementError):
        utm_epsg_for(10.0, 88.0)


def test_out_of_range_coordinates_are_rejected():
    with pytest.raises(UnsupportedCRSError):
        utm_epsg_for(200.0, 10.0)


def test_multi_zone_dataset_gets_a_warning_note():
    frame = gpd.GeoDataFrame(geometry=[box(70, 10, 90, 12)], crs="EPSG:4326")
    assert estimate_measurement_crs(frame).notes


def test_transformation_changes_coordinates_to_metres():
    frame = frame_at(*CHENNAI)
    choice = estimate_measurement_crs(frame)
    planar = transform_to_measurement_crs(frame, choice)
    assert planar.crs.to_epsg() == 32644
    assert planar.total_bounds[0] > 100_000


def test_no_transform_returns_same_object():
    frame = frame_at(420800, 1447000, "EPSG:32644")
    assert transform_to_measurement_crs(frame, estimate_measurement_crs(frame)) is frame
