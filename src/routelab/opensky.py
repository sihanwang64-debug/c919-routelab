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

Access policy (verified 2026-09): **the anonymous tier is effectively
unusable for this purpose** -- history older than ~24 h returns 403, and
even a last-24-h window returns almost no rows (measured: 1 arrival and
51 departures for EDDF, a densely-covered hub). Real data requires "You cannot access
historical flights". Registered users get OAuth2 client credentials
(client id + secret from the OpenSky profile page, 400 credits/day) which
unlock history -- pass them via ``client_id``/``client_secret`` or the
``OPENSKY_CLIENT_ID`` / ``OPENSKY_CLIENT_SECRET`` environment variables;
tokens are fetched once and cached until shortly before expiry. A 403
fails immediately with an actionable message instead of being retried
(retrying a policy refusal cannot help); only connection errors and 5xx
are retried, over alternating direct/proxy paths with a short backoff
(this machine often needs ``http://127.0.0.1:10808`` to reach blocked
targets).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pandas as pd

ARRIVALS_URL = "https://opensky-network.org/api/flights/arrival"
TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)
DEFAULT_PROXY = "http://127.0.0.1:10808"  # local v2rayN mixed port on this machine
DEFAULT_CACHE_DIR = Path("data_cache") / "opensky"

_TOKEN_CACHE: dict[str, tuple[str, float]] = {}  # client_id -> (token, expires_at)


def _cache_path(cache_dir: Path, airport: str, begin: int, end: int) -> Path:
    return cache_dir / f"arrivals_{airport}_{begin}_{end}.json"


def _bearer_token(
    client_id: str | None, client_secret: str | None, proxy: str | None
) -> dict[str, str]:
    """OAuth2 client-credentials token, cached until ~60 s before expiry."""
    import httpx  # lazy: only the importer needs it

    if not (client_id and client_secret):
        return {}
    cached = _TOKEN_CACHE.get(client_id)
    if cached and cached[1] > time.time():
        return {"Authorization": f"Bearer {cached[0]}"}
    with httpx.Client(timeout=20.0, proxy=proxy, trust_env=False) as client:
        res = client.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
        res.raise_for_status()
        payload = res.json()
    token = payload["access_token"]
    expires_in = float(payload.get("expires_in", 1_700))
    _TOKEN_CACHE[client_id] = (token, time.time() + expires_in - 60)
    return {"Authorization": f"Bearer {token}"}


def fetch_arrivals(
    airport: str,
    begin: int,
    end: int,
    *,
    cache_dir: Path | str | None = DEFAULT_CACHE_DIR,
    proxy: str | None = DEFAULT_PROXY,
    timeout_s: float = 20.0,
    max_attempts: int = 3,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> list[dict]:
    """Arrivals JSON rows for ``airport`` between unix seconds begin/end.

    Cached on first success (replaying the cache never touches the
    network). A 403 fails immediately with the registration hint -- OpenSky
    only serves the last ~24 h anonymously, so retrying cannot help. A 404
    is a valid "no arrivals recorded in this window" answer (empty list).
    Connection errors and 5xx are retried over alternating direct/proxy
    paths.
    """
    import httpx  # lazy: only the importer needs it

    airport = airport.upper()
    client_id = client_id or os.environ.get("OPENSKY_CLIENT_ID")
    client_secret = client_secret or os.environ.get("OPENSKY_CLIENT_SECRET")
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
            headers = _bearer_token(client_id, client_secret, use_proxy)
            with httpx.Client(
                timeout=timeout_s, proxy=use_proxy, trust_env=False
            ) as client:
                res = client.get(
                    ARRIVALS_URL,
                    params={"airport": airport, "begin": begin, "end": end},
                    headers=headers,
                )
            if res.status_code == 403:
                raise RuntimeError(
                    "OpenSky 拒绝访问（403）：匿名账号只能读取最近约 24 小时的到达数据。"
                    "免费注册 opensky-network.org 后，在网站首页 Profile 页创建 "
                    "OAuth2 Client ID / Secret 并填入上方输入框，即可访问历史数据"
                    "（400 次/天）。"
                )
            if res.status_code == 404:
                return []  # valid: no arrivals recorded in this window
            res.raise_for_status()
            rows = res.json()
        except RuntimeError:
            raise  # actionable policy errors must not be retried or wrapped
        except Exception as exc:  # noqa: BLE001 - network or HTTP errors
            last_error = exc
            if attempt < max_attempts - 1:
                time.sleep(min(2**attempt, 4))
            continue
        if not isinstance(rows, list):
            last_error = RuntimeError(f"unexpected payload: {rows!r:.120}")
            if attempt < max_attempts - 1:
                time.sleep(min(2**attempt, 4))
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
