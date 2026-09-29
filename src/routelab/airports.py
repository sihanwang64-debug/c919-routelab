"""Airport and runway data layer.

The bundled CSV files are a tiny hand-picked sample of the OurAirports open
dataset (public domain), shipped inside the package so the toolkit works
offline out of the box. To use the full dataset, download airports.csv and
runways.csv from https://ourairports.com/data/ and point the environment
variables ROUTELAB_AIRPORTS_CSV / ROUTELAB_RUNWAYS_CSV at them -- the loader
reads a documented column subset, identical to the bundled sample files.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from routelab.greatcircle import Route, route_between

_DATA_DIR = Path(__file__).resolve().parent / "data"
AIRPORTS_CSV = Path(
    os.environ.get("ROUTELAB_AIRPORTS_CSV", _DATA_DIR / "ourairports" / "airports.csv")
)
RUNWAYS_CSV = Path(
    os.environ.get("ROUTELAB_RUNWAYS_CSV", _DATA_DIR / "ourairports" / "runways.csv")
)


@dataclass(frozen=True)
class Airport:
    """One row of the OurAirports airports.csv subset."""

    ident: str  # ICAO-style ident, e.g. ZSPD
    name: str
    iata: str  # e.g. PVG, "" when the airport has none
    iso_country: str
    municipality: str
    lat_deg: float
    lon_deg: float
    elevation_ft: float

    @property
    def position(self) -> tuple[float, float]:
        return (self.lat_deg, self.lon_deg)


class AirportDB:
    """Lookup table over the airports CSV, indexed by ICAO ident and IATA code."""

    def __init__(
        self,
        airports_csv: Path | None = None,
        runways_csv: Path | None = None,
    ) -> None:
        csv_path = Path(airports_csv) if airports_csv else AIRPORTS_CSV
        df = pd.read_csv(csv_path, dtype=str)
        df["latitude_deg"] = pd.to_numeric(df["latitude_deg"])
        df["longitude_deg"] = pd.to_numeric(df["longitude_deg"])
        df["elevation_ft"] = pd.to_numeric(df["elevation_ft"])
        df["iata_code"] = df["iata_code"].fillna("")
        self._airports = [
            Airport(
                ident=row["ident"],
                name=row["name"],
                iata=row["iata_code"],
                iso_country=row["iso_country"],
                municipality=row["municipality"],
                lat_deg=float(row["latitude_deg"]),
                lon_deg=float(row["longitude_deg"]),
                elevation_ft=float(row["elevation_ft"]),
            )
            for _, row in df.iterrows()
        ]
        self._by_code: dict[str, Airport] = {}
        for airport in self._airports:
            self._by_code[airport.ident.upper()] = airport
            if airport.iata:
                self._by_code[airport.iata.upper()] = airport

        rw_path = Path(runways_csv) if runways_csv else RUNWAYS_CSV
        self._runways: pd.DataFrame | None = (
            pd.read_csv(rw_path, dtype=str) if rw_path.exists() else None
        )

    def get(self, code: str) -> Airport:
        """Look up an airport by ICAO ident or IATA code (case-insensitive)."""
        key = code.strip().upper()
        if key in self._by_code:
            return self._by_code[key]
        raise KeyError(
            f"airport {code!r} not found among {len(self._airports)} entries; "
            "download the full OurAirports dataset and set ROUTELAB_AIRPORTS_CSV "
            "to cover more airports"
        )

    def by_country(self, iso_country: str) -> list[Airport]:
        """All bundled airports for one ISO country code, e.g. 'CN'."""
        return [a for a in self._airports if a.iso_country == iso_country.upper()]

    def all(self) -> list[Airport]:
        """All bundled airports."""
        return list(self._airports)

    def max_runway_m(self, airport: Airport) -> float | None:
        """Longest runway at the airport, in metres; None when unknown."""
        if self._runways is None:
            return None
        subset = self._runways[self._runways["airport_ident"] == airport.ident]
        if subset.empty:
            return None
        lengths = pd.to_numeric(subset["length_m"], errors="coerce").dropna()
        return float(lengths.max()) if not lengths.empty else None

    def route(self, origin: str, destination: str) -> Route:
        """Great-circle route between two airports given by code."""
        a, b = self.get(origin), self.get(destination)
        return route_between(
            a.ident, b.ident, a.lat_deg, a.lon_deg, b.lat_deg, b.lon_deg
        )
