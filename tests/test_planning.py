import pytest

from routelab.airports import AirportDB
from routelab.fuel import FuelPolicy
from routelab.performance import ProxyAircraft
from routelab.planning import DEFAULT_ALTERNATE_DISTANCE_KM, plan_leg


@pytest.fixture()
def db() -> AirportDB:
    return AirportDB()


def test_plan_leg_with_alternate(db: AirportDB):
    plan = plan_leg(db, ProxyAircraft(), "ZSPD", "ZWWW", "ZWSH", payload_kg=15_000)
    assert plan.route.origin == "ZSPD"
    assert plan.route.destination == "ZWWW"
    assert plan.route.distance_km == pytest.approx(3300, rel=0.05)
    assert plan.alternate_distance_km == pytest.approx(1060, rel=0.05)
    assert plan.alternate_note == "to ZWSH"
    assert plan.fuel.trip_kg > 0
    assert plan.fuel.block_kg > plan.fuel.trip_kg
    assert plan.feasible
    assert 0 < plan.max_payload_on_leg_kg <= ProxyAircraft().max_payload_kg


def test_plan_leg_without_alternate_uses_default_distance(db: AirportDB):
    plan = plan_leg(db, ProxyAircraft(), "ZSPD", "ZWWW")
    assert plan.alternate_distance_km == DEFAULT_ALTERNATE_DISTANCE_KM
    assert "300 km diversion" in plan.alternate_note


def test_plan_leg_infeasible_when_payload_and_fuel_exceed_limits(db: AirportDB):
    heavy = ProxyAircraft(max_payload_kg=20_000)
    # Shanghai -> Paris is far beyond the proxy's legs at near-max payload
    plan = plan_leg(db, heavy, "ZSPD", "LFPG", payload_kg=heavy.max_payload_kg)
    assert not plan.feasible


def test_plan_leg_headwind_increases_fuel(db: AirportDB):
    ac = ProxyAircraft()
    calm = plan_leg(db, ac, "ZSPD", "ZBAA")
    windy = plan_leg(db, ac, "ZSPD", "ZBAA", headwind_kmh=100)
    assert windy.fuel.trip_kg > calm.fuel.trip_kg
    assert windy.trip_time_h > calm.trip_time_h


def test_plan_leg_respects_policy(db: AirportDB):
    fat = FuelPolicy(contingency_frac=0.1, taxi_kg=300)
    plan = plan_leg(db, ProxyAircraft(), "ZSPD", "ZBAA", policy=fat)
    assert plan.fuel.taxi_kg == 300
    assert plan.fuel.contingency_kg == pytest.approx(0.1 * plan.fuel.trip_kg)
