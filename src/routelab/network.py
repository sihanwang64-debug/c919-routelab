"""Delay-propagation network analysis (roadmap module, planned for v0.3).

Plan of record, to be implemented in cases/03_delay_network.ipynb:

1. Input: arrival records with aircraft tail assignment, e.g. from OpenSky ADS-B
   history or a flight database dump, one row per flight with
   (registration, origin, destination, scheduled_arrival, actual_arrival).
2. Build a directed graph whose nodes are flight legs and whose edges link
   consecutive rotations of the same airframe (tail chains) and short
   turnarounds at the same airport; label each edge with the inherited delay.
3. Metrics: how much of a destination's arrival delay traces back upstream
   (delay inheritance ratio), which tails and turnarounds are the strongest
   propagation hubs, and network-level centrality of critical airports.
"""

from __future__ import annotations


def build_tail_chain(flights):
    """Build the rotation (tail-chain) graph from flight records.

    Not implemented yet -- see module docstring for the design.
    """
    raise NotImplementedError(
        "delay-propagation analysis is planned for v0.3; "
        "see cases/03_delay_network.ipynb and docs/methodology.md"
    )
