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
    cruise_tas_kmh: float = 833.0  # ~M0.78 at FL350
    cruise_fuel_kg_per_h: float = 2_300.0
    climb_descent_extra_h: float = 0.2  # combined climb + descent time allowance

    @property
    def max_usable_weight_kg(self) -> float:
        """MTOW - OEW: everything you can split between payload and fuel."""
        return self.mtow_kg - self.oew_kg


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


def payload_range_table(ac: ProxyAircraft, step_kg: float = 500.0) -> pd.DataFrame:
    """Payload-range envelope from max structural payload down to zero.

    The resulting curve has the classic shape: an MTOW-limited rising segment
    at high payload, then a flat segment at full tank capacity.
    """
    rows = []
    payload = ac.max_payload_kg
    while payload >= 0:
        rows.append(
            {
                "payload_kg": payload,
                "usable_fuel_kg": usable_fuel_at_payload(ac, payload),
                "max_range_km": max_range_km(ac, payload),
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


def takeoff_field_length_m(
    pressure_altitude_ft: float, isa_dev_c: float = 0.0, headwind_mps: float = 0.0
) -> float:
    """Heuristic takeoff field length (metres) for the proxy aircraft class."""
    factor = 1.0
    factor += _TOFL_PER_1000FT * pressure_altitude_ft / 1000.0
    factor += _TOFL_PER_ISA_DEV_C * isa_dev_c
    factor -= _TOFL_HEADWIND_FACTOR_PER_MPS * headwind_mps
    return _TOFL_BASE_M * max(0.5, factor)
