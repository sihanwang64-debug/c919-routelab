"""Smoke test: the Streamlit app executes end to end without raising."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit", reason="streamlit [app] extra not installed")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def test_app_runs_clean() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.run()
    assert not at.exception
