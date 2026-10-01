"""Carbon emissions for planned legs (learning-grade).

Headline CO2
------------
``KEROSENE_CO2_KG_PER_KG = 3.16`` is the ICAO/IPCC convention for kerosene:
essentially stoichiometry, so "CO2 = 3.16 x fuel burnt" is the physically
robust part of any carbon claim. Everything derived here inherits the
uncertainties of the fuel model itself, not of the factor.

Species that genuinely vary with combustion conditions
-------------------------------------------------------
NOx, H2O and HC are computed by OpenAP's ``Emission`` model (same optional
``[perf]`` extra) from instantaneous mass/speed/altitude -- useful for
demonstrating *why* the cruise NOx number is not a simple fuel multiple.
Requires an aircraft type OpenAP can model; the C919 again uses ``a320``
as its stand-in (docs/methodology.md).
"""

from __future__ import annotations

KEROSENE_CO2_KG_PER_KG = 3.16  # ICAO/IPCC kerosene emission factor


def co2_from_fuel_kg(
    fuel_kg: float, factor: float = KEROSENE_CO2_KG_PER_KG
) -> float:
    """Headline CO2 (kg) for burnt fuel: 3.16 kg CO2 per kg of kerosene."""
    if fuel_kg < 0:
        raise ValueError("fuel_kg must be non-negative")
    return fuel_kg * factor


def openap_emission_rates(
    actype: str,
    mass_kg: float,
    alt_ft: float = 35_000.0,
    mach: float = 0.78,
) -> dict[str, float]:
    """State-dependent emission rates (kg/s) from the OpenAP Emission model.

    Requires the ``[perf]`` extra. OpenAP 2.6 convention: CO2/H2O scale
    directly with the fuel flow (``emission.co2(ff)``), while NOx also
    depends on TAS/altitude (combustion temperature). Rates are
    instantaneous; the headline CO2 above remains the simple fuel multiple.
    """
    openap = _openap()
    em = openap.Emission(actype.lower())
    tas = float(openap.aero.mach2tas(mach, alt_ft * 0.3048))
    alt_m = alt_ft * 0.3048
    ff = float(openap.FuelFlow(actype.lower()).enroute(mass=mass_kg, tas=tas, alt=alt_m))
    rates: dict[str, float] = {"fuel": ff, "co2": float(em.co2(ff)), "h2o": float(em.h2o(ff))}
    try:
        rates["nox"] = float(em.nox(ff, tas, alt_m))
    except TypeError:
        rates["nox"] = float(em.nox(ff, tas))
    return rates


def _openap():
    import importlib.util

    if importlib.util.find_spec("openap") is None:
        raise ImportError(
            "OpenAP emission rates require the optional dependency openap; "
            'install with pip install -e ".[perf]"'
        )
    import importlib

    return importlib.import_module("openap")
