"""API tests: endpoints agree with the underlying package computation."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="server extra not installed")
pytest.importorskip("httpx", reason="httpx not installed")
from fastapi.testclient import TestClient  # noqa: E402

from routelab.airports import AirportDB  # noqa: E402
from routelab.performance import ProxyAircraft  # noqa: E402
from routelab.planning import plan_leg  # noqa: E402
from server import app  # noqa: E402

client = TestClient(app)

try:
    import openap  # noqa: F401

    HAVE_OPENAP = True
except ImportError:  # Python 3.10 CI leg installs no openap
    HAVE_OPENAP = False

openap_required = pytest.mark.skipif(
    not HAVE_OPENAP, reason="openap not installed (needs Python 3.11+)"
)


def test_airports_endpoint_respects_limit() -> None:
    res = client.get("/api/airports", params={"limit": 500})
    assert res.status_code == 200
    body = res.json()
    assert 0 < len(body) <= 500
    assert all({"ident", "lat_deg", "runway_m"} <= set(r) for r in body)


def test_airports_search_endpoint() -> None:
    res = client.get("/api/airports/search", params={"q": "urc", "limit": 5})
    assert res.status_code == 200
    body = res.json()
    assert body[0]["ident"] == "ZWWW"          # IATA exact/prefix first
    assert all({"lat_deg", "lon_deg", "runway_m"} <= set(r) for r in body)


def test_airports_search_endpoint_short_query() -> None:
    res = client.get("/api/airports/search", params={"q": "Z"})
    assert res.status_code == 200
    assert res.json() == []


def test_presets_endpoint_has_three_aircraft() -> None:
    body = client.get("/api/presets").json()
    assert len(body) == 3
    assert all("mtow_kg" in v for v in body.values())


def test_route_endpoint_matches_plan_leg() -> None:
    res = client.post("/api/route", json={
        "origin": "ZSPD", "destination": "ZWWW", "alternate": "ZWSH",
        "payload_kg": 15_000, "headwind_kmh": 0,
    })
    assert res.status_code == 200
    body = res.json()
    plan = plan_leg(AirportDB(), ProxyAircraft(), "ZSPD", "ZWWW", "ZWSH", 15_000)
    assert body["distance_km"] == pytest.approx(plan.route.distance_km)
    assert body["block_kg"] == pytest.approx(plan.fuel.block_kg)
    assert body["feasible"] is plan.feasible
    assert body["max_payload_on_leg_kg"] == pytest.approx(plan.max_payload_on_leg_kg)


def test_route_unknown_airport_returns_404() -> None:
    res = client.post("/api/route", json={"origin": "ZSPD", "destination": "XXXX"})
    assert res.status_code == 404


def test_envelope_endpoint_monotonic() -> None:
    res = client.post("/api/envelope", json={"reserve_kg": 2_500})
    assert res.status_code == 200
    body = res.json()
    ranges = body["max_range_km"]
    assert len(ranges) == len(body["payload_kg"])
    assert all(b >= a - 1e-6 for a, b in zip(ranges, ranges[1:]))


def test_hot_endpoint_returns_margins_and_critical_temp() -> None:
    res = client.post("/api/hot", json={
        "airports": [{"ident": "ZSPD", "temp_c": 33}, {"ident": "ZWSH", "temp_c": 34}],
    })
    assert res.status_code == 200
    rows = {r["ident"]: r for r in res.json()}
    assert rows["ZWSH"]["margin_m"] < rows["ZSPD"]["margin_m"]
    assert rows["ZWSH"]["critical_temp_c"] is not None
    assert rows["ZSPD"]["elevation_ft"] == 13


def test_hot_unknown_airport_returns_404() -> None:
    res = client.post("/api/hot", json={"airports": [{"ident": "XXXX", "temp_c": 30}]})
    assert res.status_code == 404


def test_frontend_index_served() -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "航线运行分析台" in res.text


@openap_required
def test_aircraft_types_endpoint() -> None:
    res = client.get("/api/aircraft-types")
    assert res.status_code == 200
    assert "a320" in res.json()


@openap_required
def test_route_endpoint_openap_backend() -> None:
    res = client.post("/api/route", json={
        "origin": "ZSPD", "destination": "ZWWW", "alternate": "ZWSH",
        "payload_kg": 15_000, "backend": "openap", "actype": "a320",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["backend"] == "openap" and body["actype"] == "a320"
    plan = plan_leg(AirportDB(), ProxyAircraft(), "ZSPD", "ZWWW", "ZWSH",
                    15_000, backend="openap", actype="a320")
    assert body["block_kg"] == pytest.approx(plan.fuel.block_kg)
    assert body["feasible"] is plan.feasible


@openap_required
def test_route_endpoint_openap_unknown_actype_is_404() -> None:
    res = client.post("/api/route", json={
        "origin": "ZSPD", "destination": "ZWWW",
        "backend": "openap", "actype": "c919",
    })
    assert res.status_code == 404


@openap_required
def test_route_endpoint_openap_requires_actype() -> None:
    res = client.post("/api/route", json={
        "origin": "ZSPD", "destination": "ZWWW", "backend": "openap",
    })
    assert res.status_code == 400


def test_route_endpoint_rejects_unknown_backend() -> None:
    res = client.post("/api/route", json={
        "origin": "ZSPD", "destination": "ZWWW", "backend": "magic",
    })
    assert res.status_code == 422  # pydantic Literal validation


@openap_required
def test_envelope_endpoint_openap_backend() -> None:
    res = client.post("/api/envelope", json={
        "reserve_kg": 2_500, "backend": "openap", "actype": "a320",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["backend"] == "openap" and body["actype"] == "a320"
    ranges = body["max_range_km"]
    assert all(b >= a - 1e-6 for a, b in zip(ranges, ranges[1:]))
    assert ranges[-1] > ranges[0]


def test_delay_endpoint_synthetic_detects_injected_propagation() -> None:
    res = client.post("/api/delay", json={
        "source": "synthetic", "n_aircraft": 30, "n_days": 5, "seed": 7,
    })
    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "synthetic"
    assert body["summary"]["n_flights"] > 100
    assert body["summary"]["n_edges"] > 0
    lifts = [r["lift"] for r in body["inheritance"]]
    assert all(v is not None and v > 1.0 for v in lifts)  # injected by construction
    assert len(body["hubs"]) > 0 and len(body["flow"]) > 0
    assert body["hubs"][0]["label"]  # airport labels joined


def test_delay_endpoint_opensky_with_mocked_fetch(monkeypatch) -> None:
    import routelab.opensky as osky

    def fake_fetch(airport, begin, end, **kwargs):
        rows = []
        # 3 airframes x 55 rotations: enough rows, one well-sampled route
        for k in range(165):
            icao = f"abc{k // 55:03d}"
            base = 1_700_000_000 + k * 14_400
            rows.append({
                "icao24": icao, "firstSeen": base, "lastSeen": base + 4_800,
                "estDepartureAirport": "ZSPD", "estArrivalAirport": "ZWWW",
                "callsign": "CSN123  ",
            })
        return rows

    monkeypatch.setattr(osky, "fetch_arrivals", fake_fetch)
    res = client.post("/api/delay", json={
        "source": "opensky", "opensky_airport": "ZSPD", "opensky_days": 3,
    })
    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "opensky"
    assert body["summary"]["n_tails"] == 3


def test_delay_endpoint_opensky_failure_degrades(monkeypatch) -> None:
    import routelab.opensky as osky

    def dead_fetch(*a, **k):
        raise RuntimeError("anonymous rate limit")

    monkeypatch.setattr(osky, "fetch_arrivals", dead_fetch)
    res = client.post("/api/delay", json={"source": "opensky"})
    assert res.status_code == 502
    assert "OpenSky" in res.json()["detail"]
