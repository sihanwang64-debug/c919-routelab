import pytest

from routelab.fuel import FuelPolicy, block_fuel
from routelab.performance import ProxyAircraft

AC = ProxyAircraft()


def test_block_fuel_itemisation():
    policy = FuelPolicy(
        taxi_kg=100.0,
        contingency_frac=0.10,
        approach_allowance_kg=0.0,
        final_reserve_min=60.0,
    )
    breakdown = block_fuel(AC, trip_kg=1000.0, alternate_distance_km=230.0, policy=policy)
    assert breakdown.contingency_kg == pytest.approx(100.0)
    assert breakdown.alternate_kg == pytest.approx(
        AC.cruise_fuel_kg_per_h * (230.0 / AC.cruise_tas_kmh + AC.climb_descent_extra_h)
    )
    assert breakdown.final_reserve_kg == pytest.approx(AC.cruise_fuel_kg_per_h)
    assert breakdown.block_kg == pytest.approx(
        breakdown.trip_kg
        + breakdown.contingency_kg
        + breakdown.alternate_kg
        + breakdown.final_reserve_kg
        + breakdown.taxi_kg
    )


def test_default_policy_block_beats_trip():
    breakdown = block_fuel(AC, trip_kg=9000.0, alternate_distance_km=300.0)
    assert breakdown.block_kg > breakdown.trip_kg
