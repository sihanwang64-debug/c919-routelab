"""Leg planning: one route, one aircraft, one fuel policy -> a full leg report.

Shared by the CLI (``routelab range``) and the web backends so every entry
point tells the same story. Two burn models are available:

- ``backend="simple"`` (default): constant cruise fuel flow, the
  learning-grade model in :mod:`routelab.performance`;
- ``backend="openap"``: mass-dependent cruise burn integrated with OpenAP
  (optional dependency), weight limits (MTOW/OEW) taken from OpenAP's
  aircraft database; tank capacity and payload cap stay from the preset
  aircraft. The leg fuel is solved by fixed-point iteration because the
  burn depends on the mass that includes the burn itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from routelab.airports import AirportDB
from routelab.fuel import BlockFuelBreakdown, FuelPolicy, block_fuel
from routelab.greatcircle import Route
from routelab.performance import ProxyAircraft, trip_fuel_kg, trip_time_h

DEFAULT_ALTERNATE_DISTANCE_KM = 300.0


@dataclass(frozen=True)
class LegPlan:
    """Everything a leg report needs, computed once."""

    route: Route
    alternate_distance_km: float
    alternate_note: str
    trip_time_h: float
    fuel: BlockFuelBreakdown
    payload_kg: float
    fuel_limit_kg: float
    max_payload_on_leg_kg: float
    backend: str = "simple"
    actype: str | None = None

    @property
    def feasible(self) -> bool:
        return self.fuel.block_kg <= self.fuel_limit_kg


def plan_leg(
    db: AirportDB,
    ac: ProxyAircraft,
    origin: str,
    destination: str,
    alternate: str = "",
    payload_kg: float = 15_000.0,
    headwind_kmh: float = 0.0,
    policy: FuelPolicy | None = None,
    backend: str = "simple",
    actype: str | None = None,
) -> LegPlan:
    """Plan one leg: route, block fuel breakdown, weight/tank feasibility.

    ``alternate`` is optional; without it a fixed default diversion distance
    is assumed (learning-grade convention used by the CLI as well).
    """
    policy = policy or FuelPolicy()
    route = db.route(origin, destination)
    if alternate:
        diversion = db.route(destination, alternate)
        alternate_distance_km = diversion.distance_km
        alternate_note = f"to {diversion.destination}"
    else:
        alternate_distance_km = DEFAULT_ALTERNATE_DISTANCE_KM
        alternate_note = f"{DEFAULT_ALTERNATE_DISTANCE_KM:.0f} km diversion"

    if backend == "openap":
        plan = _plan_leg_openap(
            ac, route, alternate_distance_km, alternate_note, payload_kg,
            headwind_kmh, policy, actype,
        )
    elif backend == "simple":
        plan = _plan_leg_simple(
            ac, route, alternate_distance_km, alternate_note, payload_kg,
            headwind_kmh, policy,
        )
    else:
        raise ValueError(f"unknown backend {backend!r} (use 'simple' or 'openap')")
    return plan


def _plan_leg_simple(
    ac: ProxyAircraft,
    route: Route,
    alternate_distance_km: float,
    alternate_note: str,
    payload_kg: float,
    headwind_kmh: float,
    policy: FuelPolicy,
) -> LegPlan:
    trip = trip_fuel_kg(ac, route.distance_km, headwind_kmh)
    fuel = block_fuel(ac, trip, alternate_distance_km, policy)
    fuel_limit_kg = min(ac.max_fuel_kg, ac.max_usable_weight_kg - payload_kg)
    max_payload = min(
        ac.max_payload_kg, max(0.0, ac.max_usable_weight_kg - fuel.block_kg)
    )
    return LegPlan(
        route=route,
        alternate_distance_km=alternate_distance_km,
        alternate_note=alternate_note,
        trip_time_h=trip_time_h(ac, route.distance_km, headwind_kmh),
        fuel=fuel,
        payload_kg=payload_kg,
        fuel_limit_kg=fuel_limit_kg,
        max_payload_on_leg_kg=max_payload,
    )


def _plan_leg_openap(
    ac: ProxyAircraft,
    route: Route,
    alternate_distance_km: float,
    alternate_note: str,
    payload_kg: float,
    headwind_kmh: float,
    policy: FuelPolicy,
    actype: str | None,
) -> LegPlan:
    if not actype:
        raise ValueError("backend 'openap' needs 'actype', e.g. 'a320'")
    from routelab import openap_backend as ob

    mtow_kg, oew_kg = ob.aircraft_mass_limits(actype)
    max_payload_cap = ac.max_payload_kg
    tank_capacity = ac.max_fuel_kg

    # fixed-point iteration: block fuel contains the trip fuel, the trip
    # burn depends on the mass that includes the block fuel. Three passes
    # converge well below a kilogram.
    block_kg = 8_000.0  # first guess, order of magnitude for a narrow-body leg
    trip_kg = alternate_kg = final_reserve_kg = 0.0
    for _ in range(4):
        mass0 = oew_kg + payload_kg + block_kg
        trip_res = ob.integrate_cruise(
            actype, mass0, fuel_available_kg=mass0,
            distance_limit_km=route.distance_km, headwind_kmh=headwind_kmh,
        )
        trip_kg = trip_res.fuel_kg
        trip_time = trip_res.time_h + ob.CLIMB_DESCENT_H
        mass1 = mass0 - trip_kg
        alternate_kg = (
            ob.trip_fuel_openap(actype, mass1, alternate_distance_km)
            + policy.approach_allowance_kg
        )
        mass2 = mass1 - alternate_kg
        final_reserve_kg = (
            ob._fuel_flow_kg_per_s(actype, mass2, ob.DEFAULT_CRUISE_ALT_FT, ob.DEFAULT_MACH)
            * policy.final_reserve_min
            * 60.0
        )
        block_kg = (
            trip_kg + policy.contingency_frac * trip_kg + alternate_kg
            + final_reserve_kg + policy.taxi_kg
        )

    fuel = BlockFuelBreakdown(
        trip_kg=trip_kg,
        contingency_kg=policy.contingency_frac * trip_kg,
        alternate_kg=alternate_kg,
        final_reserve_kg=final_reserve_kg,
        taxi_kg=policy.taxi_kg,
    )
    fuel_limit_kg = min(tank_capacity, mtow_kg - oew_kg - payload_kg)
    max_payload = min(max_payload_cap, max(0.0, mtow_kg - oew_kg - fuel.block_kg))
    return LegPlan(
        route=route,
        alternate_distance_km=alternate_distance_km,
        alternate_note=alternate_note,
        trip_time_h=trip_time,
        fuel=fuel,
        payload_kg=payload_kg,
        fuel_limit_kg=fuel_limit_kg,
        max_payload_on_leg_kg=max_payload,
        backend="openap",
        actype=actype,
    )
