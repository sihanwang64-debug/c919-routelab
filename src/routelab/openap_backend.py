"""Research-grade cruise burn model backed by OpenAP (optional dependency).

OpenAP (https://github.com/junzis/openap) provides published, peer-reviewed
aircraft performance models. When the ``openap`` package is installed
(``pip install -e ".[perf]"``), this module replaces the constant-flow
cruise assumption of :mod:`routelab.performance` with a mass-dependent
burn: fuel flow is evaluated at the instantaneous aircraft mass, and the
cruise is integrated numerically.

Scope and honesty notes
-----------------------
- Only the *cruise* phase is modelled; climb/descent remain a fixed time
  allowance (``CLIMB_DESCENT_H``), consistent with the simple backend.
- Aircraft weight limits (MTOW, OEW) come from OpenAP's aircraft database
  (``openap.prop``); tank capacity and maximum payload remain the editable
  presets from the simple model, because OpenAP does not expose them.
- The C919 has no published model in OpenAP; use ``a320`` as the same-class
  proxy (see docs/methodology.md).

Requires openap >= 2.6 (FuelFlow.enroute / prop.aircraft API).
"""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass

CLIMB_DESCENT_H = 0.2  # same fixed allowance as the simple backend
DEFAULT_CRUISE_ALT_FT = 35_000.0
DEFAULT_MACH = 0.78
FT_TO_M = 0.3048
_EULER_STEP_S = 120.0  # integration step; fuel flow changes slowly with mass


def is_available() -> bool:
    """True when the openap package is importable."""
    return importlib.util.find_spec("openap") is not None


def _openap():
    if not is_available():
        raise ImportError(
            "backend 'openap' requires the optional dependency openap; "
            'install with pip install -e ".[perf]"'
        )
    return importlib.import_module("openap")


def supported_aircraft() -> list[str]:
    """Aircraft type codes OpenAP can model (lowercase, e.g. 'a320', 'b738')."""
    openap = _openap()
    return sorted(openap.prop.available_aircraft())


def aircraft_mass_limits(actype: str) -> tuple[float, float]:
    """(MTOW, OEW) in kg from the OpenAP aircraft database."""
    openap = _openap()
    meta = openap.prop.aircraft(actype.lower())
    return float(meta["mtow"]), float(meta["oew"])


def _fuel_flow_kg_per_s(
    actype: str, mass_kg: float, alt_ft: float, mach: float
) -> float:
    openap = _openap()
    ff = openap.FuelFlow(actype.lower())
    tas_mps = openap.aero.mach2tas(mach, alt_ft * FT_TO_M)
    return float(ff.enroute(mass=mass_kg, tas=tas_mps, alt=alt_ft * FT_TO_M))


def _ground_speed_mps(openap, alt_ft: float, mach: float, headwind_kmh: float) -> float:
    # float(): aero.mach2tas returns numpy scalars; keep numpy out of the
    # package boundary (FastAPI/JSON cannot serialize it)
    tas = float(openap.aero.mach2tas(mach, alt_ft * FT_TO_M))
    gs = tas - headwind_kmh / 3.6
    if gs <= 0:
        raise ValueError("headwind exceeds cruise TAS")
    return gs


@dataclass(frozen=True)
class CruiseResult:
    """Outcome of an integrated cruise segment."""

    distance_km: float
    time_h: float
    fuel_kg: float


def integrate_cruise(
    actype: str,
    initial_mass_kg: float,
    fuel_available_kg: float,
    *,
    distance_limit_km: float | None = None,
    cruise_alt_ft: float = DEFAULT_CRUISE_ALT_FT,
    mach: float = DEFAULT_MACH,
    headwind_kmh: float = 0.0,
) -> CruiseResult:
    """Integrate a cruise segment with mass-dependent fuel flow.

    Two stop conditions, whichever comes first:

    - the given ``fuel_available_kg`` is burnt (used for range computations);
    - ``distance_limit_km`` is reached (used for trip fuel on a fixed leg).

    Euler integration with a 60 s step: fuel flow changes slowly with mass,
    so the discretisation error is small at learning-grade scope.
    """
    openap = _openap()
    if initial_mass_kg <= 0 or fuel_available_kg <= 0:
        raise ValueError("mass and fuel must be positive")
    gs_mps = _ground_speed_mps(openap, cruise_alt_ft, mach, headwind_kmh)
    gs_km_s = gs_mps / 1000.0

    mass = initial_mass_kg
    fuel_left = fuel_available_kg
    distance_km = 0.0
    time_s = 0.0
    ff = openap.FuelFlow(actype.lower())
    tas_mps = openap.aero.mach2tas(mach, cruise_alt_ft * FT_TO_M)
    alt_m = cruise_alt_ft * FT_TO_M
    limit_m = None if distance_limit_km is None else distance_limit_km * 1000.0

    while fuel_left > 0:
        flow = float(ff.enroute(mass=mass, tas=tas_mps, alt=alt_m))  # kg/s
        step_s = _EULER_STEP_S
        if limit_m is not None and (distance_km * 1000.0 + gs_mps * step_s) >= limit_m:
            step_s = (limit_m - distance_km * 1000.0) / gs_mps
        step_fuel = min(flow * step_s, fuel_left)
        mass -= step_fuel
        fuel_left -= step_fuel
        distance_km += gs_km_s * step_s
        time_s += step_s
        if limit_m is not None and distance_km * 1000.0 >= limit_m - 1e-6:
            break
    return CruiseResult(
        distance_km=float(distance_km), time_h=float(time_s / 3600.0),
        fuel_kg=float(fuel_available_kg - fuel_left),
    )


