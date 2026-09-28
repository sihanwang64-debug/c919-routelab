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
