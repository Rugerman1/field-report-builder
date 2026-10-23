import os

import pytest


@pytest.fixture(autouse=True)
def no_claude(monkeypatch, tmp_path):
    """Keep tests offline and away from the real settings file."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", os.environ.get("LOCALAPPDATA", str(tmp_path / "local")))


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
LIVE = os.environ.get("FRB_LIVE") == "1"
