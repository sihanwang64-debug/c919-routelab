# Data sources & licences

All data used by this project comes from public sources.

## Bundled now

### OurAirports (public domain)
- What: worldwide airports and runways, community-maintained.
- Used for: `src/routelab/data/ourairports/*.csv` — a **tiny hand-picked sample** so the toolkit works offline; coordinates and elevations are approximate.
- Full dataset: <https://ourairports.com/data/> (public domain). Run `python scripts/download_airports.py` to fetch both files (with retries) into `data_cache/ourairports/`, then point `ROUTELAB_AIRPORTS_CSV` / `ROUTELAB_RUNWAYS_CSV` at them as printed by the script. The loader accepts both column dialects (`length_m` in the bundled sample, `length_ft` in the full dataset, converted to metres).

## Planned

### OpenSky Network (ADS-B flight data)
- What: live and historical ADS-B state vectors, used by cases 03/04.
- Licence: check the current terms at <https://openskynetwork.github.io/opensky-api/> before redistribution; attribute the OpenSky Network as data source.

### OpenFlights
- What: airline/route sample data, possible seed for the network cases.
- Licence: ODbL, <https://openflights.org/data.html>.

### OpenAP (performance models, code not data)
- What: open aircraft performance model (A320neo included) for the `perf` extra.
- Licence: MIT, <https://github.com/junzis/openap>.

## Regulatory references (summarised only, never reproduced)

- CCAR-121 (CAAC) — consult the official CAAC publication;
- ICAO Annex 6, Doc 8168 etc. — consult official ICAO texts.

We deliberately summarise structure and cite official sources instead of copying regulation text, which is copyrighted.
