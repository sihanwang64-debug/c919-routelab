"""Research-grade cruise burn model backed by OpenAP (optional dependency).

OpenAP (https://github.com/junzis/openap) provides published, peer-reviewed
aircraft performance models. When the ``openap`` package is installed
(``pip install -e ".[perf]"``), this module replaces the constant-flow
cruise assumption of :mod:`routelab.performance` with a mass-dependent
burn: fuel flow is evaluated at the instantaneous aircraft mass and the
cruise is integrated.

Performance design
------------------
``FuelFlow`` objects are expensive to build (tens of milliseconds) and the
envelope needs thousands of burn evaluations, so this module:

1. caches one ``FuelFlow`` instance per aircraft type;
2. precomputes, per (type, altitude, Mach), the cumulative burn-time
   integral ``G(m) = int dm / FF(m)`` on a fixed 250-kg mass grid with a
   single *vectorized* ``enroute`` call (OpenAP's NumpyBackend accepts
   arrays);
3. answers every subsequent question -- distance for a fuel budget, fuel
   for a distance, fuel flow at a mass -- with ``np.interp`` lookups,
   i.e. microseconds instead of milliseconds.

Accuracy: the grid integral matches a fine stepwise Euler reference to
better than ~0.5 % (tests/test_openap_backend.py).

Honesty notes
-------------
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

import numpy as np

CLIMB_DESCENT_H = 0.2  # same fixed allowance as the simple backend
DEFAULT_CRUISE_ALT_FT = 35_000.0
DEFAULT_MACH = 0.78
FT_TO_M = 0.3048

# mass grid for the cached integrators: covers OEW..MTOW of every type in
# the OpenAP narrow-body range with headroom for custom weight presets
_MASS_GRID = np.arange(30_000.0, 100_000.0 + 1e-9, 250.0)

_FUELFLOW_CACHE: dict[str, object] = {}
_INTEGRATOR_CACHE: dict[tuple, "_CruiseIntegrator"] = {}


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


def _aircraft_mlw(actype: str) -> float:
    """Max landing weight (kg) from the OpenAP aircraft database."""
    openap = _openap()
    return float(openap.prop.aircraft(actype.lower())["mlw"])


def _fuelflow(actype: str):
    """Cached FuelFlow instance -- construction costs tens of milliseconds."""
    key = actype.lower()
    ff = _FUELFLOW_CACHE.get(key)
    if ff is None:
        ff = _openap().FuelFlow(key)
        _FUELFLOW_CACHE[key] = ff
    return ff


class _CruiseIntegrator:
    """Cached burn-time integral over a fixed mass grid.

    ``cum_s[k]`` is the seconds of flight needed to burn mass from the grid
    start down to ``_MASS_GRID[k]`` -- built with one vectorized ``enroute``
    call and a trapezoidal cumulative integral of ``1 / FF(m)``.
    """

    def __init__(self, actype: str, alt_ft: float, mach: float) -> None:
        openap = _openap()
        self.tas_kms = float(openap.aero.mach2tas(mach, alt_ft * FT_TO_M)) / 1000.0
        ff = np.clip(
            np.asarray(
                _fuelflow(actype).enroute(
                    mass=_MASS_GRID, tas=self.tas_kms * 1000.0, alt=alt_ft * FT_TO_M
                ),
                dtype=float,
            ),
            1e-6,
            None,
        )
        self.ff_kg_s = ff
        dt_dm = 1.0 / ff
        self.cum_s = np.concatenate(
            ([0.0], np.cumsum(0.5 * (dt_dm[:-1] + dt_dm[1:]) * np.diff(_MASS_GRID)))
        )

    def burn_seconds(self, m0: float | np.ndarray, fuel: float | np.ndarray):
        """Seconds of cruise needed to burn ``fuel`` from initial mass ``m0``."""
        m0 = np.asarray(m0, dtype=float)
        fuel = np.asarray(fuel, dtype=float)
        return np.interp(m0, _MASS_GRID, self.cum_s) - np.interp(
            m0 - fuel, _MASS_GRID, self.cum_s
        )

    def distance_km(self, m0, fuel):
        """Great-circle-free cruise distance (km) while burning ``fuel``."""
        return self.burn_seconds(m0, fuel) * self.tas_kms

    def fuel_for_distance(self, m0, distance_km):
        """Fuel (kg) needed from ``m0`` to cover ``distance_km`` at cruise."""
        m0 = np.asarray(m0, dtype=float)
        target_s = np.asarray(distance_km, dtype=float) / self.tas_kms
        g0 = np.interp(m0, _MASS_GRID, self.cum_s)
        m1 = np.interp(g0 - target_s, self.cum_s, _MASS_GRID)
        return m0 - m1

    def ff_at(self, masses):
        """Fuel flow (kg/s) interpolated at the given masses."""
        return np.interp(masses, _MASS_GRID, self.ff_kg_s)


def _integrator(
    actype: str, alt_ft: float = DEFAULT_CRUISE_ALT_FT, mach: float = DEFAULT_MACH
) -> _CruiseIntegrator:
    key = (actype.lower(), round(float(alt_ft)), round(float(mach), 4))
    integ = _INTEGRATOR_CACHE.get(key)
    if integ is None:
        integ = _INTEGRATOR_CACHE[key] = _CruiseIntegrator(key[0], key[1], key[2])
    return integ


def _fuel_flow_kg_per_s(
    actype: str, mass_kg: float, alt_ft: float, mach: float
) -> float:
    """Fuel flow (kg/s) at a given mass, interpolated on the cached grid."""
    return float(_integrator(actype, alt_ft, mach).ff_at(mass_kg))


def _allowance_km(integ: _CruiseIntegrator) -> float:
    """Distance (km) lost to the fixed climb/descent allowance."""
    return CLIMB_DESCENT_H * 3600.0 * integ.tas_kms


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
    """Cruise segment with mass-dependent burn, two stop conditions.

    Burns the whole ``fuel_available_kg`` (range problems) unless
    ``distance_limit_km`` is reached first (trip-fuel problems) -- whichever
    comes first. Headwind reduces ground speed; the fuel flow itself is the
    still-air OpenAP model.
    """
    if initial_mass_kg <= 0 or fuel_available_kg <= 0:
        raise ValueError("mass and fuel must be positive")
    integ = _integrator(actype, cruise_alt_ft, mach)
    tas_kms = integ.tas_kms  # fuel flow depends on air speed only
    ground_kms = tas_kms - headwind_kmh / 3.6 / 1000.0
    if ground_kms <= 0:
        raise ValueError("headwind exceeds cruise TAS")

    full_air_km = float(integ.distance_km(m0=initial_mass_kg, fuel=fuel_available_kg))
    full_ground_km = full_air_km * (ground_kms / tas_kms)
    if distance_limit_km is None or distance_limit_km >= full_ground_km:
        fuel_kg = float(fuel_available_kg)
        ground_km = full_ground_km
    else:
        ground_km = float(distance_limit_km)
        air_needed = ground_km * (tas_kms / ground_kms)
        fuel_kg = float(integ.fuel_for_distance(initial_mass_kg, air_needed))
    seconds = float(integ.burn_seconds(initial_mass_kg, fuel_kg))
    return CruiseResult(
        distance_km=ground_km,
        time_h=seconds / 3600.0,
        fuel_kg=fuel_kg,
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
    return float(
        _integrator(actype, cruise_alt_ft, mach).fuel_for_distance(
            initial_mass_kg, distance_km
        )
    )


def range_openap(
    actype: str,
    initial_mass_kg: float,
    usable_fuel_kg: float,
    *,
    cruise_alt_ft: float = DEFAULT_CRUISE_ALT_FT,
    mach: float = DEFAULT_MACH,
    headwind_kmh: float = 0.0,
) -> float:
    """Distance (km) covered until ``usable_fuel_kg`` is burnt at cruise.

    Mirrors the simple model: the fixed climb/descent allowance does not
    earn range. Headwind stretches the same air distance over less ground.
    """
    integ = _integrator(actype, cruise_alt_ft, mach)
    ground_kms = integ.tas_kms - headwind_kmh / 3.6 / 1000.0
    air_km = float(integ.distance_km(initial_mass_kg, usable_fuel_kg))
    return max(0.0, air_km * (ground_kms / integ.tas_kms) - _allowance_km(integ))


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
    capacity and payload cap are the editable presets. Fully vectorized:
    one grid-integral lookup serves every payload row.
    """
    mtow_kg, oew_kg = aircraft_mass_limits(actype)
    integ = _integrator(actype, cruise_alt_ft, mach)
    allowance_km = _allowance_km(integ)
    ground_kms = integ.tas_kms - headwind_kmh / 3.6 / 1000.0

    payload = max_payload_kg
    rows: list[dict] = []
    while payload >= 0:
        usable = max(
            0.0, min(tank_capacity_kg, mtow_kg - oew_kg - payload) - reserve_kg
        )
        if usable > 0:
            initial_mass = oew_kg + payload + usable
            air_km = float(integ.distance_km(initial_mass, usable))
            range_km = max(0.0, air_km * (ground_kms / integ.tas_kms) - allowance_km)
        else:
            range_km = 0.0
        rows.append(
            {"payload_kg": payload, "usable_fuel_kg": usable, "max_range_km": range_km}
        )
        payload -= step_kg
    return rows
