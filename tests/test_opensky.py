"""OpenSky importer tests: schema mapping, cache replay, retry exhaustion.

All tests are offline: the live fetch is exercised only by monkeypatched
httpx calls, never against the real API.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("httpx", reason="httpx not installed")

from routelab import opensky  # noqa: E402
from routelab.network import build_tail_chain, delay_inheritance  # noqa: E402


def sample_rows() -> list[dict]:
    # icao24 "abc000" flies PVG->URC twice; "def111" once (route below the
    # min_route_samples threshold and thus dropped)
    def row(icao: str, dep: int, arr: int, dest: str) -> dict:
        return {
            "icao24": icao,
            "firstSeen": dep,
            "lastSeen": arr,
            "estDepartureAirport": "ZSPD",
            "estArrivalAirport": dest,
            "callsign": "CSN123  ",
        }

    return [
        row("abc000", 1_700_000_000, 1_700_004_600, "ZWWW"),  # 77 min block
        row("abc000", 1_700_010_800, 1_700_015_600, "ZWWW"),  # 80 min block
        row("abc000", 1_700_021_600, 1_700_026_500, "ZWWW"),  # 82 min block
        row("def111", 1_700_030_000, 1_700_032_000, "ZWSH"),  # 33 min, lone flight
    ]


def test_arrivals_to_flights_schema_and_pseudo_schedule() -> None:
    flights = opensky.arrivals_to_flights(sample_rows(), min_route_samples=3)
    assert list(flights.columns) == [
        "registration", "origin", "destination", "sched_dep", "sched_arr", "actual_arr",
    ]
    assert set(flights["registration"]) == {"ABC000"}   # lone route dropped
    assert (flights["origin"] == "ZSPD").all()
    # pseudo schedule: sched_arr = firstSeen + route median block (80 min)
    block = (flights["actual_arr"] - flights["sched_dep"]).dt.total_seconds() / 60
    sched_block = (flights["sched_arr"] - flights["sched_dep"]).dt.total_seconds() / 60
    assert sched_block.nunique() == 1
    delays = block - sched_block
    assert delays.round(1).to_list() == [-3.3, 0.0, 1.7]


def test_mapped_flights_feed_the_network_pipeline() -> None:
    flights = opensky.arrivals_to_flights(sample_rows(), min_route_samples=3)
    chain = build_tail_chain(flights, max_turnaround_min=180)
    # abc000: arr 1_700_004_600 -> next dep 1_700_010_800: turnaround 103 min
    assert sum(len(v) for v in chain.values()) == 2
    stats = delay_inheritance(flights, chain, threshold_min=1.5)
    assert stats["n_pairs"] == 2


def test_fetch_arrivals_uses_cache_without_network(tmp_path, monkeypatch) -> None:
    cache_dir = tmp_path / "opensky"
    cache_dir.mkdir()
    cached = [{"icao24": "abc000", "firstSeen": 1, "lastSeen": 2,
               "estDepartureAirport": "ZSPD", "estArrivalAirport": "ZWWW"}]
    (cache_dir / "arrivals_ZSPD_1_2.json").write_text(json.dumps(cached), encoding="utf-8")

    def boom(*a, **k):  # any network touch fails the test
        raise AssertionError("network must not be touched when the cache hits")

    monkeypatch.setattr("httpx.Client", boom)
    rows = opensky.fetch_arrivals("ZSPD", 1, 2, cache_dir=cache_dir)
    assert rows == cached


def test_fetch_arrivals_exhausts_retries_and_writes_cache_on_success(tmp_path) -> None:
    calls = {"n": 0}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict]:
            return sample_rows()[:1]

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

        def get(self, url, params=None):
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError("connection reset")
            return FakeResponse()

    monkey = pytest.MonkeyPatch()
    monkey.setattr("httpx.Client", FakeClient)
    try:
        rows = opensky.fetch_arrivals(
            "ZSPD", 1, 2, cache_dir=tmp_path, max_attempts=5,
        )
    finally:
        monkey.undo()
    assert calls["n"] == 3                    # two failures then success
    assert rows[0]["icao24"] == "ABC000".lower()
    # and the payload was cached for offline replay
    assert (tmp_path / "arrivals_ZSPD_1_2.json").exists()
    assert json.loads((tmp_path / "arrivals_ZSPD_1_2.json").read_text()) == rows


def test_fetch_arrivals_raises_after_all_attempts(tmp_path, monkeypatch) -> None:
    class DeadClient:
        def __init__(self, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

        def get(self, url, params=None):
            raise OSError("down")

    monkeypatch.setattr("httpx.Client", DeadClient)
    monkeypatch.setattr(opensky.time, "sleep", lambda s: None)  # speed up
    with pytest.raises(RuntimeError, match="failed after"):
        opensky.fetch_arrivals("ZSPD", 1, 2, cache_dir=tmp_path, max_attempts=2)
