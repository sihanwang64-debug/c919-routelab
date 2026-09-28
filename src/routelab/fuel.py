"""Block-fuel policy -- a documented, learning-grade simplification.

Reference frame: CCAR-121 / ICAO Annex 6 style fuel planning
(taxi + trip + contingency + alternate + final reserve), deliberately
simplified:

- contingency: 5 % of trip fuel (a typical planning value, not a rule);
- alternate: trip fuel for the alternate leg plus a fixed approach allowance;
- final reserve: 30 min holding at cruise fuel flow (the ICAO turbine-hold
  convention; CCAR-121 for domestic operations instead cites 45 min at normal
  cruise consumption -- adjust via ``final_reserve_min`` and note that neither
  choice is authoritative here);
- taxi: fixed allowance.

Nothing here is certified or even conservative -- see DISCLAIMER.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from routelab.performance import ProxyAircraft, trip_fuel_kg


@dataclass(frozen=True)
class FuelPolicy:
    """Simplified fuel-planning parameters."""

    taxi_kg: float = 200.0
    contingency_frac: float = 0.05
    approach_allowance_kg: float = 200.0
    final_reserve_min: float = 30.0


@dataclass(frozen=True)
class BlockFuelBreakdown:
    """Itemised block fuel, ready for a report table."""

    trip_kg: float
    contingency_kg: float
    alternate_kg: float
    final_reserve_kg: float
    taxi_kg: float

    @property
    def block_kg(self) -> float:
        return (
            self.trip_kg
            + self.contingency_kg
            + self.alternate_kg
            + self.final_reserve_kg
            + self.taxi_kg
        )


def alternate_fuel_kg(
    ac: ProxyAircraft,
    alternate_distance_km: float,
    policy: FuelPolicy,
) -> float:
    """Fuel for the diversion leg + a fixed approach allowance."""
    return trip_fuel_kg(ac, alternate_distance_km) + policy.approach_allowance_kg


def block_fuel(
    ac: ProxyAircraft,
    trip_kg: float,
    alternate_distance_km: float,
    policy: FuelPolicy | None = None,
) -> BlockFuelBreakdown:
    """Build the itemised block fuel from a known trip-fuel figure."""
    policy = policy or FuelPolicy()
    return BlockFuelBreakdown(
        trip_kg=trip_kg,
        contingency_kg=policy.contingency_frac * trip_kg,
        alternate_kg=alternate_fuel_kg(ac, alternate_distance_km, policy),
        final_reserve_kg=ac.cruise_fuel_kg_per_h * policy.final_reserve_min / 60.0,
        taxi_kg=policy.taxi_kg,
    )
