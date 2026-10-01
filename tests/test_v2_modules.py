"""Tests for the v2 modules: weight limits, emissions, airport adaptation."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from routelab.adaptability import adapt_for_airport, plateau_airports, scan_region
from routelab.airports import AirportDB
from routelab.emissions import KEROSENE_CO2_KG_PER_KG, co2_from_fuel_kg
from routelab.performance import (
    ProxyAircraft,
    landing_distance_m,
    max_weight_fraction_for_runway,
    payload_range_table,
    takeoff_field_length_m,
)
from routelab.planning import plan_leg


@pytest.fixture(scope="module")
def db() -> AirportDB:
    return AirportDB()


# ------------------------------------------------- module C: weights


def test_mzfw_caps_payload_axis() -> None:
    ac = ProxyAircraft()  # MZFW-OEW = 18.2 t < structural 18.5 t
    df = payload_range_table(ac, step_kg=500)
    assert df["payload_kg"].max() == pytest.approx(ac.mzfw_kg - ac.oew_kg)
    assert df["payload_kg"].max() < ac.max_payload_kg


def test_binding_column_sequence() -> None:
    ac = ProxyAircraft()
    df = payload_range_table(ac, step_kg=500)
    bindings = df["binding"].to_list()
    assert bindings[0] == "MZFW/MLW"          # capped end
    assert "MTOW" in bindings and "tank" in bindings
    # the flat high-range segment must be tank-limited
    assert bindings[-1] == "tank"


def test_weight_fraction_validation() -> None:
    with pytest.raises(ValueError):
        takeoff_field_length_m(0.0, weight_fraction=1.2)


# ------------------------------------------------- module B: emissions


def test_co2_factor_conservation() -> None:
    assert co2_from_fuel_kg(1_000) == pytest.approx(3_160.0)
    assert co2_from_fuel_kg(0) == 0
    with pytest.raises(ValueError):
        co2_from_fuel_kg(-1)


def test_plan_leg_carries_co2(db: AirportDB):
    plan = plan_leg(db, ProxyAircraft(), "ZSPD", "ZWWW", "ZWSH", 15_000,
                    seats=ProxyAircraft().seats)
    assert plan.co2_kg == pytest.approx(plan.fuel.block_kg * KEROSENE_CO2_KG_PER_KG)
    assert plan.co2_per_seat_km == pytest.approx(
        plan.co2_kg / (ProxyAircraft().seats * plan.route.distance_km)
    )


# ------------------------------------------------- module A: adaptation


def test_tofl_weight_scaling_and_inverse() -> None:
    full = takeoff_field_length_m(0.0, weight_fraction=1.0)
    half = takeoff_field_length_m(0.0, weight_fraction=0.5)
    assert half == pytest.approx(full * 0.25)          # quadratic scaling
    frac = max_weight_fraction_for_runway(0.0, 0.0, full)
    assert frac == pytest.approx(1.0)                  # runway == requirement
    frac_short = max_weight_fraction_for_runway(0.0, 0.0, full * 0.25)
    assert frac_short == pytest.approx(0.5)
    frac_long = max_weight_fraction_for_runway(0.0, 0.0, full * 4)
    assert frac_long == 1.0                            # capped at MTOW


def test_landing_is_fraction_of_takeoff() -> None:
    assert landing_distance_m(0.0) == pytest.approx(0.65 * takeoff_field_length_m(0.0))


def test_adapt_sea_level_hub_is_ok(db: AirportDB):
    report = adapt_for_airport(db, ProxyAircraft(), "ZSPD")  # 13 ft, 4000 m
    assert report.verdict == "ok"
    assert report.max_weight_fraction == 1.0
    assert report.max_payload_kg == ProxyAircraft().max_payload_kg


def test_adapt_plateau_pair_daocheng_vs_bangda(db: AirportDB):
    # real-world pair from the full dataset: both ~14k ft, but Daocheng has
    # a 4,200 m runway vs Bangda's 4,500 m -- Daocheng must be tighter
    daocheng = adapt_for_airport(db, ProxyAircraft(), "ZUDC")
    bangda = adapt_for_airport(db, ProxyAircraft(), "ZUBD")
    assert daocheng.max_weight_fraction <= bangda.max_weight_fraction
    assert daocheng.verdict == "reduced" and daocheng.max_weight_fraction < 1.0
    assert bangda.verdict == "ok" and bangda.max_weight_fraction == 1.0
    assert daocheng.max_tow_kg < ProxyAircraft().mtow_kg
    # at frac 0.999 the cut comes off the FUEL first: the structural payload
    # still fits (weight room = max_tow - oew = 34.6 t > 18.5 t)
    assert daocheng.max_payload_kg == ProxyAircraft().max_payload_kg


def test_scan_region_filters(db: AirportDB):
    plateau = scan_region(db, ProxyAircraft(), country="CN",
                          min_elevation_ft=3500.0, min_runway_m=2000.0)
    assert plateau, "no plateau airports found"
    assert all(r.elevation_ft >= 3500.0 and r.country == "CN" for r in plateau)
    # worst-first ordering (infeasible before reduced before ok)
    order = {"infeasible": 0, "reduced": 1, "ok": 2}
    ranks = [order[r.verdict] for r in plateau]
    assert ranks == sorted(ranks)
    as_dicts = [asdict(r) for r in plateau]
    assert all(d["runway_m"] >= 2000.0 for d in as_dicts)


def test_plateau_airports_lists_high_cn_fields(db: AirportDB):
    fields = plateau_airports(db, min_elevation_ft=3500.0)
    idents = {f["ident"] for f in fields}
    assert {"ZWSH", "ZPPP"} & idents                 # Kashgar / Kunming
    assert all(f["elevation_ft"] >= 3500.0 for f in fields)
