import pytest

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
    assert db.max_runway_m(db.get("ZPPP")) == pytest.approx(4500.0)
    assert db.max_runway_m(db.get("KJFK")) == pytest.approx(4423.0)


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
