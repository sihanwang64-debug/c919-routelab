import pytest

from routelab.performance import (
    ProxyAircraft,
    max_range_km,
    payload_range_table,
    takeoff_field_length_m,
    trip_fuel_kg,
    trip_time_h,
    usable_fuel_at_payload,
)

AC = ProxyAircraft()


def test_trip_time_includes_climb_allowance():
    # one hour of cruise at exactly TAS 833 km/h + 0.2 h allowance
    assert trip_time_h(AC, 833.0) == pytest.approx(1.2)


def test_trip_fuel_is_constant_flow_times_time():
    assert trip_fuel_kg(AC, 833.0) == pytest.approx(AC.cruise_fuel_kg_per_h * 1.2)


def test_payload_range_monotonic():
    # table runs payload from max structural down to zero, so range is non-decreasing
    df = payload_range_table(AC, step_kg=1000.0)
    ranges = df["max_range_km"].to_list()
    assert all(b >= a - 1e-9 for a, b in zip(ranges, ranges[1:]))
    assert ranges[-1] > ranges[0]


def test_mtow_limited_segment_shape():
    # at max structural payload the fuel is limited by MTOW, not tank capacity
    assert usable_fuel_at_payload(AC, AC.max_payload_kg) < AC.max_fuel_kg
    assert usable_fuel_at_payload(AC, 0.0) == pytest.approx(AC.max_fuel_kg)
    # and range at zero payload is the (largest) full-tank range
    assert max_range_km(AC, 0.0) == pytest.approx(
        (AC.max_fuel_kg / AC.cruise_fuel_kg_per_h - AC.climb_descent_extra_h)
        * AC.cruise_tas_kmh
    )


def test_field_length_worse_hot_and_high():
    sea_level = takeoff_field_length_m(0.0, 0.0, 0.0)
    assert takeoff_field_length_m(4000.0, 0.0, 0.0) > sea_level
    assert takeoff_field_length_m(0.0, 15.0, 0.0) > sea_level
    assert takeoff_field_length_m(0.0, 0.0, 10.0) < sea_level


def test_negative_payload_rejected():
    with pytest.raises(ValueError):
        usable_fuel_at_payload(AC, -1.0)
