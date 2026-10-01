"""Delay-propagation network analysis on aircraft rotation (tail) chains.

Consecutive legs flown by the same airframe form a chain: whatever delay a
landing carries can seep into the next departure during the turnaround. This
module turns a table of flights into that chain graph and answers three
questions:

1. **How strong is inheritance?** ``delay_inheritance`` compares
   P(next leg delayed | current leg delayed) against the unconditional
   baseline; a lift above 1 is the signature of propagation.
2. **Where does it concentrate?** ``propagation_hubs`` ranks turnaround
   airports by how often (and how much) delay crosses their apron.
3. **How does it flow network-wide?** ``airport_centrality`` aggregates
   propagated pairs into a weighted airport-to-airport graph and reports
   each airport's sending/receiving strength.

Input schema (one row per flight, column names fixed)::

    registration   airframe identity (civil registration or icao24)
    origin         departure airport code
    destination    arrival airport code
    sched_dep      scheduled departure (datetime)
    sched_arr      scheduled arrival (datetime)
    actual_arr     actual arrival (datetime)

Arrival delay is derived as ``actual_arr - sched_arr`` in minutes. All
metrics are learning-grade statistics on this chain model -- no crew,
maintenance or ATC slotting effects are modelled (docs/methodology.md).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = (
    "registration",
    "origin",
    "destination",
    "sched_dep",
    "sched_arr",
    "actual_arr",
)
DEFAULT_MAX_TURNAROUND_MIN = 180.0
DEFAULT_THRESHOLD_MIN = 15.0


def _validate(flights: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in flights.columns]
    if missing:
        raise ValueError(f"flights is missing required columns: {missing}")
    if flights.empty:
        raise ValueError("flights is empty")


def _with_delays(flights: pd.DataFrame) -> pd.DataFrame:
    """Copy of the input with parsed datetimes and arrival_delay_min."""
    df = flights.copy()
    for col in ("sched_dep", "sched_arr", "actual_arr"):
        df[col] = pd.to_datetime(df[col])
    df["arrival_delay_min"] = (
        df["actual_arr"] - df["sched_arr"]
    ).dt.total_seconds() / 60.0
    return df


def build_tail_chain(
    flights: pd.DataFrame, max_turnaround_min: float = DEFAULT_MAX_TURNAROUND_MIN
) -> dict[int, list[int]]:
    """Chain graph over flight rows: ``{row_index: [next_row_indices]}``.

    An edge ``i -> j`` exists when both legs share the airframe, ``j`` is
    the next scheduled departure of that airframe, and the planned
    turnaround ``sched_dep(j) - sched_arr(i)`` lies in
    ``[0, max_turnaround_min]`` (a same-day rotation; overnight rests
    reset the chain by design).
    """
    _validate(flights)
    df = flights.copy()
    for col in ("sched_dep", "sched_arr"):
        df[col] = pd.to_datetime(df[col])
    df = df.sort_values(["registration", "sched_dep"], kind="mergesort")

    chain: dict[int, list[int]] = {}
    for _, group in df.groupby("registration", sort=False):
        rows = group.index.to_list()
        for prev, cur in zip(rows, rows[1:]):
            turnaround = (
                df.at[cur, "sched_dep"] - df.at[prev, "sched_arr"]
            ).total_seconds() / 60.0
            if 0.0 <= turnaround <= max_turnaround_min:
                chain.setdefault(int(prev), []).append(int(cur))
    return chain


def _pair_table(
    flights: pd.DataFrame, chain: dict[int, list[int]], threshold_min: float
) -> pd.DataFrame:
    """One row per chain edge with both arrival delays and the hub airport."""
    df = _with_delays(flights)
    records = []
    for i, nexts in chain.items():
        for j in nexts:
            records.append(
                {
                    "i": i,
                    "j": j,
                    "hub": df.at[i, "destination"],
                    "origin": df.at[i, "origin"],
                    "next_origin": df.at[j, "origin"],
                    "next_dest": df.at[j, "destination"],
                    "delay_i": df.at[i, "arrival_delay_min"],
                    "delay_j": df.at[j, "arrival_delay_min"],
                    "propagated": (
                        df.at[i, "arrival_delay_min"] >= threshold_min
                        and df.at[j, "arrival_delay_min"] >= threshold_min
                    ),
                    "inherited_min": (
                        df.at[j, "arrival_delay_min"]
                        if df.at[i, "arrival_delay_min"] >= threshold_min
                        else np.nan
                    ),
                }
            )
    return pd.DataFrame(records)


def delay_inheritance(
    flights: pd.DataFrame,
    chain: dict[int, list[int]],
    threshold_min: float = DEFAULT_THRESHOLD_MIN,
) -> dict:
    """Inheritance statistics over chain edges.

    ``lift`` is P(next delayed | current delayed) / P(next delayed): values
    clearly above 1 mean delay travels along rotations rather than occurring
    independently. Returns ``None`` statistics when the sample is empty.
    """
    _validate(flights)
    pairs = _pair_table(flights, chain, threshold_min)
    n_pairs = int(len(pairs))
    n_prev = int(pairs["delay_i"].ge(threshold_min).sum()) if n_pairs else 0
    n_next = int(pairs["delay_j"].ge(threshold_min).sum()) if n_pairs else 0
    n_prop = int(pairs["propagated"].sum()) if n_pairs else 0

    p_next = n_next / n_pairs if n_pairs else None
    p_next_given_prev = n_prop / n_prev if n_prev else None
    lift = (
        p_next_given_prev / p_next
        if p_next_given_prev is not None and p_next and p_next > 0
        else None
    )
    return {
        "threshold_min": threshold_min,
        "n_pairs": n_pairs,
        "n_prev_delayed": n_prev,
        "n_next_delayed": n_next,
        "n_propagated": n_prop,
        "p_next_delayed": p_next,
        "p_next_given_prev": p_next_given_prev,
        "lift": lift,
    }


def propagation_hubs(
    flights: pd.DataFrame,
    chain: dict[int, list[int]],
    threshold_min: float = DEFAULT_THRESHOLD_MIN,
    min_turnarounds: int = 20,
) -> pd.DataFrame:
    """Rank turnaround airports by how much delay crosses their apron.

    ``propagation_ratio`` is the share of turnarounds where a delayed
    inbound led to a delayed outbound; ``inherited_delay_min`` sums the
    outbound delays of those propagated pairs. Airports with fewer than
    ``min_turnarounds`` sampled turnarounds are hidden (small-sample noise).
    """
    _validate(flights)
    pairs = _pair_table(flights, chain, threshold_min)
    if pairs.empty:
        return pd.DataFrame(
            columns=["n_turnarounds", "n_propagated", "propagation_ratio",
                     "inherited_delay_min"]
        )
    grouped = pairs.groupby("hub").agg(
        n_turnarounds=("i", "size"),
        n_propagated=("propagated", "sum"),
        inherited_delay_min=("inherited_min", "sum"),
    )
    grouped["propagation_ratio"] = grouped["n_propagated"] / grouped["n_turnarounds"]
    grouped = grouped[grouped["n_turnarounds"] >= min_turnarounds]
    return grouped.sort_values("propagation_ratio", ascending=False).round(2)


def airport_centrality(
    flights: pd.DataFrame,
    chain: dict[int, list[int]],
    threshold_min: float = DEFAULT_THRESHOLD_MIN,
) -> pd.DataFrame:
    """Airport-level flow graph from propagated pairs.

    Every propagated pair (leg i into hub A, leg j out of A) contributes a
    weighted edge ``origin(i) -> destination(j)``: delay received at A
    flowing onward to the next destination. ``sent``/``received`` are the
    weighted out/in strengths; ``net > 0`` marks airports that push more
    delay into the network than they receive. All airports touched by a
    propagated pair appear; sample sizes live in :func:`propagation_hubs`.
    """
    _validate(flights)
    pairs = _pair_table(flights, chain, threshold_min)
    prop = pairs[pairs["propagated"]] if not pairs.empty else pairs
    if prop.empty:
        return pd.DataFrame(columns=["sent", "received", "net"])
    flow: dict[tuple[str, str], float] = {}
    for row in prop.itertuples():
        key = (row.origin, row.next_dest)
        flow[key] = flow.get(key, 0.0) + float(row.delay_j)

    nodes = sorted({n for a, b in flow for n in (a, b)})
    stats = {n: {"sent": 0.0, "received": 0.0} for n in nodes}
    for (src, dst), weight in flow.items():
        stats[src]["sent"] += weight
        stats[dst]["received"] += weight
    out = pd.DataFrame(stats).T
    out["net"] = out["sent"] - out["received"]
    return out.round(1).sort_values("sent", ascending=False)


# ------------------------------------------------------------------ synth


def synthesize_rotations(
    n_aircraft: int = 120,
    n_days: int = 14,
    seed: int = 42,
    airport_pool: list[str] | None = None,
) -> pd.DataFrame:
    """Synthetic rotation schedule with delay propagation baked in.

    **This is not real traffic.** It generates a plausible three-week
    rotation plan for ``n_aircraft`` narrow-bodies over the bundled airport
    sample, then simulates delays with an explicit propagation mechanism
    (arrival delay carried into the next departure, minus schedule
    recovery, plus a fresh exogenous perturbation). Registrations use a
    ``SIM-`` prefix so nobody mistakes them for real airframes.

    Purpose: develop and demonstrate the network metrics offline, with a
    dataset whose ground-truth propagation strength is known by
    construction. Defaults reproduce with a fixed ``seed``.
    """
    rng = np.random.default_rng(seed)
    # a compact trunk network keeps rotations dense enough for the hub
    # metrics regardless of whether the bundled sample or the full 86k
    # OurAirports dataset is installed
    pool = airport_pool or [
        "ZSPD", "ZBAA", "ZGGG", "ZUUU", "ZLXY", "ZWWW", "ZWSH", "ZPPP",
    ]
    if len(pool) < 3:
        raise ValueError("airport_pool needs at least three airports")
    hub = pool[0]  # pool[0] acts as the main base airport

    records: list[dict] = []
    for ac in range(n_aircraft):
        registration = f"SIM-{ac:04d}"
        clock = pd.Timestamp("2026-07-01 06:20") + pd.to_timedelta(
            rng.integers(0, 90), unit="min"
        )
        origin = hub
        arr_delay = 0.0
        for _day in range(n_days):
            n_legs = int(rng.integers(3, 6))
            for _leg in range(n_legs):
                destination = rng.choice([p for p in pool if p != origin])
                distance_km = haversine_between(airport_db(), origin, destination)
                block_h = distance_km / 780.0 + 0.55
                sched_dep = clock
                sched_arr = clock + pd.to_timedelta(block_h * 60, unit="min")

                if _leg == 0:
                    # overnight rest: the rotation starts clean every day
                    arr_delay = float(max(0.0, rng.normal(3, 5)))
                else:
                    # propagation: carry the previous arrival delay into
                    # this departure, minus schedule recovery, plus a fresh
                    # exogenous perturbation (heavy tail for weather/ATC)
                    recovery = float(np.clip(rng.normal(22, 12), 0, None))
                    dep_delay = max(0.0, arr_delay - recovery)
                    if rng.random() < 0.18:
                        exogenous = float(rng.exponential(45) + 10)
                    else:
                        exogenous = float(max(0.0, rng.normal(3, 6)))
                    arr_delay = dep_delay + exogenous

                actual_arr = sched_arr + pd.to_timedelta(arr_delay, unit="min")
                records.append(
                    {
                        "registration": registration,
                        "origin": origin,
                        "destination": destination,
                        "sched_dep": sched_dep,
                        "sched_arr": sched_arr,
                        "actual_arr": actual_arr,
                        "arrival_delay_min": round(arr_delay, 1),
                    }
                )
                origin, clock = destination, sched_arr + pd.to_timedelta(
                    rng.integers(55, 115), unit="min"
                )
            # overnight rest resets the rotation
            clock = clock.normalize() + pd.to_timedelta(
                24 * 60 + rng.integers(370, 480), unit="min"
            )
    return pd.DataFrame.from_records(records)


def haversine_between(db, a: str, b: str) -> float:
    """Great-circle distance via the AirportDB (km); used by the synthesizer."""
    from routelab.greatcircle import haversine_distance_km

    x, y = db.get(a), db.get(b)
    return haversine_distance_km(x.lat_deg, x.lon_deg, y.lat_deg, y.lon_deg)


def airport_db():
    """Shared AirportDB (cached by the airports module across calls)."""
    from routelab.airports import AirportDB

    return AirportDB()
