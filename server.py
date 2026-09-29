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

from dataclasses import asdict
from pathlib import Path

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

app = FastAPI(
    title="c919-routelab API",
    description=(
        "Learning-grade narrow-body route operations analysis "
        "(public data only, unofficial -- not for flight planning)."
    ),
    version="0.1.0",
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


class EnvelopeRequest(BaseModel):
    aircraft: AircraftIn = AircraftIn()
    reserve_kg: float = Field(default=0.0, ge=0)
    step_kg: float = Field(default=100.0, gt=0)


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
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
    }


@app.post("/api/envelope")
def envelope(req: EnvelopeRequest) -> dict:
    """Payload-range envelope points for one aircraft."""
    df = payload_range_table(
        req.aircraft.to_proxy(), step_kg=req.step_kg, reserve_kg=req.reserve_kg
    )
    return {
        "payload_kg": df["payload_kg"].tolist(),
        "max_range_km": df["max_range_km"].round(1).tolist(),
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


# Serve the frontend last so /api/* routes take precedence.
app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
