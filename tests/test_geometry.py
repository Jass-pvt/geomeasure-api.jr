from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
    box,
)

from app.services.geometry import geometry_type_name, validate_geometries

BOW_TIE = Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)])
COLLINEAR = Polygon([(0, 0), (1, 1), (2, 2), (0, 0)])


def test_valid_geometries_are_untouched():
    geometries = [
        box(0, 0, 1, 1),
        MultiPolygon([box(0, 0, 1, 1), box(3, 3, 4, 4)]),
        LineString([(0, 0), (1, 1)]),
        MultiLineString([[(0, 0), (1, 1)], [(2, 2), (3, 3)]]),
        Point(1, 1),
        MultiPoint([(0, 0), (1, 1)]),
    ]
    fixed, reports = validate_geometries(geometries)
    assert all(r.valid and not r.repaired and r.usable for r in reports)
    assert all(a is b for a, b in zip(fixed, geometries, strict=True))


def test_self_intersecting_polygon_is_repaired():
    fixed, reports = validate_geometries([BOW_TIE])
    assert not reports[0].valid
    assert reports[0].repaired and reports[0].usable
    assert fixed[0].is_valid
    assert fixed[0].geom_type in {"Polygon", "MultiPolygon"}
    assert fixed[0].area == 2.0


def test_unrepairable_polygon_is_flagged_without_raising():
    fixed, reports = validate_geometries([COLLINEAR])
    assert not reports[0].usable
    assert reports[0].error


def test_missing_and_empty_geometries_are_unusable():
    _, reports = validate_geometries([None, Polygon()])
    assert [r.usable for r in reports] == [False, False]
    assert "no geometry" in reports[0].error
    assert "empty" in reports[1].error


def test_one_bad_feature_does_not_affect_others():
    _, reports = validate_geometries([box(0, 0, 1, 1), COLLINEAR, LineString([(0, 0), (1, 0)])])
    assert [r.usable for r in reports] == [True, False, True]


def test_geometry_type_name():
    assert geometry_type_name(Point(0, 0)) == "Point"
    assert geometry_type_name(None) == "Unknown"
