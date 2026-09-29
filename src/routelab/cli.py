"""Command-line interface.

Messages are kept in English on purpose: Windows console code pages (GBK/CJK)
can garble Chinese output from installed entry points.
"""

from __future__ import annotations

import typer

from routelab.airports import AirportDB
from routelab.fuel import FuelPolicy
from routelab.performance import ProxyAircraft
from routelab.planning import plan_leg

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
    plan = plan_leg(db, _PROXY, origin, destination, alternate, payload, headwind, _POLICY)
    b = plan.fuel
    feasible = plan.feasible
    lines = [
        f"Route        {plan.route.origin} -> {plan.route.destination}  "
        f"{plan.route.distance_km:.0f} km",
        f"Aircraft     {_PROXY.name}",
        f"Trip time    {plan.trip_time_h:.2f} h",
        f"Trip fuel    {b.trip_kg:.0f} kg",
        f"Contingency  {b.contingency_kg:.0f} kg (5%)",
        f"Alternate    {b.alternate_kg:.0f} kg ({plan.alternate_note} + approach)",
        f"Final rsv    {b.final_reserve_kg:.0f} kg "
        f"({_POLICY.final_reserve_min:.0f} min hold)",
        f"Taxi         {b.taxi_kg:.0f} kg",
        f"BLOCK        {b.block_kg:.0f} kg",
        (
            f"Feasibility  payload {payload:.0f} kg + block {b.block_kg:.0f} kg "
            f"vs limit {plan.fuel_limit_kg:.0f} kg -> "
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
