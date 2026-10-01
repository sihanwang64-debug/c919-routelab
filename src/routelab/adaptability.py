"""Airport adaptation: which of the world's airports can the type serve?

Combines the heuristic field-length model (weight-parameterised) with the
OurAirports dataset -- bundled sample or the full 86k download -- to answer
the operations-support question an airframer's performance team answers
daily: for a given airport and season, does the type get in and out at
MTOW, at reduced weight, or not at all?

Classification (per airport, at an assumed temperature):
- ``ok``       required field length <= available runway at MTOW;
- ``reduced``  MTOW exceeds the runway but a reduced-weight takeoff fits:
  the report carries the max weight fraction and the corresponding max
  payload (full fuel assumed);
- ``infeasible`` even a severely reduced takeoff (floor 0.5 of the base
  factor) does not fit.

Honesty notes: heuristic field lengths with no obstacle/clearway analysis,
landing distance is a 0.65 x takeoff figure, temperatures are assumptions
(OurAirports has no climate data) -- docs/methodology.md.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from routelab.airports import Airport, AirportDB
from routelab.performance import (
    ProxyAircraft,
    isa_temperature_c,
    max_weight_fraction_for_runway,
    takeoff_field_length_m,
)

DEFAULT_ISA_DEV_C = 15.0  # hot-day assumption: ISA + 15 (conservative summer)
REDUCED_FLOOR = 0.5  # below this weight fraction the takeoff is not credible


@dataclass(frozen=True)
class AdaptationReport:
    """Single-airport adaptation verdict for one aircraft preset."""

    ident: str
    iata: str
    name: str
    country: str
    elevation_ft: float
    runway_m: float
    isa_temp_c: float
    assumed_temp_c: float
    isa_dev_c: float
    required_tofl_m: float
    max_weight_fraction: float
    max_tow_kg: float
    max_payload_kg: float
    landing_distance_m: float
    verdict: str  # "ok" | "reduced" | "infeasible"


def adapt_for_airport(
    db: AirportDB,
    ac: ProxyAircraft,
    ident: str,
    temp_c: float | None = None,
    airport: Airport | None = None,
) -> AdaptationReport:
    """Adaptation report for one airport (raises KeyError for unknown ids).

    ``airport`` lets batch scans pass the object they already hold -- with
    86k entries an ident can collide with another airport's IATA code, and
    re-resolving through ``get`` would silently analyse the wrong field.

    ``temp_c`` defaults to ISA + 15 (hot-day conservative). The max payload
    at the reduced weight assumes the weight cut comes off the fuel first
    (structural payload only yields once the weight room drops below it).
    """
    ap = airport or db.get(ident)
    isa = isa_temperature_c(ap.elevation_ft)
    assumed = isa + DEFAULT_ISA_DEV_C if temp_c is None else temp_c
    isa_dev = assumed - isa

    required = takeoff_field_length_m(ap.elevation_ft, isa_dev)
    runway = db.max_runway_m(ap) or 0.0
    fraction = max_weight_fraction_for_runway(ap.elevation_ft, isa_dev, runway)

    if fraction >= 1.0:
        verdict = "ok"
    elif fraction >= REDUCED_FLOOR:
        verdict = "reduced"
    else:
        verdict = "infeasible"

    max_tow = ac.mtow_kg * fraction
    max_payload = max(0.0, min(ac.max_payload_kg, max_tow - ac.oew_kg))
    return AdaptationReport(
        ident=ap.ident,
        iata=ap.iata,
        name=ap.name,
        country=ap.iso_country,
        elevation_ft=ap.elevation_ft,
        runway_m=round(runway, 1),
        isa_temp_c=round(isa, 1),
        assumed_temp_c=round(assumed, 1),
        isa_dev_c=round(isa_dev, 1),
        required_tofl_m=round(required, 1),
        max_weight_fraction=round(fraction, 3),
        max_tow_kg=round(max_tow),
        max_payload_kg=round(max_payload),
        landing_distance_m=round(
            0.65 * takeoff_field_length_m(ap.elevation_ft, isa_dev, weight_fraction=1.0), 1
        ),
        verdict=verdict,
    )


def scan_region(
    db: AirportDB,
    ac: ProxyAircraft,
    *,
    country: str | None = None,
    min_elevation_ft: float | None = None,
    temp_c: float | None = None,
    min_runway_m: float = 1500.0,
) -> list[AdaptationReport]:
    """Batch adaptation scan -- O(1) heuristic per airport.

    Filters: ``country`` (ISO code), and when ``min_elevation_ft`` is set a
    high-elevation cut (the plateau scenario); ``min_runway_m`` always
    applies so 86k grass strips do not drown the signal. Reports sort
    worst-first (infeasible > reduced > ok), then by required field length.
    """
    order = {"infeasible": 0, "reduced": 1, "ok": 2}
    reports: list[AdaptationReport] = []
    for ap in db.all():
        if country and ap.iso_country != country.upper():
            continue
        elev = ap.elevation_ft
        if min_elevation_ft is not None and (
            elev != elev or elev < min_elevation_ft
        ):
            # `elev != elev` catches NaN elevations (closed/unknown airports)
            continue
        if (db.max_runway_m(ap) or 0.0) < min_runway_m:
            continue
        try:
            reports.append(adapt_for_airport(db, ac, ap.ident, temp_c, airport=ap))
        except KeyError:
            continue
    reports.sort(key=lambda r: (order.get(r.verdict, 3), -r.required_tofl_m))
    return reports


def plateau_airports(
    db: AirportDB, min_elevation_ft: float = 3500.0, country: str = "CN"
) -> list[dict]:
    """High-plateau airports (default: China >= 3500 ft), highest first."""
    hits = [
        {**asdict(a), "runway_m": db.max_runway_m(a) or 0.0}
        for a in db.by_country(country)
        if a.elevation_ft >= min_elevation_ft
    ]
    return sorted(hits, key=lambda r: -r["elevation_ft"])
