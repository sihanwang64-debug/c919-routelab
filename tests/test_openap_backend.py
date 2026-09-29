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


def test_integrator_matches_stepwise_euler_reference() -> None:
    # fine-step Euler reference (30 s) vs the cached grid integral: the two
    # must agree within 1 % on both range and trip fuel

    openap = ob._openap()
    ff = ob._fuelflow("a320")
    tas = float(openap.aero.mach2tas(0.78, 35000 * 0.3048))  # m/s

    m0, fuel_budget = 71_600.0, 12_000.0
    mass, fuel_left, dist_m = m0, fuel_budget, 0.0
    while fuel_left > 0:
        flow = float(ff.enroute(mass=mass, tas=tas, alt=35000 * 0.3048))
        step = min(30.0 * flow, fuel_left)
        mass -= step
        fuel_left -= step
        dist_m += tas * 30.0
    reference_km = dist_m / 1000.0

    modelled_km = float(ob.integrate_cruise("a320", m0, fuel_budget).distance_km)
    assert modelled_km == pytest.approx(reference_km, rel=0.01)

    # inverse problem: fuel for a given distance matches the same reference
    fuel_back = ob.trip_fuel_openap("a320", m0, reference_km)
    assert fuel_back == pytest.approx(fuel_budget, rel=0.01)


def test_fueflow_and_integrator_instances_are_cached() -> None:
    ob.payload_range_table_openap(
        "a320", max_payload_kg=18_500, tank_capacity_kg=19_000, step_kg=2_000
    )
    n_ff = len(ob._FUELFLOW_CACHE)
    n_int = len(ob._INTEGRATOR_CACHE)
    ob.payload_range_table_openap(
        "a320", max_payload_kg=18_500, tank_capacity_kg=19_000, step_kg=2_000
    )
    ob.trip_fuel_openap("a320", 71_600, 3_312)
    assert len(ob._FUELFLOW_CACHE) == n_ff      # no re-construction
    assert len(ob._INTEGRATOR_CACHE) == n_int   # grid integral reused


def test_headwind_reduces_range_but_not_burn_time() -> None:
    calm = ob.integrate_cruise("a320", 71_600, 10_000)
    windy = ob.integrate_cruise("a320", 71_600, 10_000, headwind_kmh=90)
    assert windy.distance_km < calm.distance_km
    assert windy.time_h == pytest.approx(calm.time_h, rel=0.02)  # same air time
