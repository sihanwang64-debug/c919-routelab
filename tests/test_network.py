"""Unit tests for the delay-propagation network metrics."""

from __future__ import annotations

import pandas as pd
import pytest

from routelab.network import (
    airport_centrality,
    build_tail_chain,
    delay_inheritance,
    propagation_hubs,
    synthesize_rotations,
)


def make_flights(rows: list[dict]) -> pd.DataFrame:
    base = pd.Timestamp("2026-07-01")
    out = []
    for r in rows:
        out.append(
            {
                "registration": r["registration"],
                "origin": r["origin"],
                "destination": r["destination"],
                "sched_dep": base + pd.to_timedelta(r["dep_min"], unit="min"),
                "sched_arr": base
                + pd.to_timedelta(r["dep_min"] + r["block_min"], unit="min"),
                "actual_arr": base
                + pd.to_timedelta(
                    r["dep_min"] + r["block_min"] + r.get("delay_min", 0.0),
                    unit="min",
                ),
            }
        )
    return pd.DataFrame(out)


def test_build_tail_chain_links_consecutive_legs() -> None:
    # one airframe: A->B (morning), B->C (turnaround 60 min), C->A (next day)
    flights = make_flights(
        [
            {"registration": "SIM-1", "origin": "A", "destination": "B",
             "dep_min": 8 * 60, "block_min": 100},
            {"registration": "SIM-1", "origin": "B", "destination": "C",
             "dep_min": 11 * 60, "block_min": 90},
            {"registration": "SIM-1", "origin": "C", "destination": "A",
             "dep_min": 40 * 60, "block_min": 120},
        ]
    )
    chain = build_tail_chain(flights)
    assert list(chain[0]) == [1]       # morning leg feeds the midday leg
    assert chain.get(1) is None        # next-day rest breaks the chain


def test_build_tail_chain_ignores_other_airframes() -> None:
    flights = make_flights(
        [
            {"registration": "SIM-1", "origin": "A", "destination": "B",
             "dep_min": 8 * 60, "block_min": 100},
            {"registration": "SIM-2", "origin": "B", "destination": "C",
             "dep_min": 11 * 60, "block_min": 90},
        ]
    )
    assert build_tail_chain(flights) == {}


def test_build_tail_chain_respects_turnaround_window() -> None:
    # 4-hour turnaround exceeds the default 180-minute window
    flights = make_flights(
        [
            {"registration": "SIM-1", "origin": "A", "destination": "B",
             "dep_min": 8 * 60, "block_min": 100},
            {"registration": "SIM-1", "origin": "B", "destination": "C",
             "dep_min": 13 * 60, "block_min": 90},
        ]
    )
    assert build_tail_chain(flights) == {}


def test_missing_columns_rejected() -> None:
    with pytest.raises(ValueError, match="missing required columns"):
        build_tail_chain(pd.DataFrame([{"registration": "X"}]))
    with pytest.raises(ValueError, match="empty"):
        build_tail_chain(pd.DataFrame(columns=list(
            "registration origin destination sched_dep sched_arr actual_arr".split()
        )))


def test_inheritance_lift_detects_injected_propagation() -> None:
    # 25 tails propagate (inbound 60 min late -> outbound 60 min late) and
    # 25 tails run on time: P(next|prev)=1 against baseline P(next)=0.5,
    # so the lift must come out at exactly 2.0
    rows = []
    for k in range(25):
        rows.append(
            {"registration": f"S{k:03d}", "origin": "A", "destination": "B",
             "dep_min": 8 * 60, "block_min": 90, "delay_min": 60.0}
        )
        rows.append(
            {"registration": f"S{k:03d}", "origin": "B", "destination": "C",
             "dep_min": 10 * 60, "block_min": 90, "delay_min": 60.0}
        )
        rows.append(
            {"registration": f"R{k:03d}", "origin": "A", "destination": "B",
             "dep_min": 9 * 60, "block_min": 90, "delay_min": 0.0}
        )
        rows.append(
            {"registration": f"R{k:03d}", "origin": "B", "destination": "C",
             "dep_min": 11 * 60, "block_min": 90, "delay_min": 0.0}
        )
    flights = make_flights(rows)
    chain = build_tail_chain(flights)
    stats = delay_inheritance(flights, chain, threshold_min=15)
    assert stats["n_pairs"] == 50
    assert stats["n_prev_delayed"] == 25
    assert stats["p_next_given_prev"] == pytest.approx(1.0)
    assert stats["p_next_delayed"] == pytest.approx(0.5)
    assert stats["lift"] == pytest.approx(2.0)

    # control: reshuffling actual arrivals across the whole table breaks the
    # pairing and must push the lift down toward 1
    ctrl_flights = flights.copy()
    ctrl_flights["actual_arr"] = flights["actual_arr"].sample(frac=1, random_state=0).to_list()
    ctrl = delay_inheritance(ctrl_flights, build_tail_chain(ctrl_flights), 15)
    assert ctrl["lift"] is None or ctrl["lift"] < stats["lift"]


