"""Public-spec comparison presets (same parameter sets as cases/01).

All figures are brochure-grade public specifications or clearly labelled
estimates -- see the honesty notes in cases/01_range_payload.ipynb and
docs/methodology.md. The C919 entry is *not* official data.
"""

from __future__ import annotations

from routelab.performance import ProxyAircraft

PRESET_AIRCRAFT: dict[str, ProxyAircraft] = {
    "A320neo (公开手册量级)": ProxyAircraft(
        name="A320neo",
        seats=174,
        mtow_kg=79_000,
        oew_kg=44_300,
        max_fuel_kg=14_800,
        max_payload_kg=18_200,
        cruise_tas_kmh=833,
        cruise_fuel_kg_per_h=1_950,
    ),
    "737 MAX 8 (公开手册量级)": ProxyAircraft(
        name="737 MAX 8",
        seats=178,
        mtow_kg=82_200,
        oew_kg=45_100,
        max_fuel_kg=16_500,
        max_payload_kg=19_600,
        cruise_tas_kmh=839,
        cruise_fuel_kg_per_h=2_050,
    ),
    "C919 (公开报道+估计，非官方)": ProxyAircraft(
        name="C919 (estimates)",
        seats=164,
        mtow_kg=77_300,
        oew_kg=43_500,
        max_fuel_kg=18_500,
        max_payload_kg=16_800,
        cruise_tas_kmh=828,
        cruise_fuel_kg_per_h=2_100,
    ),
}
