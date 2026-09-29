"""Optional OpenSky REST importer for real arrival data.

Pulls historical arrivals from the public OpenSky REST API
(``/flights/arrival``), caches the raw JSON on disk (one download per
airport/time-window, replayable offline), and maps it onto the flight
schema understood by :mod:`routelab.network`.

Honest approximations, documented because they matter:

- **Airframe identity**: the OpenSky REST endpoint exposes the transponder
  address (``icao24``), not the civil registration. ``icao24`` uniquely
  identifies the airframe just as a registration would, so tail chains
  built on it are equally valid; the column is filled with the ``icao24``.
- **No schedule exists in this endpoint**: arrival delay is estimated with
  a *pseudo-schedule* -- the median observed block time per route acts as
  the planned block time, and the delay of a flight is its actual block
  time minus that route median. Routes with fewer than
  ``min_route_samples`` observations are dropped (median too noisy).

The endpoint is anonymous-rate-limited; :func:`fetch_arrivals` retries
with exponential backoff and alternating direct/proxy paths (this machine
often needs ``http://127.0.0.1:10808`` to reach github-grade targets).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

ARRIVALS_URL = "https://opensky-network.org/api/flights/arrival"
DEFAULT_PROXY = "http://127.0.0.1:10808"  # local v2rayN mixed port on this machine
DEFAULT_CACHE_DIR = Path("data_cache") / "opensky"


def _cache_path(cache_dir: Path, airport: str, begin: int, end: int) -> Path:
    return cache_dir / f"arrivals_{airport}_{begin}_{end}.json"


def fetch_arrivals(
    airport: str,
    begin: int,
    end: int,
    *,
    cache_dir: Path | str | None = DEFAULT_CACHE_DIR,
    proxy: str | None = DEFAULT_PROXY,
    timeout_s: float = 30.0,
    max_attempts: int = 6,
) -> list[dict]:
    """Arrivals JSON rows for ``airport`` between unix seconds begin/end.

    Cached on first success (replaying the cache never touches the
    network). Retries alternate between the direct path and ``proxy`` with
    exponential backoff; raises RuntimeError after ``max_attempts``.
    """
    import httpx  # lazy: only the importer needs it

    airport = airport.upper()
    cache_file = None
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_file = _cache_path(cache_dir, airport, begin, end)
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))

    paths = [None] if proxy is None else [None, proxy]
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        use_proxy = paths[attempt % len(paths)]
        try:
            with httpx.Client(
                timeout=timeout_s, proxy=use_proxy, trust_env=False
            ) as client:
                res = client.get(
                    ARRIVALS_URL,
                    params={"airport": airport, "begin": begin, "end": end},
                )
                res.raise_for_status()
                rows = res.json()
        except Exception as exc:  # noqa: BLE001 - network or HTTP errors
            last_error = exc
            time.sleep(min(2**attempt, 20))
            continue
        if not isinstance(rows, list):
            last_error = RuntimeError(f"unexpected payload: {rows!r:.120}")
            time.sleep(min(2**attempt, 20))
            continue
        if cache_file is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(rows), encoding="utf-8")
        return rows
    raise RuntimeError(
        f"OpenSky arrivals for {airport} failed after {max_attempts} attempts: {last_error}"
    )


def arrivals_to_flights(
    rows: list[dict], *, min_route_samples: int = 5
) -> pd.DataFrame:
    """Map OpenSky arrivals JSON onto the ``network.py`` flight schema.

    Columns produced: registration (=icao24), origin, destination,
    sched_dep (=firstSeen), sched_arr (=firstSeen + route-median block
    time), actual_arr (=lastSeen). Rows on routes with fewer than
    ``min_route_samples`` observations are dropped.
    """
    if not rows:
        return pd.DataFrame(
            columns=["registration", "origin", "destination",
                     "sched_dep", "sched_arr", "actual_arr"]
        )
    df = pd.DataFrame(
        [
            {
                "registration": str(r["icao24"]).strip().upper(),
                "origin": str(r.get("estDepartureAirport") or "").strip().upper(),
                "destination": str(r.get("estArrivalAirport") or "").strip().upper(),
                "sched_dep": pd.to_datetime(r["firstSeen"], unit="s"),
                "actual_arr": pd.to_datetime(r["lastSeen"], unit="s"),
            }
            for r in rows
            if r.get("estDepartureAirport") and r.get("estArrivalAirport")
        ]
    )
    if df.empty:
        return df
    df["actual_block_min"] = (
        df["actual_arr"] - df["sched_dep"]
    ).dt.total_seconds() / 60.0
    counts = df.groupby(["origin", "destination"])["actual_block_min"].transform("size")
    medians = df.groupby(["origin", "destination"])["actual_block_min"].transform("median")
    keep = counts >= min_route_samples
    df = df[keep].copy()
    df["sched_arr"] = df["sched_dep"] + pd.to_timedelta(medians[keep], unit="min")
    return df[
        ["registration", "origin", "destination", "sched_dep", "sched_arr", "actual_arr"]
    ].sort_values(["registration", "sched_dep"]).reset_index(drop=True)
