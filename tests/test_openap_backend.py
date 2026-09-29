"""OpenAP backend tests: integration math, presets wiring, and API surface.

Skipped entirely when the optional ``openap`` package is not installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("openap", reason="openap [perf] extra not installed")

from routelab import openap_backend as ob  # noqa: E402
from routelab.airports import AirportDB  # noqa: E402
from routelab.performance import ProxyAircraft, trip_fuel_kg  # noqa: E402
from routelab.planning import plan_leg  # noqa: E402


@pytest.fixture(scope="module")
def a320_limits() -> tuple[float, float]:
    return ob.aircraft_mass_limits("a320")


def test_supported_aircraft_contains_common_narrowbodies() -> None:
    types = ob.supported_aircraft()
    assert "a320" in types and "b738" in types
    assert all(t == t.lower() for t in types)


def test_mass_limits_plausible(a320_limits: tuple[float, float]) -> None:
    mtow, oew = a320_limits
    assert 70_000 < mtow < 90_000
    assert 38_000 < oew < 48_000
    assert oew < mtow


def test_fuel_flow_increases_with_mass() -> None:
    light = ob._fuel_flow_kg_per_s("a320", 60_000, 35_000, 0.78)
    heavy = ob._fuel_flow_kg_per_s("a320", 78_000, 35_000, 0.78)
    assert light > 0
    assert heavy > light


def test_trip_fuel_plausible_and_heavier_than_simple_model() -> None:
    # ZSPD -> ZWWW is 3,312 km; simple constant-flow model says 9,606 kg
    simple = trip_fuel_kg(ProxyAircraft(), 3312.0)
    openap_trip = ob.trip_fuel_openap("a320", 71_600, 3312.0)
    assert 7_000 < openap_trip < 13_000
    assert openap_trip == pytest.approx(simple, rel=0.35)


def test_range_grows_when_fuel_grows() -> None:
    r1 = ob.range_openap("a320", 42_600 + 10_000 + 10_000, 10_000)
    r2 = ob.range_openap("a320", 42_600 + 10_000 + 15_000, 15_000)
    assert r2 > r1 > 0


def test_openap_envelope_monotonic() -> None:
    rows = ob.payload_range_table_openap(
        "a320", max_payload_kg=18_500, tank_capacity_kg=19_000, step_kg=2_000
    )
    ranges = [r["max_range_km"] for r in rows]
    assert all(b >= a - 1e-6 for a, b in zip(ranges, ranges[1:]))
    assert ranges[-1] > ranges[0]


def test_plan_leg_openap_matches_simple_order_and_feasible() -> None:
    db = AirportDB()
    plan = plan_leg(db, ProxyAircraft(), "ZSPD", "ZWWW", "ZWSH", 15_000,
                    backend="openap", actype="a320")
    simple = plan_leg(db, ProxyAircraft(), "ZSPD", "ZWWW", "ZWSH", 15_000)
    assert plan.backend == "openap" and plan.actype == "a320"
    assert plan.route.distance_km == pytest.approx(simple.route.distance_km)
    assert 0.6 < plan.fuel.trip_kg / simple.fuel.trip_kg < 1.6
    assert plan.fuel.block_kg > plan.fuel.trip_kg
    assert plan.feasible
    # reserve + alternate physics: block strictly above trip
    assert plan.fuel.alternate_kg > 0 and plan.fuel.final_reserve_kg > 0


def test_plan_leg_openap_requires_actype() -> None:
    db = AirportDB()
    with pytest.raises(ValueError, match="actype"):
        plan_leg(db, ProxyAircraft(), "ZSPD", "ZWWW", backend="openap")


def test_plan_leg_unknown_backend_rejected() -> None:
    db = AirportDB()
    with pytest.raises(ValueError, match="unknown backend"):
        plan_leg(db, ProxyAircraft(), "ZSPD", "ZWWW", backend="magic")
