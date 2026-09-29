"""Great-circle geometry on a spherical-Earth approximation.

All positions are (latitude, longitude) in decimal degrees, north/east positive.
We use the haversine formula with the IUGG mean-Earth radius. The spherical
approximation deviates from true (WGS-84 ellipsoid) distances by at most about
0.5 % at these ranges, which is acceptable for learning-grade operations
analysis. See docs/methodology.md for the full list of simplifications.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0088
KM_PER_NM = 1.852


@dataclass(frozen=True)
class Route:
    """Great-circle route between two named points (usually airports)."""

    origin: str
    destination: str
    distance_km: float
    bearing_deg: float

    @property
    def distance_nm(self) -> float:
        return self.distance_km / KM_PER_NM


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, clockwise from north."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlmb = math.radians(lon2 - lon1)
    y = math.sin(dlmb) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlmb)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def route_between(
    origin: str,
    destination: str,
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> Route:
    """Build a Route from raw coordinates, with codes used as names."""
    return Route(
        origin=origin.upper(),
        destination=destination.upper(),
        distance_km=haversine_distance_km(lat1, lon1, lat2, lon2),
        bearing_deg=initial_bearing_deg(lat1, lon1, lat2, lon2),
    )


def intermediate_points(
    lat1: float, lon1: float, lat2: float, lon2: float, n: int = 64
) -> list[tuple[float, float]]:
    """Sample ``n`` (lat, lon) points along the great-circle path, endpoints included.

    Uses spherical linear interpolation between the two unit vectors, so the
    sampled path length matches the haversine distance to within discretisation
    error. Intended for drawing route arcs on maps.
    """
    if n < 2:
        raise ValueError("n must be at least 2")
    phi1, lmb1 = math.radians(lat1), math.radians(lon1)
    phi2, lmb2 = math.radians(lat2), math.radians(lon2)
    v1 = (
        math.cos(phi1) * math.cos(lmb1),
        math.cos(phi1) * math.sin(lmb1),
        math.sin(phi1),
    )
    v2 = (
        math.cos(phi2) * math.cos(lmb2),
        math.cos(phi2) * math.sin(lmb2),
        math.sin(phi2),
    )
    dot = max(-1.0, min(1.0, sum(a * b for a, b in zip(v1, v2))))
    omega = math.acos(dot)
    if omega < 1e-9:  # same point: no arc to interpolate
        return [(lat1, lon1)] * n
    sin_omega = math.sin(omega)
    points: list[tuple[float, float]] = []
    for i in range(n):
        f = i / (n - 1)
        a = math.sin((1.0 - f) * omega) / sin_omega
        b = math.sin(f * omega) / sin_omega
        x, y, z = (a * p + b * q for p, q in zip(v1, v2))
        points.append((math.degrees(math.asin(z)), math.degrees(math.atan2(y, x))))
    return points
