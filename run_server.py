"""Start the c919-routelab backend and open the web UI in the default browser.

Usage::

    python run_server.py            # serves on http://127.0.0.1:8300

Dependencies (fastapi/uvicorn) are checked with a friendly hint if missing.
"""

from __future__ import annotations

import sys
import threading
import webbrowser

HOST = "127.0.0.1"
PORT = 8300


def main() -> None:
    try:
        import uvicorn  # noqa: F401

        import server  # noqa: F401
    except ImportError as exc:
        sys.exit(
            f"Missing dependency ({exc}). Install with:\n"
            f'    pip install -e ".[server]"'
        )

    url = f"http://{HOST}:{PORT}"
    print(f"c919-routelab web UI: {url}  (Ctrl+C to stop)")
    threading.Timer(1.5, webbrowser.open, args=(url,)).start()

    import uvicorn

    uvicorn.run("server:app", host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
