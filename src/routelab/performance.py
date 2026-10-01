"""Learning-grade cruise and field performance for a narrow-body proxy aircraft.

Honesty note
------------
COMAC does not publish open performance data for the C919, so this module
models a *proxy aircraft in the same class* (A320neo-class: ~170 seats,
LEAP-1-class engines), with parameters assembled from publicly available
aircraft specifications. Cruise fuel flow is treated as constant: weight,
altitude, temperature, winds aloft and step-climb effects are ignored, and
climb/descent are folded into a fixed time allowance. Outputs are for
education and portfolio demonstration only -- never for flight planning or
engineering work. Integrating the research-grade OpenAP A320neo model as an
optional backend is on the roadmap (see docs/methodology.md).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ProxyAircraft:
    """A320neo-class proxy parameters (approximate, public specifications)."""

    name: str = "A320neo-class proxy (C919 stand-in)"
    seats: int = 174
    mtow_kg: float = 79_000.0
    oew_kg: float = 44_300.0
    max_fuel_kg: float = 19_000.0
    max_payload_kg: float = 18_500.0
    mlw_kg: float = 66_000.0    # max landing weight (approximate, A320-class)
    mzfw_kg: float = 62_500.0   # max zero-fuel weight (approximate, A320-class)
    cruise_tas_kmh: float = 833.0  # ~M0.78 at FL350
    cruise_fuel_kg_per_h: float = 2_300.0
    climb_descent_extra_h: float = 0.2  # combined climb + descent time allowance

    @property
    def max_usable_weight_kg(self) -> float:
        """MTOW - OEW: everything you can split between payload and fuel."""
        return self.mtow_kg - self.oew_kg

    @property
    def max_payload_by_weight_limits_kg(self) -> float:
        """Payload ceiling from the zero-fuel/landing weight limits.

        At touchdown with the trip fuel burnt the airframe weighs
        OEW + payload, so both MLW and MZFW cap the payload from below
        (textbook third segment of the payload-range envelope).
        """
        return min(
            self.max_payload_kg,
            self.mlw_kg - self.oew_kg,
            self.mzfw_kg - self.oew_kg,
        )


def trip_time_h(
    ac: ProxyAircraft, distance_km: float, headwind_kmh: float = 0.0
) -> float:
    """Block-time-ish estimate: cruise time at TAS minus headwind + climb/descent allowance."""
    if distance_km <= 0:
        raise ValueError("distance_km must be positive")
    ground_speed = ac.cruise_tas_kmh - headwind_kmh
    if ground_speed <= 0:
        raise ValueError("headwind exceeds cruise TAS")
    return distance_km / ground_speed + ac.climb_descent_extra_h


def trip_fuel_kg(
    ac: ProxyAircraft, distance_km: float, headwind_kmh: float = 0.0
) -> float:
    """Trip fuel at constant cruise fuel flow (simplification, see module docstring)."""
    return ac.cruise_fuel_kg_per_h * trip_time_h(ac, distance_km, headwind_kmh)


def usable_fuel_at_payload(ac: ProxyAircraft, payload_kg: float) -> float:
    """Fuel that still fits at a given payload, limited by tank capacity and MTOW."""
    if payload_kg < 0:
        raise ValueError("payload_kg must be non-negative")
    return max(0.0, min(ac.max_fuel_kg, ac.max_usable_weight_kg - payload_kg))


def max_range_km(
    ac: ProxyAircraft, payload_kg: float, headwind_kmh: float = 0.0
) -> float:
    """Range achievable when burning exactly the usable fuel at this payload."""
    cruise_hours = usable_fuel_at_payload(ac, payload_kg) / ac.cruise_fuel_kg_per_h
    ground_speed = ac.cruise_tas_kmh - headwind_kmh
    return max(0.0, cruise_hours - ac.climb_descent_extra_h) * ground_speed


def payload_range_table(
    ac: ProxyAircraft, step_kg: float = 500.0, reserve_kg: float = 0.0
) -> pd.DataFrame:
    """Payload-range envelope from max payload down to zero.

    The payload axis is capped at ``max_payload_by_weight_limits_kg``:
    structural payload beyond that cannot be loaded because the zero-fuel
    (MZFW) or landing (MLW) weight limits would be exceeded -- the textbook
    third segment of the envelope. A ``binding`` column records which
    constraint limits each row (MZFW/MLW at the capped end, then MTOW on
    the rising segment, then tank capacity on the flat segment).
    ``reserve_kg`` subtracts a fixed reserve allowance from the usable fuel
    before computing range -- brochure-style "range" figures typically
    include such reserves.
    """
    if reserve_kg < 0:
        raise ValueError("reserve_kg must be non-negative")
    payload_cap = ac.max_payload_by_weight_limits_kg
    rows = []
    payload = payload_cap
    while payload >= 0:
        tank_limited = usable_fuel_at_payload(ac, payload) >= ac.max_fuel_kg
        usable = max(0.0, usable_fuel_at_payload(ac, payload) - reserve_kg)
        cruise_hours = usable / ac.cruise_fuel_kg_per_h
        binding = (
            "MZFW/MLW"
            if payload >= payload_cap - 1e-9
            else ("tank" if tank_limited else "MTOW")
        )
        rows.append(
            {
                "payload_kg": payload,
                "usable_fuel_kg": usable_fuel_at_payload(ac, payload),
                "max_range_km": max(0.0, cruise_hours - ac.climb_descent_extra_h)
                * ac.cruise_tas_kmh,
                "binding": binding,
            }
        )
        payload -= step_kg
    return pd.DataFrame(rows)


def plot_payload_range(ac: ProxyAircraft, step_kg: float = 500.0):
    """Return (fig, ax) with the payload-range envelope plotted."""
    import matplotlib.pyplot as plt

    df = payload_range_table(ac, step_kg)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(df["payload_kg"] / 1000.0, df["max_range_km"] / 1000.0)
    ax.set_xlabel("Payload (t)")
    ax.set_ylabel("Max range (1000 km)")
    ax.set_title(f"Payload-range envelope - {ac.name}")
    ax.grid(True, alpha=0.3)
    return fig, ax


# Heuristic takeoff field-length sizing -- deliberately crude, documented in
# docs/methodology.md. Base value and coefficients are order-of-magnitude aids
# for the hot-and-high case study, not performance engineering.
_TOFL_BASE_M = 2_000.0  # sea-level ISA takeoff field length at MTOW, no wind
_TOFL_PER_1000FT = 0.07  # +7 % per 1000 ft pressure altitude
_TOFL_PER_ISA_DEV_C = 0.006  # +0.6 % per degC above ISA
_TOFL_HEADWIND_FACTOR_PER_MPS = 0.01  # -1 % per m/s headwind

_ISA_LAPSE_C_PER_1000FT = 1.9812  # standard troposphere lapse rate


def isa_temperature_c(elevation_ft: float) -> float:
    """ISA temperature at a pressure altitude (troposphere lapse rate)."""
    return 15.0 - _ISA_LAPSE_C_PER_1000FT * elevation_ft / 1000.0


def takeoff_field_length_m(
    pressure_altitude_ft: float,
    isa_dev_c: float = 0.0,
    headwind_mps: float = 0.0,
    weight_fraction: float = 1.0,
) -> float:
    """Heuristic takeoff field length (m) for the proxy aircraft class.

    ``weight_fraction`` is takeoff weight / MTOW (0 < w <= 1): the field
    length scales with its square (kinetic-energy-at-rotation scaling --
    the honest order-of-magnitude relation, documented in
    docs/methodology.md). Inverting this relation gives the weight a
    runway can accept, i.e. the payload cut for hot-and-high/short fields.
    """
    if not 0 < weight_fraction <= 1.0:
        raise ValueError("weight_fraction must be in (0, 1]")
    factor = 1.0
    factor += _TOFL_PER_1000FT * pressure_altitude_ft / 1000.0
    factor += _TOFL_PER_ISA_DEV_C * isa_dev_c
    factor -= _TOFL_HEADWIND_FACTOR_PER_MPS * headwind_mps
    return _TOFL_BASE_M * max(0.5, factor) * weight_fraction**2


def max_weight_fraction_for_runway(
    pressure_altitude_ft: float,
    isa_dev_c: float,
    runway_m: float,
    headwind_mps: float = 0.0,
) -> float:
    """Inverse of :func:`takeoff_field_length_m`: the weight fraction at
    which the required field length exactly equals ``runway_m`` (capped at
    1.0 -- a long runway never lets you exceed MTOW)."""
    factor = 1.0
    factor += _TOFL_PER_1000FT * pressure_altitude_ft / 1000.0
    factor += _TOFL_PER_ISA_DEV_C * isa_dev_c
    factor -= _TOFL_HEADWIND_FACTOR_PER_MPS * headwind_mps
    factor = max(0.5, factor)
    return min(1.0, (runway_m / (_TOFL_BASE_M * factor)) ** 0.5)


def landing_distance_m(
    pressure_altitude_ft: float,
    isa_dev_c: float = 0.0,
    headwind_mps: float = 0.0,
    weight_fraction: float = 1.0,
) -> float:
    """Heuristic landing distance (m): 0.65 x the takeoff figure.

    Learning-grade coefficient -- real landing distances depend on brake
    condition, reverse thrust, auto-brake setting and approach speed, none
    of which are modelled.
    """
    return 0.65 * takeoff_field_length_m(
        pressure_altitude_ft, isa_dev_c, headwind_mps, weight_fraction
    )