def trip_fuel_openap(
    actype: str,
    initial_mass_kg: float,
    distance_km: float,
    *,
    cruise_alt_ft: float = DEFAULT_CRUISE_ALT_FT,
    mach: float = DEFAULT_MACH,
    headwind_kmh: float = 0.0,
) -> float:
    """Fuel burnt (kg) covering ``distance_km`` at cruise from ``initial_mass_kg``."""
    res = integrate_cruise(
        actype,
        initial_mass_kg,
        fuel_available_kg=initial_mass_kg,  # never run dry before the limit bites
        distance_limit_km=distance_km,
        cruise_alt_ft=cruise_alt_ft,
        mach=mach,
        headwind_kmh=headwind_kmh,
    )
    return res.fuel_kg


def range_openap(
    actype: str,
    initial_mass_kg: float,
    usable_fuel_kg: float,
    *,
    cruise_alt_ft: float = DEFAULT_CRUISE_ALT_FT,
    mach: float = DEFAULT_MACH,
    headwind_kmh: float = 0.0,
) -> float:
    """Distance (km) covered until ``usable_fuel_kg`` is burnt at cruise."""
    res = integrate_cruise(
        actype,
        initial_mass_kg,
        fuel_available_kg=usable_fuel_kg,
        cruise_alt_ft=cruise_alt_ft,
        mach=mach,
        headwind_kmh=headwind_kmh,
    )
    # the fixed climb/descent allowance does not earn range, mirroring the
    # simple model's max_range_km convention
    return max(0.0, res.distance_km - (CLIMB_DESCENT_H * 3600.0) * (_ground_speed_mps(
        _openap(), cruise_alt_ft, mach, headwind_kmh
    ) / 1000.0))


def payload_range_table_openap(
    actype: str,
    *,
    max_payload_kg: float,
    tank_capacity_kg: float,
    step_kg: float = 500.0,
    reserve_kg: float = 0.0,
    cruise_alt_ft: float = DEFAULT_CRUISE_ALT_FT,
    mach: float = DEFAULT_MACH,
    headwind_kmh: float = 0.0,
) -> list[dict]:
    """Payload-range envelope using OpenAP burn integrated over cruise.

    Weight limits (MTOW/OEW) come from the OpenAP database; the tank
    capacity and payload cap are the editable presets. Rows run from max
    structural payload down to zero, mirroring the simple backend's table.
    """
    mtow_kg, oew_kg = aircraft_mass_limits(actype)
    rows: list[dict] = []
    payload = max_payload_kg
    while payload >= 0:
        usable = max(
            0.0, min(tank_capacity_kg, mtow_kg - oew_kg - payload) - reserve_kg
        )
        if usable > 0:
            initial_mass = oew_kg + payload + usable
            res = integrate_cruise(
                actype, initial_mass, fuel_available_kg=usable,
                cruise_alt_ft=cruise_alt_ft, mach=mach, headwind_kmh=headwind_kmh,
            )
            range_km = max(
                0.0,
                res.distance_km
                - CLIMB_DESCENT_H * 3600.0
                * (_ground_speed_mps(_openap(), cruise_alt_ft, mach, headwind_kmh) / 1000.0),
            )
        else:
            range_km = 0.0
        rows.append({"payload_kg": payload, "usable_fuel_kg": usable, "max_range_km": range_km})
        payload -= step_kg
    return rows