def test_inheritance_zero_delay_baseline_is_none() -> None:
    flights = make_flights(
        [
            {"registration": "SIM-1", "origin": "A", "destination": "B",
             "dep_min": 8 * 60, "block_min": 90, "delay_min": 0.0},
            {"registration": "SIM-1", "origin": "B", "destination": "C",
             "dep_min": 10 * 60, "block_min": 90, "delay_min": 0.0},
        ]
    )
    stats = delay_inheritance(flights, build_tail_chain(flights), threshold_min=15)
    assert stats["p_next_delayed"] == 0
    assert stats["p_next_given_prev"] is None
    assert stats["lift"] is None


def test_propagation_hubs_rank_and_min_filter() -> None:
    # 40 propagating turnarounds at HUB, 2 at TINY
    rows = []
    for k in range(40):
        rows.append({"registration": f"S{k:03d}", "origin": "A", "destination": "HUB",
                     "dep_min": 8 * 60, "block_min": 90, "delay_min": 60.0})
        rows.append({"registration": f"S{k:03d}", "origin": "HUB", "destination": "B",
                     "dep_min": 10 * 60, "block_min": 90, "delay_min": 60.0})
    for k in range(2):
        rows.append({"registration": f"T{k:03d}", "origin": "A", "destination": "TINY",
                     "dep_min": 8 * 60, "block_min": 90, "delay_min": 60.0})
        rows.append({"registration": f"T{k:03d}", "origin": "TINY", "destination": "B",
                     "dep_min": 10 * 60, "block_min": 90, "delay_min": 60.0})
    flights = make_flights(rows)
    chain = build_tail_chain(flights)
    hubs = propagation_hubs(flights, chain, threshold_min=15, min_turnarounds=20)
    assert hubs.index.to_list() == ["HUB"]          # TINY filtered out
    assert hubs.loc["HUB", "n_propagated"] == 40
    assert hubs.loc["HUB", "propagation_ratio"] == pytest.approx(1.0)


def test_airport_centrality_flow_direction() -> None:
    rows = []
    for k in range(30):
        rows.append({"registration": f"C{k:03d}", "origin": "ORIG", "destination": "HUB",
                     "dep_min": 8 * 60, "block_min": 90, "delay_min": 50.0})
        rows.append({"registration": f"C{k:03d}", "origin": "HUB", "destination": "DEST",
                     "dep_min": 10 * 60, "block_min": 90, "delay_min": 40.0})
    flights = make_flights(rows)
    cent = airport_centrality(flights, build_tail_chain(flights), threshold_min=15)
    assert cent.loc["ORIG", "sent"] == pytest.approx(30 * 40.0)  # inbound delay pushed on
    assert cent.loc["DEST", "received"] == pytest.approx(30 * 40.0)
    assert cent.loc["ORIG", "net"] > 0 and cent.loc["DEST", "net"] < 0


def test_synthetic_rotations_reproducible_and_propagating() -> None:
    a = synthesize_rotations(n_aircraft=20, n_days=5, seed=7)
    b = synthesize_rotations(n_aircraft=20, n_days=5, seed=7)
    pd.testing.assert_frame_equal(a, b)
    assert a["registration"].str.startswith("SIM-").all()  # clearly synthetic
    chain = build_tail_chain(a)
    stats = delay_inheritance(a, chain, threshold_min=15)
    # the generator injects propagation by construction
    assert stats["n_pairs"] > 100
    assert stats["lift"] is not None and stats["lift"] > 1.3
