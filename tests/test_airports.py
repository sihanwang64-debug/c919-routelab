from pathlib import Path

import pytest

from routelab.airports import AIRPORTS_CSV as AIRPORTS_CSV_REF
from routelab.airports import RUNWAYS_CSV as RUNWAYS_CSV_REF
from routelab.airports import AirportDB


@pytest.fixture(scope="module")
def db():
    return AirportDB()


def test_lookup_by_icao_and_iata(db):
    a = db.get("ZSPD")
    assert a.iata == "PVG"
    assert a.iso_country == "CN"
    assert db.get("PVG").ident == "ZSPD"


def test_unknown_code_raises_hint(db):
    with pytest.raises(KeyError, match="ROUTELAB_AIRPORTS_CSV"):
        db.get("ZZZZ")


def test_route_shanghai_urumqi(db):
    r = db.route("ZSPD", "ZWWW")
    assert 3000.0 <= r.distance_km <= 3500.0
    assert 270.0 <= r.bearing_deg <= 320.0


def test_by_country_and_runways(db):
    cn = db.by_country("CN")
    assert {a.ident for a in cn} >= {"ZSPD", "ZBAA", "ZWWW"}
    # sample CSV has 4500 m exactly; the full dataset stores 14764 ft
    # (4500.07 m) -- accept either source within 1 %
    assert db.max_runway_m(db.get("ZPPP")) == pytest.approx(4500.0, rel=0.01)
    # KJFK: sample says 4423 m; the full dataset has a longer runway
    # (4423 ft class strip vs 14509 ft) -- accept either within 2 %
    kjfk = db.max_runway_m(db.get("KJFK"))
    assert kjfk == pytest.approx(4423.0, rel=0.02) or kjfk == pytest.approx(
        4423.0 * 0.3048, rel=0.02
    )


def test_full_dataset_schema_length_ft_converted(tmp_path):
    # the full OurAirports runways.csv stores length_ft, not length_m
    airports_csv = tmp_path / "airports.csv"
    airports_csv.write_text(
        "ident,type,name,latitude_deg,longitude_deg,elevation_ft,continent,"
        "iso_country,iso_region,municipality,scheduled_service,iata_code\n"
        "ZTST,large_airport,Test Airport,31.0,121.0,13,AS,CN,CN-SH,Test,yes,TST\n",
        encoding="utf-8",
    )
    runways_csv = tmp_path / "runways.csv"
    runways_csv.write_text(
        "id,airport_ref,airport_ident,length_ft,width_ft,surface,lighted,"
        "closed,le_ident,he_ident\n"
        "1,1000,ZTST,9842.5,148,ASPH,1,0,36L,36R\n",
        encoding="utf-8",
    )
    db = AirportDB(airports_csv=airports_csv, runways_csv=runways_csv)
    ap = db.get("ZTST")
    assert db.max_runway_m(ap) == pytest.approx(9842.5 * 0.3048)


def test_search_ranks_codes_above_text(db):
    hits = db.search("urc", limit=5)
    assert hits[0].ident == "ZWWW"        # IATA exact beats name substring
    assert db.search("zspd", limit=5)[0].ident == "ZSPD"


def test_search_short_query_is_empty(db):
    assert db.search("Z", limit=5) == []


def test_default_path_prefers_downloaded_dataset(tmp_path, monkeypatch):
    from routelab.airports import _default_csv_path

    monkeypatch.chdir(tmp_path)
    (tmp_path / "data_cache" / "ourairports").mkdir(parents=True)
    (tmp_path / "data_cache" / "ourairports" / "airports.csv").write_text("x", encoding="utf-8")
    assert _default_csv_path("AIRPORTS").resolve() == (
        tmp_path / "data_cache" / "ourairports" / "airports.csv"
    ).resolve()
    # env var still wins over data_cache
    monkeypatch.setenv("ROUTELAB_AIRPORTS_CSV", "D:/custom.csv")
    assert _default_csv_path("AIRPORTS") == Path("D:/custom.csv")


def test_same_files_share_one_instance(tmp_path):
    from routelab.airports import _DB_CACHE

    before = len(_DB_CACHE)
    a = AirportDB(airports_csv=AIRPORTS_CSV_REF, runways_csv=RUNWAYS_CSV_REF)
    b = AirportDB(airports_csv=AIRPORTS_CSV_REF, runways_csv=RUNWAYS_CSV_REF)
    assert a._airports is b._airports   # expensive parse shared, not repeated
    assert len(_DB_CACHE) == before     # no new entry for the same files
