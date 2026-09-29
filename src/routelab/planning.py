"""Leg planning: one route, one aircraft, one fuel policy -> a full leg report.

Shared by the CLI (``routelab range``) and the Streamlit app so both always
tell the same story.
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
