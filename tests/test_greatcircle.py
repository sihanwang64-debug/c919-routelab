import math

import pytest

from routelab.greatcircle import (
    EARTH_RADIUS_KM,
    haversine_distance_km,
    initial_bearing_deg,
)


def test_quarter_circumference_along_equator():
    d = haversine_distance_km(0.0, 0.0, 0.0, 90.0)
    assert d == pytest.approx(math.pi / 2.0 * EARTH_RADIUS_KM, rel=1e-9)


def test_quarter_circumference_along_meridian():
    d = haversine_distance_km(0.0, 0.0, 90.0, 0.0)
    assert d == pytest.approx(math.pi / 2.0 * EARTH_RADIUS_KM, rel=1e-9)


def test_bearing_east():
    assert initial_bearing_deg(0.0, 0.0, 0.0, 10.0) == pytest.approx(90.0, abs=1e-9)


def test_bearing_north():
    assert initial_bearing_deg(0.0, 0.0, 10.0, 0.0) == pytest.approx(0.0, abs=1e-9)


def test_distance_symmetric():
    assert haversine_distance_km(31.0, 121.0, 43.0, 87.0) == pytest.approx(
        haversine_distance_km(43.0, 87.0, 31.0, 121.0), rel=1e-12
    )
