"""Airport and runway data layer.

The bundled CSV files are a tiny hand-picked sample of the OurAirports open
dataset (public domain), shipped inside the package so the toolkit works
offline out of the box. To use the full dataset (~86k airports), either run
``python scripts/download_airports.py`` (which drops both files into
``data_cache/ourairports/`` -- picked up automatically on the next start)
or point the environment variables ``ROUTELAB_AIRPORTS_CSV`` /
``ROUTELAB_RUNWAYS_CSV`` at downloaded copies yourself. The loader reads a
documented column subset and accepts both OurAirports runway dialects
(``length_m`` sample / ``length_ft`` full dataset).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from routelab.greatcircle import Route, route_between

_DATA_DIR = Path(__file__).resolve().parent / "data"


def _default_csv_path(kind: str) -> Path:
    """Resolution order: env var > data_cache full dataset > bundled sample."""
    env = os.environ.get(f"ROUTELAB_{kind}_CSV")
    if env:
        return Path(env)
    downloaded = Path("data_cache") / "ourairports" / f"{kind.lower()}.csv"
    if downloaded.exists():
        return downloaded
    return _DATA_DIR / "ourairports" / f"{kind.lower()}.csv"


AIRPORTS_CSV = _default_csv_path("AIRPORTS")
RUNWAYS_CSV = _default_csv_path("RUNWAYS")

_DB_CACHE: dict[tuple, "AirportDB"] = {}


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
        key = (
            str(airports_csv) if airports_csv else str(AIRPORTS_CSV),
            str(runways_csv) if runways_csv else str(RUNWAYS_CSV),
        )
        cached = _DB_CACHE.get(key)
        if cached is not None:
            # the full 86k-airport dataset costs seconds to parse; instances
            # over the same files are shared read-only
            self.__dict__.update(cached.__dict__)
            return

        csv_path = Path(airports_csv) if airports_csv else AIRPORTS_CSV
        df = pd.read_csv(csv_path, dtype=str)
        df["latitude_deg"] = pd.to_numeric(df["latitude_deg"])
        df["longitude_deg"] = pd.to_numeric(df["longitude_deg"])
        df["elevation_ft"] = pd.to_numeric(df["elevation_ft"])
        df["iata_code"] = df["iata_code"].fillna("")
        df["municipality"] = df["municipality"].fillna("")
        df["name"] = df["name"].fillna("")
        self._airports = [
            Airport(
                ident=row.ident,
                name=row.name,
                iata=row.iata_code,
                iso_country=row.iso_country,
                municipality=row.municipality,
                lat_deg=row.latitude_deg,
                lon_deg=row.longitude_deg,
                elevation_ft=row.elevation_ft,
            )
            for row in df.itertuples(index=False)
        ]
        self._by_code: dict[str, Airport] = {}
        for airport in self._airports:
            self._by_code[airport.ident.upper()] = airport
            # with 86k entries small strips collide with real IATA codes --
            # the ICAO ident is the authoritative key, IATA only fills gaps
            if airport.iata and airport.iata.upper() not in self._by_code:
                self._by_code[airport.iata.upper()] = airport

        rw_path = Path(runways_csv) if runways_csv else RUNWAYS_CSV
        self._runways: pd.DataFrame | None = (
            pd.read_csv(rw_path, dtype=str) if rw_path.exists() else None
        )
        self._search_df: pd.DataFrame | None = None
        self._runway_max: dict[str, float] | None = None
        _DB_CACHE[key] = self

    def _search_frame(self) -> pd.DataFrame:
        """Flat, search-optimized table (built once, cached)."""
        if self._search_df is None:
            rows = [
                {
                    "ident": a.ident,
                    "iata": a.iata,
                    "name": a.name.upper(),
                    "municipality": a.municipality.upper(),
                    "country": a.iso_country,
                }
                for a in self._airports
            ]
            self._search_df = pd.DataFrame(rows)
        return self._search_df

    def search(self, query: str, limit: int = 8) -> list[Airport]:
        """Find airports by ICAO/IATA code or name/city substring.

        Ranking: exact ident/iata match first, then code prefix, then text
        substring -- so ``urc`` surfaces Urumqi above a Chinese village whose
        name happens to contain the letters. Case-insensitive; needs at
        least two characters.
        """
        q = query.strip().upper()
        if len(q) < 2:
            return []
        df = self._search_frame()
        exact = (df["ident"] == q) | (df["iata"] == q)
        prefix = df["ident"].str.startswith(q) | df["iata"].str.startswith(q)
        text = df["name"].str.contains(q, regex=False) | df["municipality"].str.contains(
            q, regex=False
        )
        hits = df[exact | prefix | text].copy()
        hits["_rank"] = 2
        hits.loc[exact, "_rank"] = 0
        hits.loc[prefix & ~exact, "_rank"] = 1
        hits = hits.sort_values(["_rank", "ident"]).head(limit)
        return [self.get(ident) for ident in hits["ident"]]

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
        """Longest runway at the airport, in metres; None when unknown.

        Handles both OurAirports schemas (``length_m`` sample / ``length_ft``
        full dataset, converted at 1 ft = 0.3048 m). The per-airport maximum
        is precomputed once for the whole file -- with 86k airports a
        per-airport scan would be quadratic.
        """
        return self._runway_max_map().get(airport.ident)

    def _runway_max_map(self) -> dict[str, float]:
        if self._runway_max is None:
            if self._runways is None:
                self._runway_max = {}
            else:
                if "length_m" in self._runways.columns:
                    lengths = pd.to_numeric(
                        self._runways["length_m"], errors="coerce"
                    )
                else:
                    lengths = (
                        pd.to_numeric(self._runways["length_ft"], errors="coerce")
                        * 0.3048
                    )
                self._runway_max = (
                    self._runways.assign(_len=lengths)
                    .groupby("airport_ident")["_len"]
                    .max()
                    .to_dict()
                )
        return self._runway_max

    def route(self, origin: str, destination: str) -> Route:
        """Great-circle route between two airports given by code."""
        a, b = self.get(origin), self.get(destination)
        return route_between(
            a.ident, b.ident, a.lat_deg, a.lon_deg, b.lat_deg, b.lon_deg
        )
