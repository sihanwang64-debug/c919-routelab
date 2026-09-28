"""Command-line interface.

Messages are kept in English on purpose: Windows console code pages (GBK/CJK)
can garble Chinese output from installed entry points.
"""

from __future__ import annotations

import typer

from routelab.airports import AirportDB
from routelab.fuel import FuelPolicy, block_fuel
from routelab.performance import ProxyAircraft, trip_fuel_kg, trip_time_h, usable_fuel_at_payload

app = typer.Typer(
    add_completion=False,
    help="Learning-grade narrow-body route operations analysis (public data only).",
)

_PROXY = ProxyAircraft()
_POLICY = FuelPolicy()


@app.command("distance")
def distance(origin: str, destination: str) -> None:
    """Great-circle distance and initial bearing between two airports (ICAO or IATA code)."""
    route = AirportDB().route(origin, destination)
    typer.echo(
        f"{route.origin} -> {route.destination}: {route.distance_km:.0f} km "
        f"({route.distance_nm:.0f} NM), initial track {route.bearing_deg:.0f} deg"
    )


@app.command("range")
def route_range(
    origin: str,
    destination: str,
    alternate: str = typer.Option("", help="Alternate airport code for the reserve computation."),
    payload: float = typer.Option(15_000.0, help="Payload assumed on board, kg."),
    headwind: float = typer.Option(0.0, help="Average cruise headwind, km/h."),
) -> None:
    """Estimated trip time and simplified block fuel for one route (proxy aircraft)."""
    db = AirportDB()
    route = db.route(origin, destination)
    trip = trip_fuel_kg(_PROXY, route.distance_km, headwind)
    alternate_note = "300 km diversion"
    alternate_distance_km = 300.0
    if alternate:
        alternate_distance_km = db.route(destination, alternate).distance_km
        alternate_note = f"to {alternate.upper()}"
    breakdown = block_fuel(_PROXY, trip, alternate_distance_km, _POLICY)
    fuel_limit_kg = min(
        _PROXY.max_fuel_kg, usable_fuel_at_payload(_PROXY, payload)
    )
    feasible = breakdown.block_kg <= fuel_limit_kg
    lines = [
        f"Route        {route.origin} -> {route.destination}  {route.distance_km:.0f} km",
        f"Aircraft     {_PROXY.name}",
        f"Trip time    {trip_time_h(_PROXY, route.distance_km, headwind):.2f} h",
        f"Trip fuel    {breakdown.trip_kg:.0f} kg",
        f"Contingency  {breakdown.contingency_kg:.0f} kg (5%)",
        f"Alternate    {breakdown.alternate_kg:.0f} kg ({alternate_note} + approach)",
        f"Final rsv    {breakdown.final_reserve_kg:.0f} kg "
        f"({_POLICY.final_reserve_min:.0f} min hold)",
        f"Taxi         {breakdown.taxi_kg:.0f} kg",
        f"BLOCK        {breakdown.block_kg:.0f} kg",
        (
            f"Feasibility  payload {payload:.0f} kg + block {breakdown.block_kg:.0f} kg "
            f"vs limit {fuel_limit_kg:.0f} kg -> "
            + ("OK" if feasible else "NOT FEASIBLE (cut payload or shorten route)")
        ),
        "Note         learning-grade estimate, not for flight planning.",
    ]
    typer.echo("\n".join(lines))


@app.command("airports")
def airports(country: str = typer.Option("CN", help="ISO country code to list.")) -> None:
    """List the bundled sample airports for one country."""
    for a in AirportDB().by_country(country):
        typer.echo(
            f"{a.ident}  {a.iata or '--'}  {a.municipality}  {a.name}  elev {a.elevation_ft:.0f} ft"
        )


if __name__ == "__main__":
    app()
