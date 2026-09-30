"""FastAPI backend: REST API over the routelab package + serves the web frontend.

All computation lives in the ``routelab`` package -- this layer only exposes
it as JSON endpoints and hosts ``web/`` (plain HTML/JS + Plotly frontend).

Run (development, auto-reload)::

    uvicorn server:app --reload --port 8300

Run (one command, opens the browser)::

    python run_server.py

Interactive API docs: http://127.0.0.1:8300/docs
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from routelab.airports import AirportDB
from routelab.fuel import FuelPolicy
from routelab.performance import (
    ProxyAircraft,
    isa_temperature_c,
    payload_range_table,
    takeoff_field_length_m,
)
from routelab.planning import plan_leg
from routelab.presets import PRESET_AIRCRAFT


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # prebuild the OpenAP grid integrator so the first user request is fast
    try:
        from routelab.openap_backend import _integrator

        _integrator("a320")
    except Exception:
        pass  # openap not installed: the simple backend serves everything
    yield


app = FastAPI(
    title="c919-routelab API",
    description=(
        "Learning-grade narrow-body route operations analysis "
        "(public data only, unofficial -- not for flight planning)."
    ),
    version="1.0.0",
    lifespan=_lifespan,
)
_DB = AirportDB()

_WEB_DIR = Path(__file__).resolve().parent / "web"


# ---------------------------------------------------------------- models


class AircraftIn(BaseModel):
    """Editable proxy-aircraft parameters (defaults = A320neo-class proxy)."""

    mtow_kg: float = Field(default=79_000, gt=0)
    oew_kg: float = Field(default=44_300, gt=0)
    max_fuel_kg: float = Field(default=19_000, gt=0)
    max_payload_kg: float = Field(default=18_500, gt=0)
    cruise_tas_kmh: float = Field(default=833, gt=0)
    cruise_fuel_kg_per_h: float = Field(default=2_300, gt=0)

    def to_proxy(self) -> ProxyAircraft:
        return ProxyAircraft(
            name="custom",
            mtow_kg=self.mtow_kg,
            oew_kg=self.oew_kg,
            max_fuel_kg=self.max_fuel_kg,
            max_payload_kg=self.max_payload_kg,
            cruise_tas_kmh=self.cruise_tas_kmh,
            cruise_fuel_kg_per_h=self.cruise_fuel_kg_per_h,
        )


class PolicyIn(BaseModel):
    """Simplified fuel-planning parameters."""

    contingency_frac: float = Field(default=0.05, ge=0, le=1)
    final_reserve_min: float = Field(default=30.0, gt=0)
    taxi_kg: float = Field(default=200.0, ge=0)
    approach_allowance_kg: float = Field(default=200.0, ge=0)

    def to_policy(self) -> FuelPolicy:
        return FuelPolicy(
            contingency_frac=self.contingency_frac,
            final_reserve_min=self.final_reserve_min,
            taxi_kg=self.taxi_kg,
            approach_allowance_kg=self.approach_allowance_kg,
        )


class RouteRequest(BaseModel):
    origin: str
    destination: str
    alternate: str = ""
    payload_kg: float = Field(default=15_000, ge=0)
    headwind_kmh: float = 0.0
    aircraft: AircraftIn = AircraftIn()
    policy: PolicyIn = PolicyIn()
    backend: Literal["simple", "openap"] = "simple"
    actype: str | None = None


class EnvelopeRequest(BaseModel):
    aircraft: AircraftIn = AircraftIn()
    reserve_kg: float = Field(default=0.0, ge=0)
    step_kg: float = Field(default=100.0, gt=0)
    backend: Literal["simple", "openap"] = "simple"
    actype: str | None = None


class HotAirportIn(BaseModel):
    ident: str
    temp_c: float


class HotRequest(BaseModel):
    airports: list[HotAirportIn]


# --------------------------------------------------------------- helpers


def _critical_temp_c(elev_ft: float, runway_m: float) -> float | None:
    """Lowest temperature (0.5 degC grid) at which required TOFL exceeds runway."""
    isa = isa_temperature_c(elev_ft)
    for temp in np.arange(0.0, 60.5, 0.5):
        if takeoff_field_length_m(elev_ft, temp - isa) > runway_m:
            return float(temp)
    return None


# -------------------------------------------------------------- endpoints


@app.get("/api/airports")
def list_airports() -> list[dict]:
    """All bundled airports with position, elevation and longest runway."""
    return [
        {
            **asdict(a),
            "runway_m": _DB.max_runway_m(a),
        }
        for a in _DB.all()
    ]


@app.get("/api/presets")
def list_presets() -> dict[str, dict]:
    """Public-spec comparison aircraft (same parameter sets as cases/01)."""
    return {name: asdict(ac) for name, ac in PRESET_AIRCRAFT.items()}


@app.get("/api/aircraft-types")
def list_aircraft_types() -> list[str]:
    """Aircraft type codes supported by the OpenAP backend (503 if not installed)."""
    try:
        from routelab.openap_backend import supported_aircraft

        return supported_aircraft()
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _backend_kwargs(req: RouteRequest | EnvelopeRequest) -> dict:
    """Common backend plumbing with friendly error mapping."""
    kwargs: dict = {"backend": req.backend}
    if req.backend == "openap":
        try:
            from routelab import openap_backend as ob

            if req.actype:
                supported = ob.supported_aircraft()
                if req.actype.lower() not in supported:
                    raise HTTPException(
                        status_code=404,
                        detail=f"aircraft type {req.actype!r} not in OpenAP; "
                        f"try e.g. 'a320', 'b738' (GET /api/aircraft-types)",
                    )
            kwargs["actype"] = req.actype
        except ImportError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    return kwargs


@app.post("/api/route")
def plan_route(req: RouteRequest) -> dict:
    """Plan one leg: distance, block fuel breakdown, feasibility."""
    try:
        plan = plan_leg(
            _DB,
            req.aircraft.to_proxy(),
            req.origin,
            req.destination,
            req.alternate,
            req.payload_kg,
            req.headwind_kmh,
            req.policy.to_policy(),
            **_backend_kwargs(req),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "origin": plan.route.origin,
        "destination": plan.route.destination,
        "distance_km": plan.route.distance_km,
        "distance_nm": plan.route.distance_nm,
        "bearing_deg": plan.route.bearing_deg,
        "alternate_distance_km": plan.alternate_distance_km,
        "alternate_note": plan.alternate_note,
        "trip_time_h": plan.trip_time_h,
        "trip_kg": plan.fuel.trip_kg,
        "contingency_kg": plan.fuel.contingency_kg,
        "alternate_kg": plan.fuel.alternate_kg,
        "final_reserve_kg": plan.fuel.final_reserve_kg,
        "taxi_kg": plan.fuel.taxi_kg,
        "block_kg": plan.fuel.block_kg,
        "fuel_limit_kg": plan.fuel_limit_kg,
        "feasible": plan.feasible,
        "max_payload_on_leg_kg": plan.max_payload_on_leg_kg,
        "backend": plan.backend,
        "actype": plan.actype,
    }


@app.post("/api/envelope")
def envelope(req: EnvelopeRequest) -> dict:
    """Payload-range envelope points for one aircraft."""
    try:
        if req.backend == "openap":
            from routelab.openap_backend import payload_range_table_openap

            if not req.actype:
                raise HTTPException(
                    status_code=400, detail="backend 'openap' needs 'actype'"
                )
            rows = payload_range_table_openap(
                req.actype,
                max_payload_kg=req.aircraft.max_payload_kg,
                tank_capacity_kg=req.aircraft.max_fuel_kg,
                step_kg=max(req.step_kg, 250.0),
                reserve_kg=req.reserve_kg,
            )
            return {
                "payload_kg": [r["payload_kg"] for r in rows],
                "max_range_km": [round(r["max_range_km"], 1) for r in rows],
                "backend": "openap",
                "actype": req.actype.lower(),
            }
        df = payload_range_table(
            req.aircraft.to_proxy(), step_kg=req.step_kg, reserve_kg=req.reserve_kg
        )
    except (ValueError, ImportError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "payload_kg": df["payload_kg"].tolist(),
        "max_range_km": df["max_range_km"].round(1).tolist(),
        "backend": "simple",
        "actype": None,
    }


@app.post("/api/hot")
def hot_high(req: HotRequest) -> list[dict]:
    """Heuristic field-length margins and critical temperatures."""
    rows = []
    for item in req.airports:
        try:
            airport = _DB.get(item.ident)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        isa = isa_temperature_c(airport.elevation_ft)
        required = takeoff_field_length_m(airport.elevation_ft, item.temp_c - isa)
        available = _DB.max_runway_m(airport) or 0.0
        rows.append(
            {
                "ident": airport.ident,
                "iata": airport.iata,
                "name": airport.name,
                "elevation_ft": airport.elevation_ft,
                "isa_temp_c": round(isa, 1),
                "temp_c": item.temp_c,
                "isa_dev_c": round(item.temp_c - isa, 1),
                "required_tofl_m": round(required, 1),
                "runway_m": available,
                "margin_m": round(available - required, 1),
                "critical_temp_c": _critical_temp_c(airport.elevation_ft, available),
            }
        )
    return rows


class DelayRequest(BaseModel):
    """Delay-propagation analysis parameters (synthetic or OpenSky data)."""

    source: Literal["synthetic", "opensky"] = "synthetic"
    n_aircraft: int = Field(default=120, ge=5, le=500)
    n_days: int = Field(default=14, ge=3, le=60)
    seed: int = Field(default=42)
    opensky_airport: str = "ZSPD"
    opensky_days: int = Field(default=3, ge=1, le=14)


def _airport_label(ident: str) -> str:
    """ICAO code + name when the bundled sample knows the airport."""
    try:
        return f"{ident} {_DB.get(ident).name}"
    except KeyError:
        return ident


@app.post("/api/delay")
def delay_analysis(req: DelayRequest) -> dict:
    """Tail-rotation delay analysis: inheritance lift, hubs, airport flow.

    ``source="synthetic"`` runs the honest synthetic fleet generator;
    ``source="opensky"`` pulls real arrivals (cached on disk, retried) and
    degrades with 502 when the anonymous API refuses.
    """
    import time as _time

    from routelab.network import (
        airport_centrality,
        build_tail_chain,
        delay_inheritance,
        propagation_hubs,
        synthesize_rotations,
    )

    if req.source == "opensky":
        try:
            from routelab.opensky import arrivals_to_flights, fetch_arrivals

            end = int(_time.time()) - 6 * 3600  # feed lags ~5.5 h
            begin = end - req.opensky_days * 86_400
            raw = fetch_arrivals(
                req.opensky_airport.upper(), begin, end,
                cache_dir="data_cache/opensky",
            )
            flights = arrivals_to_flights(raw, min_route_samples=5)
            if len(flights) < 100:
                raise ValueError(
                    f"only {len(flights)} usable rows for "
                    f"{req.opensky_airport.upper()} in this window"
                )
        except (ImportError, RuntimeError, ValueError) as exc:
            raise HTTPException(
                status_code=502,
                detail=f"OpenSky 数据不可用：{exc}",
            ) from exc
    else:
        flights = synthesize_rotations(
            n_aircraft=req.n_aircraft, n_days=req.n_days, seed=req.seed
        )

    chain = build_tail_chain(flights, max_turnaround_min=180)
    inheritance = [
        delay_inheritance(flights, chain, threshold_min=t) for t in (15, 30, 60)
    ]
    hubs = propagation_hubs(flights, chain, threshold_min=15, min_turnarounds=30)
    flow = airport_centrality(flights, chain, threshold_min=15)
    delays_min = flights["actual_arr"] - flights["sched_arr"]

    return {
        "source": req.source,
        "summary": {
            "n_flights": int(len(flights)),
            "n_tails": int(flights["registration"].nunique()),
            "n_edges": int(sum(len(v) for v in chain.values())),
            "mean_delay_min": round(delays_min.dt.total_seconds().mean() / 60.0, 1),
        },
        "inheritance": [
            {
                "threshold_min": s["threshold_min"],
                "n_pairs": s["n_pairs"],
                "n_prev_delayed": s["n_prev_delayed"],
                "n_propagated": s["n_propagated"],
                "p_next_delayed": round(s["p_next_delayed"], 3)
                if s["p_next_delayed"] is not None else None,
                "p_next_given_prev": round(s["p_next_given_prev"], 3)
                if s["p_next_given_prev"] is not None else None,
                "lift": round(s["lift"], 2) if s["lift"] is not None else None,
            }
            for s in inheritance
        ],
        "hubs": [
            {
                "airport": ident,
                "label": _airport_label(ident),
                "n_turnarounds": int(r["n_turnarounds"]),
                "n_propagated": int(r["n_propagated"]),
                "propagation_ratio": float(r["propagation_ratio"]),
                "inherited_delay_min": float(r["inherited_delay_min"]),
            }
            for ident, r in hubs.head(8).iterrows()
        ],
        "flow": [
            {
                "airport": ident,
                "label": _airport_label(ident),
                "sent": float(r["sent"]),
                "received": float(r["received"]),
                "net": float(r["net"]),
            }
            for ident, r in flow.head(8).iterrows()
        ],
    }


# Serve the frontend last so /api/* routes take precedence.
app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
