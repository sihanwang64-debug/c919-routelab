"""Download the full OurAirports dataset (public domain) for offline use.

The bundled sample ships 11 airports; the full dataset has 10k+ airports
and 14k+ runways. This script downloads both CSVs, validates them, and
prints the exact environment variables to point routelab at them
(``routelab.airports`` reads ``ROUTELAB_AIRPORTS_CSV`` /
``ROUTELAB_RUNWAYS_CSV``).

Usage::

    python scripts/download_airports.py                # default destination
    python scripts/download_airports.py --dest D:/data # custom directory

Standard library only (urllib) -- no extra dependencies.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

BASE = "https://davidmegginson.github.io/ourairports-data/"
FILES = ("airports.csv", "runways.csv")
MIN_BYTES = {"airports.csv": 5_000_000, "runways.csv": 1_000_000}


def fetch(url: str, dest: Path, attempts: int = 4) -> None:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            print(f"  [{attempt}/{attempts}] {url}")
            req = urllib.request.Request(url, headers={"User-Agent": "c919-routelab/1.0"})
            with urllib.request.urlopen(req, timeout=60) as res:
                dest.write_bytes(res.read())
            return
        except Exception as exc:  # noqa: BLE001 - any network error is retryable
            last = exc
            if attempt < attempts:
                time_sleep = min(2**attempt, 15)
                print(f"    failed ({exc}); retrying in {time_sleep}s")
                import time

                time.sleep(time_sleep)
    raise RuntimeError(f"download failed after {attempts} attempts: {last}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dest",
        default=str(Path("data_cache") / "ourairports"),
        help="target directory (default: ./data_cache/ourairports, git-ignored)",
    )
    args = parser.parse_args()
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)

    print(f"Downloading the full OurAirports dataset into {dest.resolve()}")
    for name in FILES:
        print(f"- {name}")
        fetch(BASE + name, dest / name)
        size = (dest / name).stat().st_size
        if size < MIN_BYTES[name]:
            print(f"  ERROR: file looks truncated ({size:,} bytes)")
            return 1
        print(f"  ok ({size:,} bytes)")

    print("\nDone. Point routelab at the full dataset:\n")
    abs_dest = dest.resolve()
    print(f'  Windows (cmd):     set ROUTELAB_AIRPORTS_CSV={abs_dest / FILES[0]}')
    print(f'                     set ROUTELAB_RUNWAYS_CSV={abs_dest / FILES[1]}')
    print(f'  bash:              export ROUTELAB_AIRPORTS_CSV={abs_dest / FILES[0]}')
    print(f'                     export ROUTELAB_RUNWAYS_CSV={abs_dest / FILES[1]}')
    print("\nThen start the app / CLI as usual -- routelab reads these variables")
    print("on startup (see docs/data-sources.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
